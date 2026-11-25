from .i18n import t as ui_t, localized_layout
import math
import time

import bpy
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from mathutils import Vector

from . import curve_data, draw, hair_curves, preset_ops, props, snap


_active_modal_operator = None
_addon_keymaps = []
MODE_HUD_HOLD_SECONDS = 0.11
MODE_HUD_TIMER_SECONDS = 0.016
MODE_HUD_MIN_SELECT_DISTANCE = 26.0
MODE_HUD_CELL_SIZE = 68.0
MODE_HUD_CELL_GAP = 16.0
MODE_HUD_TOOLS = ("DRAW", "CONTROL", "INTERPOLATE", "SELECT")
DUPLICATE_HOLD_SECONDS = 0.09
DUPLICATE_TIMER_SECONDS = 0.016
DUPLICATE_DRAG_ACTIVATE_DISTANCE = 3.0
GUIDE_SELECT_EVENTS = {
    "MOUSEMOVE",
    "INBETWEEN_MOUSEMOVE",
    "LEFTMOUSE",
    "RIGHTMOUSE",
    "ESC",
    "RET",
    "ENTER",
    "B",
    "C",
    "WHEELUPMOUSE",
    "WHEELDOWNMOUSE",
    "WHEELINMOUSE",
    "WHEELOUTMOUSE",
}
GUIDE_SELECT_DEFAULT_SHORTCUTS = {
    "guide_box_select": ("B", False, False, False),
    "guide_brush_select": ("C", False, False, False),
}


def clear_active_modal_state():
    op = _active_modal_operator
    if not op:
        return
    op.current_points = []
    op.preview_points = []
    op.drag_preview = []
    op.drag_original_points = []
    op.drag_preview_points = []
    op.drag_preview_data = []
    op.drag_item = None
    op.drag_point_index = -1
    op.drag_point = None
    op.drag_origin_point = None
    op.drag_handle_lines = []
    op.dragging = False
    op.painting = False
    op.ik_mode = False
    op.ik_influence_points = []
    op.warning_points = []
    op.interpolate_preview = []
    op.interpolate_preview_controls = []
    op.interpolate_preview_sources = []
    op.duplicate_pending = False
    op.duplicate_dragging = False
    op.duplicate_sources = []
    op.duplicate_preview = []
    op.duplicate_preview_controls = []
    op.guide_select_mode = ""
    if hasattr(op, "remove_duplicate_timer"):
        try:
            op.remove_duplicate_timer(bpy.context)
        except Exception:
            pass
    op.hover_curve_id = ""
    op.mode_hud_pending = False
    op.mode_hud_active = False
    op.mode_hud_hover = ""
    op.hover_point_index = -1
    op.hover_handle_side = ""
    if hasattr(op, "remove_mode_hud_timer"):
        try:
            op.remove_mode_hud_timer(bpy.context)
        except Exception:
            pass
    if getattr(op, "running", False) and hasattr(op, "rebuild_overlay_cache"):
        try:
            op.rebuild_overlay_cache()
        except Exception as exc:
            print(f"Surface Hair overlay cache rebuild failed: {exc}")
    else:
        op.overlay_state = {}
        op.overlay_curves = []


def scrub_stale_curve_state(settings):
    if not settings:
        return
    invalid = []
    for idx, item in enumerate(settings.curves):
        if curve_data.item_object(item) is None:
            invalid.append(idx)
            continue
        if item.selected and item.hidden:
            item.selected = False
    for idx in reversed(invalid):
        settings.curves.remove(idx)
    if settings.curve_index >= len(settings.curves):
        settings.curve_index = len(settings.curves) - 1
    if not settings.curves:
        settings.curve_index = -1


def object_exists(obj):
    try:
        return bool(obj and obj.name in bpy.data.objects)
    except ReferenceError:
        return False


def duplicate_root_surface(settings, fallback_surface=None):
    if settings and getattr(settings, "scalp_root_snap", False):
        try:
            scalp_obj = settings.scalp_object
        except ReferenceError:
            scalp_obj = None
        if scalp_obj and object_exists(scalp_obj) and getattr(scalp_obj, "type", "") == "MESH":
            return scalp_obj
    return fallback_surface


def tag_redraw_all_view3d(context, rebuild=False, refresh=True):
    op = _active_modal_operator
    if refresh and op and getattr(op, "running", False):
        try:
            if rebuild and hasattr(op, "rebuild_overlay_cache"):
                op.rebuild_overlay_cache(context)
            elif hasattr(op, "refresh_overlay_state"):
                op.refresh_overlay_state(context)
        except Exception as exc:
            print(f"Surface Hair overlay refresh failed: {exc}")
    screen = getattr(context, "screen", None)
    if not screen:
        return
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def settings_or_report(operator, context):
    settings = props.get_settings(context)
    if not settings:
        operator.report({"ERROR"}, ui_t("Surface Hair 设置未注册"))
        return None
    props.ensure_default_group(settings)
    curve_data.ensure_all_group_collections(context, settings)
    normalize_tool(settings)
    return settings


def normalize_tool(settings):
    if settings and getattr(settings, "tool", "DRAW") == "DRAG":
        settings.tool = "CONTROL"


def selected_interpolation_guides(settings):
    items = curve_data.selected_curve_items(settings, include_active=False)
    return sorted(
        items,
        key=lambda item: next((idx for idx, curve_item in enumerate(settings.curves) if curve_item.curve_id == item.curve_id), 0),
    )


def aligned_interpolation_points(left_points, right_points):
    count = min(len(left_points), len(right_points))
    if count < 2:
        return left_points, right_points
    forward_distance = 0.0
    reverse_distance = 0.0
    for idx in range(count):
        forward_distance += (left_points[idx] - right_points[idx]).length_squared
        reverse_distance += (left_points[idx] - right_points[count - 1 - idx]).length_squared
    if reverse_distance < forward_distance:
        return left_points, list(reversed(right_points))
    return left_points, right_points


def build_interpolation_curve_sets(context, settings, items):
    if len(items) < 2:
        return [], 0
    group = props.active_group(settings)
    curve_sets = []
    source_pairs = 0
    point_count = max(2, int(settings.interpolate_point_count))
    between_count = max(1, int(settings.interpolate_count))
    for left_item, right_item in zip(items, items[1:]):
        left_obj = curve_data.item_object(left_item)
        right_obj = curve_data.item_object(right_item)
        if not left_obj or not right_obj:
            continue
        left_points = curve_data.resample_curve_world(left_obj, point_count, resolution=24)
        right_points = curve_data.resample_curve_world(right_obj, point_count, resolution=24)
        if len(left_points) < 2 or len(right_points) < 2:
            continue
        left_points, right_points = aligned_interpolation_points(left_points, right_points)
        source_pairs += 1
        surface_obj = left_item.surface_object or right_item.surface_object
        target_group = group or curve_data.group_for_item(settings, left_item)
        for idx in range(1, between_count + 1):
            factor = idx / (between_count + 1)
            points = curve_data.interpolate_point_sets(left_points, right_points, factor)
            if settings.interpolate_surface_lock and surface_obj:
                projected = []
                for point in points:
                    result = snap.project_world_to_surface(context, point, surface_obj, settings)
                    projected.append(result.location.copy() if result.hit else point.copy())
                points = projected
            curve_sets.append(
                {
                    "points": points,
                    "group": target_group,
                    "surface_object": surface_obj,
                }
            )
    return curve_sets, source_pairs


def create_interpolation_curves(context, settings, curve_sets):
    created = []
    for curve_set in curve_sets:
        obj = curve_data.create_bezier_curve(
            context,
            curve_set["points"],
            group=curve_set.get("group"),
            surface_object=curve_set.get("surface_object"),
            name=f"SHT_插值_{len(created) + 1}",
        )
        if obj:
            created.append(obj)
    if created:
        for item in settings.curves:
            item.selected = curve_data.item_object(item) in created
        curve_data.sync_curve_object_states(settings)
    return created


def preview_curve_points_from_controls(points, resolution=16):
    if len(points) < 2:
        return [point.copy() for point in points]
    data = []
    for point in points:
        data.append(
            {
                "co": point.copy(),
                "left": point.copy(),
                "right": point.copy(),
                "left_type": "AUTO",
                "right_type": "AUTO",
            }
        )
    for idx, point_data in enumerate(data):
        if idx == 0:
            tangent = data[1]["co"] - point_data["co"]
        elif idx == len(data) - 1:
            tangent = point_data["co"] - data[idx - 1]["co"]
        else:
            tangent = data[idx + 1]["co"] - data[idx - 1]["co"]
        point_data["left"] = point_data["co"] - tangent / 6.0
        point_data["right"] = point_data["co"] + tangent / 6.0
    return curve_data.sample_bezier_data(data, resolution=max(4, int(resolution)))


def is_navigation_event(event):
    if event.type in {
        "MIDDLEMOUSE",
        "WHEELUPMOUSE",
        "WHEELDOWNMOUSE",
        "WHEELINMOUSE",
        "WHEELOUTMOUSE",
        "NDOF_MOTION",
        "HOME",
        "NUMPAD_1",
        "NUMPAD_2",
        "NUMPAD_3",
        "NUMPAD_4",
        "NUMPAD_5",
        "NUMPAD_6",
        "NUMPAD_7",
        "NUMPAD_8",
        "NUMPAD_9",
        "NUMPAD_0",
        "PERIOD",
    }:
        return True
    return False


def is_viewport_ui_shortcut_event(event):
    event_type = getattr(event, "type", "")
    if event_type == "ACCENT_GRAVE" and not (event.ctrl or event.alt):
        return True
    if event_type in {"ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"} and not (event.ctrl or event.alt or event.shift):
        return True
    if getattr(event, "value", "PRESS") != "PRESS":
        return False
    if event_type in {"N", "T"} and not (event.ctrl or event.alt or event.shift):
        return True
    if event_type == "Z" and not event.ctrl and not event.alt:
        return True
    return False


def is_view3d_window_event(context, event):
    screen = getattr(context, "screen", None)
    if not screen:
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        return bool(area and area.type == "VIEW_3D" and region and region.type == "WINDOW")
    x = getattr(event, "mouse_x", None)
    y = getattr(event, "mouse_y", None)
    if x is None or y is None:
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        return bool(area and area.type == "VIEW_3D" and region and region.type == "WINDOW")
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        if not (area.x <= x < area.x + area.width and area.y <= y < area.y + area.height):
            continue
        containing_regions = [
            region
            for region in area.regions
            if region.x <= x < region.x + region.width and region.y <= y < region.y + region.height
        ]
        if any(region.type != "WINDOW" for region in containing_regions):
            return False
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            if region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return True
    return False


def is_ui_region_event(context, event):
    return not is_view3d_window_event(context, event)


def guide_select_shortcut_matches(event, action, preferences):
    if props.shortcut_matches(event, action, preferences):
        return True
    if preferences:
        return False
    default = GUIDE_SELECT_DEFAULT_SHORTCUTS.get(action)
    if not default or getattr(event, "value", "PRESS") != "PRESS":
        return False
    key, ctrl, alt, shift = default
    return (
        getattr(event, "type", "") == key
        and bool(getattr(event, "ctrl", False)) == ctrl
        and bool(getattr(event, "alt", False)) == alt
        and bool(getattr(event, "shift", False)) == shift
    )


def enum_next(enum_items, current, step=1):
    keys = [item[0] for item in enum_items]
    if not keys:
        return current
    try:
        idx = keys.index(current)
    except ValueError:
        return keys[0]
    return keys[(idx + step) % len(keys)]


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def next_group_name(settings, base="分组"):
    names = {group.name for group in settings.groups} if settings else set()
    if base not in names:
        return base
    index = 2
    while f"{base} {index}" in names:
        index += 1
    return f"{base} {index}"


def refresh_group_preset_preview_if_live(context, settings, group):
    preset_ops.refresh_group_preset_preview_if_live(context, settings, group)


def refresh_all_live_group_preset_previews(context, settings):
    preset_ops.refresh_all_live_group_preset_previews(context, settings)


def refresh_live_group_preset_previews_by_id(context, settings, group_ids):
    preset_ops.refresh_live_group_preset_previews_by_id(context, settings, group_ids)


class SURFACE_HAIR_OT_add_group(bpy.types.Operator):
    bl_idname = "surface_hair_curve.add_group"
    bl_label = ui_t("添加曲线分组")
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name=ui_t("名称"), default="分组")

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = settings.groups.add()
        requested_name = (self.name or "").strip()
        group.name = next_group_name(settings) if requested_name in {"", "分组"} else requested_name
        group.group_id = curve_data.new_id("group")
        hue = (len(settings.groups) * 0.23) % 1.0
        group.color = (0.15 + 0.65 * hue, 0.85 - 0.25 * hue, 0.25 + 0.45 * (1.0 - hue), 1.0)
        group.curve_radius = getattr(settings, "curve_radius", 0.003)
        settings.group_index = len(settings.groups) - 1
        curve_data.ensure_group_collection(context, settings, group)
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_remove_group(bpy.types.Operator):
    bl_idname = "surface_hair_curve.remove_group"
    bl_label = ui_t("删除曲线分组")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings or not settings.groups:
            return {"CANCELLED"}
        idx = settings.group_index
        if idx < 0 or idx >= len(settings.groups):
            return {"CANCELLED"}
        removed_group = settings.groups[idx]
        group_id = removed_group.group_id
        old_collection_name = removed_group.collection_name
        hair_curves.remove_group_preset_preview(context, removed_group)
        settings.groups.remove(idx)
        if not settings.groups:
            props.ensure_default_group(settings)
        settings.group_index = min(idx, len(settings.groups) - 1)
        fallback = props.active_group(settings)
        fallback_id = fallback.group_id if fallback else ""
        if fallback:
            curve_data.ensure_group_collection(context, settings, fallback)
        for item in settings.curves:
            if item.group_id == group_id:
                item.group_id = fallback_id
                obj = curve_data.item_object(item)
                if obj:
                    obj[curve_data.GROUP_ID_PROP] = fallback_id
                    curve_data.assign_object_to_group_collection(context, settings, obj, fallback)
        if old_collection_name:
            old_collection = bpy.data.collections.get(old_collection_name)
            if old_collection and not old_collection.objects and not old_collection.children:
                bpy.data.collections.remove(old_collection)
        curve_data.sync_curve_object_states(settings)
        refresh_group_preset_preview_if_live(context, settings, fallback)
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_set_group_visibility(bpy.types.Operator):
    bl_idname = "surface_hair_curve.set_group_visibility"
    bl_label = ui_t("切换分组显示")
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        idx = self.index if self.index >= 0 else settings.group_index
        if 0 <= idx < len(settings.groups):
            settings.groups[idx].visible = not settings.groups[idx].visible
            tag_redraw_all_view3d(context, rebuild=True)
            return {"FINISHED"}
        return {"CANCELLED"}


class SURFACE_HAIR_OT_set_group_solo(bpy.types.Operator):
    bl_idname = "surface_hair_curve.set_group_solo"
    bl_label = ui_t("切换分组独显")
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        idx = self.index if self.index >= 0 else settings.group_index
        if 0 <= idx < len(settings.groups):
            settings.groups[idx].solo = not settings.groups[idx].solo
            tag_redraw_all_view3d(context, rebuild=True)
            return {"FINISHED"}
        return {"CANCELLED"}


class SURFACE_HAIR_OT_assign_selected_to_group(bpy.types.Operator):
    bl_idname = "surface_hair_curve.assign_selected_to_group"
    bl_label = ui_t("移入当前分组")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有可用分组"))
            return {"CANCELLED"}
        items = curve_data.selected_curve_items(settings)
        if not items:
            self.report({"WARNING"}, ui_t("没有选中的曲线"))
            return {"CANCELLED"}
        affected_group_ids = {item.group_id for item in items}
        affected_group_ids.add(group.group_id)
        for item in items:
            item.group_id = group.group_id
            obj = curve_data.item_object(item)
            if obj:
                obj[curve_data.GROUP_ID_PROP] = group.group_id
                curve_data.assign_object_to_group_collection(context, settings, obj, group)
        curve_data.sync_curve_object_states(settings)
        refresh_live_group_preset_previews_by_id(context, settings, affected_group_ids)
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(f"已移入分组：{group.name}"))
        return {"FINISHED"}


