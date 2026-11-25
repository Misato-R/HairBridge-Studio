from ..i18n import t as ui_t, localized_layout
"""Import HairDeck cards as editable Surface Hair guides with live SHP geometry."""
bl_info = {
    "name": "HairDeck JSON Bridge", "author": "IIS A2 project", "version": (0, 1, 1),
    "blender": (5, 2, 0), "location": "File > Import and View3D > Sidebar > HairDeck",
    "description": "Import editable Surface Hair guides and adjust SHP tip width and thickness",
    "category": "Import-Export",
}

import importlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector
from .mapping import SECTION_SIDES, attach_profile, make_profile, max_curve_error, select_only

REST = "hairdeck_rest_position"
WIDTH = "hairdeck_tip_width_percent"
THICKNESS = "hairdeck_tip_thickness_percent"


def dependency(name, scene_prop, relative_path):
    modules = [m for key, m in tuple(sys.modules.items()) if key.split(".")[-1] == name and m is not None]
    if modules and hasattr(bpy.types.Scene, scene_prop):
        return modules[0]
    # A Steam upgrade can leave an already installed add-on in the previous minor version.
    # Search Blender user-resource directories only; never resolve code beside the input JSON.
    current = Path(bpy.utils.resource_path("USER"))
    versions = [current]
    if current.parent.is_dir():
        older = [d for d in current.parent.iterdir() if d.name.count(".") == 1
                 and all(p.isdigit() for p in d.name.split("."))]
        versions += sorted((d for d in older if d != current and d.name.split(".")[0] == current.name.split(".")[0]),
                           key=lambda d: tuple(map(int, d.name.split("."))), reverse=True)
    module = modules[0] if modules else None
    for version in versions:
        parent = version / relative_path
        if module is None and (parent / name / "__init__.py").is_file():
            sys.path.insert(0, str(parent))
            try:
                module = importlib.import_module(name)
            finally:
                sys.path.remove(str(parent))
            break
    if module is None:
        raise RuntimeError(f"Enable the installed {name} add-on in Blender Preferences")
    if not hasattr(bpy.types.Scene, scene_prop):
        module.register()
    return module


def hair_tools():
    return (dependency("surface_hair_curve_tool", "surface_hair_curve_tool", "scripts/addons"),
            dependency("stylized_hair_pro", "shp_addon", "extensions/user_default"))


def read_cards(path):
    cards = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(cards, list) or not cards:
        raise ValueError("Expected a non-empty list of HairDeck cards")
    result = []
    for i, card in enumerate(cards):
        if not isinstance(card, dict) or card.get("shape") not in ("square", "triangle"):
            raise ValueError(f"Card {i}: expected square or triangle")
        rows = np.asarray(card.get("seq"), dtype=float)
        if rows.ndim != 2 or rows.shape[1] != 8 or len(rows) < 2 or not np.isfinite(rows).all():
            raise ValueError(f"Card {i}: expected at least two finite, eight-column samples")
        if (rows[:, 3:5] < 0).any() or np.linalg.norm(np.diff(rows[:, :3], axis=0), axis=1).sum() <= 1e-9:
            raise ValueError(f"Card {i}: invalid size or zero curve length")
        result.append((card, rows))
    return result


def fit_guide(context, surface, group, name, coords):
    obj = None
    for count in range(min(7, len(coords)), len(coords) + 1):
        ids = np.rint(np.linspace(0, len(coords)-1, count)).astype(int)
        points = [Vector(p) for p in coords[ids]]
        if obj is None:
            obj = surface.create_bezier_curve(context, points, group=group, name=name)
        else:
            surface.set_bezier_points(obj, points)
        dense = np.asarray(surface.sample_bezier_world(obj, resolution=32))
        error = max(max_curve_error(coords, dense), max_curve_error(dense, coords))
        if error <= 0.001:
            break
    else:
        # Preserve a sharp polyline corner when even fully sampled AUTO handles overshoot.
        for point in obj.data.splines[0].bezier_points:
            point.handle_left_type = point.handle_right_type = "VECTOR"
    obj.data.bevel_depth = 0
    obj["hairdeck_control_source_indices"] = ids.tolist()
    return obj


