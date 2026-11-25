import json

import bpy

from . import modifier_compat

from . import curve_data


PREVIEW_PROP = "sht_preset_preview"


def _result_name(group, suffix):
    base = (getattr(group, "name", "") or "Group").strip() or "Group"
    return f"SHT_{base}_{suffix}"


def group_curve_items(settings, group):
    if not settings or not group:
        return []
    return [
        item
        for item in settings.curves
        if item.group_id == group.group_id and curve_data.item_object(item) is not None
    ]


def curve_item_to_poly_spline_data(item, point_count=None):
    obj = curve_data.item_object(item)
    if point_count:
        points = curve_data.resample_curve_world(obj, point_count, resolution=24)
    else:
        points = curve_data.world_points_from_curve(obj)
    if len(points) < 2:
        return None
    return {
        "type": "POLY",
        "points": [{"co": point.copy()} for point in points],
        "use_cyclic_u": False,
        "resolution_u": 8,
    }


def build_hair_curve_splines(items, point_count=None):
    if point_count is not None:
        point_count = max(2, int(point_count))
    splines = [curve_item_to_poly_spline_data(item, point_count=point_count) for item in items]
    return [spline for spline in splines if spline]


def mark_export_object(context, settings, obj, group, id_prefix="hair_export"):
    obj[curve_data.MANAGED_PROP] = True
    obj[curve_data.EXPORT_PROP] = True
    obj[curve_data.CURVE_ID_PROP] = curve_data.new_id(id_prefix)
    if group:
        obj[curve_data.GROUP_ID_PROP] = group.group_id
        curve_data.apply_group_display_color(obj, group)
    if settings and group:
        curve_data.assign_object_to_group_collection(context, settings, obj, group)
    elif obj.name not in context.collection.objects.keys():
        context.collection.objects.link(obj)
    return obj


def detach_export_object_from_group(context, settings, obj):
    if not obj:
        return
    try:
        if curve_data.GROUP_ID_PROP in obj:
            del obj[curve_data.GROUP_ID_PROP]
    except Exception:
        pass
    root = curve_data.ensure_root_collection(context)
    if obj.name not in root.objects.keys():
        try:
            root.objects.link(obj)
        except RuntimeError:
            pass
    for collection in list(obj.users_collection):
        if collection == root:
            continue
        if len(obj.users_collection) > 1:
            try:
                collection.objects.unlink(obj)
            except RuntimeError:
                pass


def find_group_preset_preview(group):
    if not group:
        return None
    name = getattr(group, "preview_object_name", "")
    obj = bpy.data.objects.get(name) if name else None
    if obj and obj.get(PREVIEW_PROP) and obj.name in bpy.data.objects:
        return obj
    group_id = getattr(group, "group_id", "")
    for candidate in bpy.data.objects:
        if candidate.get(PREVIEW_PROP) and candidate.get(curve_data.GROUP_ID_PROP, "") == group_id:
            try:
                group.preview_object_name = candidate.name
            except Exception:
                pass
            return candidate
    return None


def group_preset_preview_objects(group):
    if not group:
        return []
    group_id = getattr(group, "group_id", "")
    return [
        candidate
        for candidate in bpy.data.objects
        if candidate.get(PREVIEW_PROP) and candidate.get(curve_data.GROUP_ID_PROP, "") == group_id
    ]


def remove_extra_group_preset_previews(context, group, keep_obj=None):
    removed = 0
    for obj in group_preset_preview_objects(group):
        if keep_obj and obj == keep_obj:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        except Exception:
            pass
    return removed


def remove_group_preset_preview(context, group):
    obj = find_group_preset_preview(group)
    save_group_preset_slot_values(group, obj)
    for preview_obj in group_preset_preview_objects(group):
        if preview_obj.name in bpy.data.objects:
            bpy.data.objects.remove(preview_obj, do_unlink=True)
    if group:
        try:
            group.preview_object_name = ""
        except Exception:
            pass
    return True


def hide_group_preset_preview(context, group):
    obj = find_group_preset_preview(group)
    save_group_preset_slot_values(group, obj)
    if obj:
        try:
            obj.hide_viewport = True
            obj.hide_render = True
            obj.hide_set(True)
        except Exception:
            pass
    return True


def remove_all_group_preset_previews(context, settings):
    if not settings:
        return
    for group in settings.groups:
        remove_group_preset_preview(context, group)


