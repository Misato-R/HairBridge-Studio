from .i18n import t as ui_t, localized_layout
"""Selected-guide editing and transport of the actual SHP cross-sections."""

import bpy
import numpy as np

from . import hairdeck_bridge as bridge
from .hairdeck_bridge.mapping import RADIUS, SECTION_SIDES, geometry, make_profile, select_only

UTILITY = "utility_settings"
PROFILE_SOCKET = "utils_cust_geo_object"
OWNED_PROFILE = "hairbridge_owned_profile"


def is_editable_guide(obj):
    return obj is not None and obj.type == "CURVE" and bool(
        obj.get("hairdeck_card_json") or obj.get("hairbridge_strand_id") is not None
    )


def points(data):
    if len(data.splines) != 1:
        raise ValueError(ui_t("请选择只有一条路径的发束。"))
    spline = data.splines[0]
    if spline.type != "BEZIER" or spline.use_cyclic_u or len(spline.bezier_points) < 2:
        raise ValueError(ui_t("需要一条从发根到发梢的开放 Bézier 导线。"))
    return spline.bezier_points


def apply_profile(context, guide, profile, shp):
    shp.shp_set_value(UTILITY, PROFILE_SOCKET, profile, guide)
    profile.update_tag()
    guide.update_tag()
    context.view_layer.update()


def current_profile(guide, shp):
    if shp.shp_modifier_name not in guide.modifiers:
        raise ValueError(ui_t("此发束缺少 SHP 修改器。"))
    source = shp.shp_read_value(UTILITY, PROFILE_SOCKET, guide)
    if not (source and source.type == "MESH" and shp.shp_read_value(UTILITY, "utils_cust_geo_enable", guide)):
        raise ValueError(ui_t("此发束缺少可编辑的 SHP 自定义截面。"))
    if shp.shp_read_value(UTILITY, "utils_cust_geo_rescale", guide):
        raise ValueError(ui_t("请关闭该发束的 SHP 自定义网格自动缩放。"))
    return source


def profile_data(profile):
    mesh = profile.data
    coordinates = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    mesh.vertices.foreach_get("co", coordinates.ravel())
    stations, rows = np.unique(coordinates[:, 2], return_inverse=True)
    if len(stations) < 2 or not np.isfinite(coordinates).all():
        raise ValueError(ui_t("此发束的截面采样无效。"))
    attribute = mesh.attributes.get(bridge.REST)
    rest = None
    if attribute is not None and attribute.data_type == "FLOAT_VECTOR" and attribute.domain == "POINT":
        rest = np.empty_like(coordinates)
        attribute.data.foreach_get("vector", rest.ravel())
    return coordinates, stations, rows, rest


def profile_copy(source, coordinates, rest):
    name = f"{source.get('hairbridge_profile_label', source.name)} · HairBridge"
    obj = source.copy()
    obj.data = source.data.copy()
    obj.name = name
    obj[OWNED_PROFILE] = True
    obj["hairbridge_profile_label"] = source.get("hairbridge_profile_label", source.name)
    for collection in source.users_collection[:1]:
        collection.objects.link(obj)
    if not obj.users_collection:
        bpy.context.scene.collection.objects.link(obj)
    obj.matrix_world = source.matrix_world
    obj.hide_set(True)
    obj.hide_render = True
    try:
        obj.data.vertices.foreach_set("co", np.ascontiguousarray(coordinates, dtype=np.float32).ravel())
        if rest is not None:
            obj.data.attributes[bridge.REST].data.foreach_set("vector", np.ascontiguousarray(rest, dtype=np.float32).ravel())
        obj.data.update()
    except Exception:
        remove_probe(obj)
        raise
    return obj


def remove_probe(obj):
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def release_profile(profile):
    if profile and profile.get(OWNED_PROFILE) and profile.users == len(profile.users_collection):
        remove_probe(profile)


