import math
import uuid

import bpy
from mathutils import Vector

from . import props, snap


CURVE_ID_PROP = "sht_curve_id"
GROUP_ID_PROP = "sht_group_id"
SURFACE_NAME_PROP = "sht_surface_object"
MANAGED_PROP = "sht_managed_curve"
EXPORT_PROP = "sht_hair_export"
COLLECTION_GROUP_ID_PROP = "sht_group_collection_id"
ROOT_COLLECTION_NAME = "Surface Hair Curves"


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def group_color_tuple(group, fallback=(0.0, 0.85, 0.25, 1.0)):
    if not group:
        return fallback
    try:
        return tuple(float(group.color[idx]) for idx in range(4))
    except Exception:
        return fallback


def group_curve_radius(group, settings=None, fallback=0.003):
    if group:
        try:
            return max(0.0, float(group.curve_radius))
        except Exception:
            pass
    if settings:
        try:
            return max(0.0, float(settings.curve_radius))
        except Exception:
            pass
    return fallback


def group_material_name(group):
    group_id = getattr(group, "group_id", "") or "default"
    return f"SHT_GroupColor_{group_id}"


def ensure_group_material(group):
    color = group_color_tuple(group)
    material = bpy.data.materials.get(group_material_name(group))
    if material is None:
        material = bpy.data.materials.new(group_material_name(group))
    material.diffuse_color = color
    try:
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = color
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = color[3]
    except Exception:
        pass
    return material


def apply_group_display_color(obj, group):
    if not obj or not group:
        return
    color = group_color_tuple(group)
    material = ensure_group_material(group)
    try:
        obj.color = color
    except Exception:
        pass
    data = getattr(obj, "data", None)
    if not data or not hasattr(data, "materials"):
        return
    try:
        if data.materials:
            data.materials[0] = material
        else:
            data.materials.append(material)
    except Exception:
        pass


def is_native_curve_object(obj):
    try:
        if not obj or obj.name not in bpy.data.objects:
            return False
        if obj.type != "CURVE" or not obj.get(MANAGED_PROP) or obj.get(EXPORT_PROP):
            return False
        return bool(getattr(obj.data, "splines", None))
    except ReferenceError:
        return False


def world_points_from_curve(obj):
    points = []
    if not obj or obj.type != "CURVE":
        return points
    matrix = obj.matrix_world
    for spline in obj.data.splines:
        if spline.type == "BEZIER":
            for point in spline.bezier_points:
                points.append(matrix @ point.co)
        elif spline.type == "POLY":
            for point in spline.points:
                points.append(matrix @ Vector((point.co.x, point.co.y, point.co.z)))
    return points


def item_object(item):
    try:
        obj = item.object
        if is_native_curve_object(obj):
            return obj
    except ReferenceError:
        return None
    return None


def surface_object_for_item(item, obj=None):
    try:
        surface_obj = item.surface_object if item else None
        if surface_obj and surface_obj.name in bpy.data.objects and surface_obj.type == "MESH":
            return surface_obj
    except ReferenceError:
        pass
    try:
        obj = obj or (item_object(item) if item else None)
        surface_name = obj.get(SURFACE_NAME_PROP, "") if obj else ""
        surface_obj = bpy.data.objects.get(surface_name) if surface_name else None
        if surface_obj and surface_obj.type == "MESH":
            return surface_obj
    except ReferenceError:
        return None
    return None


def ensure_root_collection(context):
    scene = getattr(context, "scene", None)
    root = bpy.data.collections.get(ROOT_COLLECTION_NAME)
    if not root:
        root = bpy.data.collections.new(ROOT_COLLECTION_NAME)
    if scene and root.name not in scene.collection.children.keys():
        try:
            scene.collection.children.link(root)
        except RuntimeError:
            pass
    return root


def _unique_collection_name(base_name):
    clean = (base_name or "Group").strip() or "Group"
    name = f"SHT_{clean}"
    if name not in bpy.data.collections:
        return name
    index = 2
    while f"{name}.{index:03d}" in bpy.data.collections:
        index += 1
    return f"{name}.{index:03d}"