class SURFACE_HAIR_OT_merge_group_curves(bpy.types.Operator):
    bl_idname = "surface_hair_curve.merge_group_curves"
    bl_label = ui_t("合并当前分组头发")
    bl_description = ui_t("把当前分组内的插件原生曲线合并为一个 Curve 对象，并清理源曲线")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有当前分组"))
            return {"CANCELLED"}
        obj, message = hair_curves.merge_group_curves(context, settings, group)
        if not obj:
            self.report({"WARNING"}, ui_t(message))
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj
        settings.live_status = message
        clear_active_modal_state()
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(message))
        return {"FINISHED"}


class SURFACE_HAIR_OT_convert_group_to_hair_curves(bpy.types.Operator):
    bl_idname = "surface_hair_curve.convert_group_to_hair_curves"
    bl_label = ui_t("当前分组转换为发丝")
    bl_description = ui_t("把当前分组插件曲线按前置发丝点数重采样后转换为 Hair Curves，便于后续雕刻")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有当前分组"))
            return {"CANCELLED"}
        point_count = int(clamp(settings.hair_curve_point_count, 2, 256))
        obj, message = hair_curves.convert_group_to_hair_curves(context, settings, group, point_count)
        if not obj:
            self.report({"WARNING"}, ui_t(message))
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj
        settings.live_status = message
        clear_active_modal_state()
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(message))
        return {"FINISHED"}


class SURFACE_HAIR_OT_duplicate_selected(bpy.types.Operator):
    bl_idname = "surface_hair_curve.duplicate_selected"
    bl_label = ui_t("复制选中曲线")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        created = []
        for item in curve_data.selected_curve_items(settings):
            surface_object = curve_data.surface_object_for_item(item, curve_data.item_object(item))
            obj = curve_data.duplicate_curve(
                context,
                item,
                root_surface_object=duplicate_root_surface(settings, surface_object),
            )
            if obj:
                created.append(obj)
        if not created:
            self.report({"WARNING"}, ui_t("没有可复制的曲线"))
            return {"CANCELLED"}
        for item in settings.curves:
            item.selected = curve_data.item_object(item) in created
        curve_data.refresh_curve_registry(context)
        refresh_all_live_group_preset_previews(context, settings)
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(f"已复制 {len(created)} 条曲线"))
        return {"FINISHED"}


class SURFACE_HAIR_OT_delete_selected(bpy.types.Operator):
    bl_idname = "surface_hair_curve.delete_selected"
    bl_label = ui_t("删除选中曲线")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        remove_indices = []
        for idx, item in enumerate(settings.curves):
            if item.selected or idx == settings.curve_index:
                obj = curve_data.item_object(item)
                if obj:
                    bpy.data.objects.remove(obj, do_unlink=True)
                remove_indices.append(idx)
        for idx in reversed(remove_indices):
            settings.curves.remove(idx)
        settings.curve_index = min(settings.curve_index, len(settings.curves) - 1)
        curve_data.refresh_curve_registry(context)
        refresh_all_live_group_preset_previews(context, settings)
        clear_active_modal_state()
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_interpolate_selected(bpy.types.Operator):
    bl_idname = "surface_hair_curve.interpolate_selected"
    bl_label = ui_t("插值生成中间曲线")
    bl_description = ui_t("学习 HairBricks 的导引插值思路，在选中曲线之间生成可编辑的中间曲线")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        items = selected_interpolation_guides(settings)
        if len(items) < 2:
            self.report({"WARNING"}, ui_t("至少选择两条导引曲线"))
            return {"CANCELLED"}
        curve_sets, source_pairs = build_interpolation_curve_sets(context, settings, items)
        created = create_interpolation_curves(context, settings, curve_sets)
        if not created:
            self.report({"WARNING"}, ui_t("没有生成插值曲线"))
            return {"CANCELLED"}
        refresh_all_live_group_preset_previews(context, settings)
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(f"已基于 {source_pairs} 组导引生成 {len(created)} 条插值曲线"))
        return {"FINISHED"}


class SURFACE_HAIR_OT_rebuild_overlay_cache(bpy.types.Operator):
    bl_idname = "surface_hair_curve.rebuild_overlay_cache"
    bl_label = ui_t("刷新曲线缓存")
    bl_options = {"REGISTER"}

    def execute(self, context):
        curve_data.refresh_curve_registry(context)
        scrub_stale_curve_state(props.get_settings(context))
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_finish_modal(bpy.types.Operator):
    bl_idname = "surface_hair_curve.finish_modal"
    bl_label = ui_t("完成当前曲线")

    def execute(self, context):
        global _active_modal_operator
        if _active_modal_operator:
            _active_modal_operator.confirm_current_action(context)
            _active_modal_operator.finish(context)
            return {"FINISHED"}
        return {"CANCELLED"}


class SURFACE_HAIR_OT_cancel_modal(bpy.types.Operator):
    bl_idname = "surface_hair_curve.cancel_modal"
    bl_label = ui_t("退出工具")

    def execute(self, context):
        global _active_modal_operator
        if _active_modal_operator:
            _active_modal_operator.cancel(context)
            return {"FINISHED"}
        return {"CANCELLED"}


