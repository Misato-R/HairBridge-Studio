from .i18n import t as ui_t, localized_layout, LANGUAGES, redraw
"""Local workflow companion; generation remains in the local web service."""
bl_info = {"name": "HairBridge Studio", "author": "IIS A2 project", "version": (0, 1, 1),
           "blender": (5, 2, 0), "location": "3D View > Sidebar > HairBridge", "category": "Import-Export"}

import json
import textwrap
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit
import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils.bvhtree import BVHTree
from . import hairdeck_bridge as bridge
from . import strand_edit
from .preview_export import export_guides_glb


def studio_origin(scene):
    address = scene.hairbridge_studio_url or scene.get("hairbridge_studio_url") or "http://127.0.0.1:8787"
    parts = urlsplit(address)
    if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parts.username is not None or parts.password is not None or parts.path not in {"", "/"}
            or parts.query or parts.fragment):
        raise ValueError(ui_t("工作台地址需要使用本地 HTTP 服务。"))
    return f"http://{parts.netloc}"


def mesh_only(_self, obj):
    return obj.type == "MESH"


def import_separated_references(context, paths):
    """Keep approved parts in the GLB frame and let the user show each reference independently."""
    original_objects = set(bpy.data.objects)
    original_collections = set(bpy.data.collections)
    root = bpy.data.collections.new("HairBridge · 拆分参考")
    context.scene.collection.children.link(root)
    try:
        for role, label in (("head", "头皮参考"), ("hair", "头发参考")):
            before = set(bpy.data.objects)
            if bpy.ops.import_scene.gltf(filepath=str(paths[role])) != {"FINISHED"}:
                raise ValueError(ui_t(f"{label} GLB 导入失败。"))
            imported = set(bpy.data.objects) - before
            if not any(obj.type == "MESH" and obj.data.polygons for obj in imported):
                raise ValueError(ui_t(f"{label} GLB 无可用的表面网格。"))
            part = bpy.data.collections.new(label)
            root.children.link(part)
            part.hide_render = True
            for obj in imported:
                old_collections = tuple(obj.users_collection)
                part.objects.link(obj)
                for old_collection in old_collections:
                    old_collection.objects.unlink(obj)
                obj["hairbridge_reference_part"] = role
            context.view_layer.update()
            context.view_layer.layer_collection.children[root.name].children[part.name].hide_viewport = True
    except Exception:
        bpy.data.batch_remove(ids=[*(set(bpy.data.objects) - original_objects),
                                   *(set(bpy.data.collections) - original_collections)])
        raise
    return root


def show_flow_review(layout, guide):
    strand_id = guide.get("hairbridge_strand_id")
    if strand_id is not None:
        layout.label(text=ui_t(f"第 {strand_id} 束"), icon="CURVE_BEZCURVE")
    else:
        layout.label(text=guide.name, icon="CURVE_BEZCURVE")
    try:
        review = json.loads(guide.get("hairbridge_flow_review", "{}"))
    except (TypeError, ValueError):
        return
    if not isinstance(review, dict):
        return
    decision = {"keep": "保留走向", "connect": "连接发束", "split": "拆分发束", "adjust": "调整控制点"}
    action = decision.get(review.get("decision"))
    if not action:
        return
    box = layout.box()
    box.label(text=ui_t(f"发流确认 · {action}"))
    if review.get("direction") == "reverse":
        box.label(text=ui_t("标记为反向，请复核根梢"))
    if review.get("targetId") is not None:
        box.label(text=ui_t(f"关联发束 · {review['targetId']}"))
    note = review.get("note")
    if isinstance(note, str):
        for line in textwrap.wrap(note, width=18, max_lines=4, placeholder="…", break_on_hyphens=False):
            box.label(text=line)


class HAIRBRIDGE_OT_web(bpy.types.Operator):
    bl_idname = "hairbridge.open_studio"
    bl_label = ui_t("打开本地工作台")

    def execute(self, context):
        webbrowser.open(studio_origin(context.scene))
        return {"FINISHED"}