def find_group_by_id(settings, group_id):
    if not settings:
        return None
    for group in settings.groups:
        if group.group_id == group_id:
            return group
    return None


def ensure_group_collection(context, settings, group):
    if not group:
        return ensure_root_collection(context)
    root = ensure_root_collection(context)
    collection = None
    if group.collection_name:
        collection = bpy.data.collections.get(group.collection_name)
    if collection is None:
        for candidate in bpy.data.collections:
            if candidate.get(COLLECTION_GROUP_ID_PROP) == group.group_id:
                collection = candidate
                break
    if collection is None:
        collection = bpy.data.collections.new(_unique_collection_name(group.name))
    collection[COLLECTION_GROUP_ID_PROP] = group.group_id
    group.collection_name = collection.name
    if collection.name not in root.children.keys():
        try:
            root.children.link(collection)
        except RuntimeError:
            pass
    return collection


def ensure_all_group_collections(context, settings):
    if not settings:
        return
    props.ensure_default_group(settings)
    for group in settings.groups:
        ensure_group_collection(context, settings, group)


def assign_object_to_group_collection(context, settings, obj, group):
    if not obj:
        return
    collection = ensure_group_collection(context, settings, group)
    apply_group_display_color(obj, group)
    root = ensure_root_collection(context)
    scene_collection = getattr(getattr(context, "scene", None), "collection", None)
    if obj.name not in collection.objects.keys():
        try:
            collection.objects.link(obj)
        except RuntimeError:
            pass
    for old_collection in list(obj.users_collection):
        if old_collection == collection:
            continue
        should_unlink = (
            old_collection.get(COLLECTION_GROUP_ID_PROP)
            or old_collection == root
            or old_collection == scene_collection
        )
        if should_unlink and len(obj.users_collection) > 1:
            try:
                old_collection.objects.unlink(obj)
            except RuntimeError:
                pass


def apply_group_curve_radius(settings, group):
    if not settings or not group:
        return 0
    radius = group_curve_radius(group, settings)
    changed = 0
    for item in settings.curves:
        if item.group_id != group.group_id:
            continue
        obj = item_object(item)
        data = getattr(obj, "data", None) if obj else None
        if not data or not hasattr(data, "bevel_depth"):
            continue
        try:
            data.bevel_depth = radius
            data.update_tag()
            changed += 1
        except Exception:
            pass
    return changed


def remove_empty_group_collection(group):
    if not group or not group.collection_name:
        return
    collection = bpy.data.collections.get(group.collection_name)
    if collection and not collection.objects and not collection.children:
        try:
            bpy.data.collections.remove(collection)
        except RuntimeError:
            pass


def bezier_world_data(obj):
    if not obj or obj.type != "CURVE" or not obj.data.splines:
        return []
    matrix = obj.matrix_world
    spline = obj.data.splines[0]
    if spline.type != "BEZIER":
        return []
    data = []
    for point in spline.bezier_points:
        data.append(
            {
                "co": matrix @ point.co,
                "left": matrix @ point.handle_left,
                "right": matrix @ point.handle_right,
                "left_type": point.handle_left_type,
                "right_type": point.handle_right_type,
            }
        )
    return data


def copy_bezier_data(data):
    copied = []
    for pt in data:
        copied.append(
            {
                "co": pt["co"].copy(),
                "left": pt["left"].copy(),
                "right": pt["right"].copy(),
                "left_type": pt.get("left_type", "AUTO"),
                "right_type": pt.get("right_type", "AUTO"),
            }
        )
    return copied


def translated_bezier_data(data, offset):
    if not data:
        return []
    offset = offset.copy() if hasattr(offset, "copy") else Vector(offset)
    copied = copy_bezier_data(data)
    for point_data in copied:
        point_data["co"] += offset
        point_data["left"] += offset
        point_data["right"] += offset
    return copied