class SURFACE_HAIR_OT_enter_modal(bpy.types.Operator):
    bl_idname = "surface_hair_curve.enter_modal"
    bl_label = ui_t("开始表面头发曲线工具")
    bl_options = {"REGISTER", "UNDO"}

    _handle_3d = None
    _handle_2d = None

    def refresh_overlay_state(self, context=None):
        self.overlay_state = self._snapshot_overlay_state()
        self.apply_overlay_state_to_cached_curves()

    def rebuild_overlay_cache(self, context=None):
        self.overlay_state = self._snapshot_overlay_state()
        self.overlay_curves = self._snapshot_overlay_curves()
        self.apply_overlay_state_to_cached_curves()
        self.invalidate_screen_cache()

    def invalidate_screen_cache(self):
        self.screen_cache = {}
        self.screen_cache_key = None

    def _snapshot_overlay_state(self):
        settings = getattr(self, "settings", None)
        state = {
            "xray": True,
            "line_width": 6.0,
            "point_size": 12.0,
            "unselected_display_scale": 0.55,
            "brush_radius": 28.0,
            "show_control_points": True,
            "show_handles": False,
            "show_hud": True,
            "tool": "DRAW",
            "draw_mode": "CLICK",
            "snap_enabled": True,
            "snap_element": "AUTO",
            "scalp_root_snap": False,
            "scalp_name": "未选",
            "shrink_strength": 0.18,
            "shrink_tail_fixed_points": 0,
            "smooth_strength": 0.55,
            "smooth_surface_lock": True,
            "target_point_count": 4,
            "confirm_mode": "RIGHT_CLICK",
            "ik_enabled": True,
            "ik_snap": True,
            "surface_lock": True,
            "root_lock": True,
            "ik_falloff_points": 3,
            "interpolate_count": 3,
            "interpolate_point_count": 8,
            "live_status": "就绪",
            "group_name": "无",
            "group_state": "",
            "overlay_alpha": 0.92,
            "overlay_fast_mode": True,
            "shortcuts": props.shortcut_labels(),
        }
        if not settings:
            return state
        try:
            try:
                scalp_obj = settings.scalp_object
            except ReferenceError:
                scalp_obj = None
            scalp_name = str(scalp_obj.name) if scalp_obj else "未选"
            state.update(
                {
                    "xray": bool(settings.xray),
                    "line_width": float(settings.line_width),
                    "point_size": float(settings.point_size),
                    "unselected_display_scale": float(settings.unselected_display_scale),
                    "brush_radius": float(settings.brush_radius),
                    "show_control_points": bool(settings.show_control_points),
                    "show_handles": bool(settings.show_handles),
                    "show_hud": bool(settings.show_hud),
                    "tool": str(settings.tool),
                    "draw_mode": str(settings.draw_mode),
                    "snap_enabled": bool(settings.snap_enabled),
                    "snap_element": str(settings.snap_element),
                    "scalp_root_snap": bool(settings.scalp_root_snap),
                    "scalp_name": scalp_name,
                    "shrink_strength": float(settings.shrink_strength),
                    "shrink_tail_fixed_points": int(settings.shrink_tail_fixed_points),
                    "smooth_strength": float(settings.smooth_strength),
                    "smooth_surface_lock": bool(settings.smooth_surface_lock),
                    "target_point_count": int(settings.target_point_count),
                    "confirm_mode": str(settings.confirm_mode),
                    "ik_enabled": bool(settings.ik_enabled),
                    "ik_snap": bool(settings.ik_snap),
                    "surface_lock": bool(settings.surface_lock),
                    "root_lock": bool(settings.root_lock),
                    "ik_falloff_points": int(settings.ik_falloff_points),
                    "interpolate_count": int(settings.interpolate_count),
                    "interpolate_point_count": int(settings.interpolate_point_count),
                    "live_status": str(settings.live_status or "就绪"),
                    "overlay_alpha": float(settings.overlay_alpha),
                    "overlay_fast_mode": bool(settings.overlay_fast_mode),
                    "shortcuts": props.shortcut_labels(),
                }
            )
            group = props.active_group(settings)
            if group:
                state["group_name"] = str(group.name or "无")
                flags = []
                if not bool(group.visible):
                    flags.append("隐藏")
                if bool(group.solo):
                    flags.append("独显")
                if bool(group.locked):
                    flags.append("锁定")
                state["group_state"] = f" ({'/'.join(flags)})" if flags else ""
        except Exception:
            pass
        return state

    def _snapshot_overlay_curves(self):
        settings = getattr(self, "settings", None)
        state = getattr(self, "overlay_state", None) or {}
        if not settings:
            return []
        try:
            groups = {}
            solo_group_ids = set()
            for group in settings.groups:
                group_id = str(group.group_id)
                info = {
                    "color": self._copy_color(group.color, draw.GREEN),
                    "visible": bool(group.visible),
                    "locked": bool(group.locked),
                    "solo": bool(group.solo),
                    "display_strength": float(group.display_strength),
                }
                groups[group_id] = info
                if info["solo"]:
                    solo_group_ids.add(group_id)
            curves = []
            for item in settings.curves:
                obj = curve_data.item_object(item)
                if not obj:
                    continue
                group_id = str(item.group_id)
                group_info = groups.get(group_id)
                if bool(item.hidden):
                    continue
                if solo_group_ids and group_id not in solo_group_ids:
                    continue
                if group_info and not group_info["visible"]:
                    continue
                if bool(item.locked) or (group_info and group_info["locked"]):
                    continue
                selected = bool(item.selected)
                hovered = str(item.curve_id) == getattr(self, "hover_curve_id", "")
                fast_mode = bool(state.get("overlay_fast_mode", True))
                total_curves = len(settings.curves)
                simplify_unselected = bool(fast_mode and not selected and not hovered and total_curves > 24)
                segment_resolution = 16 if selected else 8
                if simplify_unselected:
                    segment_resolution = 3
                segment_sets = []
                points = []
                for seg_idx, samples in curve_data.sample_bezier_segments_world(obj, resolution=segment_resolution):
                    copied_samples = self._copy_points(samples)
                    if not copied_samples:
                        continue
                    segment_sets.append({"index": int(seg_idx), "points": copied_samples})
                    if points and points[-1] == copied_samples[0]:
                        points.extend(copied_samples[1:])
                    else:
                        points.extend(copied_samples)
                if len(points) < 2:
                    raw_points = self._copy_points(curve_data.world_points_from_curve(obj))
                    if len(raw_points) >= 2:
                        points = raw_points
                        segment_sets = [
                            {"index": idx, "points": [raw_points[idx], raw_points[idx + 1]]}
                            for idx in range(len(raw_points) - 1)
                        ]
                if len(points) < 2:
                    continue
                base_color = group_info["color"] if group_info else draw.GREEN
                strength = group_info["display_strength"] if group_info else 1.0
                alpha = state.get("overlay_alpha", 0.92) * strength
                color = draw.color_with_alpha(draw.ORANGE if selected else base_color, alpha)
                line_width = state.get("line_width", 6.0)
                point_size = state.get("point_size", 12.0)
                unselected_scale = max(0.15, min(1.0, float(state.get("unselected_display_scale", 0.55))))
                display_scale = 1.0 if selected else unselected_scale
                raw_width = max(1.0, line_width * display_scale) + (2.0 if selected else 0.0)
                raw_point_size = max(3.0, point_size * display_scale)
                control_points = self._copy_points(curve_data.world_points_from_curve(obj))
                display_control_points = control_points
                if simplify_unselected and len(control_points) > 2:
                    display_control_points = [control_points[0], control_points[-1]]
                locked_point_indices = []
                if selected and control_points:
                    locked_point_indices = self.locked_point_indices_for_count(len(control_points))
                curve = {
                    "curve_id": str(item.curve_id),
                    "object_name": str(obj.name),
                    "points": points,
                    "segments": segment_sets,
                    "control_points": control_points,
                    "display_control_points": display_control_points,
                    "locked_point_indices": locked_point_indices,
                    "selected": selected,
                    "hovered": hovered,
                    "simplified": simplify_unselected,
                    "base_color": base_color,
                    "display_strength": strength,
                    "raw_color": color,
                    "raw_width": raw_width,
                    "raw_point_size": raw_point_size,
                    "color": color,
                    "width": raw_width,
                    "point_size": raw_point_size,
                    "show_control_points": state.get("show_control_points", True) and (selected or hovered or not simplify_unselected),
                    "show_handles": state.get("show_handles", False) and selected,
                }
                if state.get("show_handles", False):
                    handle_lines, handles = curve_data.handle_lines_world(obj)
                    curve["handle_lines"] = self._copy_points(handle_lines)
                    curve["handle_points"] = self._copy_points([handle[2] for handle in handles])
                    handle_data = []
                    for handle in handles:
                        copied = self._copy_points([handle[2]])
                        if copied:
                            handle_data.append({"index": int(handle[0]), "side": str(handle[1]), "point": copied[0]})
                    curve["handle_data"] = handle_data
                curves.append(curve)
            return curves
        except Exception:
            return []

    def _points_center(self, points):
        if not points:
            return None
        total = Vector((0.0, 0.0, 0.0))
        count = 0
        for point in points:
            try:
                total += Vector(point)
                count += 1
            except Exception:
                pass
        return total / count if count else None

    def apply_overlay_state_to_cached_curves(self):
        state = getattr(self, "overlay_state", None) or {}
        point_size = state.get("point_size", 12.0)
        line_width = state.get("line_width", 6.0)
        unselected_scale = max(0.15, min(1.0, float(state.get("unselected_display_scale", 0.55))))
        show_control_points = state.get("show_control_points", True)
        show_handles = state.get("show_handles", False)
        fast_mode = bool(state.get("overlay_fast_mode", True))
        total_curves = len(getattr(self, "overlay_curves", []) or [])
        item_lookup = {}
        settings = getattr(self, "settings", None)
        if settings:
            item_lookup = {str(item.curve_id): item for item in settings.curves}
        for curve in getattr(self, "overlay_curves", []) or []:
            item = item_lookup.get(str(curve.get("curve_id", "")))
            selected = bool(item.selected) if item else bool(curve.get("selected", False))
            old_selected = bool(curve.get("selected", False))
            old_hovered = bool(curve.get("hovered", False))
            hovered = str(curve.get("curve_id", "")) == getattr(self, "hover_curve_id", "")
            if (
                old_selected == selected
                and old_hovered == hovered
                and curve.get("_state_line_width") == line_width
                and curve.get("_state_point_size") == point_size
                and curve.get("_state_unselected_scale") == unselected_scale
                and curve.get("_state_show_control_points") == show_control_points
                and curve.get("_state_show_handles") == show_handles
                and curve.get("_state_overlay_alpha") == state.get("overlay_alpha", 0.92)
                and curve.get("_state_overlay_fast_mode") == fast_mode
            ):
                continue
            display_scale = 1.0 if selected else unselected_scale
            simplify_unselected = bool(fast_mode and not selected and not hovered and total_curves > 24)
            raw_width = max(1.0, line_width * display_scale) + (2.0 if selected else 0.0)
            raw_point_size = max(3.0, point_size * display_scale)
            curve["selected"] = selected
            curve["hovered"] = hovered
            curve["raw_width"] = raw_width
            curve["raw_point_size"] = raw_point_size
            curve["width"] = raw_width
            curve["point_size"] = raw_point_size
            curve["show_control_points"] = show_control_points and (selected or hovered or not simplify_unselected)
            curve["locked_point_indices"] = self.locked_point_indices_for_count(len(curve.get("control_points") or [])) if selected else []
            curve["display_control_points"] = (
                curve.get("control_points") if not simplify_unselected else (curve.get("control_points") or [])[:1] + (curve.get("control_points") or [])[-1:]
            )
            curve["simplified"] = simplify_unselected
            strength = float(curve.get("display_strength", 1.0))
            alpha = state.get("overlay_alpha", 0.92) * strength
            base_color = curve.get("base_color", draw.GREEN)
            raw_color = draw.color_with_alpha(draw.ORANGE if selected else base_color, alpha)
            curve["raw_color"] = raw_color
            curve["color"] = raw_color
            curve["show_handles"] = bool(show_handles and selected and curve.get("handle_lines"))
            curve["_state_line_width"] = line_width
            curve["_state_point_size"] = point_size
            curve["_state_unselected_scale"] = unselected_scale
            curve["_state_show_control_points"] = show_control_points
            curve["_state_show_handles"] = show_handles
            curve["_state_overlay_alpha"] = state.get("overlay_alpha", 0.92)
            curve["_state_overlay_fast_mode"] = fast_mode

    def locked_point_indices_for_count(self, point_count):
        if point_count <= 0:
            return []
        state = getattr(self, "overlay_state", None) or {}
        tail_fixed = max(1, int(state.get("shrink_tail_fixed_points", 0)))
        tail_fixed = min(tail_fixed, max(1, point_count - 1))
        indices = {0}
        for idx in range(point_count - tail_fixed, point_count):
            indices.add(idx)
        return sorted(idx for idx in indices if 0 <= idx < point_count)

    def _copy_points(self, points):
        copied = []
        for point in points or []:
            try:
                copied.append((float(point.x), float(point.y), float(point.z)))
            except Exception:
                try:
                    copied.append((float(point[0]), float(point[1]), float(point[2])))
                except Exception:
                    continue
        return copied

    def _copy_color(self, color, fallback):
        try:
            values = tuple(float(color[idx]) for idx in range(4))
            return values
        except Exception:
            return fallback

    def invoke(self, context, event):
        global _active_modal_operator
        if context.area.type != "VIEW_3D":
            self.report({"WARNING"}, ui_t("请在 3D 视图中运行"))
            return {"CANCELLED"}
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        curve_data.refresh_curve_registry(context)
        if _active_modal_operator:
            _active_modal_operator.finish(context)
        scrub_stale_curve_state(settings)
        self.settings = settings
        self.running = True
        self.current_points = []
        self.preview_points = []
        self.drag_preview = []
        self.drag_original_points = []
        self.drag_preview_points = []
        self.drag_preview_data = []
        self.drag_item = None
        self.drag_point_index = -1
        self.drag_point = None
        self.drag_origin_point = None
        self.drag_handle_lines = []
        self.drag_kind = "POINT"
        self.drag_handle_side = ""
        self.drag_segment_index = -1
        self.drag_handle_commit = None
        self.drag_bezier_original_data = []
        self.dragging = False
        self.painting = False
        self.ik_mode = False
        self.ik_influence_points = []
        self.warning_points = []
        self.interpolate_preview = []
        self.interpolate_preview_controls = []
        self.interpolate_preview_sources = []
        self.duplicate_pending = False
        self.duplicate_dragging = False
        self.duplicate_start_time = 0.0
        self.duplicate_anchor = (event.mouse_region_x, event.mouse_region_y)
        self.duplicate_reference = None
        self.duplicate_base_offset = Vector((0.0, 0.0, 0.0))
        self.duplicate_sources = []
        self.duplicate_preview = []
        self.duplicate_preview_controls = []
        self.duplicate_timer = None
        self.guide_select_mode = ""
        self.guide_select_anchor = (event.mouse_region_x, event.mouse_region_y)
        self.guide_select_current = (event.mouse_region_x, event.mouse_region_y)
        self.guide_select_extend = False
        self.guide_select_subtract = False
        self.guide_select_dirty = False
        self.mouse_region_pos = (event.mouse_region_x, event.mouse_region_y)
        self.snap_result = None
        self.snap_is_scalp_root = False
        self.current_surface_object = None
        self.hover_curve_id = ""
        self.hover_kind = ""
        self.hover_point_index = -1
        self.hover_handle_side = ""
        self.current_cursor = ""
        self.last_click_time = 0.0
        self.undo_stack = []
        self.mode_hud_pending = False
        self.mode_hud_active = False
        self.mode_hud_start_time = 0.0
        self.mode_hud_anchor = (event.mouse_region_x, event.mouse_region_y)
        self.mode_hud_hover = ""
        self.mode_hud_timer = None
        self.overlay_state = {}
        self.overlay_curves = []
        self.screen_cache = {}
        self.screen_cache_key = None
        self.rebuild_overlay_cache(context)
        self.draw_manager = draw.OverlayDrawManager(self)
        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw.draw_callback_3d, (self,), "WINDOW", "POST_VIEW"
        )
        self._handle_2d = bpy.types.SpaceView3D.draw_handler_add(
            draw.draw_callback_2d, (self,), "WINDOW", "POST_PIXEL"
        )
        context.window_manager.modal_handler_add(self)
        self.set_modal_cursor(context, "CROSSHAIR")
        settings.live_status = "工具已启动：可连续绘制"
        _active_modal_operator = self
        tag_redraw_all_view3d(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not self.running:
            return {"CANCELLED"}
        if context.area:
            context.area.tag_redraw()
        self.mouse_region_pos = (event.mouse_region_x, event.mouse_region_y)
        if is_ui_region_event(context, event):
            return {"PASS_THROUGH"}
        guide_select_result = self.handle_guide_select_event(context, event)
        if guide_select_result:
            return guide_select_result
        if is_viewport_ui_shortcut_event(event):
            return {"PASS_THROUGH"}
        preferences = props.get_preferences(context)
        mode_hud_result = self.handle_mode_hud_event(context, event, preferences)
        if mode_hud_result:
            return mode_hud_result
        duplicate_result = self.handle_duplicate_event(context, event, preferences)
        if duplicate_result:
            return duplicate_result
        shortcut_result = self.handle_modal_shortcuts(context, event)
        if shortcut_result:
            return shortcut_result
        if is_navigation_event(event):
            return {"PASS_THROUGH"}
        if props.shortcut_matches(event, "toggle_xray", preferences):
            self.settings.xray = not self.settings.xray
            self.settings.live_status = "X-Ray ON" if self.settings.xray else "X-Ray OFF"
            tag_redraw_all_view3d(context)
            return {"RUNNING_MODAL"}
        if props.shortcut_matches(event, "cancel", preferences):
            if self.current_points or self.dragging or self.painting:
                self.cancel_submode(context)
                return {"RUNNING_MODAL"}
            self.finish(context)
            return {"CANCELLED"}
        if props.shortcut_matches(event, "undo", preferences):
            if self.undo_last_action(context):
                return {"RUNNING_MODAL"}
            self.finish(context)
            return {"PASS_THROUGH"}
        if props.shortcut_matches(event, "finish", preferences):
            self.confirm_current_action(context)
            self.finish(context)
            return {"FINISHED"}
        if event.type == "RIGHTMOUSE" and event.value == "PRESS":
            if self.settings.tool == "INTERPOLATE":
                self.commit_interpolation_preview(context)
            elif self.settings.tool == "DRAW" and self.current_points:
                self.commit_current_curve(context)
            else:
                self.cancel_submode(context)
            return {"RUNNING_MODAL"}
        if props.shortcut_matches(event, "delete_last", preferences):
            if self.current_points:
                self.current_points.pop()
                self.preview_points = list(self.current_points)
                self.settings.live_status = "已删除最后一个点"
                tag_redraw_all_view3d(context)
            return {"RUNNING_MODAL"}
        if self.needs_snap_update(event):
            self.update_snap(context, event)
        else:
            self.snap_result = None
            self.snap_is_scalp_root = False
        if event.type == "MOUSEMOVE":
            self.update_hover(context, event)
            if self.dragging:
                self.update_drag(context, event)
                return {"RUNNING_MODAL"}
            if self.painting:
                self.append_paint_sample(context)
                return {"RUNNING_MODAL"}
            if self.current_points:
                self.preview_points = list(self.current_points)
                if self.snap_result and self.snap_result.hit:
                    self.preview_points.append(self.snap_result.location)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            return self.left_press(context, event)
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return self.left_release(context, event)
        return {"RUNNING_MODAL"}

    def handle_guide_select_event(self, context, event):
        event_value = getattr(event, "value", "")
        preferences = props.get_preferences(context)
        if event_value == "PRESS" and guide_select_shortcut_matches(event, "guide_box_select", preferences):
            self.start_guide_select(context, "BOX", event)
            return {"RUNNING_MODAL"}
        if event_value == "PRESS" and guide_select_shortcut_matches(event, "guide_brush_select", preferences):
            self.start_guide_select(context, "BRUSH", event)
            return {"RUNNING_MODAL"}
        if not getattr(self, "guide_select_mode", ""):
            return None
        event_type = getattr(event, "type", "")
        if event_type not in GUIDE_SELECT_EVENTS:
            return {"RUNNING_MODAL"}
        if event_type in {"ESC", "RIGHTMOUSE"} and event_value == "PRESS":
            self.finish_guide_select(context, cancel=True)
            return {"RUNNING_MODAL"}
        if event_type in {"RET", "ENTER"} and event_value == "PRESS":
            self.finish_guide_select(context)
            return {"RUNNING_MODAL"}
        if event_type in {"WHEELUPMOUSE", "WHEELINMOUSE", "WHEELDOWNMOUSE", "WHEELOUTMOUSE"} and self.guide_select_mode == "BRUSH":
            direction = 1 if event_type in {"WHEELUPMOUSE", "WHEELINMOUSE"} else -1
            self.settings.brush_radius = clamp(float(self.settings.brush_radius) + direction * 4.0, 4.0, 240.0)
            self.settings.live_status = f"刷选半径：{self.settings.brush_radius:.0f}"
            tag_redraw_all_view3d(context)
            return {"RUNNING_MODAL"}
        if event_type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            self.guide_select_current = (event.mouse_region_x, event.mouse_region_y)
            if self.guide_select_mode == "BRUSH" and self.guide_select_dirty:
                self.apply_guide_brush_selection(context, event)
            tag_redraw_all_view3d(context, refresh=False)
            return {"RUNNING_MODAL"}
        if event_type == "LEFTMOUSE" and event_value == "PRESS":
            self.guide_select_current = (event.mouse_region_x, event.mouse_region_y)
            self.guide_select_dirty = True
            if self.guide_select_mode == "BRUSH":
                self.apply_guide_brush_selection(context, event)
            tag_redraw_all_view3d(context, refresh=False)
            return {"RUNNING_MODAL"}
        if event_type == "LEFTMOUSE" and event_value == "RELEASE":
            self.guide_select_current = (event.mouse_region_x, event.mouse_region_y)
            if self.guide_select_mode == "BOX":
                self.apply_guide_box_selection(context)
            elif self.guide_select_mode == "BRUSH":
                self.apply_guide_brush_selection(context, event)
            self.finish_guide_select(context)
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def start_guide_select(self, context, mode, event):
        self.guide_select_mode = mode
        self.guide_select_anchor = (event.mouse_region_x, event.mouse_region_y)
        self.guide_select_current = (event.mouse_region_x, event.mouse_region_y)
        self.guide_select_extend = bool(event.shift and not event.ctrl)
        self.guide_select_subtract = bool(event.ctrl)
        self.guide_select_dirty = False
        if not self.guide_select_extend and not self.guide_select_subtract:
            self.clear_guide_selection()
        self.set_modal_cursor(context, "CROSSHAIR" if mode == "BOX" else "PAINT_BRUSH")
        self.settings.live_status = "导引线框选：拖拽选择" if mode == "BOX" else "导引线刷选：左键刷过导引线"
        tag_redraw_all_view3d(context)

    def finish_guide_select(self, context, cancel=False):
        self.guide_select_mode = ""
        self.guide_select_dirty = False
        self.set_modal_cursor(context, "CROSSHAIR" if self.settings.tool == "DRAW" else "DEFAULT")
        if cancel:
            self.settings.live_status = "已取消导引线选择"
        else:
            selected_count = len(curve_data.selected_curve_items(self.settings, include_active=False))
            self.settings.live_status = f"已选择 {selected_count} 条导引线"
        self.refresh_overlay_state(context)
        tag_redraw_all_view3d(context)

    def clear_guide_selection(self):
        for item in self.settings.curves:
            item.selected = False

    def apply_guide_box_selection(self, context):
        x1, y1 = self.guide_select_anchor
        x2, y2 = self.guide_select_current
        xmin, xmax = sorted((float(x1), float(x2)))
        ymin, ymax = sorted((float(y1), float(y2)))
        hits = self.curve_ids_in_screen_rect(context, xmin, ymin, xmax, ymax)
        self.apply_guide_selection_ids(hits)

    def apply_guide_brush_selection(self, context, event):
        radius = max(2.0, float(self.settings.brush_radius))
        hits = self.curve_ids_near_screen_point(context, float(event.mouse_region_x), float(event.mouse_region_y), radius)
        self.apply_guide_selection_ids(hits)

    def apply_guide_selection_ids(self, curve_ids):
        if not curve_ids:
            return
        props.suspend_overlay_updates()
        try:
            last_index = -1
            for idx, item in enumerate(self.settings.curves):
                if item.curve_id not in curve_ids:
                    continue
                item.selected = not self.guide_select_subtract
                last_index = idx
            if last_index >= 0:
                self.settings.curve_index = last_index
        finally:
            props.resume_overlay_updates()
        self.refresh_overlay_state()

    def screen_cache_view_key(self, context):
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        if not region or not region_data:
            return None
        try:
            matrix = getattr(region_data, "perspective_matrix", None)
            if matrix is None:
                matrix = getattr(region_data, "view_matrix", None)
            matrix_key = tuple(round(float(value), 6) for row in matrix for value in row)
        except Exception:
            matrix_key = ()
        return (
            int(getattr(region, "width", 0)),
            int(getattr(region, "height", 0)),
            int(region.as_pointer()) if hasattr(region, "as_pointer") else 0,
            matrix_key,
            len(getattr(self, "overlay_curves", []) or []),
        )

    def screen_projection_cache(self, context):
        key = self.screen_cache_view_key(context)
        if key is None:
            return {}
        if getattr(self, "screen_cache_key", None) == key and getattr(self, "screen_cache", None) is not None:
            return self.screen_cache
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        if not region or not region_data:
            return {}
        cache = {}
        for curve in getattr(self, "overlay_curves", []) or []:
            curve_id = str(curve.get("curve_id", ""))
            if not curve_id:
                continue
            entry = {
                "control_points": [],
                "handle_points": [],
                "sample_segments": [],
                "line_segments": [],
            }
            for idx, point in enumerate(curve.get("control_points") or []):
                screen = view3d_utils.location_3d_to_region_2d(region, region_data, Vector(point))
                if screen:
                    entry["control_points"].append((idx, Vector((screen.x, screen.y))))
            for handle in curve.get("handle_data") or []:
                point = handle.get("point")
                if not point:
                    continue
                screen = view3d_utils.location_3d_to_region_2d(region, region_data, Vector(point))
                if screen:
                    entry["handle_points"].append(
                        (
                            int(handle.get("index", 0)),
                            str(handle.get("side", "")),
                            Vector((screen.x, screen.y)),
                        )
                    )
            for segment in curve.get("segments") or []:
                seg_idx = int(segment.get("index", 0))
                projected = []
                previous = None
                for point in segment.get("points") or []:
                    screen = view3d_utils.location_3d_to_region_2d(region, region_data, Vector(point))
                    current = Vector((screen.x, screen.y)) if screen else None
                    if current is not None:
                        projected.append(current)
                    if previous is not None and current is not None:
                        entry["line_segments"].append((previous, current))
                    previous = current
                if projected:
                    entry["sample_segments"].append({"index": seg_idx, "points": projected})
            cache[curve_id] = entry
        self.screen_cache = cache
        self.screen_cache_key = key
        return cache

    def curve_ids_in_screen_rect(self, context, xmin, ymin, xmax, ymax):
        hits = set()
        for curve in getattr(self, "overlay_curves", []) or []:
            curve_id = str(curve.get("curve_id", ""))
            if not curve_id:
                continue
            for a, b in self.curve_screen_segments(context, curve):
                if self.segment_intersects_rect(a, b, xmin, ymin, xmax, ymax):
                    hits.add(curve_id)
                    break
        return hits

    def curve_ids_near_screen_point(self, context, x, y, radius):
        hits = set()
        center = Vector((x, y))
        radius_sq = radius * radius
        for curve in getattr(self, "overlay_curves", []) or []:
            curve_id = str(curve.get("curve_id", ""))
            if not curve_id:
                continue
            for a, b in self.curve_screen_segments(context, curve):
                if self.screen_segment_distance_sq(center, a, b) <= radius_sq:
                    hits.add(curve_id)
                    break
        return hits

    def curve_screen_segments(self, context, curve):
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        if not region or not region_data:
            return []
        curve_id = str(curve.get("curve_id", ""))
        cached = self.screen_projection_cache(context).get(curve_id) if curve_id else None
        if cached is not None:
            return cached.get("line_segments", [])
        segments = []
        points = curve.get("points") or []
        previous = None
        for point in points:
            screen = view3d_utils.location_3d_to_region_2d(region, region_data, Vector(point))
            current = Vector((screen.x, screen.y)) if screen else None
            if previous is not None and current is not None:
                segments.append((previous, current))
            previous = current
        return segments

    def segment_intersects_rect(self, a, b, xmin, ymin, xmax, ymax):
        if xmin <= a.x <= xmax and ymin <= a.y <= ymax:
            return True
        if xmin <= b.x <= xmax and ymin <= b.y <= ymax:
            return True
        if max(a.x, b.x) < xmin or min(a.x, b.x) > xmax or max(a.y, b.y) < ymin or min(a.y, b.y) > ymax:
            return False
        edges = (
            (Vector((xmin, ymin)), Vector((xmax, ymin))),
            (Vector((xmax, ymin)), Vector((xmax, ymax))),
            (Vector((xmax, ymax)), Vector((xmin, ymax))),
            (Vector((xmin, ymax)), Vector((xmin, ymin))),
        )
        return any(self.screen_segments_intersect(a, b, c, d) for c, d in edges)

    def screen_segments_intersect(self, a, b, c, d):
        def orient(p, q, r):
            return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)

        def on_segment(p, q, r):
            return min(p.x, r.x) - 1.0e-6 <= q.x <= max(p.x, r.x) + 1.0e-6 and min(p.y, r.y) - 1.0e-6 <= q.y <= max(p.y, r.y) + 1.0e-6

        o1 = orient(a, b, c)
        o2 = orient(a, b, d)
        o3 = orient(c, d, a)
        o4 = orient(c, d, b)
        if o1 * o2 < 0.0 and o3 * o4 < 0.0:
            return True
        eps = 1.0e-6
        return (
            abs(o1) <= eps and on_segment(a, c, b)
            or abs(o2) <= eps and on_segment(a, d, b)
            or abs(o3) <= eps and on_segment(c, a, d)
            or abs(o4) <= eps and on_segment(c, b, d)
        )

    def screen_segment_distance_sq(self, point, a, b):
        segment = b - a
        length_sq = segment.length_squared
        if length_sq <= 1.0e-8:
            return (point - a).length_squared
        t = max(0.0, min(1.0, (point - a).dot(segment) / length_sq))
        nearest = a + segment * t
        return (point - nearest).length_squared

    def mode_hud_shortcut_matches(self, event, preferences):
        if not preferences:
            return False
        key = getattr(preferences, "hotkey_cycle_tool_key", "NONE")
        if key == "NONE":
            return False
        aliases = props.KEY_ALIASES.get(key, {key})
        if event.type not in aliases:
            return False
        return (
            bool(event.ctrl) == bool(getattr(preferences, "hotkey_cycle_tool_ctrl", False))
            and bool(event.alt) == bool(getattr(preferences, "hotkey_cycle_tool_alt", False))
            and bool(event.shift) == bool(getattr(preferences, "hotkey_cycle_tool_shift", False))
        )

    def handle_mode_hud_event(self, context, event, preferences):
        if self.mode_hud_pending or self.mode_hud_active:
            if event.type == "TIMER" and event.value == "NOTHING":
                if self.mode_hud_pending and time.monotonic() - self.mode_hud_start_time >= MODE_HUD_HOLD_SECONDS:
                    self.activate_mode_hud(context)
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE":
                if self.mode_hud_pending and time.monotonic() - self.mode_hud_start_time >= MODE_HUD_HOLD_SECONDS:
                    self.activate_mode_hud(context)
                if self.mode_hud_active:
                    self.mode_hud_hover = self.mode_hud_target_from_mouse(context, event)
                    tag_redraw_all_view3d(context)
                return {"RUNNING_MODAL"}
            if self.mode_hud_shortcut_matches(event, preferences) and event.value == "RELEASE":
                self.finish_mode_hud(context)
                return {"RUNNING_MODAL"}
            if props.shortcut_matches(event, "cancel", preferences):
                self.cancel_mode_hud(context)
                return {"RUNNING_MODAL"}
            if self.mode_hud_pending and self.mode_hud_shortcut_matches(event, preferences) and event.value == "PRESS":
                return {"RUNNING_MODAL"}
            if self.mode_hud_active:
                return {"RUNNING_MODAL"}
        if self.mode_hud_shortcut_matches(event, preferences) and event.value == "PRESS":
            self.start_mode_hud(context, event)
            return {"RUNNING_MODAL"}
        return None

    def duplicate_shortcut_matches(self, event, preferences):
        if not preferences:
            return False
        key = getattr(preferences, "hotkey_duplicate_selected_key", "NONE")
        if key == "NONE":
            return False
        aliases = props.KEY_ALIASES.get(key, {key})
        if event.type not in aliases:
            return False
        return (
            bool(event.ctrl) == bool(getattr(preferences, "hotkey_duplicate_selected_ctrl", False))
            and bool(event.alt) == bool(getattr(preferences, "hotkey_duplicate_selected_alt", False))
            and bool(event.shift) == bool(getattr(preferences, "hotkey_duplicate_selected_shift", False))
        )

    def duplicate_key_matches(self, event, preferences):
        if not preferences:
            return False
        key = getattr(preferences, "hotkey_duplicate_selected_key", "NONE")
        if key == "NONE":
            return False
        aliases = props.KEY_ALIASES.get(key, {key})
        return event.type in aliases

    def handle_duplicate_event(self, context, event, preferences):
        if self.duplicate_dragging:
            if event.type == "MOUSEMOVE":
                self.update_duplicate_drag(context, event)
                tag_redraw_all_view3d(context)
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                self.finish_duplicate_drag(context)
                return {"RUNNING_MODAL"}
            if (
                props.shortcut_matches(event, "cancel", preferences)
                or event.type in {"RIGHTMOUSE", "ESC"}
                or (event.type == "LEFTMOUSE" and event.value == "RELEASE")
            ):
                if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                    return {"RUNNING_MODAL"}
                self.cancel_duplicate_pending(context)
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}
        if self.duplicate_pending:
            if event.type == "TIMER" and event.value == "NOTHING":
                if self.duplicate_pending and time.monotonic() - self.duplicate_start_time >= DUPLICATE_HOLD_SECONDS:
                    self.activate_duplicate_drag(context, event)
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE":
                if self.duplicate_pending:
                    moved = Vector(
                        (
                            event.mouse_region_x - self.duplicate_anchor[0],
                            event.mouse_region_y - self.duplicate_anchor[1],
                        )
                    ).length
                    if moved >= DUPLICATE_DRAG_ACTIVATE_DISTANCE or time.monotonic() - self.duplicate_start_time >= DUPLICATE_HOLD_SECONDS:
                        self.activate_duplicate_drag(context, event)
                if self.duplicate_dragging:
                    self.update_duplicate_drag(context, event)
                    tag_redraw_all_view3d(context)
                return {"RUNNING_MODAL"}
            if self.duplicate_key_matches(event, preferences) and event.value == "RELEASE":
                self.perform_smart_duplicate(context, self.duplicate_anchor)
                self.cancel_duplicate_pending(context)
                return {"RUNNING_MODAL"}
            if props.shortcut_matches(event, "cancel", preferences) or event.type in {"RIGHTMOUSE", "ESC"}:
                self.cancel_duplicate_pending(context)
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}
        if self.duplicate_shortcut_matches(event, preferences) and event.value == "PRESS":
            self.start_duplicate_pending(context, event)
            return {"RUNNING_MODAL"}
        return None

    def start_mode_hud(self, context, event):
        self.mode_hud_pending = True
        self.mode_hud_active = False
        self.mode_hud_start_time = time.monotonic()
        self.mode_hud_anchor = (event.mouse_region_x, event.mouse_region_y)
        self.mode_hud_hover = self.settings.tool if self.settings.tool in MODE_HUD_TOOLS else "DRAW"
        self.add_mode_hud_timer(context)
        tag_redraw_all_view3d(context)

    def activate_mode_hud(self, context):
        self.mode_hud_pending = False
        self.mode_hud_active = True
        self.mode_hud_hover = self.settings.tool if self.settings.tool in MODE_HUD_TOOLS else "DRAW"
        self.settings.live_status = "Tab 模式选择：移动方向，松开切换"
        tag_redraw_all_view3d(context)

    def finish_mode_hud(self, context):
        active = self.mode_hud_active
        target = self.mode_hud_hover
        self.mode_hud_pending = False
        self.mode_hud_active = False
        self.mode_hud_hover = ""
        self.remove_mode_hud_timer(context)
        if active:
            if target in MODE_HUD_TOOLS:
                self.switch_tool(context, target)
        else:
            order = MODE_HUD_TOOLS
            try:
                idx = order.index(self.settings.tool)
            except ValueError:
                idx = -1
            self.switch_tool(context, order[(idx + 1) % len(order)])
        tag_redraw_all_view3d(context)

    def cancel_mode_hud(self, context):
        self.mode_hud_pending = False
        self.mode_hud_active = False
        self.mode_hud_hover = ""
        self.remove_mode_hud_timer(context)
        tag_redraw_all_view3d(context)

    def add_mode_hud_timer(self, context):
        self.remove_mode_hud_timer(context)
        window_manager = getattr(context, "window_manager", None) if context else None
        window = getattr(context, "window", None) if context else None
        if not window_manager or not window:
            return
        try:
            self.mode_hud_timer = window_manager.event_timer_add(MODE_HUD_TIMER_SECONDS, window=window)
        except Exception:
            self.mode_hud_timer = None

    def remove_mode_hud_timer(self, context):
        timer = getattr(self, "mode_hud_timer", None)
        if not timer:
            return
        window_manager = getattr(context, "window_manager", None) if context else None
        if window_manager:
            try:
                window_manager.event_timer_remove(timer)
            except Exception:
                pass
        self.mode_hud_timer = None

    def mode_hud_target_from_mouse(self, context, event):
        ax, ay = self.mode_hud_anchor
        region = getattr(context, "region", None)
        if region:
            ax = max(110.0, min(float(ax), float(region.width) - 110.0))
            ay = max(110.0, min(float(ay), float(region.height) - 110.0))
        dx = event.mouse_region_x - ax
        dy = event.mouse_region_y - ay
        cell = MODE_HUD_CELL_SIZE
        offset = MODE_HUD_CELL_SIZE + MODE_HUD_CELL_GAP
        mouse_x = float(event.mouse_region_x)
        mouse_y = float(event.mouse_region_y)
        hit_boxes = (
            ("DRAW", ax - cell * 0.5, ay + offset - cell * 0.5),
            ("CONTROL", ax + offset - cell * 0.5, ay - cell * 0.5),
            ("INTERPOLATE", ax - offset - cell * 0.5, ay - cell * 0.5),
            ("SELECT", ax - cell * 0.5, ay - offset - cell * 0.5),
        )
        for tool, x, y in hit_boxes:
            if x <= mouse_x <= x + cell and y <= mouse_y <= y + cell:
                return tool
        if abs(dx) < MODE_HUD_MIN_SELECT_DISTANCE and abs(dy) < MODE_HUD_MIN_SELECT_DISTANCE:
            return self.settings.tool if self.settings.tool in MODE_HUD_TOOLS else "DRAW"
        if abs(dx) > abs(dy):
            return "CONTROL" if dx > 0.0 else "INTERPOLATE"
        return "DRAW" if dy > 0.0 else "SELECT"

    def handle_modal_shortcuts(self, context, event):
        settings = self.settings
        normalize_tool(settings)
        if event.value != "PRESS":
            return None
        preferences = props.get_preferences(context)
        result = None
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            direction = 1 if event.type == "WHEELUPMOUSE" else -1
            if props.wheel_matches(event, "shrink_strength", preferences):
                settings.shrink_strength = round(clamp(settings.shrink_strength + direction * 0.01, 0.01, 0.8), 2)
                settings.live_status = f"收缩强度：{settings.shrink_strength:.2f}"
                result = {"RUNNING_MODAL"}
            elif props.wheel_matches(event, "shrink_tail", preferences):
                settings.shrink_tail_fixed_points = int(clamp(settings.shrink_tail_fixed_points + direction, 0, 32))
                display_fixed = max(1, settings.shrink_tail_fixed_points)
                settings.live_status = f"收缩尾端固定：{display_fixed} 点"
                result = {"RUNNING_MODAL"}
            elif props.wheel_matches(event, "group_cycle", preferences):
                self.switch_group(context, direction)
                result = {"RUNNING_MODAL"}
            elif props.wheel_matches(event, "snap_cycle", preferences):
                settings.snap_element = enum_next(props.SNAP_ELEMENT_ITEMS, settings.snap_element, direction)
                settings.live_status = f"吸附元素：{dict((item[0], item[1]) for item in props.SNAP_ELEMENT_ITEMS).get(settings.snap_element, settings.snap_element)}"
                result = {"RUNNING_MODAL"}
            elif props.wheel_matches(event, "adjust", preferences) and settings.tool == "DRAW" and settings.draw_mode == "PAINT":
                settings.brush_radius = clamp(settings.brush_radius + direction * 4.0, 4.0, 240.0)
                settings.live_status = f"刷子半径：{settings.brush_radius:.0f}"
                result = {"RUNNING_MODAL"}
            elif props.wheel_matches(event, "smooth_strength", preferences):
                settings.smooth_strength = round(clamp(settings.smooth_strength + direction * 0.05, 0.05, 0.95), 2)
                settings.live_status = f"平滑强度：{settings.smooth_strength:.2f}"
                result = {"RUNNING_MODAL"}
            if result is not None:
                tag_redraw_all_view3d(context)
            return result
        elif props.shortcut_matches(event, "cycle_tool", preferences):
            order = ("DRAW", "CONTROL", "INTERPOLATE", "SELECT")
            try:
                idx = order.index(settings.tool)
            except ValueError:
                idx = -1
            self.switch_tool(context, order[(idx + 1) % len(order)])
            result = {"RUNNING_MODAL"}
        elif props.shortcut_matches(event, "duplicate_selected", preferences):
            self.perform_smart_duplicate(context, (event.mouse_region_x, event.mouse_region_y))
            result = {"RUNNING_MODAL"}
        tool_shortcuts = (
            ("draw_tool", "DRAW"),
            ("control_tool", "CONTROL"),
            ("control_tool_alt", "CONTROL"),
            ("interpolate_tool", "INTERPOLATE"),
            ("select_tool", "SELECT"),
        )
        matched_tool = next((tool for action, tool in tool_shortcuts if props.shortcut_matches(event, action, preferences)), None)
        if result is None and matched_tool:
            self.switch_tool(context, matched_tool)
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_paint", preferences):
            settings.draw_mode = "PAINT" if settings.draw_mode == "CLICK" else "CLICK"
            settings.tool = "DRAW"
            settings.live_status = f"绘制模式：{'按住绘制' if settings.draw_mode == 'PAINT' else '单击点'}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "increase", preferences, allow_extra_ctrl=True):
            if settings.tool == "INTERPOLATE":
                if event.ctrl:
                    settings.interpolate_count = int(clamp(settings.interpolate_count + 1, 1, 64))
                    settings.live_status = f"插值数量：{settings.interpolate_count} 条"
                else:
                    settings.interpolate_point_count = int(clamp(settings.interpolate_point_count + 1, 2, 128))
                    settings.live_status = f"插值点数：{settings.interpolate_point_count}"
                self.refresh_interpolation_preview(context)
            else:
                settings.live_status = "绘制点模式：左键加点，右键确认"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "decrease", preferences, allow_extra_ctrl=True):
            if settings.tool == "INTERPOLATE":
                if event.ctrl:
                    settings.interpolate_count = int(clamp(settings.interpolate_count - 1, 1, 64))
                    settings.live_status = f"插值数量：{settings.interpolate_count} 条"
                else:
                    settings.interpolate_point_count = int(clamp(settings.interpolate_point_count - 1, 2, 128))
                    settings.live_status = f"插值点数：{settings.interpolate_point_count}"
                self.refresh_interpolation_preview(context)
            else:
                settings.live_status = "绘制点模式：左键加点，右键确认"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "ik_points_up", preferences):
            settings.ik_falloff_points = int(clamp(settings.ik_falloff_points + 1, 0, 32))
            settings.live_status = f"IK 影响点数：{settings.ik_falloff_points}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "ik_points_down", preferences):
            settings.ik_falloff_points = int(clamp(settings.ik_falloff_points - 1, 0, 32))
            settings.live_status = f"IK 影响点数：{settings.ik_falloff_points}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_snap", preferences):
            settings.snap_enabled = not settings.snap_enabled
            settings.live_status = "吸附开启" if settings.snap_enabled else "吸附关闭"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_ik_snap", preferences):
            settings.ik_snap = not settings.ik_snap
            settings.live_status = "IK 吸附开启" if settings.ik_snap else "IK 吸附关闭"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_ik", preferences):
            settings.ik_enabled = not settings.ik_enabled
            settings.live_status = "IK 模式开启：拖点会带动邻近点" if settings.ik_enabled else "IK 模式关闭：只拖当前点"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_surface_lock", preferences):
            settings.surface_lock = not settings.surface_lock
            settings.live_status = "贴面锁定开启" if settings.surface_lock else "贴面锁定关闭"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_root_lock", preferences):
            settings.root_lock = not settings.root_lock
            settings.live_status = "发根锁定开启" if settings.root_lock else "发根锁定关闭"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_handle_snap", preferences):
            settings.handle_snap = not settings.handle_snap
            settings.live_status = "弯曲吸附开启" if settings.handle_snap else "弯曲吸附关闭"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "cycle_confirm", preferences):
            settings.live_status = "绘制点模式固定为右键完成"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_hud", preferences):
            settings.show_hud = not settings.show_hud
            settings.live_status = "快捷 HUD 开启" if settings.show_hud else "快捷 HUD 关闭"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_control_points", preferences):
            settings.show_control_points = not settings.show_control_points
            settings.live_status = "控制点显示开启" if settings.show_control_points else "控制点显示关闭"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_group_visible", preferences):
            group = props.active_group(settings)
            if group:
                group.visible = not group.visible
                settings.live_status = f"分组 {group.name}：{'显示' if group.visible else '隐藏'}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "toggle_group_solo", preferences):
            group = props.active_group(settings)
            if group:
                group.solo = not group.solo
                settings.live_status = f"分组 {group.name}：{'独显' if group.solo else '取消独显'}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "add_group", preferences):
            self.add_group_from_modal(context)
            group = props.active_group(settings)
            settings.live_status = f"已新建分组：{group.name if group else '无'}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "assign_group", preferences):
            bpy.ops.surface_hair_curve.assign_selected_to_group()
            group = props.active_group(settings)
            settings.live_status = f"已移入当前分组：{group.name if group else '无'}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "merge_group", preferences):
            bpy.ops.surface_hair_curve.merge_group_curves()
            group = props.active_group(settings)
            settings.live_status = f"已合并当前分组：{group.name if group else '无'}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "convert_group_hair", preferences):
            bpy.ops.surface_hair_curve.convert_group_to_hair_curves()
            group = props.active_group(settings)
            settings.live_status = f"已转换当前分组为发丝：{group.name if group else '无'}"
            result = {"RUNNING_MODAL"}
        elif result is None and props.shortcut_matches(event, "delete_selected", preferences):
            bpy.ops.surface_hair_curve.delete_selected()
            settings.live_status = "已删除选中曲线"
            result = {"RUNNING_MODAL"}
        if result is not None:
            tag_redraw_all_view3d(context)
        return result

    def switch_tool(self, context, tool):
        if tool == "DRAG":
            tool = "CONTROL"
        if tool != "DRAW" and len(self.current_points) >= 2:
            self.commit_current_curve(context)
        elif tool != "DRAW" and self.current_points:
            self.current_points = []
            self.preview_points = []
        if tool != "INTERPOLATE":
            self.interpolate_preview = []
            self.interpolate_preview_controls = []
            self.interpolate_preview_sources = []
        self.settings.tool = tool
        labels = {item[0]: item[1] for item in props.TOOL_ITEMS}
        self.settings.live_status = f"已切换：{labels.get(tool, tool)}"
        if tool == "DRAW":
            self.set_modal_cursor(context, "CROSSHAIR")
        elif tool == "CONTROL":
            self.set_modal_cursor(context, "DEFAULT")
        elif tool == "INTERPOLATE":
            self.set_modal_cursor(context, "DEFAULT")
            self.refresh_interpolation_preview(context)
        else:
            self.set_modal_cursor(context, "DEFAULT")

    def switch_group(self, context, direction):
        settings = self.settings
        self.finalize_current_stroke_for_group_switch(context)
        if not settings.groups:
            props.ensure_default_group(settings)
        if settings.groups:
            settings.group_index = (settings.group_index + direction) % len(settings.groups)
            group = props.active_group(settings)
            settings.live_status = f"当前分组：{group.name if group else '无'}"

    def add_group_from_modal(self, context):
        self.finalize_current_stroke_for_group_switch(context)
        bpy.ops.surface_hair_curve.add_group()

    def finalize_current_stroke_for_group_switch(self, context):
        if self.painting:
            self.painting = False
            self.set_modal_cursor(context, "CROSSHAIR")
        if len(self.current_points) >= 2:
            self.commit_current_curve(context)
        elif self.current_points:
            self.current_points = []
            self.preview_points = []
            self.current_surface_object = None
            self.snap_is_scalp_root = False

    def selected_duplicate_items(self):
        return curve_data.selected_curve_items(self.settings)

    def duplicate_reference_points(self, items):
        points = []
        for item in items:
            obj = curve_data.item_object(item)
            if not obj:
                continue
            sampled = curve_data.sample_bezier_world(obj, resolution=12)
            points.extend([point.copy() for point in sampled])
        return points

    def duplicate_screen_side_offset(self, context, items, mouse_xy):
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        if not region or not region_data or not items:
            return Vector((0.015, 0.015, 0.0)), None
        mouse = Vector((float(mouse_xy[0]), float(mouse_xy[1])))
        best = None
        for item in items:
            obj = curve_data.item_object(item)
            if not obj:
                continue
            samples = curve_data.sample_bezier_world(obj, resolution=16)
            screens = []
            for point in samples:
                screen = view3d_utils.location_3d_to_region_2d(region, region_data, point)
                screens.append(Vector((screen.x, screen.y)) if screen else None)
            for idx in range(len(samples) - 1):
                a2 = screens[idx]
                b2 = screens[idx + 1]
                if a2 is None or b2 is None:
                    continue
                seg = b2 - a2
                seg_len_sq = seg.length_squared
                if seg_len_sq <= 1.0e-8:
                    continue
                t = max(0.0, min(1.0, (mouse - a2).dot(seg) / seg_len_sq))
                nearest = a2 + seg * t
                dist = (mouse - nearest).length
                if best is None or dist < best["dist"]:
                    best = {
                        "dist": dist,
                        "point": samples[idx].lerp(samples[idx + 1], t),
                        "segment": samples[idx + 1] - samples[idx],
                        "screen_segment": seg,
                        "mouse_delta": mouse - nearest,
                    }
        if not best:
            return self.fallback_view_duplicate_offset(context, items), None
        side = best["screen_segment"].x * best["mouse_delta"].y - best["screen_segment"].y * best["mouse_delta"].x
        if abs(side) <= 1.0e-4:
            side = 1.0
        normal2 = Vector((-best["screen_segment"].y, best["screen_segment"].x))
        if normal2.length <= 1.0e-8:
            return self.fallback_view_duplicate_offset(context, items), best["point"]
        normal2.normalize()
        if side < 0.0:
            normal2.negate()
        distance_px = 32.0
        nearest_screen = mouse - best["mouse_delta"]
        target_screen = nearest_screen + normal2 * distance_px
        target_world = self.mouse_plane_location_xy(context, target_screen, best["point"])
        if target_world is None:
            return self.fallback_view_duplicate_offset(context, items), best["point"]
        offset = target_world - best["point"]
        if offset.length <= 1.0e-8:
            return self.fallback_view_duplicate_offset(context, items), best["point"]
        return offset, best["point"]

    def fallback_view_duplicate_offset(self, context, items):
        points = self.duplicate_reference_points(items)
        reference = points[0] if points else Vector((0.0, 0.0, 0.0))
        try:
            region = context.region
            region_data = context.region_data
            screen = view3d_utils.location_3d_to_region_2d(region, region_data, reference)
            if screen:
                target_world = self.mouse_plane_location_xy(context, Vector((screen.x + 28.0, screen.y, 0.0)), reference)
                if target_world is not None:
                    offset = target_world - reference
                    if offset.length > 1.0e-8:
                        return offset
        except Exception:
            pass
        return Vector((0.015, 0.015, 0.0))

    def mouse_plane_location_xy(self, context, mouse_xy, fallback):
        if fallback is None:
            return None
        region = context.region
        rv3d = context.region_data
        if not region or not rv3d:
            return None
        try:
            coord = (float(mouse_xy[0]), float(mouse_xy[1]))
            view_vec = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            plane_normal = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
            denom = view_vec.dot(plane_normal)
            if abs(denom) < 1.0e-8:
                return None
            factor = (fallback - ray_origin).dot(plane_normal) / denom
            return ray_origin + view_vec * factor
        except Exception:
            return None

    def build_duplicate_sources(self, context, mouse_xy):
        items = self.selected_duplicate_items()
        if not items:
            return [], Vector((0.0, 0.0, 0.0)), None
        offset, reference = self.duplicate_screen_side_offset(context, items, mouse_xy)
        sources = []
        for item in items:
            obj = curve_data.item_object(item)
            if not obj:
                continue
            data = curve_data.bezier_world_data(obj)
            if not data:
                points = curve_data.world_points_from_curve(obj)
                data = [
                    {"co": point.copy(), "left": point.copy(), "right": point.copy(), "left_type": "AUTO", "right_type": "AUTO"}
                    for point in points
                ]
            if len(data) < 2:
                continue
            group = curve_data.group_for_item(self.settings, item)
            surface_object = curve_data.surface_object_for_item(item, obj)
            root_surface_object = duplicate_root_surface(self.settings, surface_object)
            preview = curve_data.translated_bezier_data(data, offset)
            preview = curve_data.snap_bezier_root_to_surface(context, preview, root_surface_object, self.settings)
            sources.append(
                {
                    "item": item,
                    "object": obj,
                    "data": data,
                    "group": group,
                    "surface_object": surface_object,
                    "root_surface_object": root_surface_object,
                    "offset": offset.copy(),
                    "preview": preview,
                }
            )
        return sources, offset, reference

    def update_duplicate_preview_from_sources(self):
        self.duplicate_preview = []
        self.duplicate_preview_controls = []
        for source in self.duplicate_sources:
            preview = source.get("preview") or []
            if len(preview) < 2:
                continue
            self.duplicate_preview.append(curve_data.sample_bezier_data(preview, resolution=18))
            self.duplicate_preview_controls.append([point_data["co"].copy() for point_data in preview])

    def start_duplicate_pending(self, context, event):
        sources, offset, reference = self.build_duplicate_sources(context, (event.mouse_region_x, event.mouse_region_y))
        if not sources:
            self.settings.live_status = "没有可复制的曲线"
            tag_redraw_all_view3d(context)
            return
        self.duplicate_pending = True
        self.duplicate_dragging = False
        self.duplicate_start_time = time.monotonic()
        self.duplicate_anchor = (event.mouse_region_x, event.mouse_region_y)
        self.duplicate_reference = reference or sources[0]["data"][0]["co"].copy()
        self.duplicate_base_offset = offset.copy()
        self.duplicate_sources = sources
        self.duplicate_preview = []
        self.duplicate_preview_controls = []
        self.add_duplicate_timer(context)
        self.settings.live_status = "松开直接复制，按住进入拖拽预览"

    def activate_duplicate_drag(self, context, event):
        if not self.duplicate_pending and not self.duplicate_sources:
            return
        self.duplicate_pending = False
        self.duplicate_dragging = True
        self.update_duplicate_drag(context, event)
        self.set_modal_cursor(context, "SCROLL_XY")
        self.settings.live_status = "拖动复制预览，左键确认，右键取消"
        tag_redraw_all_view3d(context)

    def update_duplicate_drag(self, context, event):
        if not self.duplicate_sources:
            return
        anchor_world = self.mouse_plane_location_xy(context, Vector(self.duplicate_anchor), self.duplicate_reference)
        mouse_world = self.mouse_plane_location(context, event, self.duplicate_reference)
        if anchor_world is None or mouse_world is None:
            offset = self.duplicate_base_offset.copy()
        else:
            offset = self.duplicate_base_offset + (mouse_world - anchor_world)
        for source in self.duplicate_sources:
            preview = curve_data.translated_bezier_data(source["data"], offset)
            preview = curve_data.snap_bezier_root_to_surface(
                context,
                preview,
                source.get("root_surface_object") or source.get("surface_object"),
                self.settings,
            )
            source["offset"] = offset.copy()
            source["preview"] = preview
        self.update_duplicate_preview_from_sources()

    def create_duplicate_from_sources(self, context):
        created = []
        for source in self.duplicate_sources:
            obj = source.get("object")
            preview = source.get("preview") or []
            if len(preview) < 2:
                continue
            new_obj = curve_data.create_bezier_curve_from_data(
                context,
                preview,
                group=source.get("group"),
                surface_object=source.get("root_surface_object") or source.get("surface_object"),
                name=f"{obj.name}_copy" if obj else "SurfaceHairCurve_copy",
            )
            if new_obj:
                created.append(new_obj)
        if created:
            self.undo_stack.extend({"type": "CREATE_CURVE", "object": obj, "name": obj.name} for obj in created)
            for item in self.settings.curves:
                item.selected = curve_data.item_object(item) in created
            curve_data.refresh_curve_registry(context)
            for item in self.settings.curves:
                item.selected = curve_data.item_object(item) in created
            self.settings.live_status = f"已复制 {len(created)} 条曲线"
            refresh_live_group_preset_previews_by_id(
                context,
                self.settings,
                [source.get("group").group_id for source in self.duplicate_sources if source.get("group")],
            )
        else:
            self.settings.live_status = "没有可复制的曲线"
        return created

    def perform_smart_duplicate(self, context, mouse_xy=None):
        mouse_xy = mouse_xy or self.mouse_region_pos
        sources, _offset, _reference = self.build_duplicate_sources(context, mouse_xy)
        self.duplicate_sources = sources
        self.update_duplicate_preview_from_sources()
        created = self.create_duplicate_from_sources(context)
        self.clear_duplicate_state(context, keep_status=True)
        tag_redraw_all_view3d(context, rebuild=bool(created))
        return created

    def finish_duplicate_drag(self, context):
        created = self.create_duplicate_from_sources(context)
        self.clear_duplicate_state(context, keep_status=True)
        self.set_modal_cursor(context, "DEFAULT" if self.settings.tool != "DRAW" else "CROSSHAIR")
        tag_redraw_all_view3d(context, rebuild=bool(created))

    def cancel_duplicate_pending(self, context):
        self.clear_duplicate_state(context, keep_status=True)
        self.set_modal_cursor(context, "DEFAULT" if self.settings.tool != "DRAW" else "CROSSHAIR")
        tag_redraw_all_view3d(context)

    def clear_duplicate_state(self, context=None, keep_status=False):
        self.duplicate_pending = False
        self.duplicate_dragging = False
        self.duplicate_sources = []
        self.duplicate_preview = []
        self.duplicate_preview_controls = []
        self.duplicate_reference = None
        self.duplicate_base_offset = Vector((0.0, 0.0, 0.0))
        self.remove_duplicate_timer(context)

    def add_duplicate_timer(self, context):
        self.remove_duplicate_timer(context)
        window_manager = getattr(context, "window_manager", None)
        window = getattr(context, "window", None)
        if not window_manager or not window:
            self.duplicate_timer = None
            return
        try:
            self.duplicate_timer = window_manager.event_timer_add(DUPLICATE_TIMER_SECONDS, window=window)
        except Exception:
            self.duplicate_timer = None

    def remove_duplicate_timer(self, context):
        timer = getattr(self, "duplicate_timer", None)
        if timer is not None:
            window_manager = getattr(context, "window_manager", None) if context else None
            if window_manager:
                try:
                    window_manager.event_timer_remove(timer)
                except Exception:
                    pass
        self.duplicate_timer = None

    def confirm_current_action(self, context):
        if self.duplicate_dragging or self.duplicate_pending:
            self.finish_duplicate_drag(context)
            return
        if self.dragging:
            self.finish_drag(context)
            self.settings.live_status = "已确认当前拖动"
            return
        if self.settings.tool == "INTERPOLATE":
            self.commit_interpolation_preview(context)
            return
        if self.painting:
            self.painting = False
            if context.window:
                self.set_modal_cursor(context, "CROSSHAIR")
            self.commit_current_curve(context)
            return
        if self.current_points:
            self.commit_current_curve(context)
            return
        self.settings.live_status = "已确认并退出工具"

    def refresh_interpolation_preview(self, context):
        items = selected_interpolation_guides(self.settings)
        self.interpolate_preview_sources = [item.curve_id for item in items]
        if len(items) < 2:
            self.interpolate_preview = []
            self.interpolate_preview_controls = []
            self.settings.live_status = "插值模式：先选择至少两条导引曲线"
            tag_redraw_all_view3d(context)
            return
        curve_sets, _source_pairs = build_interpolation_curve_sets(context, self.settings, items)
        self.interpolate_preview_controls = [curve_set["points"] for curve_set in curve_sets if len(curve_set["points"]) >= 2]
        self.interpolate_preview = [
            preview_curve_points_from_controls(points, resolution=18)
            for points in self.interpolate_preview_controls
        ]
        count = len(self.interpolate_preview)
        self.settings.live_status = f"插值预览 {count} 条：+/- 点数，Ctrl+/- 条数，右键确认"
        tag_redraw_all_view3d(context)

    def commit_interpolation_preview(self, context):
        items = selected_interpolation_guides(self.settings)
        if len(items) < 2:
            self.interpolate_preview = []
            self.interpolate_preview_controls = []
            self.settings.live_status = "插值需要至少两条选中导引曲线"
            tag_redraw_all_view3d(context)
            return []
        curve_sets, source_pairs = build_interpolation_curve_sets(context, self.settings, items)
        created = create_interpolation_curves(context, self.settings, curve_sets)
        self.interpolate_preview = []
        self.interpolate_preview_controls = []
        self.interpolate_preview_sources = []
        if created:
            self.undo_stack.extend({"type": "CREATE_CURVE", "object": obj, "name": obj.name} for obj in created)
            self.settings.live_status = f"已确认生成 {len(created)} 条插值曲线"
            refresh_live_group_preset_previews_by_id(
                context,
                self.settings,
                [curve_set.get("group").group_id for curve_set in curve_sets if curve_set.get("group")],
            )
        else:
            self.settings.live_status = f"没有可生成的插值曲线（导引组：{source_pairs}）"
        tag_redraw_all_view3d(context, rebuild=bool(created))
        return created

    def should_snap_root_to_scalp(self):
        settings = self.settings
        if not settings or settings.tool != "DRAW" or not settings.scalp_root_snap or self.current_points:
            return False
        try:
            scalp_obj = settings.scalp_object
        except ReferenceError:
            return False
        return bool(scalp_obj and object_exists(scalp_obj))

    def needs_snap_update(self, event):
        settings = self.settings
        if not settings or not settings.snap_enabled:
            return False
        event_type = getattr(event, "type", "")
        event_value = getattr(event, "value", "")
        if self.painting or self.current_points:
            return True
        if self.dragging:
            if self.drag_kind in {"HANDLE", "SEGMENT"}:
                return bool(settings.handle_snap)
            return True
        if event_type == "LEFTMOUSE" and event_value == "PRESS" and event.ctrl and settings.tool in {"DRAW", "SELECT", "CONTROL"}:
            return True
        if settings.tool == "DRAW" and not (event.shift or event.ctrl or event.alt):
            return not bool(getattr(self, "hover_curve_id", ""))
        return False

    def update_snap(self, context, event):
        self.snap_is_scalp_root = False
        if not self.settings.snap_enabled:
            self.snap_result = None
            return
        if self.should_snap_root_to_scalp() and not (event.shift or event.ctrl or event.alt):
            self.snap_result = snap.snap_from_mouse_to_object(context, event, self.settings, self.settings.scalp_object)
            self.snap_is_scalp_root = bool(self.snap_result and self.snap_result.hit)
            return
        try:
            scalp_missing = not self.settings.scalp_object
        except ReferenceError:
            scalp_missing = True
        elif_needs_scalp_warning = (
            self.settings.tool == "DRAW"
            and self.settings.scalp_root_snap
            and not self.current_points
            and scalp_missing
            and not (event.shift or event.ctrl or event.alt)
        )
        if elif_needs_scalp_warning:
            self.snap_result = snap.SnapResult(hit=False, warning=True)
            return
        self.snap_result = snap.snap_from_mouse(context, event, self.settings)

    def current_snap_location(self):
        if self.snap_result and self.snap_result.hit and (not self.ik_mode or self.settings.ik_snap):
            return self.snap_result.location.copy(), self.snap_result.object
        return None, None

    def record_draw_surface_object(self, obj):
        if not obj or self.snap_is_scalp_root:
            return
        try:
            if obj.type != "MESH":
                return
        except ReferenceError:
            return
        if object_exists(obj):
            self.current_surface_object = obj

    def draw_snap_miss_message(self):
        if self.settings.scalp_root_snap and not self.current_points:
            try:
                scalp_missing = not self.settings.scalp_object
            except ReferenceError:
                scalp_missing = True
            if scalp_missing:
                return "头皮发根吸附：请先在 N 面板选择头皮"
            return "头皮发根吸附：未命中头皮"
        return "未命中可吸附表面"

    def mouse_plane_location(self, context, event, fallback):
        if fallback is None:
            return None
        region = context.region
        rv3d = context.region_data
        if not region or not rv3d:
            return None
        coord = (event.mouse_region_x, event.mouse_region_y)
        try:
            view_vec = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            plane_normal = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
            denom = view_vec.dot(plane_normal)
            if abs(denom) < 1.0e-8:
                return None
            factor = (fallback - ray_origin).dot(plane_normal) / denom
            return ray_origin + view_vec * factor
        except Exception:
            return None

    def is_double_click(self, event):
        now = time.monotonic()
        is_double = (now - self.last_click_time) <= 0.32
        self.last_click_time = now
        return is_double

    def left_press(self, context, event):
        settings = self.settings
        if settings.tool == "INTERPOLATE":
            hit = self.find_edit_hit(context, event)
            if hit and hit["item"]:
                self.select_interpolation_guide(context, hit, extend=event.shift)
            else:
                self.refresh_interpolation_preview(context)
            return {"RUNNING_MODAL"}
        if (
            settings.tool == "DRAW"
            and not self.current_points
            and not (event.shift or event.ctrl or event.alt)
        ):
            hit = self.find_edit_hit(context, event)
            if hit and hit["item"]:
                item = hit["item"]
                was_selected = bool(getattr(item, "selected", False))
                self.hover_curve_id = item.curve_id
                self.hover_kind = hit["kind"]
                self.hover_point_index = int(hit.get("index", -1)) if hit["kind"] in {"POINT", "HANDLE"} else -1
                self.hover_handle_side = str(hit.get("side", "")) if hit["kind"] == "HANDLE" else ""
                curve_data.select_curve_item(settings, item.curve_id, extend=False, notify=False)
                if was_selected and hit["kind"] in {"POINT", "HANDLE"}:
                    ik_drag = hit["kind"] == "POINT" and settings.ik_enabled
                    self.start_drag(context, hit, ik_drag)
                settings.live_status = f"已选择 {item.name}"
                tag_redraw_all_view3d(context)
                return {"RUNNING_MODAL"}
        if settings.tool in {"SELECT", "CONTROL"} or (settings.tool == "DRAW" and (event.shift or event.ctrl or event.alt)):
            hit = self.find_edit_hit(context, event)
            if hit and hit["item"]:
                if self.handle_edit_click_action(context, event, hit):
                    return {"RUNNING_MODAL"}
                item = hit["item"]
                self.hover_curve_id = item.curve_id
                self.hover_kind = hit["kind"]
                self.hover_point_index = int(hit.get("index", -1)) if hit["kind"] in {"POINT", "HANDLE"} else -1
                self.hover_handle_side = str(hit.get("side", "")) if hit["kind"] == "HANDLE" else ""
                curve_data.select_curve_item(
                    settings,
                    item.curve_id,
                    extend=event.shift and not event.ctrl,
                    notify=False,
                )
                if settings.tool == "CONTROL" or event.shift:
                    ik_drag = hit["kind"] == "POINT" and (event.shift or settings.ik_enabled)
                    self.start_drag(context, hit, ik_drag)
                settings.live_status = f"已选择 {item.name}"
                tag_redraw_all_view3d(context)
                return {"RUNNING_MODAL"}
        if settings.tool == "DUPLICATE":
            self.perform_smart_duplicate(context, (event.mouse_region_x, event.mouse_region_y))
            return {"RUNNING_MODAL"}
        if settings.tool == "DRAW":
            if settings.draw_mode == "PAINT":
                self.painting = True
                self.current_points = []
                self.preview_points = []
                self.current_surface_object = None
                self.update_snap(context, event)
                self.append_paint_sample(context, force=True)
                self.set_modal_cursor(context, "PAINT_BRUSH")
                settings.live_status = "正在沿表面绘制"
                return {"RUNNING_MODAL"}
            loc, surface_obj = self.current_snap_location()
            if loc is not None:
                self.record_draw_surface_object(surface_obj)
                self.current_points.append(loc)
                self.preview_points = list(self.current_points)
                settings.live_status = f"已添加 {len(self.current_points)} 个点，右键确认"
                tag_redraw_all_view3d(context)
            else:
                settings.live_status = self.draw_snap_miss_message()
                tag_redraw_all_view3d(context)
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def handle_edit_click_action(self, context, event, hit):
        if self.settings.tool not in {"SELECT", "CONTROL"} and not (self.settings.tool == "DRAW" and (event.shift or event.ctrl or event.alt)):
            return False
        item = hit["item"]
        obj = curve_data.item_object(item)
        if not obj:
            return False
        points = curve_data.world_points_from_curve(obj)
        if event.ctrl and event.shift and hit["kind"] == "POINT" and hit["index"] == len(points) - 1:
            self.push_curve_undo(obj, "收缩中段")
            fixed_tail = min(self.settings.shrink_tail_fixed_points, len(points) - 2)
            display_fixed_tail = max(1, fixed_tail)
            if curve_data.shrink_bezier_middle_points(obj, self.settings.shrink_strength, display_fixed_tail):
                curve_data.select_curve_item(self.settings, item.curve_id, extend=False, notify=False)
                self.settings.live_status = f"已收缩中间点（强度 {self.settings.shrink_strength:.2f}，尾端固定 {display_fixed_tail} 点）"
                refresh_live_group_preset_previews_by_id(context, self.settings, [item.group_id])
                tag_redraw_all_view3d(context, rebuild=True)
                return True
            self.drop_last_undo_if_curve(obj)
            self.settings.live_status = "至少需要三个控制点，且根尾不能重合"
            return True
        if event.shift and hit["kind"] == "POINT" and hit["index"] == len(points) - 1:
            self.push_curve_undo(obj, "平滑曲线")
            smoothed = curve_data.smoothed_bezier_points(obj, self.settings.smooth_strength)
            surface_obj = curve_data.surface_object_for_item(item, obj)
            projected_count = 0
            if smoothed and self.settings.smooth_surface_lock and surface_obj and len(smoothed) > 2:
                projected = [smoothed[0].copy()]
                for point in smoothed[1:-1]:
                    result = snap.project_world_to_surface(context, point, surface_obj, self.settings)
                    if result.hit:
                        projected.append(result.location.copy())
                        projected_count += 1
                    else:
                        projected.append(point.copy())
                projected.append(smoothed[-1].copy())
                smoothed = projected
            if smoothed and curve_data.set_bezier_points(obj, smoothed, handle_type="AUTO"):
                curve_data.select_curve_item(self.settings, item.curve_id, extend=False, notify=False)
                if self.settings.smooth_surface_lock:
                    snap_text = f"贴面 {projected_count} 点" if surface_obj else "贴面无表面"
                else:
                    snap_text = "贴面关"
                self.settings.live_status = f"已平滑当前曲线（强度 {self.settings.smooth_strength:.2f}，{snap_text}）"
                refresh_live_group_preset_previews_by_id(context, self.settings, [item.group_id])
                tag_redraw_all_view3d(context, rebuild=True)
                return True
            self.drop_last_undo_if_curve(obj)
        if event.ctrl and hit["kind"] == "SEGMENT":
            loc, _surface_obj = self.current_snap_location()
            if loc is None:
                loc = self.nearest_sample_point(context, event, obj, hit["index"])
            if loc:
                self.push_curve_undo(obj, "加入控制点")
            if loc and curve_data.insert_bezier_point(obj, hit["index"], loc):
                curve_data.select_curve_item(self.settings, item.curve_id, extend=False, notify=False)
                self.settings.live_status = "已在线段加入控制点"
                refresh_live_group_preset_previews_by_id(context, self.settings, [item.group_id])
                tag_redraw_all_view3d(context, rebuild=True)
                return True
            self.drop_last_undo_if_curve(obj)
        if event.alt and hit["kind"] == "POINT":
            self.push_curve_undo(obj, "删除控制点")
            if curve_data.remove_bezier_point(obj, hit["index"]):
                curve_data.select_curve_item(self.settings, item.curve_id, extend=False, notify=False)
                self.settings.live_status = "已删除控制点"
                refresh_live_group_preset_previews_by_id(context, self.settings, [item.group_id])
                tag_redraw_all_view3d(context, rebuild=True)
                return True
            self.drop_last_undo_if_curve(obj)
            self.settings.live_status = "至少保留两个控制点"
            return True
        return False

    def nearest_sample_point(self, context, event, obj, segment_index):
        best = None
        best_dist = math.inf
        coord = Vector((event.mouse_region_x, event.mouse_region_y))
        segments = curve_data.sample_bezier_segments_world(obj, resolution=24)
        for idx, samples in segments:
            if idx != segment_index:
                continue
            for point in samples:
                screen = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, point)
                if not screen:
                    continue
                dist = (Vector((screen.x, screen.y)) - coord).length
                if dist < best_dist:
                    best_dist = dist
                    best = point.copy()
        return best

    def select_interpolation_guide(self, context, hit, extend):
        if not hit or not hit.get("item"):
            return False
        curve_data.select_curve_item(self.settings, hit["item"].curve_id, extend=extend, notify=False)
        self.refresh_interpolation_preview(context)
        self.refresh_overlay_state(context)
        self.settings.live_status = "已更新插值导引选择"
        return True

    def left_release(self, context, event):
        if self.dragging:
            self.finish_drag(context)
            tag_redraw_all_view3d(context)
            return {"RUNNING_MODAL"}
        if self.painting:
            self.painting = False
            self.set_modal_cursor(context, "CROSSHAIR")
            self.commit_current_curve(context)
            tag_redraw_all_view3d(context)
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def append_paint_sample(self, context, force=False):
        loc, surface_obj = self.current_snap_location()
        if loc is None:
            self.settings.live_status = f"绘制：{self.draw_snap_miss_message()}"
            return
        self.record_draw_surface_object(surface_obj)
        if force or not self.current_points:
            self.current_points.append(loc)
        elif (loc - self.current_points[-1]).length >= self.settings.sample_spacing:
            self.current_points.append(loc)
        self.preview_points = list(self.current_points)

    def commit_current_curve(self, context):
        if len(self.current_points) < 2:
            self.settings.live_status = "至少需要两个点"
            return None
        group = props.active_group(self.settings)
        surface_obj = getattr(self, "current_surface_object", None)
        snap_is_scalp_root = bool(getattr(self, "snap_is_scalp_root", False))
        if not surface_obj and self.snap_result and self.snap_result.hit and not snap_is_scalp_root:
            surface_obj = self.snap_result.object
        obj = curve_data.create_bezier_curve(
            context,
            self.current_points,
            group=group,
            surface_object=surface_obj,
            name=f"SHT_{group.name if group else 'Curve'}",
        )
        if obj and self.settings.auto_select_new_curve:
            curve_data.select_curve_item(self.settings, obj.get(curve_data.CURVE_ID_PROP), extend=False, notify=False)
        self.current_points = []
        self.preview_points = []
        self.current_surface_object = None
        self.snap_is_scalp_root = False
        self.drag_preview = []
        self.drag_preview_points = []
        self.drag_preview_data = []
        self.interpolate_preview = []
        self.interpolate_preview_controls = []
        self.interpolate_preview_sources = []
        if obj:
            curve_data.refresh_curve_registry(context)
            self.undo_stack.append({"type": "CREATE_CURVE", "object": obj, "name": obj.name})
            refresh_group_preset_preview_if_live(context, self.settings, group)
        self.settings.live_status = f"已创建 {obj.name}，可继续下一条" if obj else "无法创建曲线"
        if hasattr(self, "rebuild_overlay_cache"):
            self.rebuild_overlay_cache(context)
        tag_redraw_all_view3d(context)
        return obj

    def cancel_submode(self, context):
        self.clear_runtime_preview()
        self.set_modal_cursor(context, "CROSSHAIR")
        self.settings.live_status = "已取消当前操作"
        tag_redraw_all_view3d(context)

    def finish(self, context):
        global _active_modal_operator
        self.cancel_mode_hud(context)
        self.clear_duplicate_state(context)
        self.clear_runtime_preview()
        self.running = False
        self.remove_draw_handlers()
        if context and context.window:
            self.set_modal_cursor(context, "DEFAULT")
        if self.settings:
            self.settings.live_status = "就绪"
        if _active_modal_operator is self:
            _active_modal_operator = None
        tag_redraw_all_view3d(context)

    def cancel(self, context):
        self.finish(context)

    def clear_runtime_preview(self):
        self.current_points = []
        self.preview_points = []
        self.current_surface_object = None
        self.snap_is_scalp_root = False
        self.drag_preview = []
        self.drag_original_points = []
        self.drag_preview_points = []
        self.drag_preview_data = []
        self.drag_item = None
        self.drag_point_index = -1
        self.drag_point = None
        self.drag_origin_point = None
        self.drag_handle_lines = []
        self.drag_kind = "POINT"
        self.drag_handle_side = ""
        self.drag_segment_index = -1
        self.drag_handle_commit = None
        self.drag_bezier_original_data = []
        self.dragging = False
        self.painting = False
        self.ik_mode = False
        self.ik_influence_points = []
        self.warning_points = []
        self.interpolate_preview = []
        self.interpolate_preview_controls = []
        self.interpolate_preview_sources = []
        self.clear_duplicate_state(None)
        self.guide_select_mode = ""
        self.guide_select_anchor = (0.0, 0.0)
        self.guide_select_current = (0.0, 0.0)
        self.guide_select_extend = False
        self.guide_select_subtract = False
        self.guide_select_dirty = False
        self.hover_curve_id = ""
        self.hover_kind = ""
        self.hover_point_index = -1
        self.hover_handle_side = ""

    def set_modal_cursor(self, context, cursor):
        window = getattr(context, "window", None) if context else None
        if not window or self.current_cursor == cursor:
            return
        try:
            window.cursor_set(cursor)
            self.current_cursor = cursor
        except Exception:
            window.cursor_set("DEFAULT")
            self.current_cursor = "DEFAULT"

    def remove_draw_handlers(self):
        if self._handle_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, "WINDOW")
            self._handle_3d = None
        if self._handle_2d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_2d, "WINDOW")
            self._handle_2d = None

    def find_control_point(self, context, event):
        hit = self.find_edit_hit(context, event)
        if hit and hit["kind"] == "POINT":
            return hit["item"], hit["index"]
        return None, -1

    def screen_distance_to_world_point(self, context, point, coord):
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        if not region or not region_data:
            return math.inf
        screen = view3d_utils.location_3d_to_region_2d(region, region_data, Vector(point))
        if not screen:
            return math.inf
        return (Vector((screen.x, screen.y)) - coord).length

    def selected_control_hit_from_cache(self, context, coord, item_lookup, point_threshold, handle_threshold):
        best_point = None
        best_point_dist = math.inf
        best_handle = None
        best_handle_dist = math.inf
        selected_ids = {str(item.curve_id) for item in self.settings.curves if bool(item.selected)}
        if not selected_ids:
            return None
        screen_cache = self.screen_projection_cache(context)
        for curve in getattr(self, "overlay_curves", []) or []:
            curve_id = str(curve.get("curve_id", ""))
            if curve_id not in selected_ids:
                continue
            item = item_lookup.get(curve_id)
            if not item or bool(item.hidden) or curve_data.curve_locked(self.settings, item):
                continue
            cached = screen_cache.get(curve_id)
            if not cached:
                continue
            for idx, screen in cached.get("control_points", []):
                dist = (screen - coord).length
                if dist < best_point_dist:
                    best_point_dist = dist
                    best_point = {"item": item, "kind": "POINT", "index": idx, "side": "", "distance": dist}
            if self.settings.show_handles:
                for point_index, side, screen in cached.get("handle_points", []):
                    dist = (screen - coord).length
                    if dist < best_handle_dist:
                        best_handle_dist = dist
                        best_handle = {
                            "item": item,
                            "kind": "HANDLE",
                            "index": int(point_index),
                            "side": str(side),
                            "distance": dist,
                        }
        if best_point and best_point["distance"] <= point_threshold * 1.2:
            return best_point
        if best_handle and best_handle["distance"] <= handle_threshold * 1.2:
            return best_handle
        return None

    def selected_control_hit_from_objects(self, context, coord, point_threshold, handle_threshold):
        best_point = None
        best_point_dist = math.inf
        best_handle = None
        best_handle_dist = math.inf
        for item in self.settings.curves:
            if not bool(item.selected) or not curve_data.curve_visible(self.settings, item) or curve_data.curve_locked(self.settings, item):
                continue
            obj = curve_data.item_object(item)
            if not obj:
                continue
            for idx, point in enumerate(curve_data.world_points_from_curve(obj)):
                dist = self.screen_distance_to_world_point(context, point, coord)
                if dist < best_point_dist:
                    best_point_dist = dist
                    best_point = {"item": item, "kind": "POINT", "index": idx, "side": "", "distance": dist}
            if self.settings.show_handles:
                _lines, handles = curve_data.handle_lines_world(obj)
                for point_index, side, handle_pos in handles:
                    dist = self.screen_distance_to_world_point(context, handle_pos, coord)
                    if dist < best_handle_dist:
                        best_handle_dist = dist
                        best_handle = {"item": item, "kind": "HANDLE", "index": point_index, "side": side, "distance": dist}
        if best_point and best_point["distance"] <= point_threshold * 1.2:
            return best_point
        if best_handle and best_handle["distance"] <= handle_threshold * 1.2:
            return best_handle
        return None

    def find_edit_hit(self, context, event):
        region = getattr(context, "region", None)
        region_data = getattr(context, "region_data", None)
        if not region or not region_data:
            return None
        best_point = None
        best_point_dist = math.inf
        best_handle = None
        best_handle_dist = math.inf
        best_segment = None
        best_segment_dist = math.inf
        coord = Vector((event.mouse_region_x, event.mouse_region_y))
        item_lookup = {str(item.curve_id): item for item in self.settings.curves}
        point_threshold = max(14.0, self.settings.point_size * 1.6)
        handle_threshold = max(10.0, self.settings.point_size * 1.2)
        segment_threshold = max(12.0, self.settings.line_width * 2.5)
        screen_cache = self.screen_projection_cache(context)
        used_cache = False
        selected_control_hit = self.selected_control_hit_from_cache(context, coord, item_lookup, point_threshold, handle_threshold)
        if selected_control_hit:
            return selected_control_hit
        for curve in getattr(self, "overlay_curves", []) or []:
            item = item_lookup.get(str(curve.get("curve_id", "")))
            if not item or bool(item.hidden) or curve_data.curve_locked(self.settings, item):
                continue
            cached = screen_cache.get(str(curve.get("curve_id", "")))
            if not cached:
                continue
            used_cache = True
            for idx, screen in cached.get("control_points", []):
                dist = (screen - coord).length
                if dist < best_point_dist:
                    best_point_dist = dist
                    best_point = {"item": item, "kind": "POINT", "index": idx, "side": "", "distance": dist}
            if best_point and best_point_dist <= point_threshold * 0.55:
                return best_point
            if self.settings.show_handles:
                for point_index, side, screen in cached.get("handle_points", []):
                    dist = (screen - coord).length
                    if dist < best_handle_dist:
                        best_handle_dist = dist
                        best_handle = {
                            "item": item,
                            "kind": "HANDLE",
                            "index": int(point_index),
                            "side": str(side),
                            "distance": dist,
                        }
                if best_handle and best_handle_dist <= handle_threshold * 0.55:
                    return best_handle
            for segment in cached.get("sample_segments", []):
                seg_idx = int(segment.get("index", 0))
                for screen in segment.get("points") or []:
                    dist = (screen - coord).length
                    if dist < best_segment_dist:
                        best_segment_dist = dist
                        best_segment = {"item": item, "kind": "SEGMENT", "index": seg_idx, "side": "", "distance": dist}
        if used_cache:
            return self.best_hit_from_distances(best_point, best_handle, best_segment)
        selected_control_hit = self.selected_control_hit_from_objects(context, coord, point_threshold, handle_threshold)
        if selected_control_hit:
            return selected_control_hit
        for item in self.settings.curves:
            if not curve_data.curve_visible(self.settings, item) or curve_data.curve_locked(self.settings, item):
                continue
            obj = curve_data.item_object(item)
            if not obj:
                continue
            points = curve_data.world_points_from_curve(obj)
            for idx, point in enumerate(points):
                screen = view3d_utils.location_3d_to_region_2d(region, region_data, point)
                if not screen:
                    continue
                dist = (Vector((screen.x, screen.y)) - coord).length
                if dist < best_point_dist:
                    best_point_dist = dist
                    best_point = {"item": item, "kind": "POINT", "index": idx, "side": "", "distance": dist}
            if best_point and best_point_dist <= point_threshold * 0.55:
                return best_point
            if self.settings.show_handles:
                _lines, handles = curve_data.handle_lines_world(obj)
                for point_index, side, handle_pos in handles:
                    screen = view3d_utils.location_3d_to_region_2d(region, region_data, handle_pos)
                    if not screen:
                        continue
                    dist = (Vector((screen.x, screen.y)) - coord).length
                    if dist < best_handle_dist:
                        best_handle_dist = dist
                        best_handle = {"item": item, "kind": "HANDLE", "index": point_index, "side": side, "distance": dist}
                if best_handle and best_handle_dist <= handle_threshold * 0.55:
                    return best_handle
            for seg_idx, samples in curve_data.sample_bezier_segments_world(obj, resolution=16):
                for point in samples:
                    screen = view3d_utils.location_3d_to_region_2d(region, region_data, point)
                    if not screen:
                        continue
                    dist = (Vector((screen.x, screen.y)) - coord).length
                    if dist < best_segment_dist:
                        best_segment_dist = dist
                        best_segment = {"item": item, "kind": "SEGMENT", "index": seg_idx, "side": "", "distance": dist}
        return self.best_hit_from_distances(best_point, best_handle, best_segment)

    def best_hit_from_distances(self, best_point, best_handle, best_segment):
        point_threshold = max(14.0, self.settings.point_size * 1.6)
        handle_threshold = max(10.0, self.settings.point_size * 1.2)
        segment_threshold = max(12.0, self.settings.line_width * 2.5)
        if best_point and best_point["distance"] <= point_threshold:
            return best_point
        if best_handle and best_handle["distance"] <= handle_threshold:
            return best_handle
        if best_segment and best_segment["distance"] <= segment_threshold:
            return best_segment
        return None

    def update_hover(self, context, event):
        previous_hover = (
            getattr(self, "hover_curve_id", ""),
            getattr(self, "hover_kind", ""),
            int(getattr(self, "hover_point_index", -1)),
            getattr(self, "hover_handle_side", ""),
        )
        if self.dragging:
            self.apply_drag_cursor(context)
            return
        if self.painting:
            self.set_modal_cursor(context, "PAINT_BRUSH")
            return
        if self.settings.tool == "DRAW" and not (event.shift or event.ctrl or event.alt):
            if self.current_points:
                self.hover_curve_id = ""
                self.hover_kind = ""
                self.hover_point_index = -1
                self.hover_handle_side = ""
                self.set_modal_cursor(context, "CROSSHAIR")
                self.refresh_hover_overlay_if_changed(context, previous_hover)
                return
            hit = self.find_edit_hit(context, event)
            self.hover_curve_id = hit["item"].curve_id if hit and hit["item"] else ""
            self.hover_kind = hit["kind"] if hit else ""
            self.hover_point_index = int(hit.get("index", -1)) if hit and hit["kind"] in {"POINT", "HANDLE"} else -1
            self.hover_handle_side = str(hit.get("side", "")) if hit and hit["kind"] == "HANDLE" else ""
            self.set_modal_cursor(context, self.cursor_for_hit(hit) if hit else "CROSSHAIR")
            self.refresh_hover_overlay_if_changed(context, previous_hover)
            return
        hit = self.find_edit_hit(context, event)
        self.hover_curve_id = hit["item"].curve_id if hit and hit["item"] else ""
        self.hover_kind = hit["kind"] if hit else ""
        self.hover_point_index = int(hit.get("index", -1)) if hit and hit["kind"] in {"POINT", "HANDLE"} else -1
        self.hover_handle_side = str(hit.get("side", "")) if hit and hit["kind"] == "HANDLE" else ""
        if self.settings.tool in {"SELECT", "CONTROL", "INTERPOLATE"} or event.shift or event.ctrl or event.alt:
            self.set_modal_cursor(context, self.cursor_for_hit(hit))
        self.refresh_hover_overlay_if_changed(context, previous_hover)

    def refresh_hover_overlay_if_changed(self, context, previous_hover):
        current_hover = (
            getattr(self, "hover_curve_id", ""),
            getattr(self, "hover_kind", ""),
            int(getattr(self, "hover_point_index", -1)),
            getattr(self, "hover_handle_side", ""),
        )
        if current_hover != previous_hover:
            self.refresh_overlay_state(context)

    def cursor_for_hit(self, hit):
        if not hit:
            return "DEFAULT"
        if hit["kind"] in {"POINT", "HANDLE"}:
            return "HAND"
        if hit["kind"] == "SEGMENT":
            return "SCROLL_XY"
        return "DEFAULT"

    def apply_drag_cursor(self, context):
        if self.drag_kind == "SEGMENT":
            self.set_modal_cursor(context, "SCROLL_XY")
        else:
            self.set_modal_cursor(context, "HAND")

    def start_drag(self, context, hit, ik_mode):
        item = hit["item"]
        point_index = hit["index"]
        obj = curve_data.item_object(item)
        points = curve_data.world_points_from_curve(obj)
        bezier_data = curve_data.bezier_world_data(obj)
        if not points or point_index < 0:
            return
        self.dragging = True
        self.drag_item = item
        self.drag_kind = hit["kind"]
        self.drag_handle_side = hit.get("side", "")
        self.drag_segment_index = point_index if hit["kind"] == "SEGMENT" else -1
        self.drag_point_index = point_index
        self.drag_original_points = [p.copy() for p in points]
        self.drag_bezier_original_data = bezier_data
        self.drag_preview_points = [p.copy() for p in points]
        self.drag_preview_data = curve_data.copy_bezier_data(bezier_data)
        self.drag_preview = curve_data.sample_bezier_world(obj, resolution=16)
        self.drag_point = self.drag_preview[min(point_index, len(self.drag_preview) - 1)].copy()
        self.drag_origin_point = self.drag_point.copy()
        self.drag_handle_lines = []
        self.drag_handle_commit = None
        self.ik_mode = ik_mode
        self.ik_influence_points = []
        self.warning_points = []
        self.apply_drag_cursor(context)
        if self.drag_kind == "HANDLE" and bezier_data:
            key = "left" if self.drag_handle_side == "LEFT" else "right"
            self.drag_point = bezier_data[point_index][key].copy()
            self.drag_origin_point = self.drag_point.copy()
            self.settings.live_status = "正在调节曲线手柄"
        elif self.drag_kind == "SEGMENT":
            self.drag_origin_point = self.nearest_segment_sample_point(context, hit, obj) or self.drag_point.copy()
            self.drag_point = self.drag_origin_point.copy()
            self.settings.live_status = "正在拖拽线段弯曲度"
        else:
            self.settings.live_status = "IK 吸附拖拽" if ik_mode else "正在拖拽控制点"

    def update_drag(self, context, event):
        if not self.dragging or not self.drag_item:
            return
        loc, surface_obj = self.current_snap_location()
        if self.drag_kind in {"HANDLE", "SEGMENT"} and not self.settings.handle_snap:
            fallback = self.drag_origin_point if self.drag_kind == "SEGMENT" and self.drag_origin_point is not None else self.drag_point
            if fallback is None:
                fallback = self.drag_original_points[min(self.drag_point_index, len(self.drag_original_points) - 1)]
            loc = self.mouse_plane_location(context, event, fallback)
            surface_obj = self.drag_item.surface_object
        if loc is None:
            loc = self.mouse_plane_location(context, event, self.drag_original_points[self.drag_point_index])
            surface_obj = self.drag_item.surface_object
            if loc is None:
                self.warning_points = [self.drag_preview[self.drag_point_index]]
                self.settings.live_status = "Drag: no snap hit"
                return
        if self.drag_kind == "HANDLE":
            self.update_handle_drag(loc)
        elif self.drag_kind == "SEGMENT":
            self.update_segment_drag(loc)
        elif self.ik_mode:
            self.update_ik_drag(context, loc, surface_obj)
        else:
            control_preview = [p.copy() for p in self.drag_original_points]
            control_preview[self.drag_point_index] = loc
            self.drag_preview_points = control_preview
            self.drag_preview_data = curve_data.preview_data_with_moved_points(
                self.drag_bezier_original_data,
                control_preview,
            )
            self.drag_preview = curve_data.sample_bezier_data(self.drag_preview_data, resolution=18) if self.drag_preview_data else control_preview
            self.drag_point = loc.copy()
        self.settings.live_status = "IK 吸附" if self.ik_mode else "正在调整"

    def update_handle_drag(self, loc):
        preview_data = curve_data.preview_data_with_handle(
            self.drag_bezier_original_data,
            self.drag_point_index,
            self.drag_handle_side,
            loc,
        )
        self.drag_preview = curve_data.sample_bezier_data(preview_data, resolution=18)
        self.drag_preview_data = preview_data
        self.drag_point = loc.copy()
        point_data = preview_data[self.drag_point_index]
        self.drag_handle_lines = [point_data["co"], point_data["left"], point_data["co"], point_data["right"]]
        self.drag_handle_commit = (self.drag_point_index, self.drag_handle_side, loc.copy())

    def update_segment_drag(self, loc):
        preview_data, right, left = curve_data.preview_data_with_segment_bend(
            self.drag_bezier_original_data,
            self.drag_segment_index,
            loc,
            self.drag_origin_point,
        )
        self.drag_preview = curve_data.sample_bezier_data(preview_data, resolution=18)
        self.drag_preview_data = preview_data
        self.drag_point = loc.copy()
        if right is not None and left is not None:
            p0 = preview_data[self.drag_segment_index]["co"]
            p1 = preview_data[self.drag_segment_index + 1]["co"]
            self.drag_handle_lines = [p0, right, p1, left]
            self.drag_handle_commit = (self.drag_segment_index, right.copy(), left.copy())

    def nearest_segment_sample_point(self, context, hit, obj):
        best = None
        best_dist = math.inf
        mouse = Vector((self.mouse_region_pos[0], self.mouse_region_pos[1]))
        for idx, samples in curve_data.sample_bezier_segments_world(obj, resolution=24):
            if idx != hit["index"]:
                continue
            for point in samples:
                screen = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, point)
                if not screen:
                    continue
                dist = (Vector((screen.x, screen.y)) - mouse).length
                if dist < best_dist:
                    best_dist = dist
                    best = point.copy()
        return best

    def update_ik_drag(self, context, loc, surface_obj):
        original = self.drag_original_points
        idx = self.drag_point_index
        delta = loc - original[idx]
        influence_points = max(0, int(self.settings.ik_falloff_points))
        strength = self.settings.falloff_strength
        preview = []
        influence = []
        warnings = []
        for i, point in enumerate(original):
            if self.settings.root_lock and i == 0:
                preview.append(point.copy())
                continue
            chain_distance = abs(i - idx)
            if i == idx:
                new_point = loc.copy()
                weight = 1.0
            elif chain_distance > influence_points:
                new_point = point.copy()
                weight = 0.0
            else:
                t = chain_distance / max(influence_points + 1, 1)
                weight = (1.0 - t) ** 2 * strength
                new_point = point + delta * weight
            if self.settings.surface_lock and surface_obj:
                projected = snap.project_world_to_surface(context, new_point, surface_obj, self.settings)
                if projected.hit:
                    new_point = projected.location.copy()
                elif weight > 0.01:
                    warnings.append(new_point.copy())
                    new_point = point.copy()
            preview.append(new_point)
            if weight > 0.01:
                influence.append((new_point.copy(), weight))
        self.drag_preview_points = preview
        self.drag_preview_data = curve_data.preview_data_with_moved_points(
            self.drag_bezier_original_data,
            preview,
        )
        self.drag_preview = curve_data.sample_bezier_data(self.drag_preview_data, resolution=18) if self.drag_preview_data else preview
        self.drag_point = preview[idx].copy()
        self.ik_influence_points = influence
        self.warning_points = warnings

    def finish_drag(self, context):
        obj = curve_data.item_object(self.drag_item) if self.drag_item else None
        drag_group_id = self.drag_item.group_id if self.drag_item else ""
        if obj and self.drag_bezier_original_data:
            self.undo_stack.append(
                {
                    "type": "CURVE_DATA",
                    "object": obj,
                    "name": obj.name,
                    "data": curve_data.copy_bezier_data(self.drag_bezier_original_data),
                }
            )
        if self.drag_item and self.drag_kind == "HANDLE" and self.drag_handle_commit:
            point_index, side, loc = self.drag_handle_commit
            curve_data.set_bezier_handle(obj, point_index, side, loc)
        elif self.drag_item and self.drag_kind == "SEGMENT" and self.drag_handle_commit:
            segment_index, right, left = self.drag_handle_commit
            curve_data.set_bezier_segment_handles(obj, segment_index, right, left)
        elif self.drag_item and self.drag_preview_data:
            curve_data.set_bezier_world_data(obj, self.drag_preview_data)
        elif self.drag_item and self.drag_preview_points:
            curve_data.set_bezier_points(obj, self.drag_preview_points)
        self.dragging = False
        self.ik_mode = False
        self.drag_original_points = []
        self.drag_preview = []
        self.drag_preview_points = []
        self.drag_preview_data = []
        self.drag_item = None
        self.drag_point_index = -1
        self.drag_point = None
        self.drag_origin_point = None
        self.drag_handle_lines = []
        self.drag_kind = "POINT"
        self.drag_handle_side = ""
        self.drag_segment_index = -1
        self.drag_handle_commit = None
        self.drag_bezier_original_data = []
        self.ik_influence_points = []
        self.warning_points = []
        self.set_modal_cursor(context, "DEFAULT" if self.settings.tool == "CONTROL" else "CROSSHAIR")
        self.settings.live_status = "曲线已更新"
        refresh_live_group_preset_previews_by_id(context, self.settings, [drag_group_id])
        tag_redraw_all_view3d(context, rebuild=True)

    def push_curve_undo(self, obj, label):
        data = curve_data.bezier_world_data(obj)
        if obj and data:
            self.undo_stack.append(
                {
                    "type": "CURVE_DATA",
                    "object": obj,
                    "name": obj.name,
                    "data": curve_data.copy_bezier_data(data),
                    "label": label,
                }
            )

    def drop_last_undo_if_curve(self, obj):
        if self.undo_stack and self.undo_stack[-1].get("type") == "CURVE_DATA" and self.undo_stack[-1].get("object") == obj:
            self.undo_stack.pop()

    def undo_last_action(self, context):
        if self.current_points:
            self.current_points.pop()
            self.preview_points = list(self.current_points)
            self.settings.live_status = "撤回最后一个绘制点"
            tag_redraw_all_view3d(context)
            return True
        if self.dragging:
            self.cancel_submode(context)
            self.settings.live_status = "已撤回当前拖动预览"
            return True
        while self.undo_stack:
            action = self.undo_stack.pop()
            kind = action.get("type")
            obj = action.get("object")
            if kind == "CREATE_CURVE":
                if object_exists(obj):
                    bpy.data.objects.remove(obj, do_unlink=True)
                    curve_data.refresh_curve_registry(context)
                    refresh_all_live_group_preset_previews(context, self.settings)
                    clear_active_modal_state()
                    self.settings.live_status = "已撤回刚创建的曲线"
                    tag_redraw_all_view3d(context, rebuild=True)
                    return True
                continue
            if kind == "CURVE_DATA":
                if object_exists(obj) and curve_data.set_bezier_world_data(obj, action.get("data", [])):
                    refresh_all_live_group_preset_previews(context, self.settings)
                    self.settings.live_status = f"已撤回：{action.get('label', '曲线编辑')}"
                    tag_redraw_all_view3d(context, rebuild=True)
                    return True
                continue
        return False


