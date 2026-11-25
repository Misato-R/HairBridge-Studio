from .i18n import t as ui_t, localized_layout, LANGUAGES, redraw
import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


ADDON_ID = "surface_hair_curve_tool"
_OVERLAY_UPDATE_SUSPEND_DEPTH = 0


def suspend_overlay_updates():
    global _OVERLAY_UPDATE_SUSPEND_DEPTH
    _OVERLAY_UPDATE_SUSPEND_DEPTH += 1


def resume_overlay_updates():
    global _OVERLAY_UPDATE_SUSPEND_DEPTH
    _OVERLAY_UPDATE_SUSPEND_DEPTH = max(0, _OVERLAY_UPDATE_SUSPEND_DEPTH - 1)


def overlay_updates_suspended():
    return _OVERLAY_UPDATE_SUSPEND_DEPTH > 0

TOOL_ITEMS = (
    ("DRAW", "绘制", "单击或拖拽绘制贴面曲线"),
    ("CONTROL", "编辑", "拖动控制点、拉弯曲线段、加减点和平滑"),
    ("INTERPOLATE", "插值", "预览并生成导引曲线之间的中间曲线"),
    ("SELECT", "选择", "选择曲线或控制点"),
    ("DUPLICATE", "复制", "复制选中的曲线"),
)

DRAW_MODE_ITEMS = (
    ("CLICK", "单击点", "单击放置控制点"),
    ("PAINT", "按住绘制", "按住鼠标沿表面采样绘制"),
)

SNAP_ELEMENT_ITEMS = (
    ("AUTO", "自动", "优先吸附附近点，其次边，最后面"),
    ("VERTEX", "点", "吸附到命中面的最近顶点"),
    ("EDGE", "边", "吸附到命中面的最近边"),
    ("FACE", "面", "吸附到鼠标命中的面位置"),
)

SURFACE_FILTER_ITEMS = (
    ("VISIBLE", "可见网格", "吸附到视口可见网格"),
    ("SELECTED", "已选对象", "只吸附到已选网格对象"),
    ("ACTIVE", "活动对象", "只吸附到活动网格对象"),
)

CONFIRM_MODE_ITEMS = (
    ("POINT_COUNT", "达到点数自动完成", "兼容旧文件；绘制点模式现在固定为右键完成"),
    ("DOUBLE_CLICK", "双击完成", "双击结束当前曲线并继续绘制下一条"),
    ("RIGHT_CLICK", "右键完成", "右键结束当前曲线并继续绘制下一条"),
)

KEY_ITEMS = (
    ("NONE", "无", "不绑定快捷键"),
    ("A", "A", ""),
    ("B", "B", ""),
    ("C", "C", ""),
    ("D", "D", ""),
    ("E", "E", ""),
    ("G", "G", ""),
    ("H", "H", ""),
    ("I", "I", ""),
    ("J", "J", ""),
    ("K", "K", ""),
    ("L", "L", ""),
    ("M", "M", ""),
    ("O", "O", ""),
    ("P", "P", ""),
    ("R", "R", ""),
    ("S", "S", ""),
    ("V", "V", ""),
    ("X", "X", ""),
    ("Z", "Z", ""),
    ("TAB", "Tab", ""),
    ("ESC", "Esc", ""),
    ("RET", "Enter", ""),
    ("BACK_SPACE", "Backspace", ""),
    ("EQUAL", "+", ""),
    ("MINUS", "-", ""),
    ("PAGE_UP", "Page Up", ""),
    ("PAGE_DOWN", "Page Down", ""),
)

WHEEL_MODIFIER_ITEMS = (
    ("NONE", "滚轮", ""),
    ("CTRL", "Ctrl + 滚轮", ""),
    ("ALT", "Alt + 滚轮", ""),
    ("SHIFT", "Shift + 滚轮", ""),
    ("CTRL_SHIFT", "Ctrl + Shift + 滚轮", ""),
    ("ALT_SHIFT", "Alt + Shift + 滚轮", ""),
    ("CTRL_ALT", "Ctrl + Alt + 滚轮", ""),
    ("CTRL_ALT_SHIFT", "Ctrl + Alt + Shift + 滚轮", ""),
    ("DISABLED", "禁用", ""),
)

KEY_ALIASES = {
    "RET": {"RET", "ENTER", "NUMPAD_ENTER"},
    "EQUAL": {"EQUAL", "PLUS", "NUMPAD_PLUS"},
    "MINUS": {"MINUS", "NUMPAD_MINUS"},
    "X": {"X", "DEL"},
}

KEY_LABELS = {item[0]: item[1] for item in KEY_ITEMS}
WHEEL_LABELS = {item[0]: item[1] for item in WHEEL_MODIFIER_ITEMS}
WHEEL_MODIFIER_FLAGS = {
    "NONE": (False, False, False),
    "CTRL": (True, False, False),
    "ALT": (False, True, False),
    "SHIFT": (False, False, True),
    "CTRL_SHIFT": (True, False, True),
    "ALT_SHIFT": (False, True, True),
    "CTRL_ALT": (True, True, False),
    "CTRL_ALT_SHIFT": (True, True, True),
}


def shortcut_update(_self, context):
    try:
        from . import operators

        operators.refresh_keymaps(context)
    except Exception:
        pass


def get_preferences(context=None):
    preferences = getattr(context, "preferences", None) if context else getattr(bpy.context, "preferences", None)
    if not preferences:
        return None
    addon = preferences.addons.get(__package__ or ADDON_ID) or preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def _shortcut_key_matches(event_type, key):
    if key == "NONE":
        return False
    return event_type in KEY_ALIASES.get(key, {key})