def snap_bezier_root_to_surface(context, data, surface_object, settings=None):
    if not data or not surface_object:
        return copy_bezier_data(data)
    try:
        if surface_object.type != "MESH" or surface_object.name not in bpy.data.objects:
            return copy_bezier_data(data)
    except ReferenceError:
        return copy_bezier_data(data)
    settings = settings or props.get_settings(context)
    if not settings:
        return copy_bezier_data(data)
    projected = snap.project_world_to_surface(context, data[0]["co"], surface_object, settings)
    if not projected.hit:
        return copy_bezier_data(data)
    return translated_bezier_data(data, projected.location - data[0]["co"])


def sample_cubic(p0, h0, h1, p1, steps):
    samples = []
    for i in range(steps + 1):
        t = i / max(steps, 1)
        inv = 1.0 - t
        samples.append((inv ** 3) * p0 + 3.0 * (inv ** 2) * t * h0 + 3.0 * inv * (t ** 2) * h1 + (t ** 3) * p1)
    return samples


def sample_bezier_data(data, resolution=16):
    if len(data) < 2:
        return [pt["co"] for pt in data]
    points = []
    for idx in range(len(data) - 1):
        seg = sample_cubic(
            data[idx]["co"],
            data[idx]["right"],
            data[idx + 1]["left"],
            data[idx + 1]["co"],
            resolution,
        )
        if idx:
            seg = seg[1:]
        points.extend(seg)
    return points


def sample_bezier_world(obj, resolution=16):
    data = bezier_world_data(obj)
    if data:
        return sample_bezier_data(data, resolution)
    return world_points_from_curve(obj)


def resample_polyline(points, count):
    if not points:
        return []
    count = max(1, int(count))
    if len(points) == 1 or count == 1:
        return [points[0].copy()]
    distances = [0.0]
    total = 0.0
    for idx in range(1, len(points)):
        total += (points[idx] - points[idx - 1]).length
        distances.append(total)
    if total <= 1.0e-9:
        return [points[0].copy() for _idx in range(count)]
    sampled = []
    segment_index = 1
    for idx in range(count):
        target = (total * idx) / max(count - 1, 1)
        while segment_index < len(distances) - 1 and distances[segment_index] < target:
            segment_index += 1
        prev_index = max(0, segment_index - 1)
        start_dist = distances[prev_index]
        end_dist = distances[segment_index]
        if end_dist <= start_dist:
            sampled.append(points[segment_index].copy())
            continue
        t = (target - start_dist) / (end_dist - start_dist)
        sampled.append(points[prev_index].lerp(points[segment_index], t))
    return sampled


def resample_curve_world(obj, count, resolution=24):
    return resample_polyline(sample_bezier_world(obj, resolution=resolution), count)


def interpolate_point_sets(points_a, points_b, factor):
    count = min(len(points_a), len(points_b))
    if count <= 0:
        return []
    factor = max(0.0, min(1.0, factor))
    return [points_a[idx].lerp(points_b[idx], factor) for idx in range(count)]


def sample_bezier_segments_world(obj, resolution=12):
    data = bezier_world_data(obj)
    if len(data) < 2:
        return []
    segments = []
    for idx in range(len(data) - 1):
        segments.append(
            (
                idx,
                sample_cubic(
                    data[idx]["co"],
                    data[idx]["right"],
                    data[idx + 1]["left"],
                    data[idx + 1]["co"],
                    resolution,
                ),
            )
        )
    return segments


def handle_lines_world(obj):
    data = bezier_world_data(obj)
    lines = []
    handle_points = []
    for idx, point in enumerate(data):
        lines.extend([point["co"], point["left"], point["co"], point["right"]])
        handle_points.append((idx, "LEFT", point["left"]))
        handle_points.append((idx, "RIGHT", point["right"]))
    return lines, handle_points


def set_bezier_handle(obj, point_index, side, world_position):
    if not obj or obj.type != "CURVE" or not obj.data.splines:
        return False
    spline = obj.data.splines[0]
    if spline.type != "BEZIER" or point_index < 0 or point_index >= len(spline.bezier_points):
        return False
    point = spline.bezier_points[point_index]
    inv = obj.matrix_world.inverted()
    local = inv @ world_position
    point.handle_left_type = "FREE"
    point.handle_right_type = "FREE"
    if side == "LEFT":
        point.handle_left = local
    else:
        point.handle_right = local
    obj.data.update_tag()
    return True