classes = (
    SURFACE_HAIR_OT_add_group,
    SURFACE_HAIR_OT_remove_group,
    SURFACE_HAIR_OT_set_group_visibility,
    SURFACE_HAIR_OT_set_group_solo,
    SURFACE_HAIR_OT_assign_selected_to_group,
    SURFACE_HAIR_OT_merge_group_curves,
    SURFACE_HAIR_OT_convert_group_to_hair_curves,
    SURFACE_HAIR_OT_duplicate_selected,
    SURFACE_HAIR_OT_delete_selected,
    SURFACE_HAIR_OT_interpolate_selected,
    SURFACE_HAIR_OT_rebuild_overlay_cache,
    SURFACE_HAIR_OT_finish_modal,
    SURFACE_HAIR_OT_cancel_modal,
    SURFACE_HAIR_OT_enter_modal,
)


def register_keymaps():
    unregister_keymaps()
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    prefs = props.get_preferences()
    key = getattr(prefs, "hotkey_start_modal_key", "H") if prefs else "H"
    if key == "NONE":
        return
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    kmi = km.keymap_items.new(
        SURFACE_HAIR_OT_enter_modal.bl_idname,
        key,
        "PRESS",
        ctrl=getattr(prefs, "hotkey_start_modal_ctrl", True) if prefs else True,
        alt=getattr(prefs, "hotkey_start_modal_alt", False) if prefs else False,
        shift=getattr(prefs, "hotkey_start_modal_shift", True) if prefs else True,
    )
    _addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()