def store_rest(mesh, coords):
    attr = mesh.attributes.new(REST, "FLOAT_VECTOR", "POINT")
    attr.data.foreach_set("vector", np.ascontiguousarray(coords, dtype=np.float32).ravel())


def import_cards(context, path, section_profiles=None, centerline_offsets=None):
    cards = read_cards(path)
    if section_profiles is None:
        section_profiles = [None] * len(cards)
    if len(section_profiles) != len(cards):
        raise ValueError("Profiles must correspond to the saved guides")
    if centerline_offsets is not None:
        if len(centerline_offsets) != len(cards):
            raise ValueError("Offsets must correspond to the saved guides")
        for i, (card, rows) in enumerate(cards):
            if centerline_offsets[i] is None:
                continue
            offsets = np.asarray(centerline_offsets[i], dtype=float)
            if offsets.shape != (len(rows), 3) or not np.isfinite(offsets).all():
                raise ValueError("Invalid generated centerline offsets")
            shifted = rows.copy()
            shifted[:, :3] += offsets
            cards[i] = ({**card, "seq": shifted.tolist()}, shifted)
    sht, shp = hair_tools()
    settings = context.scene.surface_hair_curve_tool
    prev_settings = (len(settings.curves), len(settings.groups), settings.curve_index, settings.group_index)
    selection = list(context.selected_objects)
    active = context.view_layer.objects.active
    containers = (bpy.data.objects, bpy.data.meshes, bpy.data.curves, bpy.data.collections,
                  bpy.data.materials, bpy.data.node_groups)
    existing = {idblock for blocks in containers for idblock in blocks}
    wm = context.window_manager
    wm.progress_begin(0, len(cards) * 2)
    try:
        if bpy.ops.surface_hair_curve.add_group(name=path.stem) != {"FINISHED"}:
            raise RuntimeError("Surface Hair could not create the import group")
        group = settings.groups[settings.group_index]
        group.color = (0.24, 0.065, 0.040, 1)
        profiles = bpy.data.collections.new(f"{path.stem} - SHP rest profiles")
        context.scene.collection.children.link(profiles)
        guides = []
        for i, (card, rows) in enumerate(cards):
            coords = rows[:, [0, 2, 1]] * [1, -1, 1]
            obj = fit_guide(context, sht.curve_data, group, f"{path.stem} | {i:02}", coords)
            obj["hairdeck_card_index"] = i
            obj["hairdeck_source"] = str(path)
            obj["hairdeck_card_json"] = json.dumps(card, separators=(",", ":"))
            obj.color = group.color
            guides.append(obj)
            wm.progress_update(i + 1)
        for i, ((card, rows), obj) in enumerate(zip(cards, guides)):
            select_only(obj)
            if bpy.ops.wm.shp_add_setup() != {"FINISHED"}:
                raise RuntimeError(f"Card {i}: SHP setup failed")
            arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(rows[:, :3], axis=0), axis=1))]
            section = section_profiles[i]
            sides = 4
            if section is not None:
                section = np.asarray(section, dtype=float)
                if section.shape not in ((len(rows), 4, 2), (len(rows), 16, 2)) or not np.isfinite(section).all():
                    raise ValueError("Invalid section profile for the saved guide")
                sides = section.shape[1]
            profile, rest = make_profile(profiles, i, arc, sides=sides)
            attach_profile(shp, obj, profile, rest, rows, card, sections=section)
            store_rest(profile.data, rest)
            obj[WIDTH], obj[THICKNESS] = 100.0, 100.0
            wm.progress_update(len(cards) + i + 1)
        select_only(guides[0])
        settings.curve_index = next(i for i, item in enumerate(settings.curves) if item.object == guides[0])
        return guides
    except Exception:
        nc, ng, ci, gi = prev_settings
        for props, size in ((settings.curves, nc), (settings.groups, ng)):
            while len(props) > size:
                props.remove(len(props)-1)
        created = [idblock for blocks in containers for idblock in blocks if idblock not in existing]
        bpy.data.batch_remove(ids=created)
        settings.curve_index, settings.group_index = ci, gi
        for obj in selection:
            obj.select_set(True)
        context.view_layer.objects.active = active
        raise
    finally:
        wm.progress_end()