def set_bezier_segment_handles(obj, segment_index, right_world, left_world):
    if not obj or obj.type != "CURVE" or not obj.data.splines:
        return False
    spline = obj.data.splines[0]
    if spline.type != "BEZIER" or segment_index < 0 or segment_index + 1 >= len(spline.bezier_points):
        return False
    inv = obj.matrix_world.inverted()
    p0 = spline.bezier_points[segment_index]
    p1 = spline.bezier_points[segment_index + 1]
    p0.handle_right_type = "FREE"
    p1.handle_left_type = "FREE"
    p0.handle_right = inv @ right_world
    p1.handle_left = inv @ left_world
    obj.data.update_tag()
    return True


def set_bezier_world_data(obj, data):
    if not obj or obj.type != "CURVE" or len(data) < 2:
        return False
    spline = obj.data.splines[0] if obj.data.splines else obj.data.splines.new("BEZIER")
    while len(obj.data.splines) > 1:
        obj.data.splines.remove(obj.data.splines[-1])
    if spline.type != "BEZIER":
        obj.data.splines.clear()
        spline = obj.data.splines.new("BEZIER")
    current = len(spline.bezier_points)
    needed = len(data)
    if current < needed:
        spline.bezier_points.add(needed - current)
    elif current > needed:
        obj.data.splines.clear()
        spline = obj.data.splines.new("BEZIER")
        spline.bezier_points.add(needed - 1)
    inv = obj.matrix_world.inverted()
    for point, point_data in zip(spline.bezier_points, data):
        point.co = inv @ point_data["co"]
        point.handle_left = inv @ point_data["left"]
        point.handle_right = inv @ point_data["right"]
        point.handle_left_type = point_data.get("left_type", "FREE")
        point.handle_right_type = point_data.get("right_type", "FREE")
    obj.data.update_tag()
    return True


def preview_data_with_handle(data, point_index, side, world_position):
    preview = copy_bezier_data(data)
    if 0 <= point_index < len(preview):
        key = "left" if side == "LEFT" else "right"
        preview[point_index][key] = world_position.copy()
    return preview


def preview_data_with_segment_bend(data, segment_index, pull_world, origin_world=None):
    preview = copy_bezier_data(data)
    if segment_index < 0 or segment_index + 1 >= len(preview):
        return preview, None, None
    p0 = preview[segment_index]["co"]
    p1 = preview[segment_index + 1]["co"]
    if origin_world is not None:
        delta = pull_world - origin_world
        right = preview[segment_index]["right"] + delta
        left = preview[segment_index + 1]["left"] + delta
    else:
        right = p0 + (pull_world - p0) * 0.67
        left = p1 + (pull_world - p1) * 0.67
    preview[segment_index]["right"] = right
    preview[segment_index + 1]["left"] = left
    return preview, right, left


def preview_data_with_moved_points(data, world_points):
    if not data or len(data) != len(world_points):
        return []
    preview = copy_bezier_data(data)
    for idx, world in enumerate(world_points):
        delta = world - data[idx]["co"]
        preview[idx]["co"] = world.copy()
        preview[idx]["left"] = data[idx]["left"] + delta
        preview[idx]["right"] = data[idx]["right"] + delta
    return preview


def insert_bezier_point(obj, segment_index, world_position):
    points = world_points_from_curve(obj)
    if len(points) < 2:
        return False
    insert_index = max(1, min(len(points), segment_index + 1))
    new_points = [point.copy() for point in points]
    new_points.insert(insert_index, world_position.copy())
    return set_bezier_points(obj, new_points, handle_type="AUTO")


def remove_bezier_point(obj, point_index):
    points = world_points_from_curve(obj)
    if len(points) <= 2 or point_index < 0 or point_index >= len(points):
        return False
    new_points = [point.copy() for idx, point in enumerate(points) if idx != point_index]
    return set_bezier_points(obj, new_points, handle_type="AUTO")