class HAIRBRIDGE_OT_project(bpy.types.Operator, ImportHelper):
    bl_idname = "hairbridge.load_project"
    bl_label = ui_t("载入工作台项目")
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".hairbridge"
    filter_glob: bpy.props.StringProperty(default="*.hairbridge", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        separation_root = None
        try:
            source = Path(bpy.path.abspath(self.filepath)).resolve()
            data = json.loads(source.read_text(encoding="utf-8"))
            if data.get("schemaVersion") != 1 or not data.get("cards"):
                raise ValueError(ui_t("请选择包含 cards 的项目；单独下载的清单需要与 assets 文件夹放在一起。"))
            def asset_file(asset):
                target = (source.parent / asset["file"]).resolve()
                if not target.is_relative_to(source.parent):
                    raise ValueError(ui_t("素材路径不在项目文件夹内。"))
                return target
            coarse_path = asset_file(data["model"]) if data.get("model") else None
            cards_path = asset_file(data["cards"])
            separation = data.get("separation") or {}
            review = separation.get("review") or {}
            part_paths = {role: asset_file(separation[role]) for role in ("head", "hair")} if review.get("decision") == "approved" else {}
            paths = [cards_path, *part_paths.values()]
            if coarse_path:
                paths.append(coarse_path)
            if not all(path.is_file() for path in paths):
                raise ValueError(ui_t("项目素材缺失。请从工作台显示的本地项目文件夹载入。"))
            if any(o.get("hairbridge_project_id") == data["id"] for o in context.scene.objects):
                raise ValueError(ui_t("此项目已载入当前场景，避免重复导入。"))
            if part_paths:
                separation_root = import_separated_references(context, part_paths)
            guides = bridge.import_cards(context, cards_path)
            for obj in guides:
                obj["hairbridge_project_id"] = data["id"]
            if coarse_path:
                before = set(bpy.data.objects)
                bpy.ops.import_scene.gltf(filepath=str(coarse_path))
                objects = list(set(bpy.data.objects) - before)
                meshes = [o for o in objects if o.type == "MESH"]
                for obj in objects:
                    obj["hairbridge_coarse"] = True
                if meshes:
                    context.scene.hairbridge_coarse = meshes[0]
            context.scene.hairbridge_project = str(source)
            import hashlib
            stamp = [data.get(k, {}).get("sha256") if data.get(k) else None for k in ("reference", "cards", "model")]
            context.scene.hairbridge_input_stamp = data.get("inputStamp") or hashlib.sha256(
                json.dumps(stamp, separators=(",", ":")).encode()).hexdigest()
            context.scene.hairbridge_aligned = False
            loaded = f"已载入 {len(guides)} 束导线。"
            if separation_root is not None:
                loaded += "可在大纲视图中显示头皮与头发参考。"
            if coarse_path:
                loaded += "使用表面修正前，请核对导线与参考网格的坐标和比例。"
            self.report({"INFO"}, ui_t(loaded))
            return {"FINISHED"}
        except Exception as exc:
            if separation_root is not None:
                bpy.data.batch_remove(ids=[*separation_root.all_objects, *separation_root.children, separation_root])
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}


