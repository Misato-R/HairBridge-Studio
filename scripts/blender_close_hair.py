"""Create and check a separate, coordinate-preserving hair measurement mesh."""
import json
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def read_glb(file):
    old = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(file))
    objects = [obj for obj in bpy.context.scene.objects if obj not in old and obj.type == "MESH"]
    if not objects:
        raise ValueError("GLB 中没有头发网格。")
    return objects


def combined_mesh(objects):
    vertices, faces = [], []
    for obj in objects:
        offset = len(vertices)
        vertices.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        faces.extend(tuple(offset + index for index in f.vertices) for f in obj.data.polygons)
    mesh = bpy.data.meshes.new("Tripo hair for measurement")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate()
    return mesh


def clean_mesh(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1.e-6)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1.e-8)
    return bm


def edges_of(bm):
    return {"openEdges": sum(e.is_boundary for e in bm.edges),
            "nonManifoldEdges": sum(not (e.is_boundary or e.is_manifold) for e in bm.edges)}


def close_mesh(mesh, spread):
    bm = clean_mesh(mesh)
    before = edges_of(bm)
    # Discard small conflicting faces on overused edges before filling the exposed loops.
    for edge in list(bm.edges):
        if edge.is_valid and len(edge.link_faces) > 2:
            extra = sorted(edge.link_faces, key=lambda f: f.calc_area(), reverse=True)[2:]
            bmesh.ops.delete(bm, geom=extra, context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
    bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    method = "caps"
    pending = edges_of(bm)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Tripo hair - closed", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if any(pending.values()):
        # The source can contain T-junctions or intersecting surfaces as well as holes.
        mesh.remesh_voxel_size = spread / 260
        bpy.ops.object.voxel_remesh()
        method = "voxel"
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj, before, method


def audit(reference, target):
    before, after = clean_mesh(reference), clean_mesh(target)
    try:
        source, actual = edges_of(before), edges_of(after)
        if not after.faces or any(actual.values()):
            raise ValueError(f"候选仍有开口或非流形边（{actual['openEdges']} / {actual['nonManifoldEdges']}）。")
        low = Vector(tuple(min(v.co[i] for v in before.verts) for i in range(3)))
        high = Vector(tuple(max(v.co[i] for v in before.verts) for i in range(3)))
        target_low = Vector(tuple(min(v.co[i] for v in after.verts) for i in range(3)))
        target_high = Vector(tuple(max(v.co[i] for v in after.verts) for i in range(3)))
        span = max(high - low)
        deviation = max(*(abs(low[i]-target_low[i]) for i in range(3)),
                        *(abs(high[i]-target_high[i]) for i in range(3)))
        tree = BVHTree.FromBMesh(after)
        distances = sorted(tree.find_nearest(v.co)[3] for v in list(before.verts)[::max(1, len(before.verts)//3000)])
        p95 = distances[int(.95*(len(distances)-1))]
        if deviation > .04 * span or p95 > .025 * span:
            raise ValueError("闭合结果的比例、坐标或外表面与已审核的独立头发偏差过大。")
        return {"before": source, "after": actual, "surfaceP95Mm": round(p95*1000, 3),
                "faces": len(after.faces)}
    finally:
        before.free()
        after.free()


def build(job):
    output = Path(job["output"])
    closed = output / "closed-hair.glb"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source = combined_mesh(read_glb(job["sourceHair"]))
    span = max(max(v.co[i] for v in source.vertices)-min(v.co[i] for v in source.vertices)
               for i in range(3))
    candidate, before, method = close_mesh(source.copy(), span)
    report = audit(source, candidate.data)
    report["before"] = before
    bpy.ops.object.select_all(action="DESELECT")
    candidate.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(closed), export_format="GLB", use_selection=True)
    report.update(success=True, method=method)
    (output / "result.json").write_text(json.dumps(report), encoding="utf8")


if __name__ == "__main__":
    config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf8"))
    try:
        build(config)
    except ValueError as error:
        (Path(config["output"]) / "result.json").write_text(
            json.dumps({"success": False, "error": str(error)}, ensure_ascii=False), encoding="utf8")