def smoothed_bezier_points(obj, strength=0.55):
    points = world_points_from_curve(obj)
    if len(points) < 2:
        return []
    if len(points) < 3:
        return [point.copy() for point in points]
    smoothed = [points[0].copy()]
    for idx in range(1, len(points) - 1):
        target = (points[idx - 1] + points[idx + 1]) * 0.5
        smoothed.append(points[idx].lerp(target, strength))
    smoothed.append(points[-1].copy())
    return smoothed


def smooth_bezier_points(obj, strength=0.55):
    smoothed = smoothed_bezier_points(obj, strength)
    if not smoothed:
        return False
    return set_bezier_points(obj, smoothed, handle_type="AUTO")


def shrink_bezier_middle_points(obj, strength=0.18, tail_fixed_points=1):
    points = world_points_from_curve(obj)
    if len(points) < 3:
        return False
    root = points[0]
    tail_fixed_count = max(1, min(int(tail_fixed_points), len(points) - 1))
    fixed_start = len(points) - tail_fixed_count
    if fixed_start <= 1:
        return False
    tail_anchor = points[fixed_start]
    axis = tail_anchor - root
    axis_length_sq = axis.length_squared
    if axis_length_sq <= 1.0e-12:
        return False
    amount = max(0.0, min(0.95, float(strength)))
    contracted = [root.copy()]
    for point in points[1:fixed_start]:
        t = max(0.0, min(1.0, (point - root).dot(axis) / axis_length_sq))
        axis_point = root + axis * t
        middle_weight = math.sin(math.pi * t) ** 0.65
        contracted.append(point.lerp(axis_point, amount * middle_weight))
    contracted.extend(point.copy() for point in points[fixed_start:])
    return set_bezier_points(obj, contracted, handle_type="AUTO")


def set_bezier_points(obj, world_points, handle_type="AUTO"):
    if not obj or obj.type != "CURVE" or len(world_points) < 2:
        return False
    spline = obj.data.splines[0] if obj.data.splines else obj.data.splines.new("BEZIER")
    while len(obj.data.splines) > 1:
        obj.data.splines.remove(obj.data.splines[-1])
    if spline.type != "BEZIER":
        obj.data.splines.clear()
        spline = obj.data.splines.new("BEZIER")
    current = len(spline.bezier_points)
    needed = len(world_points)
    if current < needed:
        spline.bezier_points.add(needed - current)
    elif current > needed:
        # Blender has no direct point remove for BezierPoint in all versions; rebuild safely.
        obj.data.splines.clear()
        spline = obj.data.splines.new("BEZIER")
        spline.bezier_points.add(needed - 1)
    inv = obj.matrix_world.inverted()
    for point, world in zip(spline.bezier_points, world_points):
        point.co = inv @ world
        point.handle_left_type = handle_type
        point.handle_right_type = handle_type
    obj.data.update_tag()
    return True