def group_for_preset_slot(settings, slot):
    if not settings or not slot:
        return None
    for group in settings.groups:
        for candidate in group.preset_slots:
            if candidate == slot:
                return group
    return None


def ensure_legacy_group_preset_slot(settings, group):
    if not group:
        return None
    legacy_node_group = getattr(group, "preset_node_group", None)
    if legacy_node_group and not group.preset_slots:
        slot = group.preset_slots.add()
        slot.name = legacy_node_group.name
        slot.node_group = legacy_node_group
        slot.enabled = True
        slot.expanded = True
        group.preset_slot_index = 0
        return slot
    if group.preset_slots and group.preset_slot_index < 0:
        group.preset_slot_index = 0
    return group.preset_slots[group.preset_slot_index] if 0 <= group.preset_slot_index < len(group.preset_slots) else None


def group_preset_slots(group):
    ensure_legacy_group_preset_slot(None, group)
    return [slot for slot in getattr(group, "preset_slots", []) if getattr(slot, "enabled", True) and getattr(slot, "node_group", None)]


def preset_modifier_name(group, slot, index):
    if getattr(slot, "modifier_name", ""):
        return slot.modifier_name
    node_group = getattr(slot, "node_group", None)
    label = getattr(slot, "name", "") or getattr(node_group, "name", "") or f"预设 {index + 1}"
    return f"SHT_{index + 1:02d}_{label}"


def modifier_id_property_values(modifier):
    values = {}
    if not modifier:
        return values
    for key in modifier_compat.modifier_input_keys(modifier):
        if key.endswith("_use_attribute") or key.endswith("_attribute_name"):
            continue
        try:
            value = modifier_compat.modifier_input_value(modifier, key)
            if hasattr(value, "copy"):
                value = value.copy()
            values[key] = value
        except Exception:
            pass
    return values


def _json_safe_value(value):
    if hasattr(value, "to_tuple"):
        try:
            return list(value.to_tuple())
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return list(value)
    except Exception:
        return None


def serialize_modifier_values(values):
    safe = {}
    for key, value in (values or {}).items():
        safe_value = _json_safe_value(value)
        if safe_value is not None:
            safe[key] = safe_value
    try:
        return json.dumps(safe, ensure_ascii=False)
    except Exception:
        return ""


def deserialize_modifier_values(text):
    if not text:
        return {}
    try:
        values = json.loads(text)
    except Exception:
        return {}
    return values if isinstance(values, dict) else {}


def snapshot_preset_modifier_values(obj):
    if not obj:
        return {}
    values = {}
    for modifier in obj.modifiers:
        if modifier.type != "NODES":
            continue
        values[modifier.name] = modifier_id_property_values(modifier)
    return values


def restore_modifier_values(modifier, values):
    if not modifier or not values:
        return
    modifier_keys = set(modifier_compat.modifier_input_keys(modifier))
    for key, value in values.items():
        if key not in modifier_keys:
            continue
        modifier_compat.set_modifier_input_value(modifier, key, value)


def save_group_preset_slot_values(group, obj=None):
    if not group:
        return
    obj = obj or find_group_preset_preview(group)
    if not obj:
        return
    for slot in group.preset_slots:
        modifier = None
        name = getattr(slot, "modifier_name", "")
        if name:
            modifier = obj.modifiers.get(name)
        node_group = getattr(slot, "node_group", None)
        if not modifier:
            for candidate in obj.modifiers:
                if candidate.type == "NODES" and candidate.node_group == node_group:
                    modifier = candidate
                    break
        if modifier and modifier.type == "NODES":
            slot.stored_values = serialize_modifier_values(modifier_id_property_values(modifier))


def stored_values_by_modifier_name(group):
    values = {}
    if not group:
        return values
    for index, slot in enumerate(group_preset_slots(group)):
        name = preset_modifier_name(group, slot, index)
        stored = deserialize_modifier_values(getattr(slot, "stored_values", ""))
        if stored:
            values[name] = stored
    return values