def native_frames(context, guide, source, stations, shp):
    probe, _ = make_profile(context.scene.collection, 0, stations)
    probe.matrix_world = source.matrix_world
    try:
        apply_profile(context, guide, probe, shp)
        observed, _ = geometry(guide)
        if observed.shape != (len(stations) * 4, 3):
            raise ValueError(ui_t("现有 SHP 参数改变了截面拓扑，请保留一个可校准的发束。"))
        rings = observed.reshape(-1, 4, 3)
        matrices = np.stack(((rings[:, 0] - rings[:, 2]) / (2 * RADIUS),
                             (rings[:, 1] - rings[:, 3]) / (2 * RADIUS)), axis=1)
        if np.linalg.svd(matrices, compute_uv=False).min() < 1e-6:
            raise ValueError(ui_t("当前导线上有无法定位截面的退化区间。"))
        return rings.mean(axis=1), matrices
    finally:
        apply_profile(context, guide, source, shp)
        remove_probe(probe)


def arc_length(path):
    return np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]


def interpolate(query, positions, values):
    return np.column_stack([np.interp(query, positions, values[:, axis]) for axis in range(values.shape[1])])


def ordered_stations(expected, target, coordinates, nominal, penalty):
    """Match physical sections in order, without hopping across a folded guide."""
    cost = ((expected[:, None, :] - target[None, :, :]) ** 2).sum(axis=2)
    cost += (penalty * (coordinates[None, :] - nominal[:, None])) ** 2
    column = np.arange(len(coordinates))
    cost[0, 1:] = np.inf
    cost[-1, :-1] = np.inf
    links = np.zeros(cost.shape, dtype=int)
    scores = cost[0].copy()
    for row in range(1, len(expected)):
        spacing = (nominal[row] - nominal[row - 1]) / 3
        available = np.searchsorted(coordinates, coordinates - spacing, side="left") - 1
        best = np.minimum.accumulate(scores)
        indices = np.maximum.accumulate(np.where(scores <= best, column, 0))
        links[row] = indices[available.clip(min=0)]
        scores = cost[row] + best[available.clip(min=0)]
        scores[available < 0] = np.inf
    choice = np.empty(len(expected), dtype=int)
    choice[-1] = int(np.argmin(scores))
    if not np.isfinite(scores[choice[-1]]):
        raise ValueError(ui_t("导线变化太大，无法沿原顺序保留截面。"))
    for row in range(len(expected) - 1, 0, -1):
        choice[row - 1] = links[row, choice[row]]
    return coordinates[choice]


def unit_rows(vectors):
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def section_transport(old_axes, new_axes):
    n0 = unit_rows(np.cross(old_axes[:, 0], old_axes[:, 1]))
    n1 = unit_rows(np.cross(new_axes[:, 0], new_axes[:, 1]))
    rotation = np.cross(n0, n1)[:, None, :]
    cosine = np.sum(n0 * n1, axis=1)[:, None, None]
    if cosine.min() <= -.98:
        raise ValueError(ui_t("截面的切向发生了急转弯，请先平顺导线。"))
    rotated = old_axes + np.cross(rotation, old_axes) + np.cross(rotation, np.cross(rotation, old_axes)) / (1 + cosine)
    return rotated @ np.linalg.pinv(new_axes)


def section_plan(context, guide, source, old_data, new_data, surface, shp):
    _, stations, _, _ = profile_data(source)
    guide.data = old_data
    try:
        old_path = np.asarray(surface.curve_data.sample_bezier_world(guide, resolution=32), dtype=float)
        old_centers, old_axes = native_frames(context, guide, source, stations, shp)
    finally:
        guide.data = new_data
        context.view_layer.update()
    new_path = np.asarray(surface.curve_data.sample_bezier_world(guide, resolution=32), dtype=float)
    if np.array_equal(old_path, new_path):
        return None
    old_arc, new_arc = arc_length(old_path), arc_length(new_path)
    if min(old_arc[-1], new_arc[-1]) < 1e-8:
        raise ValueError(ui_t("需要保留一条有长度的导线。"))
    coordinates = np.arange(len(old_path), dtype=float)
    progress = (stations - stations[0]) / (stations[-1] - stations[0])
    positions = np.interp(ordered_stations(old_centers, old_path, old_arc, progress * old_arc[-1], .30), old_arc, coordinates)
    expected = old_centers + interpolate(positions, coordinates, new_path - old_path)
    probe_positions = np.linspace(stations[0], stations[-1], max(257, len(stations) * 12 + 1))
    probe_centers, _ = native_frames(context, guide, source, probe_positions, shp)
    nominal = stations[0] + np.interp(positions, coordinates, new_arc) / new_arc[-1] * (stations[-1] - stations[0])
    new_stations = ordered_stations(expected, probe_centers, probe_positions, nominal, .16)
    _, new_axes = native_frames(context, guide, source, new_stations, shp)
    return stations, new_stations, section_transport(old_axes, new_axes)