def create_bezier_curve(context, world_points, group=None, surface_object=None, name="SurfaceHairCurve"):
    if len(world_points) < 2:
        return None
    settings = props.get_settings(context)
    if settings and group is None:
        group = props.active_group(settings) or props.ensure_default_group(settings)
    curve_data = bpy.data.curves.new(name=name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 16
    curve_data.bevel_depth = group_curve_radius(group, settings)
    curve_data.bevel_resolution = 1
    curve_data.materials.append(ensure_group_material(group))
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(len(world_points) - 1)
    obj = bpy.data.objects.new(name, curve_data)
    obj.location = (0.0, 0.0, 0.0)
    apply_group_display_color(obj, group)
    if settings:
        assign_object_to_group_collection(context, settings, obj, group)
    else:
        context.collection.objects.link(obj)
    for point, world in zip(spline.bezier_points, world_points):
        point.co = world
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    curve_id = new_id("curve")
    group_id = group.group_id if group else ""
    obj[CURVE_ID_PROP] = curve_id
    obj[GROUP_ID_PROP] = group_id
    obj[MANAGED_PROP] = True
    if surface_object:
        obj[SURFACE_NAME_PROP] = surface_object.name
    curve_data.update_tag()
    register_curve_item(context, obj, group, surface_object)
    return obj


def create_bezier_curve_from_data(context, data, group=None, surface_object=None, name="SurfaceHairCurve"):
    if len(data) < 2:
        return None
    obj = create_bezier_curve(
        context,
        [point_data["co"] for point_data in data],
        group=group,
        surface_object=surface_object,
        name=name,
    )
    if obj:
        set_bezier_world_data(obj, data)
    return obj


def register_curve_item(context, obj, group=None, surface_object=None):
    settings = props.get_settings(context)
    if not settings or not is_native_curve_object(obj):
        return None
    props.ensure_default_group(settings)
    curve_id = obj.get(CURVE_ID_PROP) or new_id("curve")
    obj[CURVE_ID_PROP] = curve_id
    group_id = ""
    if group:
        group_id = group.group_id
    elif obj.get(GROUP_ID_PROP):
        group_id = obj.get(GROUP_ID_PROP)
    if surface_object is None:
        surface_object = surface_object_for_item(None, obj)
    if not find_group_by_id(settings, group_id):
        fallback = props.active_group(settings) or props.ensure_default_group(settings)
        group_id = fallback.group_id if fallback else ""
    group = find_group_by_id(settings, group_id)
    obj[GROUP_ID_PROP] = group_id
    assign_object_to_group_collection(context, settings, obj, group)
    for idx, item in enumerate(settings.curves):
        if item.curve_id == curve_id:
            item.object = obj
            item.name = obj.name
            item.group_id = group_id
            item.surface_object = surface_object
            settings.curve_index = idx
            return item
    item = settings.curves.add()
    item.name = obj.name
    item.curve_id = curve_id
    item.group_id = group_id
    item.object = obj
    item.surface_object = surface_object
    settings.curve_index = len(settings.curves) - 1
    return item


def refresh_curve_registry(context):
    settings = props.get_settings(context)
    if not settings:
        return
    ensure_all_group_collections(context, settings)
    known = {item.curve_id: item for item in settings.curves}
    for obj in bpy.data.objects:
        if is_native_curve_object(obj):
            curve_id = obj.get(CURVE_ID_PROP)
            if curve_id in known:
                group_id = obj.get(GROUP_ID_PROP, "")
                surface_object = surface_object_for_item(known[curve_id], obj)
                if not find_group_by_id(settings, group_id):
                    fallback = props.active_group(settings) or props.ensure_default_group(settings)
                    group_id = fallback.group_id if fallback else ""
                    obj[GROUP_ID_PROP] = group_id
                known[curve_id].object = obj
                known[curve_id].name = obj.name
                known[curve_id].group_id = group_id
                known[curve_id].surface_object = surface_object
                assign_object_to_group_collection(context, settings, obj, find_group_by_id(settings, group_id))
            else:
                register_curve_item(context, obj, None, None)
    invalid = [idx for idx, item in enumerate(settings.curves) if item_object(item) is None]
    for idx in reversed(invalid):
        settings.curves.remove(idx)
    if settings.curve_index >= len(settings.curves):
        settings.curve_index = len(settings.curves) - 1
    sync_curve_object_states(settings)


def selected_curve_items(settings, include_active=True):
    if not settings:
        return []
    items = [item for item in settings.curves if item.selected and item_object(item) and not item.hidden]
    if not items and include_active and 0 <= settings.curve_index < len(settings.curves):
        item = settings.curves[settings.curve_index]
        if item_object(item) and not item.hidden:
            items = [item]
    return items


def select_curve_item(settings, curve_id, extend=False, return_changed=False, notify=True):
    selected_item = None
    changed = False
    props.suspend_overlay_updates()
    try:
        if not extend:
            for item in settings.curves:
                should_select = item.curve_id == curve_id
                if bool(item.selected) != should_select:
                    item.selected = should_select
                    changed = True
                if should_select:
                    selected_item = item
        else:
            for item in settings.curves:
                if item.curve_id == curve_id:
                    if not bool(item.selected):
                        item.selected = True
                        changed = True
                    selected_item = item
                    break
    finally:
        props.resume_overlay_updates()
    if changed and notify:
        props.tag_redraw_all_view3d(bpy.context)
    for idx, item in enumerate(settings.curves):
        if item.curve_id == curve_id:
            settings.curve_index = idx
            result = selected_item or item
            return (result, changed) if return_changed else result
    return (selected_item, changed) if return_changed else selected_item


def group_for_item(settings, item):
    if not settings or not item:
        return None
    for group in settings.groups:
        if group.group_id == item.group_id:
            return group
    return None


def group_curve_count(settings, group_id):
    return sum(1 for item in settings.curves if item.group_id == group_id and item_object(item) is not None)


def curve_visible(settings, item):
    if not settings or not item or item.hidden or item_object(item) is None:
        return False
    group = group_for_item(settings, item)
    solo_groups = [grp.group_id for grp in settings.groups if grp.solo]
    if solo_groups:
        return item.group_id in solo_groups
    if group and not group.visible:
        return False
    return True


def group_visible(settings, group):
    if not settings or not group:
        return True
    solo_groups = [grp.group_id for grp in settings.groups if grp.solo]
    if solo_groups:
        return group.group_id in solo_groups
    return bool(group.visible)


def curve_locked(settings, item):
    if not item or item.locked:
        return True
    group = group_for_item(settings, item)
    return bool(group and group.locked)


def curve_guide_visible(settings, item):
    return curve_visible(settings, item) and not curve_locked(settings, item)


def sync_curve_object_states(settings):
    if not settings:
        return
    for group in settings.groups:
        collection = bpy.data.collections.get(group.collection_name)
        if collection:
            collection.hide_viewport = not group_visible(settings, group)
        ensure_group_material(group)
    for obj in bpy.data.objects:
        if not obj.get("sht_preset_preview"):
            continue
        group = find_group_by_id(settings, obj.get(GROUP_ID_PROP, ""))
        apply_group_display_color(obj, group)
        visible = group_visible(settings, group) and bool(group and group.preset_enabled)
        obj.hide_viewport = not visible
        obj.hide_render = not visible
        obj.hide_select = False
        try:
            obj.hide_set(not visible)
        except RuntimeError:
            pass
    for item in settings.curves:
        obj = item_object(item)
        if not obj:
            continue
        guide_visible = curve_guide_visible(settings, item)
        locked = curve_locked(settings, item)
        obj[GROUP_ID_PROP] = item.group_id
        apply_group_display_color(obj, group_for_item(settings, item))
        obj.hide_viewport = not guide_visible
        obj.hide_select = locked
        try:
            obj.hide_set(not guide_visible)
        except RuntimeError:
            pass


def duplicate_curve(context, item, offset=None, snap_root=True, root_surface_object=None):
    obj = item_object(item)
    if not item or not obj:
        return None
    settings = props.get_settings(context)
    group = group_for_item(settings, item)
    surface_object = surface_object_for_item(item, obj)
    snap_surface_object = root_surface_object or surface_object
    bezier_data = bezier_world_data(obj)
    points = world_points_from_curve(obj)
    if len(points) < 2:
        return None
    if offset is None:
        direction = Vector((0.0, 0.0, 0.0))
        if len(points) >= 2 and (points[-1] - points[0]).length > 0:
            direction = (points[-1] - points[0]).normalized()
        offset = Vector((0.015, 0.015, 0.0)) + direction * 0.01
    if bezier_data:
        new_data = translated_bezier_data(bezier_data, offset)
        if snap_root:
            new_data = snap_bezier_root_to_surface(context, new_data, snap_surface_object, settings)
        return create_bezier_curve_from_data(
            context,
            new_data,
            group=group,
            surface_object=snap_surface_object or surface_object,
            name=f"{obj.name}_copy",
        )
    new_points = [point + offset for point in points]
    if snap_root and snap_surface_object and settings:
        projected = snap.project_world_to_surface(context, new_points[0], snap_surface_object, settings)
        if projected.hit:
            delta = projected.location - new_points[0]
            new_points = [point + delta for point in new_points]
    return create_bezier_curve(
        context,
        new_points,
        group=group,
        surface_object=snap_surface_object or surface_object,
        name=f"{obj.name}_copy",
    )


def point_distance_2d(point, screen_point):
    if not point or not screen_point:
        return math.inf
    return (point - screen_point).length
