"""Background integration QA against a generated Blend; never opens the user's live scene."""
import json
import sys
from pathlib import Path
import bpy

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "addon"))
import hairbridge_studio

hairbridge_studio.register()
source, output = [Path(p) for p in sys.argv[sys.argv.index("--") + 1:]]
bpy.ops.wm.open_mainfile(filepath=str(source))
hairbridge_studio.bridge.hair_tools()
scene = bpy.context.scene
project = json.loads(Path(scene.hairbridge_project).read_bytes())
guides = [o for o in scene.objects if o.type == "CURVE" and o.get("hairdeck_card_json")]
assert len(guides) == project["cards"]["count"]
assert all(o.get("hairbridge_project_id") == project["id"] for o in guides)
from hairbridge_studio.hairdeck_bridge.mapping import geometry
import numpy as np

guide = guides[0]
before, _ = geometry(guide)
point = guide.data.splines[0].bezier_points[len(guide.data.splines[0].bezier_points) // 2]
original = point.co.copy()
point.co.x += .005
guide.update_tag()
bpy.context.view_layer.update()
after, _ = geometry(guide)
assert np.max(np.linalg.norm(after - before, axis=1)) > .0001
point.co = original
guide.update_tag()
bpy.context.view_layer.update()
restored, _ = geometry(guide)
assert np.max(np.linalg.norm(restored - before, axis=1)) < 1e-6

# A known synthetic plane validates the distance-constrained operator, not its aesthetic quality.
bpy.ops.object.select_all(action="DESELECT")
guide.select_set(True)
bpy.context.view_layer.objects.active = guide
sample = guide.matrix_world @ point.co
mesh = bpy.data.meshes.new("QA surface")
size = 2
z = sample.z - .002
mesh.from_pydata([(-size,-size,z),(size,-size,z),(size,size,z),(-size,size,z)], [], [(0,1,2,3)])
surface = bpy.data.objects.new("QA surface", mesh)
scene.collection.objects.link(surface)
scene.hairbridge_coarse = surface
original_points = [(p, p.co.copy(), p.handle_left.copy(), p.handle_right.copy()) for s in guide.data.splines for p in s.bezier_points]
original_alignment = scene.hairbridge_aligned
scene.hairbridge_aligned = False
assert not bpy.ops.hairbridge.refine_selected.poll()
scene.hairbridge_aligned = True
assert bpy.ops.hairbridge.refine_selected(strength=.2, max_distance=.015, offset=.001, keep_root=True) == {"FINISHED"}
assert guide.get("hairbridge_refine_method")
for p, co, left, right in original_points:
    p.co, p.handle_left, p.handle_right = co, left, right
for key in ("hairbridge_refine_before", "hairbridge_refine_method"):
    del guide[key]
scene.hairbridge_coarse = None
scene.hairbridge_aligned = original_alignment
bpy.data.objects.remove(surface, do_unlink=True)
guide.update_tag()
bpy.context.view_layer.update()
final_geometry, _ = geometry(guide)
assert np.max(np.linalg.norm(final_geometry-before, axis=1)) < 1e-6
bpy.ops.object.select_all(action="DESELECT")
guide.select_set(True)
bpy.context.view_layer.objects.active = guide
assert bpy.ops.hairbridge.export_review() == {"FINISHED"}
report = {"success": True, "blender": bpy.app.version_string, "guides": len(guides),
          "guide_edit_mesh_max_move_mm": float(np.max(np.linalg.norm(after-before, axis=1))*1000),
          "restore_max_error_mm": float(np.max(np.linalg.norm(restored-before, axis=1))*1000),
          "alignment_gate": True, "surface_correction_operator": True,
          "review_copy_operator": True, "synthetic_changes_restored": True,
          "note": "Synthetic surface check only; restored before saving the review copy. Not a hair-quality evaluation."}
output.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report), flush=True)