class HAIRBRIDGE_OT_refine(bpy.types.Operator):
    bl_idname = "hairbridge.refine_selected"
    bl_label = ui_t("用粗模修正所选导线")
    bl_description = ui_t("按距离限制向参考网格表面移动导线控制点；请先对齐并选择正确的头发网格")
    bl_options = {"REGISTER", "UNDO"}
    strength: bpy.props.FloatProperty(name=ui_t("修正强度"), default=0.35, min=0, max=1)
    max_distance: bpy.props.FloatProperty(name=ui_t("最大匹配距离"), default=0.025, min=0.0001, max=1, subtype="DISTANCE", unit="LENGTH")
    offset: bpy.props.FloatProperty(name=ui_t("表面偏移"), default=0.002, min=0, max=0.1, subtype="DISTANCE", unit="LENGTH")
    keep_root: bpy.props.BoolProperty(name=ui_t("保留根部控制点"), default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.scene.hairbridge_aligned and context.scene.hairbridge_coarse is not None and any(
            o.type == "CURVE" and o.get("hairdeck_card_json") for o in context.selected_objects)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        source = context.scene.hairbridge_coarse
        depsgraph = context.evaluated_depsgraph_get()
        evaluated = source.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            matrix = source.matrix_world
            tree = BVHTree.FromPolygons([matrix @ v.co for v in mesh.vertices], [p.vertices[:] for p in mesh.polygons], all_triangles=False)
        finally:
            evaluated.to_mesh_clear()
        changed, skipped = 0, 0
        for obj in context.selected_objects:
            if obj.type != "CURVE" or not obj.get("hairdeck_card_json"):
                continue
            inverse = obj.matrix_world.inverted()
            # Retain exact original points for traceability; Blender Undo restores the edit.
            before = [[list(p.co) for p in s.bezier_points] for s in obj.data.splines]
            for spline in obj.data.splines:
                for index, point in enumerate(spline.bezier_points):
                    if self.keep_root and index == 0:
                        continue
                    world = obj.matrix_world @ point.co
                    hit = tree.find_nearest(world, self.max_distance)
                    if not hit or hit[0] is None:
                        skipped += 1
                        continue
                    location, normal, _face, _distance = hit
                    target = inverse @ world.lerp(location + normal * self.offset, self.strength)
                    delta = target - point.co
                    point.co = target
                    point.handle_left += delta
                    point.handle_right += delta
                    changed += 1
            obj["hairbridge_refine_before"] = json.dumps(before)
            obj["hairbridge_refine_method"] = "User-aligned mesh, nearest-surface constrained correction; not hair-flow inference"
            obj.update_tag()
        self.report({"INFO"}, ui_t(f"已修正 {changed} 个控制点；{skipped} 个超出范围。检查发流与覆盖，必要时 Ctrl+Z。"))
        return {"FINISHED"}


class HAIRBRIDGE_OT_snapshot(bpy.types.Operator):
    bl_idname = "hairbridge.export_review"
    bl_label = ui_t("保存审核副本到项目")
    bl_description = ui_t("保存新的 Blend 和几何预览副本，保留当前文件；工作台可下载，审核状态仍由用户决定")

    def execute(self, context):
        import datetime
        import uuid
        import urllib.request
        try:
            source = Path(context.scene.hairbridge_project).resolve()
            if not source.is_file():
                raise ValueError(ui_t("请先载入工作台项目。"))
            directory = source.parent / "reviews" / (datetime.datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6])
            directory.mkdir(parents=True, exist_ok=False)
            project_id = json.loads(source.read_bytes())["id"]
            guides = [obj for obj in context.scene.objects if strand_edit.is_editable_guide(obj)
                      and obj.get("hairbridge_project_id") == project_id]
            if not guides:
                raise ValueError(ui_t("当前场景没有此项目的发束，请先载入项目。"))
            if context.mode != "OBJECT" or context.scene.hairbridge_edit_strand:
                raise ValueError(ui_t("请先完成走向编辑，返回物体模式。"))
            origin = studio_origin(context.scene)
            export_guides_glb(context, guides, directory / "edited.glb")
            bpy.ops.wm.save_as_mainfile(filepath=str(directory / "edited.blend"), copy=True, compress=True)
            report = {"project_id": project_id, "guides": len(guides),
                      "source_stamp": context.scene.hairbridge_input_stamp,
                      "alignment_confirmed": context.scene.hairbridge_aligned,
                      "coarse": context.scene.hairbridge_coarse.name if context.scene.hairbridge_coarse else None,
                      "blend": str(directory / "edited.blend"), "status": "awaiting_user_review"}
            (directory / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            data = json.dumps({"folder": directory.name}).encode()
            request = urllib.request.Request(f"{origin}/api/projects/{report['project_id']}/review-return", data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    response.read()
                self.report({"INFO"}, ui_t("精修副本已返回本地工作台，请在网页审核。"))
            except Exception as exc:
                self.report({"WARNING"}, ui_t(f"副本已保存在 {directory}；工作台同步失败：{exc}"))
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, ui_t(str(exc)))
            return {"CANCELLED"}


class HAIRBRIDGE_PT_panel(bpy.types.Panel):
    bl_label = "HairBridge Studio"
    bl_idname = "HAIRBRIDGE_PT_studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HairBridge"

    def draw(self, context):
        layout = localized_layout(self.layout)
        layout.prop(context.scene, "hairbridge_language", expand=True)
        layout.operator("hairbridge.open_studio", icon="URL")
        layout.operator("hairbridge.load_project", icon="IMPORT")
        if context.scene.hairbridge_project:
            layout.label(text=Path(context.scene.hairbridge_project).parent.name[:24], icon="FILE_FOLDER")
        box = layout.box()
        box.label(text=ui_t("粗模辅助修正"))
        box.prop(context.scene, "hairbridge_coarse", text=ui_t("参考网格"))
        box.prop(context.scene, "hairbridge_aligned", text=ui_t("已人工核对对齐与比例"))
        box.operator("hairbridge.refine_selected", icon="MOD_SHRINKWRAP")
        if any(obj.get("hairbridge_reference_part") == "head" for obj in context.scene.objects):
            box.label(text=ui_t("在大纲视图显示头皮或头发参考"))
        layout.separator()
        layout.operator("import_scene.hairdeck_json", text=ui_t("单独导入 cards JSON"))
        obj = context.active_object
        editing = context.scene.hairbridge_edit_strand
        if editing:
            show_flow_review(layout, editing)
            layout.label(text=ui_t("移动已有控制点，确认后重定位截面"))
            layout.operator("hairbridge.finish_path_edit", icon="CHECKMARK")
            layout.operator("hairbridge.finish_path_edit", text=ui_t("取消并恢复导线"), icon="LOOP_BACK").discard = True
        elif strand_edit.is_editable_guide(obj):
            show_flow_review(layout, obj)
            pins = layout.row()
            pins.prop(context.scene, "hairbridge_lock_root")
            pins.prop(context.scene, "hairbridge_lock_tip")
            layout.operator("hairbridge.begin_path_edit", icon="CURVE_BEZCURVE")
            layout.operator("hairbridge.adjust_section", icon="MOD_CURVE")
            layout.operator("hairbridge.restore_section", icon="LOOP_BACK")
        layout.operator("hairbridge.export_review", icon="FILE_TICK")


classes = (HAIRBRIDGE_OT_web, HAIRBRIDGE_OT_project, HAIRBRIDGE_OT_refine, HAIRBRIDGE_OT_snapshot, HAIRBRIDGE_PT_panel)
_owns_bridge = False


def register():
    global _owns_bridge
    bpy.types.Scene.hairbridge_language = bpy.props.EnumProperty(name="Language", items=LANGUAGES, default="en", update=redraw)
    if not hasattr(bpy.types, "HAIRDECK_PT_bridge"):
        bridge.register()
        _owns_bridge = True
    strand_edit.register()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hairbridge_project = bpy.props.StringProperty(name=ui_t("项目文件"), subtype="FILE_PATH")
    bpy.types.Scene.hairbridge_coarse = bpy.props.PointerProperty(type=bpy.types.Object, poll=mesh_only)
    bpy.types.Scene.hairbridge_aligned = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.hairbridge_input_stamp = bpy.props.StringProperty()
    bpy.types.Scene.hairbridge_studio_url = bpy.props.StringProperty()


def unregister():
    for key in ("hairbridge_project", "hairbridge_coarse", "hairbridge_aligned", "hairbridge_input_stamp", "hairbridge_studio_url", "hairbridge_language"):
        delattr(bpy.types.Scene, key)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    strand_edit.unregister()
    if _owns_bridge:
        bridge.unregister()