def apply_group_preset_modifiers(obj, group, old_values=None):
    if not obj or not group:
        return []
    stored_values = stored_values_by_modifier_name(group)
    old_values = old_values or {}
    keep_names = set()
    modifiers = []
    for index, slot in enumerate(group_preset_slots(group)):
        name = preset_modifier_name(group, slot, index)
        modifier = obj.modifiers.get(name)
        if not modifier or modifier.type != "NODES":
            modifier = obj.modifiers.new(name, "NODES")
        node_group = getattr(slot, "node_group", None)
        modifier.node_group = node_group
        modifier.show_expanded = bool(getattr(slot, "expanded", True))
        if not getattr(slot, "name", "") or str(slot.name).startswith("预设 "):
            slot.name = getattr(node_group, "name", "") or slot.name or f"预设 {index + 1}"
        slot.modifier_name = modifier.name
        restore_modifier_values(modifier, old_values.get(modifier.name) or stored_values.get(modifier.name))
        slot.stored_values = serialize_modifier_values(modifier_id_property_values(modifier))
        keep_names.add(modifier.name)
        modifiers.append(modifier)
    for modifier in list(obj.modifiers):
        if modifier.type == "NODES" and modifier.name.startswith("SHT_") and modifier.name not in keep_names:
            obj.modifiers.remove(modifier)
    return modifiers


def mark_preset_preview_object(context, settings, obj, group):
    mark_export_object(context, settings, obj, group, id_prefix="hair_preview")
    obj[PREVIEW_PROP] = True
    obj.name = _result_name(group, "Preview")
    obj.data.name = obj.name
    obj.hide_select = False
    if group:
        group.preview_object_name = obj.name
    return obj


def write_hair_curves_data(data, splines, group=None, surface=None):
    if not data or not splines or not hasattr(data, "add_curves"):
        return False
    sizes = [len(spline["points"]) for spline in splines]
    try:
        current_count = len(data.curves) if hasattr(data, "curves") else 0
        if current_count == len(sizes):
            if current_count:
                data.resize_curves(sizes, indices=range(current_count))
        else:
            if current_count:
                data.remove_curves()
            data.add_curves(sizes)
        position_attr = data.attributes.get("position")
        if not position_attr:
            return False
        idx = 0
        for spline in splines:
            for pdata in spline["points"]:
                if idx >= len(position_attr.data):
                    return False
                position_attr.data[idx].vector = pdata["co"]
                idx += 1
        if idx != len(position_attr.data):
            return False
        if group:
            color = curve_data.group_color_tuple(group)
            try:
                color_attr = data.attributes.get("surface_hair_group_color") or data.attributes.new(
                    "surface_hair_group_color",
                    "FLOAT_COLOR",
                    "POINT",
                )
                for color_item in color_attr.data:
                    color_item.color = color
            except Exception:
                pass
        if surface:
            try:
                data.surface = surface
            except Exception:
                pass
        data.update_tag()
        return True
    except Exception as exc:
        print(f"Surface Hair curves data refresh failed: {exc}")
        return False


def update_hair_curves_object_from_items(obj, items, point_count=None, group=None):
    if not obj or obj.type != "CURVES":
        return False
    splines = build_hair_curve_splines(items, point_count=point_count)
    if not splines:
        return False
    surface = next((item.surface_object for item in items if getattr(item, "surface_object", None)), None)
    return write_hair_curves_data(obj.data, splines, group=group, surface=surface)


def refresh_group_preset_preview(context, settings, group):
    if not settings or not group:
        return None, "没有当前分组"
    ensure_legacy_group_preset_slot(settings, group)
    if not getattr(group, "preset_enabled", False):
        remove_group_preset_preview(context, group)
        return None, "当前分组预设已关闭"
    items = group_curve_items(settings, group)
    if not items:
        remove_group_preset_preview(context, group)
        return None, "当前分组没有可预览曲线"
    old_obj = find_group_preset_preview(group)
    old_values = snapshot_preset_modifier_values(old_obj)
    old_selected = False
    old_active = False
    try:
        old_selected = bool(old_obj and old_obj.select_get())
        old_active = bool(old_obj and context.view_layer.objects.active == old_obj)
    except Exception:
        pass
    point_count = max(2, int(getattr(settings, "hair_curve_point_count", 8)))
    obj = None
    if old_obj and old_obj.name in bpy.data.objects:
        if update_hair_curves_object_from_items(old_obj, items, point_count=point_count, group=group):
            obj = old_obj
            mark_preset_preview_object(context, settings, obj, group)
        else:
            bpy.data.objects.remove(old_obj, do_unlink=True)
    if obj is None:
        obj = create_hair_curves_object(
            context,
            items,
            name=_result_name(group, "Preview"),
            point_count=point_count,
            group=group,
            settings=settings,
        )
    if not obj:
        return None, "无法生成分组预设预览"
    mark_preset_preview_object(context, settings, obj, group)
    remove_extra_group_preset_previews(context, group, keep_obj=obj)
    if getattr(group, "preset_enabled", False):
        apply_group_preset_modifiers(obj, group, old_values=old_values)
    try:
        visible = curve_data.group_visible(settings, group)
        obj.hide_viewport = not visible
        obj.hide_render = not visible
        obj.hide_set(not visible)
        if old_selected:
            obj.select_set(True)
        if old_active:
            context.view_layer.objects.active = obj
    except Exception:
        pass
    return obj, f"已刷新分组预设预览：{group.name}"