def refresh_keymaps(context=None):
    if bpy.app.background:
        return
    unregister_keymaps()
    register_keymaps()


@persistent
def cleanup_modal_on_load(_dummy):
    global _active_modal_operator
    if _active_modal_operator:
        try:
            _active_modal_operator.remove_mode_hud_timer(bpy.context)
            _active_modal_operator.remove_duplicate_timer(bpy.context)
            _active_modal_operator.remove_draw_handlers()
        except Exception:
            pass
        _active_modal_operator = None


@persistent
def cleanup_modal_on_undo(_dummy):
    global _active_modal_operator
    if _active_modal_operator:
        try:
            _active_modal_operator.running = False
            _active_modal_operator.remove_mode_hud_timer(bpy.context)
            _active_modal_operator.remove_duplicate_timer(bpy.context)
            _active_modal_operator.remove_draw_handlers()
        except Exception:
            pass
        _active_modal_operator = None


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_keymaps()
    if cleanup_modal_on_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(cleanup_modal_on_load)
    if hasattr(bpy.app.handlers, "undo_pre") and cleanup_modal_on_undo not in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.append(cleanup_modal_on_undo)


def unregister():
    global _active_modal_operator
    if _active_modal_operator:
        try:
            _active_modal_operator.remove_mode_hud_timer(bpy.context)
            _active_modal_operator.remove_duplicate_timer(bpy.context)
            _active_modal_operator.remove_draw_handlers()
        except Exception:
            pass
        _active_modal_operator = None
    if cleanup_modal_on_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(cleanup_modal_on_load)
    if hasattr(bpy.app.handlers, "undo_pre") and cleanup_modal_on_undo in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.remove(cleanup_modal_on_undo)
    unregister_keymaps()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
