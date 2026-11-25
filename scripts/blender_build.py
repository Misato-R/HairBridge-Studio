"""Build a fresh project copy in a background Blender, without touching the live scene."""
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils.bvhtree import BVHTree

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
out = Path(job["output"])
report = {"success": False, "blender": bpy.app.version_string, "coarse_alignment": "not_performed"}


def open_prepared_study(prepared, studio):
    """Use measured native curves and profiles from the same aligned study."""
    studio.bridge.hair_tools()
    bpy.ops.wm.open_mainfile(filepath=prepared["file"], load_ui=False)
    scene = bpy.data.scenes[prepared["scene"]]
    bpy.context.window.scene = scene
    bpy.context.view_layer.update()
    guides = []
    for strand in prepared["strands"]:
        guide = scene.objects[strand["objectName"]]
        if guide.type != "CURVE" or not guide.visible_get():
            raise ValueError(f"The prepared strand {strand['id']} is not an editable visible curve")
        guide["hairbridge_strand_id"] = strand["id"]
        guide["hairbridge_flow_review"] = json.dumps(prepared["reviews"][strand["id"]], ensure_ascii=False)
        guides.append(guide)
    for other in list(bpy.data.scenes):
        if other != scene:
            bpy.data.scenes.remove(other)
    return scene, guides


def import_coarse(scene, path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    coarse = sorted(set(bpy.data.objects) - before, key=lambda obj: obj.name)
    candidates = [obj for obj in coarse if obj.type == "MESH"]
    for obj in coarse:
        obj["hairbridge_coarse"] = True
        obj.hide_render = True
        obj.hide_set(True)
    if candidates:
        scene.hairbridge_coarse = next((obj for obj in candidates if "hair" in obj.name.lower()), candidates[0])
    report["coarse_imported"] = bool(candidates)


def verify_scalp_insets(scene, guides, insets):
    vertices, faces = [], []
    for obj in scene.objects:
        if obj.type != "MESH" or obj.get("hairbridge_reference_part") != "head":
            continue
        start = len(vertices)
        vertices.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        obj.data.calc_loop_triangles()
        faces.extend(tuple(start + i for i in tri.vertices) for tri in obj.data.loop_triangles)
    if not faces:
        raise ValueError("贴头皮端内嵌缺少头皮参考面。")
    scalp = BVHTree.FromPolygons(vertices, faces, all_triangles=True)
    graph = bpy.context.evaluated_depsgraph_get()
    report = {}
    for guide, inset in zip(guides, insets):
        if inset is None:
            continue
        evaluated = guide.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            stations = len(inset["offsets"])
            sides, excess = divmod(len(mesh.vertices), stations)
            if excess or sides not in (4, 16):
                raise ValueError("无法检查生成发片的末端截面。")
            ring = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices[-sides:]]
            center = sum(ring[1:], ring[0].copy()) / sides
            midpoints = [point.lerp(ring[(index + 1) % sides], .5) for index, point in enumerate(ring)]
            signed_gaps = []
            for point in [*ring, *midpoints, center, *(center.lerp(mid, .5) for mid in midpoints)]:
                point_on_head, normal, _, _ = scalp.find_nearest(point)
                signed_gaps.append(normal.dot(point - point_on_head))
            minimum_depth = -1000 * max(signed_gaps)
            if minimum_depth < max(.05, inset["depth"] - .5):
                raise ValueError(f"后脑发片 {guide.name} 的端面未完全进入头皮，请检查末端。")
            report[guide["hairbridge_strand_id"]] = {
                "extra_depth_mm": inset["depth"], "minimum_depth_mm": round(minimum_depth, 2),
                "tip_shift_mm": round(inset["shift"] * 1000, 2), "blend_percent": round(inset["span"], 2),
            }
        finally:
            evaluated.to_mesh_clear()
    return report


try:
    sys.path.insert(0, str(Path(job["bridge"]).parent))
    import hairbridge_studio
    hairbridge_studio.register()
    prepared = job.get("prepared")
    if prepared:
        scene, guides = open_prepared_study(prepared, hairbridge_studio)
        report["coarse_alignment"] = "prepared_rain_study"
        report["source_strands"] = [obj["hairbridge_strand_id"] for obj in guides]
    else:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        scene = bpy.context.scene
        insets = job.get("scalpInsets")
        guides = hairbridge_studio.bridge.import_cards(bpy.context, Path(job["cards"]), job.get("sectionProfiles"),
                                                       [item and item["offsets"] for item in insets] if insets else None)
        if job.get("sectionProfiles"):
            report["cross_section_points"] = [len(section[0]) if section is not None else 4 for section in job["sectionProfiles"]]
    scene.unit_settings.system = "METRIC"
    ids = job.get("strandIds")
    if ids is not None:
        if len(ids) != len(guides) or len(set(ids)) != len(ids):
            raise ValueError("Selected strand IDs must match the saved guides")
        for guide, strand_id in zip(guides, ids):
            guide["hairbridge_strand_id"] = strand_id
        report["generated_strands"] = ids
    for guide in guides:
        guide["hairbridge_project_id"] = job["projectId"]
    scene.hairbridge_project = job["projectFile"]
    scene.hairbridge_language = job.get("uiLanguage", "en")
    scene.hairbridge_input_stamp = job["inputStamp"]
    scene.hairbridge_aligned = bool(prepared)
    scene["hairbridge_studio_url"] = job.get("studioUrl", "http://127.0.0.1:8787")
    if hasattr(bpy.types.Scene, "hairbridge_studio_url"):
        scene.hairbridge_studio_url = scene["hairbridge_studio_url"]
    scene["hairbridge_job_id"] = job["jobId"]
    if job.get("model"):
        import_coarse(scene, job["model"])
    if job.get("separation"):
        hairbridge_studio.import_separated_references(bpy.context, job["separation"])
        report["separated_references"] = ["head", "hair"]
    if job.get("scalpInsets"):
        report["scalp_insets"] = verify_scalp_insets(scene,guides,job["scalpInsets"])
    # Keep reference geometry in the Blend file and export only the generated hair.
    bpy.ops.object.select_all(action="DESELECT")
    vertices = 0
    for obj in guides:
        obj.select_set(True)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        vertices += len(mesh.vertices)
        evaluated.to_mesh_clear()
    bpy.context.view_layer.objects.active = guides[0]
    hairbridge_studio.export_guides_glb(bpy.context, guides, out / "hairbridge.glb")
    if prepared:
        for guide in guides:
            guide.select_set(guide.get("hairbridge_strand_id") == "4")
        bpy.context.view_layer.objects.active = next((obj for obj in guides if obj.select_get()), guides[0])
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "hairbridge.blend"), compress=True)
    report.update(success=True, guides=len(guides), evaluated_vertices=vertices,
                  source_cards=job["cards"], editable=True,
                  refinement="Manual alignment and selected-guide surface correction are available in the companion add-on.")
except Exception as exc:
    report.update(error=str(exc), traceback=traceback.format_exc())
    raise
finally:
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