def refresh_existing_group_preset_previews(context, settings):
    if not settings:
        return 0
    refreshed = 0
    for group in settings.groups:
        ensure_legacy_group_preset_slot(settings, group)
        if getattr(group, "preset_enabled", False) and find_group_preset_preview(group):
            obj, _message = refresh_group_preset_preview(context, settings, group)
            if obj:
                refreshed += 1
    return refreshed


def refresh_live_group_preset_preview(context, settings, group):
    if not settings or not group:
        return None
    ensure_legacy_group_preset_slot(settings, group)
    if not getattr(group, "preset_enabled", False) or not getattr(group, "preset_live_update", False):
        return None
    obj, _message = refresh_group_preset_preview(context, settings, group)
    return obj


def remove_source_curve_items(context, settings, items):
    if not settings or not items:
        return
    curve_ids = {item.curve_id for item in items}
    objects = []
    for item in items:
        obj = curve_data.item_object(item)
        if obj:
            objects.append(obj)
    for obj in objects:
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
    for idx in reversed(range(len(settings.curves))):
        if settings.curves[idx].curve_id in curve_ids:
            settings.curves.remove(idx)
    settings.curve_index = min(settings.curve_index, len(settings.curves) - 1)
    curve_data.refresh_curve_registry(context)


def create_merged_curve_object(context, items, group=None, settings=None, name=None):
    source_objects = [curve_data.item_object(item) for item in items]
    source_objects = [obj for obj in source_objects if obj]
    if not source_objects:
        return None
    data = bpy.data.curves.new(name=name or _result_name(group, "Merged"), type="CURVE")
    data.dimensions = "3D"
    data.resolution_u = max((getattr(obj.data, "resolution_u", 12) for obj in source_objects), default=12)
    data.bevel_depth = getattr(source_objects[0].data, "bevel_depth", 0.003)
    data.bevel_resolution = getattr(source_objects[0].data, "bevel_resolution", 1)
    spline_count = 0
    for obj in source_objects:
        matrix = obj.matrix_world
        for src in obj.data.splines:
            if src.type == "BEZIER" and len(src.bezier_points) >= 2:
                dst = data.splines.new("BEZIER")
                dst.bezier_points.add(len(src.bezier_points) - 1)
                dst.use_cyclic_u = bool(src.use_cyclic_u)
                dst.resolution_u = getattr(src, "resolution_u", data.resolution_u)
                for dst_point, src_point in zip(dst.bezier_points, src.bezier_points):
                    dst_point.co = matrix @ src_point.co
                    dst_point.handle_left = matrix @ src_point.handle_left
                    dst_point.handle_right = matrix @ src_point.handle_right
                    dst_point.handle_left_type = src_point.handle_left_type
                    dst_point.handle_right_type = src_point.handle_right_type
                spline_count += 1
            elif src.type == "POLY" and len(src.points) >= 2:
                dst = data.splines.new("POLY")
                dst.points.add(len(src.points) - 1)
                dst.use_cyclic_u = bool(src.use_cyclic_u)
                for dst_point, src_point in zip(dst.points, src.points):
                    world = matrix @ src_point.co.to_3d()
                    dst_point.co = (world.x, world.y, world.z, 1.0)
                spline_count += 1
            else:
                sampled = curve_data.resample_curve_world(obj, max(2, len(curve_data.world_points_from_curve(obj))), resolution=24)
                if len(sampled) < 2:
                    continue
                dst = data.splines.new("POLY")
                dst.points.add(len(sampled) - 1)
                for dst_point, world in zip(dst.points, sampled):
                    dst_point.co = (world.x, world.y, world.z, 1.0)
                spline_count += 1
    if spline_count <= 0:
        bpy.data.curves.remove(data)
        return None
    obj = bpy.data.objects.new(name or data.name, data)
    mark_export_object(context, settings, obj, group, id_prefix="merged")
    data.update_tag()
    return obj


