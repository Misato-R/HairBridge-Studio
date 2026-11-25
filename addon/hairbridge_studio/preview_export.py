from .i18n import t as ui_t, localized_layout
"""Build a portable preview containing precisely the requested hair guides."""

import bpy


def export_guides_glb(context, guides, path):
    guides = tuple(guides)
    if not guides:
        raise ValueError(ui_t("没有可导出的发束。"))
    graph = context.evaluated_depsgraph_get()
    original_scene = context.window.scene
    original_layer = context.window.view_layer
    preview = bpy.data.scenes.new("HairBridge Preview")
    meshes = []
    objects = []
    try:
        preview.unit_settings.system = original_scene.unit_settings.system
        preview.unit_settings.scale_length = original_scene.unit_settings.scale_length
        for guide in guides:
            evaluated = guide.evaluated_get(graph)
            mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=graph)
            meshes.append(mesh)
            if not mesh.vertices:
                raise ValueError(ui_t(f"{guide.name} 未生成可预览的发片。"))
            baked = bpy.data.objects.new(f"发束 {guide.get('hairbridge_strand_id', guide.get('hairdeck_card_index', guide.name))}", mesh)
            objects.append(baked)
            preview.collection.objects.link(baked)
            baked.matrix_world = evaluated.matrix_world
            for field in ("hairbridge_strand_id", "hairdeck_card_index"):
                if field in guide:
                    baked[field] = guide[field]
        context.window.scene = preview
        if bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_active_scene=True,
                                     export_extras=True) != {"FINISHED"}:
            raise RuntimeError(ui_t("发片预览导出失败。"))
    finally:
        context.window.scene = original_scene
        context.window.view_layer = original_layer
        for obj in objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(preview)
        for mesh in meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