def change_tip(obj, width, thickness):
    _, shp = hair_tools()
    def profile_of(guide):
        return shp.shp_read_value("utility_settings", "utils_cust_geo_object", guide)
    profile = profile_of(obj)
    if not profile or profile.type != "MESH":
        raise ValueError("The SHP rest profile is missing")
    mesh = profile.data
    raw = np.empty(len(mesh.vertices)*3, dtype=np.float32)
    sides = profile.get(SECTION_SIDES, 4)
    if sides not in (4, 16) or len(mesh.vertices) < sides * 2 or len(mesh.vertices) % sides:
        raise ValueError("The profile does not contain supported HairBridge rings")
    attr = mesh.attributes.get(REST)
    if attr is None:
        # Also support mapped curves created by the earlier A2 prototype (100% rest shape).
        mesh.vertices.foreach_get("co", raw)
    else:
        attr.data.foreach_get("vector", raw)
    rings = raw.reshape(-1, sides, 3)
    arc = rings[:, 0, 2]
    if arc[-1] <= arc[0]:
        raise ValueError("The rest profile has zero longitudinal span")
    u = np.clip(((arc - arc[0]) / (arc[-1] - arc[0]) - 0.65) / 0.25, 0, 1)
    weight = u*u*(3-2*u)
    adjusted = rings.copy()
    scales = np.stack((1 + weight * (width / 100 - 1), 1 + weight * (thickness / 100 - 1)), axis=1)
    if sides == 4:
        adjusted[:, 0::2, :2] *= scales[:, 0, None, None]
        adjusted[:, 1::2, :2] *= scales[:, 1, None, None]
    else:
        basis = np.stack((rings[:, 0, :2] - rings[:, sides//2, :2],
                          rings[:, sides//4, :2] - rings[:, sides*3//4, :2]), axis=1)
        transform = (np.linalg.pinv(basis) * scales[:, None, :]) @ basis
        adjusted[:, :, :2] = rings[:, :, :2] @ transform
    shared = any(g != obj and g.get("hairdeck_card_json") and shp.shp_modifier_name in g.modifiers
                 and profile_of(g) == profile for g in bpy.data.objects)
    if shared:
        new = profile.copy()
        new.data = mesh.copy()
        profile.users_collection[0].objects.link(new)
        new.hide_set(True)
        shp.shp_set_value("utility_settings", "utils_cust_geo_object", new, obj)
        profile = new
    elif mesh.users > 1:
        profile.data = mesh.copy()
    mesh = profile.data
    if mesh.attributes.get(REST) is None:
        store_rest(mesh, rings)
    mesh.vertices.foreach_set("co", adjusted.ravel())
    mesh.update()
    profile.update_tag()
    obj[WIDTH], obj[THICKNESS] = float(width), float(thickness)
    obj.update_tag()


class HAIRDECK_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.hairdeck_json"
    bl_label = "Import HairDeck JSON"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        try:
            guides = import_cards(context, Path(bpy.path.abspath(self.filepath)))
        except Exception as exc:
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}
        self.report({"INFO"}, ui_t(f"Imported {len(guides)} editable HairDeck strands"))
        return {"FINISHED"}


class HAIRDECK_OT_tip(bpy.types.Operator):
    bl_idname = "hairdeck.adjust_tip"
    bl_label = ui_t("调整发梢 / Adjust Tip")
    bl_options = {"REGISTER", "UNDO"}
    width: bpy.props.FloatProperty(name=ui_t("发梢宽度 / Width"), default=100, min=0, soft_max=200, subtype="PERCENTAGE")
    thickness: bpy.props.FloatProperty(name=ui_t("发梢厚度 / Thickness"), default=100, min=0, soft_max=200, subtype="PERCENTAGE")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return context.mode == "OBJECT" and obj is not None and obj.type == "CURVE" and bool(obj.get("hairdeck_card_json"))

    def invoke(self, context, event):
        self.width = context.active_object.get(WIDTH, 100)
        self.thickness = context.active_object.get(THICKNESS, 100)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            change_tip(context.active_object, self.width, self.thickness)
        except Exception as exc:
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}
        return {"FINISHED"}


class HAIRDECK_PT_panel(bpy.types.Panel):
    bl_label = "HairDeck"
    bl_idname = "HAIRDECK_PT_bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HairDeck"

    def draw(self, context):
        layout = localized_layout(self.layout)
        layout.operator(HAIRDECK_OT_import.bl_idname, text=ui_t("导入 HairDeck JSON"), icon="IMPORT")
        obj = context.active_object
        if obj and obj.type == "CURVE" and obj.get("hairdeck_card_json"):
            layout.label(text=obj.name, icon="CURVE_BEZCURVE")
            if context.mode in {"OBJECT", "EDIT_CURVE"}:
                edit = layout.operator("object.mode_set", text="编辑走向" if context.mode == "OBJECT" else "完成走向编辑")
                edit.mode = "EDIT" if context.mode == "OBJECT" else "OBJECT"
            layout.label(text=ui_t(f"宽度 {obj.get(WIDTH,100):g}%    厚度 {obj.get(THICKNESS,100):g}%"))
            layout.operator(HAIRDECK_OT_tip.bl_idname)


def menu_import(self, context):
    localized_layout(self.layout).operator(HAIRDECK_OT_import.bl_idname, text="HairDeck Cards (.json)")


classes = (HAIRDECK_OT_import, HAIRDECK_OT_tip, HAIRDECK_PT_panel)


@bpy.app.handlers.persistent
def restore_tools(_dummy=None):
    if any(obj.type == "CURVE" and obj.get("hairdeck_card_json") for obj in bpy.data.objects):
        try:
            hair_tools()
        except RuntimeError as exc:
            print("HairDeck Bridge:", exc)


@bpy.app.handlers.persistent
def sync_shp_mode_after_history(_scene):
    # A memfile undo can restore the edit-mode SHP socket even though the
    # curve is now in Object Mode. SHP's own handler caches the previous mode.
    shp = next((m for key, m in tuple(sys.modules.items())
                if key.split(".")[-1] == "stylized_hair_pro" and hasattr(m, "shp_read_value")), None)
    scene = bpy.context.scene
    if shp is None or scene is None:
        return
    for obj in scene.objects:
        if obj.type != "CURVE" or not obj.get("hairdeck_card_json") or shp.shp_modifier_name not in obj.modifiers:
            continue
        edit = obj.mode == "EDIT"
        if shp.shp_read_value("internal_utils", "iu_edit_mode", obj) != edit:
            shp.shp_set_value("internal_utils", "iu_edit_mode", edit, obj)
            obj.update_tag()


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.app.handlers.load_post.append(restore_tools)
    bpy.app.handlers.undo_post.append(sync_shp_mode_after_history)
    bpy.app.handlers.redo_post.append(sync_shp_mode_after_history)
    bpy.app.timers.register(restore_tools, first_interval=0.2)


def unregister():
    if bpy.app.timers.is_registered(restore_tools):
        bpy.app.timers.unregister(restore_tools)
    bpy.app.handlers.load_post.remove(restore_tools)
    bpy.app.handlers.undo_post.remove(sync_shp_mode_after_history)
    bpy.app.handlers.redo_post.remove(sync_shp_mode_after_history)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