def shortcut_matches(event, action, preferences=None, allow_extra_ctrl=False):
    prefs = preferences or get_preferences()
    if not prefs or getattr(event, "value", "PRESS") != "PRESS":
        return False
    key = getattr(prefs, f"hotkey_{action}_key", "NONE")
    if not _shortcut_key_matches(event.type, key):
        return False
    expected_ctrl = bool(getattr(prefs, f"hotkey_{action}_ctrl", False))
    ctrl_ok = bool(event.ctrl) == expected_ctrl or (allow_extra_ctrl and bool(event.ctrl) and not expected_ctrl)
    return ctrl_ok and bool(event.alt) == bool(getattr(prefs, f"hotkey_{action}_alt", False)) and bool(event.shift) == bool(getattr(prefs, f"hotkey_{action}_shift", False))


def shortcut_label(action, preferences=None):
    prefs = preferences or get_preferences()
    if not prefs:
        return ""
    key = getattr(prefs, f"hotkey_{action}_key", "NONE")
    if key == "NONE":
        return "未绑定"
    parts = []
    if getattr(prefs, f"hotkey_{action}_ctrl", False):
        parts.append("Ctrl")
    if getattr(prefs, f"hotkey_{action}_alt", False):
        parts.append("Alt")
    if getattr(prefs, f"hotkey_{action}_shift", False):
        parts.append("Shift")
    parts.append(KEY_LABELS.get(key, key))
    return "+".join(parts)


def wheel_matches(event, action, preferences=None):
    prefs = preferences or get_preferences()
    if not prefs or event.type not in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
        return False
    modifier = getattr(prefs, f"wheel_{action}", "DISABLED")
    if modifier == "DISABLED":
        return False
    expected = WHEEL_MODIFIER_FLAGS.get(modifier)
    if expected is None:
        return False
    expected_ctrl, expected_alt, expected_shift = expected
    return bool(event.ctrl) == expected_ctrl and bool(event.alt) == expected_alt and bool(event.shift) == expected_shift


def wheel_label(action, preferences=None):
    prefs = preferences or get_preferences()
    if not prefs:
        return ""
    return WHEEL_LABELS.get(getattr(prefs, f"wheel_{action}", "DISABLED"), "禁用")


def shortcut_labels(preferences=None):
    prefs = preferences or get_preferences()
    return {
        "cycle_tool": shortcut_label("cycle_tool", prefs),
        "draw_tool": shortcut_label("draw_tool", prefs),
        "control_tool": shortcut_label("control_tool", prefs),
        "control_tool_alt": shortcut_label("control_tool_alt", prefs),
        "interpolate_tool": shortcut_label("interpolate_tool", prefs),
        "select_tool": shortcut_label("select_tool", prefs),
        "duplicate_selected": shortcut_label("duplicate_selected", prefs),
        "toggle_paint": shortcut_label("toggle_paint", prefs),
        "increase": shortcut_label("increase", prefs),
        "decrease": shortcut_label("decrease", prefs),
        "ik_points_up": shortcut_label("ik_points_up", prefs),
        "ik_points_down": shortcut_label("ik_points_down", prefs),
        "toggle_snap": shortcut_label("toggle_snap", prefs),
        "toggle_ik": shortcut_label("toggle_ik", prefs),
        "toggle_ik_snap": shortcut_label("toggle_ik_snap", prefs),
        "toggle_surface_lock": shortcut_label("toggle_surface_lock", prefs),
        "toggle_root_lock": shortcut_label("toggle_root_lock", prefs),
        "toggle_handle_snap": shortcut_label("toggle_handle_snap", prefs),
        "cycle_confirm": shortcut_label("cycle_confirm", prefs),
        "toggle_hud": shortcut_label("toggle_hud", prefs),
        "toggle_control_points": shortcut_label("toggle_control_points", prefs),
        "toggle_group_visible": shortcut_label("toggle_group_visible", prefs),
        "toggle_group_solo": shortcut_label("toggle_group_solo", prefs),
        "guide_box_select": shortcut_label("guide_box_select", prefs),
        "guide_brush_select": shortcut_label("guide_brush_select", prefs),
        "add_group": shortcut_label("add_group", prefs),
        "assign_group": shortcut_label("assign_group", prefs),
        "merge_group": shortcut_label("merge_group", prefs),
        "convert_group_hair": shortcut_label("convert_group_hair", prefs),
        "toggle_xray": shortcut_label("toggle_xray", prefs),
        "finish": shortcut_label("finish", prefs),
        "cancel": shortcut_label("cancel", prefs),
        "undo": shortcut_label("undo", prefs),
        "delete_last": shortcut_label("delete_last", prefs),
        "delete_selected": shortcut_label("delete_selected", prefs),
        "group_cycle": wheel_label("group_cycle", prefs),
        "snap_cycle": wheel_label("snap_cycle", prefs),
        "adjust": wheel_label("adjust", prefs),
        "shrink_strength": wheel_label("shrink_strength", prefs),
        "shrink_tail": wheel_label("shrink_tail", prefs),
        "smooth_strength": wheel_label("smooth_strength", prefs),
    }


def draw_shortcut_row(layout, prefs, label, action):
    row = layout.row(align=True)
    row.label(text=label)
    row.prop(prefs, f"hotkey_{action}_ctrl", text="Ctrl", toggle=True)
    row.prop(prefs, f"hotkey_{action}_alt", text="Alt", toggle=True)
    row.prop(prefs, f"hotkey_{action}_shift", text="Shift", toggle=True)
    row.prop(prefs, f"hotkey_{action}_key", text="")