def transport_profile(source, plan):
    coordinates, stations, rows, rest = profile_data(source)
    expected_stations, new_stations, transform = plan
    if not np.array_equal(stations, expected_stations):
        raise ValueError(ui_t("截面位置与当前发束不同，请先完成这次截面修改。"))

    def apply(values):
        result = values.copy()
        result[:, :2] = np.einsum("ni,nij->nj", values[:, :2], transform[rows])
        result[:, 2] = new_stations[rows]
        return result

    return profile_copy(source, apply(coordinates), apply(rest) if rest is not None else None)


def section_adjustment(context, guide, source, width, thickness, angle, tip, start, shp):
    coordinates, stations, rows, rest = profile_data(source)
    _, axes = native_frames(context, guide, source, stations, shp)
    width_axis = unit_rows(axes[:, 0])
    normals = unit_rows(np.cross(axes[:, 0], axes[:, 1]))
    height_axis = np.cross(normals, width_axis)
    # The imported profiles have a specifically authored width axis.
    sides = source.get(SECTION_SIDES, 4)
    if rest is not None and len(coordinates) == len(stations) * sides and np.array_equal(rows, np.repeat(np.arange(len(stations)), sides)):
        rings = coordinates.reshape(-1, sides, 3)
        spokes = np.einsum("ni,nij->nj", rings[:, 0, :2] - rings[:, sides//2, :2], axes)
        lengths = np.linalg.norm(spokes, axis=1)
        width_axis[lengths > 1e-9] = unit_rows(spokes[lengths > 1e-9])
        height_axis = np.cross(normals, width_axis)
    blend = np.clip(((stations - stations[0]) / (stations[-1] - stations[0]) - start) / (1 - start), 0, 1)
    blend = blend * blend * (3 - 2 * blend)
    radial = 1 + blend * (tip - 1)
    cos, sin = np.cos(blend * angle), np.sin(blend * angle)
    scales = np.stack(((1 + blend * (width - 1)) * radial, (1 + blend * (thickness - 1)) * radial), axis=-1)
    new_width = width_axis * cos[:, None] + height_axis * sin[:, None]
    new_height = height_axis * cos[:, None] - width_axis * sin[:, None]
    old_basis = np.stack((width_axis, height_axis), axis=2)
    new_basis = np.stack((new_width, new_height), axis=1)
    transform = ((axes @ old_basis) * scales[:, None, :]) @ new_basis @ np.linalg.pinv(axes)

    def apply(values):
        result = values.copy()
        result[:, :2] = np.einsum("ni,nij->nj", values[:, :2], transform[rows])
        return result

    return profile_copy(source, apply(coordinates), apply(rest) if rest is not None else None)


def clear_edit(scene):
    scene.hairbridge_edit_strand = None
    scene.hairbridge_edit_original = None
    scene.hairbridge_edit_profile = None


class HAIRBRIDGE_OT_begin_path(bpy.types.Operator):
    bl_idname = "hairbridge.begin_path_edit"
    bl_label = ui_t("开始单束走向编辑")
    bl_description = ui_t("隔离所选发束的编辑数据，移动该束的现有控制点")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.mode == "OBJECT" and not context.scene.hairbridge_edit_strand
                and is_editable_guide(context.active_object))

    def execute(self, context):
        guide = context.active_object
        scene = context.scene
        old = guide.data
        temporary = None
        try:
            _, shp = bridge.hair_tools()
            profile = current_profile(guide, shp)
            original = points(old)
            if len(original) <= int(scene.hairbridge_lock_root) + int(scene.hairbridge_lock_tip):
                raise ValueError(ui_t("锁定后没有可移动的控制点。"))
            select_only(guide)
            temporary = old.copy()
            guide.data = temporary
            controls = points(temporary)
            for pin, point in ((scene.hairbridge_lock_root, controls[0]), (scene.hairbridge_lock_tip, controls[-1])):
                if pin:
                    point.select_control_point = point.select_left_handle = point.select_right_handle = False
                    point.hide = True
            scene.hairbridge_edit_strand = guide
            scene.hairbridge_edit_original = old
            scene.hairbridge_edit_profile = profile
            scene["hairbridge_pinned_ends"] = [scene.hairbridge_lock_root, scene.hairbridge_lock_tip]
            if bpy.ops.object.mode_set(mode="EDIT") != {"FINISHED"}:
                raise ValueError(ui_t("无法进入此发束的编辑模式。"))
        except Exception as exc:
            guide.data = old
            clear_edit(scene)
            if temporary and temporary.users == 0:
                bpy.data.curves.remove(temporary)
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}
        return {"FINISHED"}


