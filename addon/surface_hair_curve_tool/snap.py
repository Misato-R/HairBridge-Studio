from dataclasses import dataclass
import math

import bpy
from mathutils import Vector
from bpy_extras import view3d_utils


@dataclass
class SnapResult:
    hit: bool = False
    location: Vector = None
    normal: Vector = None
    object: bpy.types.Object = None
    face_index: int = -1
    element: str = "NONE"
    warning: bool = False


def event_mouse_region(event):
    return (event.mouse_region_x, event.mouse_region_y)


def ray_from_mouse(context, event):
    region = context.region
    rv3d = context.region_data
    if not region or not rv3d:
        return None, None
    coord = event_mouse_region(event)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    return origin, direction


def mesh_candidates(context, settings):
    active = context.view_layer.objects.active
    if settings.surface_filter == "ACTIVE":
        return [active] if active and active.type == "MESH" and active.visible_get() else []
    if settings.surface_filter == "SELECTED":
        return [obj for obj in context.selected_objects if obj.type == "MESH" and obj.visible_get()]
    objects = []
    for obj in context.visible_objects:
        if obj.type == "MESH" and obj.visible_get() and not obj.hide_get():
            objects.append(obj)
    return objects


def nearest_point_on_segment(point, a, b):
    ab = b - a
    denom = ab.length_squared
    if denom <= 1.0e-12:
        return a
    t = max(0.0, min(1.0, (point - a).dot(ab) / denom))
    return a + ab * t


def triangle_vertices_for_face(obj_eval, polygon_index):
    mesh = obj_eval.data
    if polygon_index < 0 or polygon_index >= len(mesh.polygons):
        return []
    poly = mesh.polygons[polygon_index]
    return [mesh.vertices[i].co.copy() for i in poly.vertices]


def refine_snap_element(obj, obj_eval, local_hit, polygon_index, snap_element):
    verts = triangle_vertices_for_face(obj_eval, polygon_index)
    if not verts:
        return local_hit, "FACE"
    if snap_element == "FACE":
        return local_hit, "FACE"
    if snap_element == "VERTEX":
        return min(verts, key=lambda v: (v - local_hit).length_squared), "VERTEX"
    if snap_element == "EDGE":
        best = None
        best_dist = math.inf
        count = len(verts)
        for i in range(count):
            p = nearest_point_on_segment(local_hit, verts[i], verts[(i + 1) % count])
            dist = (p - local_hit).length_squared
            if dist < best_dist:
                best = p
                best_dist = dist
        return best if best is not None else local_hit, "EDGE"
    # Auto behaves like Blender-friendly near element snapping on the hit polygon.
    nearest_vertex = min(verts, key=lambda v: (v - local_hit).length_squared)
    nearest_vertex_dist = (nearest_vertex - local_hit).length
    best_edge = local_hit
    best_edge_dist = math.inf
    count = len(verts)
    for i in range(count):
        p = nearest_point_on_segment(local_hit, verts[i], verts[(i + 1) % count])
        dist = (p - local_hit).length
        if dist < best_edge_dist:
            best_edge = p
            best_edge_dist = dist
    face_size = max((verts[i] - verts[(i + 1) % count]).length for i in range(count)) if count else 1.0
    threshold = max(face_size * 0.08, 0.01)
    if nearest_vertex_dist <= threshold:
        return nearest_vertex, "VERTEX"
    if best_edge_dist <= threshold:
        return best_edge, "EDGE"
    return local_hit, "FACE"


def raycast_mesh_object(context, obj, origin, direction, settings):
    if not obj or obj.type != "MESH":
        return SnapResult(hit=False, warning=True)
    try:
        if not obj.visible_get() or obj.hide_get():
            return SnapResult(hit=False)
    except Exception:
        return SnapResult(hit=False, warning=True)
    depsgraph = context.evaluated_depsgraph_get()
    try:
        obj_eval = obj.evaluated_get(depsgraph)
        inv = obj_eval.matrix_world.inverted()
        local_origin = inv @ origin
        local_direction = (inv.to_3x3() @ direction).normalized()
        hit, local_loc, local_normal, face_index = obj_eval.ray_cast(local_origin, local_direction)
    except Exception:
        return SnapResult(hit=False, warning=True)
    if not hit:
        return SnapResult(hit=False)
    refined_local, element = refine_snap_element(obj, obj_eval, local_loc, face_index, settings.snap_element)
    world_loc = obj_eval.matrix_world @ refined_local
    world_normal = (obj_eval.matrix_world.to_3x3() @ local_normal).normalized()
    return SnapResult(True, world_loc, world_normal, obj, face_index, element, False)


def snap_from_mouse(context, event, settings):
    if not settings.snap_enabled:
        return SnapResult(hit=False)
    origin, direction = ray_from_mouse(context, event)
    if origin is None:
        return SnapResult(hit=False)
    best = None
    best_distance = math.inf
    for obj in mesh_candidates(context, settings):
        result = raycast_mesh_object(context, obj, origin, direction, settings)
        if not result.hit:
            continue
        distance = (result.location - origin).length_squared
        if distance < best_distance:
            best_distance = distance
            best = result
    return best or SnapResult(hit=False)


def snap_from_mouse_to_object(context, event, settings, obj):
    if not settings.snap_enabled:
        return SnapResult(hit=False)
    origin, direction = ray_from_mouse(context, event)
    if origin is None:
        return SnapResult(hit=False)
    return raycast_mesh_object(context, obj, origin, direction, settings)


def project_world_to_surface(context, world_point, source_obj, settings):
    if not source_obj or source_obj.type != "MESH":
        return SnapResult(hit=False, warning=True)
    depsgraph = context.evaluated_depsgraph_get()
    try:
        obj_eval = source_obj.evaluated_get(depsgraph)
        inv = obj_eval.matrix_world.inverted()
        local_point = inv @ world_point
        hit, closest, normal, face_index = obj_eval.closest_point_on_mesh(local_point)
    except Exception:
        return SnapResult(hit=False, warning=True)
    if not hit:
        return SnapResult(hit=False, warning=True)
    refined_local, element = refine_snap_element(source_obj, obj_eval, closest, face_index, settings.snap_element)
    world_loc = obj_eval.matrix_world @ refined_local
    world_normal = (obj_eval.matrix_world.to_3x3() @ normal).normalized()
    return SnapResult(True, world_loc, world_normal, source_obj, face_index, element, False)