def get_settings(context):
    return getattr(context.scene, ADDON_ID, None)


def active_group(settings):
    if settings and 0 <= settings.group_index < len(settings.groups):
        return settings.groups[settings.group_index]
    return None


def active_curve(settings):
    if settings and 0 <= settings.curve_index < len(settings.curves):
        return settings.curves[settings.curve_index]
    return None


def ensure_default_group(settings):
    if not settings.groups:
        group = settings.groups.add()
        group.name = "Main"
        group.group_id = "group_main"
        group.collection_name = ""
        group.color = (0.0, 0.85, 0.25, 1.0)
        try:
            group.curve_radius = settings.curve_radius
        except Exception:
            pass
        settings.group_index = 0
    return active_group(settings)


def tag_redraw_all_view3d(context, rebuild=False):
    try:
        from . import operators

        operators.tag_redraw_all_view3d(context, rebuild=rebuild)
        return
    except Exception:
        pass
    screen = getattr(context, "screen", None)
    if not screen:
        return
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def sync_curve_object_states_update(_self, context):
    try:
        from . import curve_data

        curve_data.sync_curve_object_states(get_settings(context))
    except Exception:
        pass
    tag_redraw_all_view3d(context, rebuild=True)


def redraw_overlay_update(_self, context):
    if overlay_updates_suspended():
        return
    tag_redraw_all_view3d(context)


def rebuild_overlay_update(_self, context):
    if overlay_updates_suspended():
        return
    tag_redraw_all_view3d(context, rebuild=True)


def interpolation_preview_update(_self, context):
    try:
        from . import operators

        op = getattr(operators, "_active_modal_operator", None)
        if op and getattr(op, "running", False):
            if getattr(op.settings, "tool", "") == "INTERPOLATE" and hasattr(op, "refresh_interpolation_preview"):
                op.refresh_interpolation_preview(context)
                return
    except Exception:
        pass
    tag_redraw_all_view3d(context)


def mesh_object_poll(_self, obj):
    return bool(obj and obj.type == "MESH")


def geometry_node_group_poll(_self, node_tree):
    return bool(node_tree and getattr(node_tree, "bl_idname", "") == "GeometryNodeTree")


def preset_library_items(_self, _context):
    try:
        from . import preset_library

        items = preset_library.preset_items()
        if items:
            return items
    except Exception:
        pass
    return (("suifa", "碎发", "从预设库添加 碎发"),)


def group_preset_enabled_update(self, context):
    try:
        from . import hair_curves

        settings = get_settings(context)
        if self.preset_enabled:
            hair_curves.ensure_legacy_group_preset_slot(settings, self)
            hair_curves.refresh_group_preset_preview(context, settings, self)
        else:
            hair_curves.hide_group_preset_preview(context, self)
    except Exception as exc:
        print(f"Surface Hair preset preview update failed: {exc}")
    tag_redraw_all_view3d(context, rebuild=True)


def group_preset_settings_update(self, context):
    try:
        from . import hair_curves

        settings = get_settings(context)
        hair_curves.ensure_legacy_group_preset_slot(settings, self)
        if self.preset_enabled:
            hair_curves.refresh_group_preset_preview(context, settings, self)
    except Exception as exc:
        print(f"Surface Hair preset setting update failed: {exc}")
    tag_redraw_all_view3d(context, rebuild=True)


def group_preset_live_update(self, context):
    try:
        from . import hair_curves

        settings = get_settings(context)
        if self.preset_enabled and self.preset_live_update:
            hair_curves.refresh_group_preset_preview(context, settings, self)
    except Exception as exc:
        print(f"Surface Hair live preset update failed: {exc}")
    tag_redraw_all_view3d(context, rebuild=True)


def group_curve_radius_update(self, context):
    try:
        from . import curve_data

        settings = get_settings(context)
        if settings:
            curve_data.apply_group_curve_radius(settings, self)
    except Exception as exc:
        print(f"Surface Hair group curve radius update failed: {exc}")
    tag_redraw_all_view3d(context, rebuild=True)


def hair_preview_point_count_update(_self, context):
    try:
        from . import hair_curves

        hair_curves.refresh_existing_group_preset_previews(context, get_settings(context))
    except Exception as exc:
        print(f"Surface Hair preset point count update failed: {exc}")
    tag_redraw_all_view3d(context)


def preset_slot_update(self, context):
    try:
        from . import hair_curves

        settings = get_settings(context)
        group = hair_curves.group_for_preset_slot(settings, self)
        if group and getattr(group, "preset_enabled", False):
            hair_curves.refresh_group_preset_preview(context, settings, group)
    except Exception as exc:
        print(f"Surface Hair preset slot update failed: {exc}")
    tag_redraw_all_view3d(context, rebuild=True)


class SurfaceHairAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or ADDON_ID

    default_line_width: FloatProperty(
        name=ui_t("线宽"),
        default=6.0,
        min=1.0,
        max=24.0,
    )
    default_point_size: FloatProperty(
        name=ui_t("点大小"),
        default=12.0,
        min=3.0,
        max=48.0,
    )
    default_brush_radius: FloatProperty(
        name=ui_t("刷子半径"),
        default=28.0,
        min=4.0,
        max=240.0,
        subtype="PIXEL",
    )
    default_curve_radius: FloatProperty(
        name=ui_t("曲线半径"),
        default=0.003,
        min=0.0,
        max=1.0,
        soft_max=0.08,
        precision=4,
        step=0.1,
        subtype="DISTANCE",
    )
    default_xray: BoolProperty(name=ui_t("X-Ray 叠加"), default=True)
    default_ik_surface_lock: BoolProperty(name=ui_t("IK 贴面锁定"), default=True)
    default_snap_element: EnumProperty(
        name=ui_t("吸附元素"),
        items=SNAP_ELEMENT_ITEMS,
        default="AUTO",
    )
    hotkey_start_modal_key: EnumProperty(name=ui_t("开始工具"), items=KEY_ITEMS, default="H", update=shortcut_update)
    hotkey_start_modal_ctrl: BoolProperty(name="Ctrl", default=True, update=shortcut_update)
    hotkey_start_modal_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_start_modal_shift: BoolProperty(name="Shift", default=True, update=shortcut_update)
    hotkey_finish_key: EnumProperty(name=ui_t("完成/退出"), items=KEY_ITEMS, default="RET", update=shortcut_update)
    hotkey_finish_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_finish_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_finish_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_cancel_key: EnumProperty(name=ui_t("取消"), items=KEY_ITEMS, default="ESC", update=shortcut_update)
    hotkey_cancel_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_cancel_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_cancel_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_undo_key: EnumProperty(name=ui_t("撤销工具操作"), items=KEY_ITEMS, default="Z", update=shortcut_update)
    hotkey_undo_ctrl: BoolProperty(name="Ctrl", default=True, update=shortcut_update)
    hotkey_undo_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_undo_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_delete_last_key: EnumProperty(name=ui_t("删上一点"), items=KEY_ITEMS, default="BACK_SPACE", update=shortcut_update)
    hotkey_delete_last_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_delete_last_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_delete_last_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_cycle_tool_key: EnumProperty(name=ui_t("循环模式"), items=KEY_ITEMS, default="TAB", update=shortcut_update)
    hotkey_cycle_tool_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_cycle_tool_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_cycle_tool_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_draw_tool_key: EnumProperty(name=ui_t("绘制模式"), items=KEY_ITEMS, default="D", update=shortcut_update)
    hotkey_draw_tool_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_draw_tool_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_draw_tool_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_control_tool_key: EnumProperty(name=ui_t("编辑模式"), items=KEY_ITEMS, default="E", update=shortcut_update)
    hotkey_control_tool_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_control_tool_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_control_tool_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_control_tool_alt_key: EnumProperty(name=ui_t("编辑模式备用"), items=KEY_ITEMS, default="G", update=shortcut_update)
    hotkey_control_tool_alt_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_control_tool_alt_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_control_tool_alt_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_interpolate_tool_key: EnumProperty(name=ui_t("插值模式"), items=KEY_ITEMS, default="L", update=shortcut_update)
    hotkey_interpolate_tool_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_interpolate_tool_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_interpolate_tool_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_select_tool_key: EnumProperty(name=ui_t("选择模式"), items=KEY_ITEMS, default="A", update=shortcut_update)
    hotkey_select_tool_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_select_tool_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_select_tool_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_duplicate_selected_key: EnumProperty(name=ui_t("复制曲线"), items=KEY_ITEMS, default="D", update=shortcut_update)
    hotkey_duplicate_selected_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_duplicate_selected_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_duplicate_selected_shift: BoolProperty(name="Shift", default=True, update=shortcut_update)
    hotkey_toggle_paint_key: EnumProperty(name=ui_t("切换绘制方式"), items=KEY_ITEMS, default="P", update=shortcut_update)
    hotkey_toggle_paint_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_paint_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_paint_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_increase_key: EnumProperty(name=ui_t("增加数值"), items=KEY_ITEMS, default="EQUAL", update=shortcut_update)
    hotkey_increase_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_increase_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_increase_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_decrease_key: EnumProperty(name=ui_t("减少数值"), items=KEY_ITEMS, default="MINUS", update=shortcut_update)
    hotkey_decrease_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_decrease_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_decrease_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_ik_points_up_key: EnumProperty(name=ui_t("IK点数增加"), items=KEY_ITEMS, default="PAGE_UP", update=shortcut_update)
    hotkey_ik_points_up_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_ik_points_up_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_ik_points_up_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_ik_points_down_key: EnumProperty(name=ui_t("IK点数减少"), items=KEY_ITEMS, default="PAGE_DOWN", update=shortcut_update)
    hotkey_ik_points_down_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_ik_points_down_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_ik_points_down_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_snap_key: EnumProperty(name=ui_t("吸附开关"), items=KEY_ITEMS, default="S", update=shortcut_update)
    hotkey_toggle_snap_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_snap_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_snap_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_ik_key: EnumProperty(name=ui_t("IK开关"), items=KEY_ITEMS, default="I", update=shortcut_update)
    hotkey_toggle_ik_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_ik_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_ik_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_ik_snap_key: EnumProperty(name=ui_t("IK吸附开关"), items=KEY_ITEMS, default="I", update=shortcut_update)
    hotkey_toggle_ik_snap_ctrl: BoolProperty(name="Ctrl", default=True, update=shortcut_update)
    hotkey_toggle_ik_snap_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_ik_snap_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_surface_lock_key: EnumProperty(name=ui_t("贴面锁定"), items=KEY_ITEMS, default="K", update=shortcut_update)
    hotkey_toggle_surface_lock_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_surface_lock_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_surface_lock_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_root_lock_key: EnumProperty(name=ui_t("发根锁定"), items=KEY_ITEMS, default="R", update=shortcut_update)
    hotkey_toggle_root_lock_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_root_lock_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_root_lock_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_handle_snap_key: EnumProperty(name=ui_t("弯曲吸附"), items=KEY_ITEMS, default="NONE", update=shortcut_update)
    hotkey_toggle_handle_snap_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_handle_snap_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_handle_snap_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_cycle_confirm_key: EnumProperty(name=ui_t("切换完成方式"), items=KEY_ITEMS, default="NONE", update=shortcut_update)
    hotkey_cycle_confirm_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_cycle_confirm_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_cycle_confirm_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_hud_key: EnumProperty(name=ui_t("HUD开关"), items=KEY_ITEMS, default="H", update=shortcut_update)
    hotkey_toggle_hud_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_hud_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_hud_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_control_points_key: EnumProperty(name=ui_t("控制点显示"), items=KEY_ITEMS, default="P", update=shortcut_update)
    hotkey_toggle_control_points_ctrl: BoolProperty(name="Ctrl", default=True, update=shortcut_update)
    hotkey_toggle_control_points_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_control_points_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_group_visible_key: EnumProperty(name=ui_t("分组显示"), items=KEY_ITEMS, default="V", update=shortcut_update)
    hotkey_toggle_group_visible_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_group_visible_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_group_visible_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_group_solo_key: EnumProperty(name=ui_t("分组独显"), items=KEY_ITEMS, default="O", update=shortcut_update)
    hotkey_toggle_group_solo_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_group_solo_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_toggle_group_solo_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_guide_box_select_key: EnumProperty(name=ui_t("导引线框选"), items=KEY_ITEMS, default="B", update=shortcut_update)
    hotkey_guide_box_select_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_guide_box_select_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_guide_box_select_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_guide_brush_select_key: EnumProperty(name=ui_t("导引线刷选"), items=KEY_ITEMS, default="C", update=shortcut_update)
    hotkey_guide_brush_select_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_guide_brush_select_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_guide_brush_select_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_add_group_key: EnumProperty(name=ui_t("新建分组"), items=KEY_ITEMS, default="G", update=shortcut_update)
    hotkey_add_group_ctrl: BoolProperty(name="Ctrl", default=True, update=shortcut_update)
    hotkey_add_group_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_add_group_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_assign_group_key: EnumProperty(name=ui_t("移入当前分组"), items=KEY_ITEMS, default="M", update=shortcut_update)
    hotkey_assign_group_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_assign_group_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_assign_group_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_merge_group_key: EnumProperty(name=ui_t("合并当前分组"), items=KEY_ITEMS, default="J", update=shortcut_update)
    hotkey_merge_group_ctrl: BoolProperty(name="Ctrl", default=True, update=shortcut_update)
    hotkey_merge_group_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_merge_group_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_convert_group_hair_key: EnumProperty(name=ui_t("当前分组转发丝"), items=KEY_ITEMS, default="J", update=shortcut_update)
    hotkey_convert_group_hair_ctrl: BoolProperty(name="Ctrl", default=True, update=shortcut_update)
    hotkey_convert_group_hair_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_convert_group_hair_shift: BoolProperty(name="Shift", default=True, update=shortcut_update)
    hotkey_delete_selected_key: EnumProperty(name=ui_t("删除曲线"), items=KEY_ITEMS, default="X", update=shortcut_update)
    hotkey_delete_selected_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_delete_selected_alt: BoolProperty(name="Alt", default=False, update=shortcut_update)
    hotkey_delete_selected_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    hotkey_toggle_xray_key: EnumProperty(name=ui_t("X-Ray开关"), items=KEY_ITEMS, default="Z", update=shortcut_update)
    hotkey_toggle_xray_ctrl: BoolProperty(name="Ctrl", default=False, update=shortcut_update)
    hotkey_toggle_xray_alt: BoolProperty(name="Alt", default=True, update=shortcut_update)
    hotkey_toggle_xray_shift: BoolProperty(name="Shift", default=False, update=shortcut_update)
    wheel_group_cycle: EnumProperty(name=ui_t("切换分组"), items=WHEEL_MODIFIER_ITEMS, default="ALT", update=shortcut_update)
    wheel_snap_cycle: EnumProperty(name=ui_t("切换吸附元素"), items=WHEEL_MODIFIER_ITEMS, default="CTRL", update=shortcut_update)
    wheel_adjust: EnumProperty(name=ui_t("调整刷子半径"), items=WHEEL_MODIFIER_ITEMS, default="SHIFT", update=shortcut_update)
    wheel_shrink_strength: EnumProperty(name=ui_t("调整收缩强度"), items=WHEEL_MODIFIER_ITEMS, default="CTRL_SHIFT", update=shortcut_update)
    wheel_shrink_tail: EnumProperty(name=ui_t("调整尾端固定点数"), items=WHEEL_MODIFIER_ITEMS, default="ALT_SHIFT", update=shortcut_update)
    wheel_smooth_strength: EnumProperty(name=ui_t("调整平滑强度"), items=WHEEL_MODIFIER_ITEMS, default="SHIFT", update=shortcut_update)

    def draw(self, context):
        layout = localized_layout(self.layout)
        col = layout.column(align=True)
        col.label(text=ui_t("默认参数"))
        col.prop(self, "default_line_width")
        col.prop(self, "default_point_size")
        col.prop(self, "default_brush_radius")
        col.prop(self, "default_curve_radius")
        col.prop(self, "default_xray")
        col.prop(self, "default_ik_surface_lock")
        col.prop(self, "default_snap_element")
        box = layout.box()
        box.label(text=ui_t("快捷键默认配置"))
        draw_shortcut_row(box, self, "开始工具", "start_modal")
        draw_shortcut_row(box, self, "完成/退出", "finish")
        draw_shortcut_row(box, self, "取消", "cancel")
        draw_shortcut_row(box, self, "撤销工具操作", "undo")
        draw_shortcut_row(box, self, "删上一点", "delete_last")
        draw_shortcut_row(box, self, "循环模式", "cycle_tool")
        draw_shortcut_row(box, self, "绘制模式", "draw_tool")
        draw_shortcut_row(box, self, "编辑模式", "control_tool")
        draw_shortcut_row(box, self, "编辑备用", "control_tool_alt")
        draw_shortcut_row(box, self, "插值模式", "interpolate_tool")
        draw_shortcut_row(box, self, "选择模式", "select_tool")
        draw_shortcut_row(box, self, "复制曲线", "duplicate_selected")
        draw_shortcut_row(box, self, "切换绘制方式", "toggle_paint")
        draw_shortcut_row(box, self, "增加数值", "increase")
        draw_shortcut_row(box, self, "减少数值", "decrease")
        draw_shortcut_row(box, self, "IK点数+", "ik_points_up")
        draw_shortcut_row(box, self, "IK点数-", "ik_points_down")
        draw_shortcut_row(box, self, "吸附开关", "toggle_snap")
        draw_shortcut_row(box, self, "IK开关", "toggle_ik")
        draw_shortcut_row(box, self, "IK吸附", "toggle_ik_snap")
        draw_shortcut_row(box, self, "贴面锁定", "toggle_surface_lock")
        draw_shortcut_row(box, self, "发根锁定", "toggle_root_lock")
        draw_shortcut_row(box, self, "弯曲吸附", "toggle_handle_snap")
        draw_shortcut_row(box, self, "HUD开关", "toggle_hud")
        draw_shortcut_row(box, self, "控制点显示", "toggle_control_points")
        draw_shortcut_row(box, self, "分组显示", "toggle_group_visible")
        draw_shortcut_row(box, self, "分组独显", "toggle_group_solo")
        draw_shortcut_row(box, self, "导引线框选", "guide_box_select")
        draw_shortcut_row(box, self, "导引线刷选", "guide_brush_select")
        draw_shortcut_row(box, self, "新建分组", "add_group")
        draw_shortcut_row(box, self, "移入当前分组", "assign_group")
        draw_shortcut_row(box, self, "合并当前分组", "merge_group")
        draw_shortcut_row(box, self, "当前分组转发丝", "convert_group_hair")
        draw_shortcut_row(box, self, "删除曲线", "delete_selected")
        draw_shortcut_row(box, self, "X-Ray开关", "toggle_xray")
        row = box.row(align=True)
        row.label(text=ui_t("滚轮分组"))
        row.prop(self, "wheel_group_cycle", text="")
        row = box.row(align=True)
        row.label(text=ui_t("滚轮吸附"))
        row.prop(self, "wheel_snap_cycle", text="")
        row = box.row(align=True)
        row.label(text=ui_t("滚轮刷子半径"))
        row.prop(self, "wheel_adjust", text="")
        row = box.row(align=True)
        row.label(text=ui_t("滚轮收缩强度"))
        row.prop(self, "wheel_shrink_strength", text="")
        row = box.row(align=True)
        row.label(text=ui_t("滚轮尾端固定"))
        row.prop(self, "wheel_shrink_tail", text="")
        row = box.row(align=True)
        row.label(text=ui_t("滚轮平滑强度"))
        row.prop(self, "wheel_smooth_strength", text="")