class HAIRBRIDGE_OT_finish_path(bpy.types.Operator):
    bl_idname = "hairbridge.finish_path_edit"
    bl_label = ui_t("确认走向并重定位截面")
    bl_description = ui_t("固定已锁定的控制点，将截面沿新弧长及切向放回所选发束")
    bl_options = {"REGISTER", "UNDO"}
    discard: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        guide = context.scene.hairbridge_edit_strand
        return guide is not None and (context.mode == "OBJECT" or context.edit_object == guide)

    def execute(self, context):
        scene = context.scene
        guide = scene.hairbridge_edit_strand
        original = scene.hairbridge_edit_original
        edited = guide.data
        if context.edit_object == guide:
            bpy.ops.object.mode_set(mode="OBJECT")
            edited = guide.data
        select_only(guide)
        if self.discard:
            guide.data = original
            clear_edit(scene)
            context.view_layer.update()
            if edited.users == 0:
                bpy.data.curves.remove(edited)
            return {"FINISHED"}
        source = scene.hairbridge_edit_profile
        copies = []
        previous = guide.hairbridge_previous_section
        try:
            surface, shp = bridge.hair_tools()
            if current_profile(guide, shp) != source:
                raise ValueError(ui_t("走向编辑期间截面已变化，请先取消此次走向编辑。"))
            old, new = points(original), points(edited)
            if len(old) != len(new):
                raise ValueError(ui_t("此次操作需保留控制点数量。请取消后移动已有控制点。"))
            pins = dict(zip((0, len(new) - 1), scene["hairbridge_pinned_ends"]))
            for index, (before, after) in enumerate(zip(old, new)):
                after.radius, after.tilt, after.hide = before.radius, before.tilt, before.hide
                if pins.get(index):
                    after.handle_left_type = after.handle_right_type = "FREE"
                    after.co = before.co
                    after.handle_left, after.handle_right = before.handle_left, before.handle_right
            context.view_layer.update()
            plan = section_plan(context, guide, source, original, edited, surface, shp)
            if plan is None:
                guide.data = original
            else:
                copies.append(transport_profile(source, plan))
                if previous:
                    copies.append(transport_profile(previous, plan))
                apply_profile(context, guide, copies[0], shp)
                geometry(guide)
                guide.hairbridge_previous_section = copies[1] if previous else None
        except Exception as exc:
            if copies:
                apply_profile(context, guide, source, shp)
                for copy in copies:
                    remove_probe(copy)
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}
        clear_edit(scene)
        if plan is None:
            if edited.users == 0:
                bpy.data.curves.remove(edited)
        else:
            if original.users == 0:
                bpy.data.curves.remove(original)
            release_profile(source)
            release_profile(previous)
        self.report({"INFO"}, ui_t("已确认这一束的走向，截面随导线重定位。"))
        return {"FINISHED"}