def create_export_curve_object(context, items, name="SHT_HairCurves_Export"):
    curves_obj = create_hair_curves_object(context, items, name)
    if curves_obj:
        return curves_obj
    splines = [curve_item_to_poly_spline_data(item) for item in items]
    splines = [spline for spline in splines if spline]
    if not splines:
        return None
    data = bpy.data.curves.new(name=name, type="CURVE")
    data.dimensions = "3D"
    data.resolution_u = 8
    data.bevel_depth = 0.002
    data.bevel_resolution = 0
    obj = bpy.data.objects.new(name, data)
    context.collection.objects.link(obj)
    for spline_data in splines:
        spline = data.splines.new("POLY")
        points = spline_data["points"]
        spline.points.add(len(points) - 1)
        for point, pdata in zip(spline.points, points):
            co = pdata["co"]
            point.co = (co.x, co.y, co.z, 1.0)
    obj[curve_data.MANAGED_PROP] = True
    obj[curve_data.EXPORT_PROP] = True
    obj[curve_data.CURVE_ID_PROP] = curve_data.new_id("hair_export")
    data.update_tag()
    return obj


def create_hair_curves_object(context, items, name="SHT_HairCurves_Export", point_count=None, group=None, settings=None):
    splines = build_hair_curve_splines(items, point_count=point_count)
    if not splines or not hasattr(bpy.data, "hair_curves"):
        return None
    try:
        data = bpy.data.hair_curves.new(name)
        obj = bpy.data.objects.new(name, data)
        context.collection.objects.link(obj)
        surface = next((item.surface_object for item in items if getattr(item, "surface_object", None)), None)
        if not write_hair_curves_data(data, splines, group=group, surface=surface):
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.hair_curves.remove(data)
            return None
        mark_export_object(context, settings, obj, group, id_prefix="hair_export")
        return obj
    except Exception:
        return None


def add_to_existing_curves_object(target_object, items):
    if not target_object or target_object.type != "CURVES":
        return False
    splines = [curve_item_to_poly_spline_data(item) for item in items]
    splines = [spline for spline in splines if spline]
    if not splines:
        return False
    try:
        curves = target_object.data
        points_per_curve = [len(spline["points"]) for spline in splines]
        if not hasattr(curves, "add_curves"):
            return False
        current_point_count = len(curves.attributes["position"].data)
        curves.add_curves(points_per_curve)
        position_attr = curves.attributes.get("position")
        idx = current_point_count
        inv = target_object.matrix_world.inverted()
        for spline in splines:
            for pdata in spline["points"]:
                if idx >= len(position_attr.data):
                    break
                local = inv @ pdata["co"]
                position_attr.data[idx].vector = local
                idx += 1
        curves.update_tag()
        return True
    except Exception:
        return False


def join_selected_to_hair_curves(context, settings):
    items = curve_data.selected_curve_items(settings)
    if not items:
        return None, "No selected managed curves to export"
    active = context.view_layer.objects.active
    if active and active.type == "CURVES" and add_to_existing_curves_object(active, items):
        return active, f"Added {len(items)} curves to active Hair Curves object"
    obj = create_export_curve_object(context, items)
    if not obj:
        return None, "Could not build export curve data"
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except Exception:
        pass
    return obj, f"Exported {len(items)} curves to {obj.name}"


def merge_group_curves(context, settings, group):
    items = group_curve_items(settings, group)
    if not items:
        return None, "当前分组没有可合并的插件曲线"
    obj = create_merged_curve_object(context, items, group=group, settings=settings)
    if not obj:
        return None, "无法合并当前分组曲线"
    remove_source_curve_items(context, settings, items)
    remove_group_preset_preview(context, group)
    return obj, f"已合并当前分组 {len(items)} 根头发"


def convert_group_to_hair_curves(context, settings, group, point_count):
    items = group_curve_items(settings, group)
    if not items:
        return None, "当前分组没有可转换的插件曲线"
    obj = create_hair_curves_object(
        context,
        items,
        name=_result_name(group, "Hair"),
        point_count=point_count,
        group=group,
        settings=settings,
    )
    if not obj:
        return None, "无法生成 Hair Curves 发丝对象"
    if getattr(group, "preset_enabled", False):
        apply_group_preset_modifiers(obj, group)
    detach_export_object_from_group(context, settings, obj)
    remove_source_curve_items(context, settings, items)
    remove_group_preset_preview(context, group)
    return obj, f"已转换当前分组 {len(items)} 根发丝，点数 {int(point_count)}"
