"""HairDeck section fitting for native SHP Custom Hair Geometry."""
import bpy
import numpy as np
from . import frames

RADIUS = 0.01
SECTION_SIDES = "hairbridge_section_sides"

def select_only(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def max_curve_error(points, polyline):
    """Directed maximum point-to-polyline distance, including segment interiors."""
    starts, ends = polyline[:-1], polyline[1:]
    edges = ends - starts
    offsets = points[:, None, :] - starts
    frac = np.clip((offsets * edges).sum(axis=2) / np.maximum((edges ** 2).sum(axis=1), 1e-18), 0, 1)
    return float(np.linalg.norm(offsets - frac[:, :, None] * edges, axis=2).min(axis=1).max())


def geometry(obj):
    """Capture evaluated mesh in world space; copy data before releasing Blender's temporary mesh."""
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(graph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        verts = np.asarray([evaluated.matrix_world @ v.co for v in mesh.vertices], dtype=float)
        tris = np.asarray([tuple(t.vertices) for t in mesh.loop_triangles], dtype=np.int32)
        if len(verts) == 0 or not len(tris) or not np.isfinite(verts).all():
            raise ValueError(f"No finite evaluated surface on {obj.name}")
        return verts, tris
    finally:
        evaluated.to_mesh_clear()


def make_profile(collection, idx, arc, sides=4):
    # A symmetric probe measures the *actual* SHP frame/scale at every source station.
    if sides == 4:
        xy = np.array([(RADIUS, 0), (0, RADIUS), (-RADIUS, 0), (0, -RADIUS)])
    else:
        theta = np.arange(sides) * 2 * np.pi / sides
        xy = RADIUS * np.stack((np.cos(theta), np.sin(theta)), axis=1)
    verts = np.empty((len(arc), sides, 3))
    verts[:, :, :2] = xy
    verts[:, :, 2] = arc[:, None]
    tris = [(0, k + 1, k) for k in range(1, sides - 1)]
    for i in range(1, len(arc)):
        for k in range(sides):
            a = sides * (i - 1) + k
            b = sides * (i - 1) + (k + 1) % sides
            tris.extend([(a + sides, a, b + sides), (b, b + sides, a)])
    last = sides * (len(arc) - 1)
    tris.extend((last, last + k, last + k + 1) for k in range(1, sides - 1))
    mesh = bpy.data.meshes.new(f"HairDeck section data {idx:02}")
    mesh.from_pydata(verts.reshape(-1, 3).tolist(), [], tris)
    mesh.update()
    ob = bpy.data.objects.new(f"Rest profile {idx:02}", mesh)
    ob[SECTION_SIDES] = sides
    if sides > 4:
        for face in mesh.polygons:
            face.use_smooth = True
    collection.objects.link(ob)
    ob.hide_set(True)
    ob.hide_render = True
    return ob, verts


def world_axes(rows):
    # HairDeck's exporter transports the first direction, using its own tangent stencil.
    tangent = frames.tangents(rows[:, :3])
    width = frames.bishop(rows[0, 5:8], tangent)
    thick = np.cross(width, tangent)
    def rotate(v):
        return v[:, [0, 2, 1]] * [1, -1, 1]
    return rotate(width), rotate(thick)


def attach_profile(shp, obj, profile, rest, rows, card, sections=None):
    for key, value in [("utils_cust_geo_object", profile), ("utils_cust_geo_rescale", False),
                       ("utils_cust_geo_enable", True)]:
        shp.shp_set_value("utility_settings", key, value, obj)
    # Keep HairDeck's centerline when SHP samples the editable guide.
    shp.shp_set_value("hair_settings_misc", "settings_pre_smooth", 0.0, obj)
    obj.update_tag()
    bpy.context.view_layer.update()
    probe, _ = geometry(obj)
    if len(probe) != rest.size // 3:
        raise ValueError(f"Custom SHP output has {len(probe)} vertices for {obj.name}; expected {rest.size // 3}")
    sides = rest.shape[1]
    quarter = sides // 4
    rings = probe.reshape(-1, sides, 3)
    sx = (rings[:, 0] - rings[:, 2 * quarter]) / (2 * RADIUS)
    sy = (rings[:, quarter] - rings[:, 3 * quarter]) / (2 * RADIUS)
    basis = np.stack([sx, sy], axis=2)
    if np.linalg.svd(basis, compute_uv=False).min() < 1e-6:
        raise ValueError(f"Degenerate SHP cross-section frame at {obj.name}")
    width, thick = world_axes(rows)
    # Rotate the source frame into the guide plane by the shortest arc. Preserve both physical dimensions.
    old_normal = np.cross(width, thick)
    new_normal = np.cross(sx, sy)
    new_normal /= np.linalg.norm(new_normal, axis=1, keepdims=True)
    new_normal *= np.where((old_normal * new_normal).sum(axis=1) < 0, -1., 1.)[:, None]
    axis = np.cross(old_normal, new_normal)
    cos = np.sum(old_normal * new_normal, axis=1, keepdims=True)
    def rotate(v):
        return v + np.cross(axis, v) + np.cross(axis, np.cross(axis, v)) / (1 + cos)
    width, thick = rotate(width), rotate(thick)
    up, down = (3, 6) if card["shape"] == "triangle" else (2, 2)
    if sections is None:
        off_w = width * rows[:, 3, None] / 2
        off_t = thick * rows[:, 4, None]
        offsets = np.stack([off_w, off_t / up, -off_w, -off_t / down], axis=1)
    else:
        offsets = sections[:, :, 0, None] * width[:, None, :] + sections[:, :, 1, None] * thick[:, None, :]
    rest[:, :, :2] = np.einsum("nkw,ncw->nkc", offsets, np.linalg.pinv(basis))
    profile.data.vertices.foreach_set("co", np.ascontiguousarray(rest, dtype=np.float32).ravel())
    profile.data.update()
    profile.update_tag()
    obj.update_tag()
    bpy.context.view_layer.update()
    v, t = geometry(obj)
    final = v.reshape(-1, sides, 3)
    if sections is None:
        observed_w = np.linalg.norm(final[:, 0] - final[:, 2], axis=1)
        observed_t = np.linalg.norm(final[:, 1] - final[:, 3], axis=1)
        err = np.abs(observed_w - rows[:, 3]).max()
        err_t = np.abs(observed_t - rows[:, 4] * (1 / up + 1 / down)).max()
    else:
        spans = np.ptp(np.stack((np.einsum("vki,vi->vk", final, width),
                                 np.einsum("vki,vi->vk", final, thick)), axis=2), axis=1)
        err, err_t = np.max(np.abs(spans - np.ptp(sections, axis=1)), axis=0)
    if max(err, err_t) > 2e-5:
        raise ValueError(f"Native SHP did not realize the mapped dimensions: {obj.name}, {err}, {err_t}")
    return v, t, 1000 * err, 1000 * err_t