class SurfaceHairPresetSlot(bpy.types.PropertyGroup):
    name: StringProperty(name=ui_t("名称"), default="预设")
    node_group: PointerProperty(
        name=ui_t("节点组"),
        description=ui_t("当前预设槽使用的 Geometry Nodes 节点组"),
        type=bpy.types.NodeTree,
        poll=geometry_node_group_poll,
        update=preset_slot_update,
    )
    enabled: BoolProperty(name=ui_t("启用"), default=True, update=preset_slot_update)
    expanded: BoolProperty(name=ui_t("展开"), default=True)
    modifier_name: StringProperty(name=ui_t("修改器"), default="")
    stored_values: StringProperty(name=ui_t("参数缓存"), default="")


class SurfaceHairGroup(bpy.types.PropertyGroup):
    name: StringProperty(name=ui_t("名称"), default="分组")
    group_id: StringProperty(name=ui_t("分组 ID"), default="")
    collection_name: StringProperty(name=ui_t("合集"), default="")
    preset_node_group: PointerProperty(
        name=ui_t("预设节点组"),
        description=ui_t("给当前分组预览和最终 Hair Curves 使用的 Geometry Nodes 节点组"),
        type=bpy.types.NodeTree,
        poll=geometry_node_group_poll,
        update=group_preset_settings_update,
    )
    preset_enabled: BoolProperty(
        name=ui_t("启用预设"),
        description=ui_t("开启后为当前分组生成 Hair Curves 预览对象，并挂载所选预设节点组"),
        default=False,
        update=group_preset_enabled_update,
    )
    preset_live_update: BoolProperty(
        name=ui_t("实时更新"),
        description=ui_t("开启后绘制、编辑、删除、插值等提交操作会自动刷新当前分组预设预览；关闭后需要手动刷新"),
        default=True,
        update=group_preset_live_update,
    )
    preset_slots: CollectionProperty(type=SurfaceHairPresetSlot)
    preset_slot_index: IntProperty(name=ui_t("预设索引"), default=-1)
    preview_object_name: StringProperty(name=ui_t("预览对象"), default="")
    color: FloatVectorProperty(
        name=ui_t("颜色"),
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 0.8, 0.25, 1.0),
        update=rebuild_overlay_update,
    )
    visible: BoolProperty(name=ui_t("显示"), default=True, update=sync_curve_object_states_update)
    locked: BoolProperty(name=ui_t("锁定"), default=False, update=sync_curve_object_states_update)
    solo: BoolProperty(name=ui_t("独显"), default=False, update=sync_curve_object_states_update)
    display_strength: FloatProperty(
        name=ui_t("显示强度"),
        default=1.0,
        min=0.05,
        max=1.0,
        update=rebuild_overlay_update,
    )
    curve_radius: FloatProperty(
        name=ui_t("曲线半径"),
        description=ui_t("当前分组插件导引曲线的显示半径；修改后会同步这个分组已生成的曲线"),
        default=0.003,
        min=0.0,
        max=1.0,
        soft_max=0.08,
        precision=4,
        step=0.1,
        subtype="DISTANCE",
        update=group_curve_radius_update,
    )