class HAIRBRIDGE_OT_adjust_section(bpy.types.Operator):
    bl_idname = "hairbridge.adjust_section"
    bl_label = ui_t("调整发片截面")
    bl_description = ui_t("相对当前宽厚和朝向调整所选发束，从设置的沿线位置渐变至发梢")
    bl_options = {"REGISTER", "UNDO"}
    width: bpy.props.FloatProperty(name=ui_t("宽度"), default=100, min=0, soft_max=200, max=400, subtype="PERCENTAGE")
    thickness: bpy.props.FloatProperty(name=ui_t("厚度"), default=100, min=0, soft_max=200, max=400, subtype="PERCENTAGE")
    rotation: bpy.props.FloatProperty(name=ui_t("截面朝向"), default=0, subtype="ANGLE", soft_min=-1.57, soft_max=1.57)
    tip: bpy.props.FloatProperty(name=ui_t("整体收尖"), default=100, min=0, max=100, subtype="PERCENTAGE")
    start: bpy.props.FloatProperty(name=ui_t("沿线过渡起点"), default=60, min=0, max=99, subtype="PERCENTAGE")

    @classmethod
    def poll(cls, context):
        return (context.mode == "OBJECT" and not context.scene.hairbridge_edit_strand
                and is_editable_guide(context.active_object))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if (self.width, self.thickness, self.rotation, self.tip) == (100, 100, 0, 100):
            return {"FINISHED"}
        guide = context.active_object
        copy = None
        try:
            _, shp = bridge.hair_tools()
            source = current_profile(guide, shp)
            copy = section_adjustment(context, guide, source, self.width / 100, self.thickness / 100,
                                      self.rotation, self.tip / 100, self.start / 100, shp)
            apply_profile(context, guide, copy, shp)
            geometry(guide)
            previous = guide.hairbridge_previous_section
            guide.hairbridge_previous_section = source
            release_profile(previous)
        except Exception as exc:
            if copy:
                apply_profile(context, guide, source, shp)
                remove_probe(copy)
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}
        return {"FINISHED"}


class HAIRBRIDGE_OT_restore_section(bpy.types.Operator):
    bl_idname = "hairbridge.restore_section"
    bl_label = ui_t("撤销最近截面调整")
    bl_description = ui_t("恢复所选发束的上一版截面，保留当前导线")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        guide = context.active_object
        return (context.mode == "OBJECT" and not context.scene.hairbridge_edit_strand and is_editable_guide(guide)
                and guide.hairbridge_previous_section is not None)

    def execute(self, context):
        guide = context.active_object
        try:
            _, shp = bridge.hair_tools()
            current = current_profile(guide, shp)
            previous = guide.hairbridge_previous_section
            apply_profile(context, guide, previous, shp)
            guide.hairbridge_previous_section = None
            release_profile(current)
        except Exception as exc:
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (HAIRBRIDGE_OT_begin_path, HAIRBRIDGE_OT_finish_path, HAIRBRIDGE_OT_adjust_section, HAIRBRIDGE_OT_restore_section)
SCENE_PROPS = {
    "hairbridge_edit_strand": lambda: bpy.props.PointerProperty(type=bpy.types.Object),
    "hairbridge_edit_original": lambda: bpy.props.PointerProperty(type=bpy.types.Curve),
    "hairbridge_edit_profile": lambda: bpy.props.PointerProperty(type=bpy.types.Object),
    "hairbridge_lock_root": lambda: bpy.props.BoolProperty(name=ui_t("锁定发根"), default=True),
    "hairbridge_lock_tip": lambda: bpy.props.BoolProperty(name=ui_t("锁定发梢"), default=True),
}


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name, factory in SCENE_PROPS.items():
        setattr(bpy.types.Scene, name, factory())
    bpy.types.Object.hairbridge_previous_section = bpy.props.PointerProperty(type=bpy.types.Object)


def unregister():
    del bpy.types.Object.hairbridge_previous_section
    for name in SCENE_PROPS:
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