class SurfaceHairCurveItem(bpy.types.PropertyGroup):
    name: StringProperty(name=ui_t("名称"), default="曲线")
    curve_id: StringProperty(name=ui_t("曲线 ID"), default="")
    group_id: StringProperty(name=ui_t("分组 ID"), default="")
    object: PointerProperty(name=ui_t("曲线对象"), type=bpy.types.Object)
    surface_object: PointerProperty(name=ui_t("表面对象"), type=bpy.types.Object)
    selected: BoolProperty(name=ui_t("选中"), default=False, update=redraw_overlay_update)
    hidden: BoolProperty(name=ui_t("隐藏"), default=False, update=sync_curve_object_states_update)
    locked: BoolProperty(name=ui_t("锁定"), default=False, update=sync_curve_object_states_update)
    is_hair_export: BoolProperty(name=ui_t("Hair 导出"), default=False)


class SurfaceHairToolSettings(bpy.types.PropertyGroup):
    tool: EnumProperty(name=ui_t("工具"), items=TOOL_ITEMS, default="DRAW", update=interpolation_preview_update)
    draw_mode: EnumProperty(name=ui_t("绘制模式"), items=DRAW_MODE_ITEMS, default="CLICK", update=redraw_overlay_update)
    confirm_mode: EnumProperty(name=ui_t("完成方式"), items=CONFIRM_MODE_ITEMS, default="RIGHT_CLICK", update=redraw_overlay_update)
    snap_enabled: BoolProperty(name=ui_t("吸附"), default=True, update=redraw_overlay_update)
    snap_element: EnumProperty(name=ui_t("吸附元素"), items=SNAP_ELEMENT_ITEMS, default="AUTO", update=interpolation_preview_update)
    surface_filter: EnumProperty(
        name=ui_t("吸附目标"),
        items=SURFACE_FILTER_ITEMS,
        default="VISIBLE",
        update=redraw_overlay_update,
    )
    scalp_root_snap: BoolProperty(
        name=ui_t("头皮发根吸附"),
        description=ui_t("开启后绘制每根曲线的第一个点只吸附到指定头皮对象，其余点仍使用普通吸附目标"),
        default=False,
        update=redraw_overlay_update,
    )
    scalp_object: PointerProperty(
        name=ui_t("头皮对象"),
        description=ui_t("发根专用吸附的头皮网格对象"),
        type=bpy.types.Object,
        poll=mesh_object_poll,
        update=redraw_overlay_update,
    )
    curve_radius: FloatProperty(
        name=ui_t("生成曲线半径"),
        description=ui_t("新建、复制、插值生成的插件曲线圆形截面半径；设为 0 可生成无厚度曲线"),
        default=0.003,
        min=0.0,
        max=1.0,
        soft_max=0.08,
        precision=4,
        step=0.1,
        subtype="DISTANCE",
        update=redraw_overlay_update,
    )
    shrink_strength: FloatProperty(
        name=ui_t("收缩强度"),
        description=ui_t("Ctrl+Shift 单击尾点时，中间控制点向首端到尾端固定段的轴线收缩的强度"),
        default=0.18,
        min=0.01,
        max=0.8,
        subtype="FACTOR",
        update=redraw_overlay_update,
    )
    shrink_tail_fixed_points: IntProperty(
        name=ui_t("尾端固定档"),
        description=ui_t("Ctrl+Shift 收缩时从尾端往前固定的控制点数量；0 为旧行为，滚轮三格固定最后三个点，首端始终固定"),
        default=0,
        min=0,
        max=32,
        update=redraw_overlay_update,
    )
    smooth_strength: FloatProperty(
        name=ui_t("平滑强度"),
        description=ui_t("Shift 单击尾点平滑曲线时使用的强度"),
        default=0.55,
        min=0.05,
        max=0.95,
        subtype="FACTOR",
        update=redraw_overlay_update,
    )
    smooth_surface_lock: BoolProperty(
        name=ui_t("平滑后贴面"),
        description=ui_t("Shift 平滑后把控制点重新投射到曲线记录的表面对象；关闭可保持空间平滑结果"),
        default=True,
        update=redraw_overlay_update,
    )
    ik_enabled: BoolProperty(
        name=ui_t("IK 模式"),
        description=ui_t("开启后拖动控制点会按控制点数量向两侧链式衰减；Shift 拖动仍可临时启用 IK"),
        default=True,
        update=redraw_overlay_update,
    )
    ik_snap: BoolProperty(name=ui_t("IK 吸附"), default=True, update=redraw_overlay_update)
    surface_lock: BoolProperty(name=ui_t("贴面锁定"), default=True, update=redraw_overlay_update)
    root_lock: BoolProperty(name=ui_t("锁定发根"), default=True, update=redraw_overlay_update)
    falloff_radius: FloatProperty(
        name=ui_t("衰减半径"),
        default=0.35,
        min=0.01,
        max=10.0,
        subtype="DISTANCE",
        update=redraw_overlay_update,
    )
    ik_falloff_points: IntProperty(
        name=ui_t("影响点数"),
        description=ui_t("IK 拖动时向两侧传播影响的控制点数量，不按空间半径计算"),
        default=3,
        min=0,
        max=32,
        update=redraw_overlay_update,
    )
    falloff_strength: FloatProperty(
        name=ui_t("衰减强度"),
        default=0.75,
        min=0.0,
        max=1.0,
        update=redraw_overlay_update,
    )
    brush_radius: FloatProperty(
        name=ui_t("刷子半径"),
        default=28.0,
        min=4.0,
        max=240.0,
        subtype="PIXEL",
        update=redraw_overlay_update,
    )
    sample_spacing: FloatProperty(
        name=ui_t("采样间距"),
        default=0.035,
        min=0.001,
        max=2.0,
        subtype="DISTANCE",
        update=redraw_overlay_update,
    )
    target_point_count: IntProperty(name=ui_t("目标点数"), default=4, min=2, max=64, update=redraw_overlay_update)
    hair_curve_point_count: IntProperty(
        name=ui_t("前置发丝点数"),
        description=ui_t("当前分组转换为 Hair Curves 前，每根发丝重采样到的点数，便于后续雕刻"),
        default=8,
        min=2,
        max=256,
        update=hair_preview_point_count_update,
    )
    interpolate_count: IntProperty(
        name=ui_t("插值数量"),
        description=ui_t("在两条相邻导引曲线之间生成的中间曲线数量"),
        default=3,
        min=1,
        max=64,
        update=interpolation_preview_update,
    )
    interpolate_point_count: IntProperty(
        name=ui_t("插值点数"),
        description=ui_t("每条插值曲线重采样后的控制点数量；数值越大越贴近导引曲线形状"),
        default=8,
        min=2,
        max=128,
        update=interpolation_preview_update,
    )
    interpolate_surface_lock: BoolProperty(
        name=ui_t("插值贴面"),
        description=ui_t("生成插值曲线时投射回导引曲线记录的表面模型"),
        default=True,
        update=interpolation_preview_update,
    )
    auto_select_new_curve: BoolProperty(name=ui_t("完成后选中新曲线"), default=True, update=redraw_overlay_update)
    continuous_draw: BoolProperty(name=ui_t("连续绘制"), default=True, update=redraw_overlay_update)
    smart_handles: BoolProperty(name=ui_t("智能弯曲"), default=True, update=redraw_overlay_update)
    handle_snap: BoolProperty(name=ui_t("弯曲吸附"), default=True, update=redraw_overlay_update)
    line_width: FloatProperty(name=ui_t("线宽"), default=6.0, min=1.0, max=24.0, update=redraw_overlay_update)
    point_size: FloatProperty(name=ui_t("点大小"), default=12.0, min=3.0, max=48.0, update=redraw_overlay_update)
    unselected_display_scale: FloatProperty(
        name=ui_t("未选中缩放"),
        description=ui_t("未选中导引线和控制点的显示缩放；选中曲线保持完整大小，便于聚焦当前头发"),
        default=0.55,
        min=0.15,
        max=1.0,
        update=redraw_overlay_update,
    )
    overlay_alpha: FloatProperty(name=ui_t("透明度"), default=0.92, min=0.05, max=1.0, update=rebuild_overlay_update)
    overlay_fast_mode: BoolProperty(
        name=ui_t("性能模式"),
        description=ui_t("线很多时使用合批绘制和简化未选中控制点，降低视口 UI 开销"),
        default=True,
        update=rebuild_overlay_update,
    )
    show_control_points: BoolProperty(name=ui_t("显示控制点"), default=True, update=redraw_overlay_update)
    show_handles: BoolProperty(name=ui_t("调试显示手柄"), default=False, update=rebuild_overlay_update)
    show_hud: BoolProperty(name=ui_t("显示快捷 HUD"), default=True, update=redraw_overlay_update)
    xray: BoolProperty(name="X-Ray", default=True, update=redraw_overlay_update)
    library_preset_id: EnumProperty(name=ui_t("预设库"), items=preset_library_items)
    library_preset_name: StringProperty(
        name=ui_t("预设名称"),
        description=ui_t("保存当前分组预设栈时使用的名称"),
        default="",
    )
    ui_group_expanded: BoolProperty(name=ui_t("展开分组面板"), default=True)
    ui_curve_expanded: BoolProperty(name=ui_t("展开曲线面板"), default=True)
    live_status: StringProperty(name=ui_t("状态"), default="就绪")
    groups: CollectionProperty(type=SurfaceHairGroup)
    group_index: IntProperty(name="Group Index", default=0)
    curves: CollectionProperty(type=SurfaceHairCurveItem)
    curve_index: IntProperty(name="Curve Index", default=-1)


classes = (
    SurfaceHairAddonPreferences,
    SurfaceHairPresetSlot,
    SurfaceHairGroup,
    SurfaceHairCurveItem,
    SurfaceHairToolSettings,
)


def register():
    bpy.types.Scene.surface_hair_language = EnumProperty(name="Language", items=LANGUAGES, default="en", update=redraw)
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.surface_hair_curve_tool = PointerProperty(type=SurfaceHairToolSettings)


def unregister():
    if hasattr(bpy.types.Scene, "surface_hair_language"):
        del bpy.types.Scene.surface_hair_language
    if hasattr(bpy.types.Scene, ADDON_ID):
        del bpy.types.Scene.surface_hair_curve_tool
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
