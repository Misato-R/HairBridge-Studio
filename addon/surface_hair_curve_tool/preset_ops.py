from .i18n import t as ui_t, localized_layout
import bpy

from . import hair_curves, preset_library, props


def settings_or_report(operator, context):
    settings = props.get_settings(context)
    if not settings:
        operator.report({"ERROR"}, ui_t("Surface Hair settings not found"))
    return settings


def tag_redraw_all_view3d(context, rebuild=False):
    try:
        from . import operators

        operators.tag_redraw_all_view3d(context, rebuild=rebuild)
        return
    except Exception as exc:
        print(f"Surface Hair preset redraw fallback: {exc}")
    screen = getattr(context, "screen", None)
    if not screen:
        return
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def refresh_group_preset_preview_if_live(context, settings, group):
    try:
        hair_curves.refresh_live_group_preset_preview(context, settings, group)
    except Exception as exc:
        print(f"Surface Hair live preset preview failed: {exc}")


def refresh_all_live_group_preset_previews(context, settings):
    if not settings:
        return
    for group in settings.groups:
        refresh_group_preset_preview_if_live(context, settings, group)


def refresh_live_group_preset_previews_by_id(context, settings, group_ids):
    if not settings or not group_ids:
        return
    for group_id in set(group_ids):
        group = next((candidate for candidate in settings.groups if candidate.group_id == group_id), None)
        refresh_group_preset_preview_if_live(context, settings, group)


def preset_slot_modifier(group, slot):
    obj = hair_curves.find_group_preset_preview(group)
    if not obj:
        return None
    name = getattr(slot, "modifier_name", "")
    modifier = obj.modifiers.get(name) if name else None
    if modifier and modifier.type == "NODES":
        return modifier
    node_group = getattr(slot, "node_group", None)
    for candidate in obj.modifiers:
        if candidate.type == "NODES" and candidate.node_group == node_group:
            slot.modifier_name = candidate.name
            return candidate
    return None


def snapshot_group_slot_values(group):
    values = []
    if not group:
        return values
    hair_curves.save_group_preset_slot_values(group)
    for slot in group.preset_slots:
        stored = hair_curves.deserialize_modifier_values(getattr(slot, "stored_values", ""))
        if stored:
            values.append(stored)
        else:
            modifier = preset_slot_modifier(group, slot)
            values.append(hair_curves.modifier_id_property_values(modifier))
    return values


def restore_group_slot_values(group, values):
    if not group or not values:
        return
    for index, slot in enumerate(group.preset_slots):
        if index >= len(values):
            break
        modifier = preset_slot_modifier(group, slot)
        hair_curves.restore_modifier_values(modifier, values[index])
        slot.stored_values = hair_curves.serialize_modifier_values(values[index])


def active_node_modifier(context):
    obj = getattr(context, "active_object", None)
    if not obj or obj.type not in {"CURVE", "CURVES"}:
        return None
    active = getattr(obj.modifiers, "active", None)
    if active and active.type == "NODES" and active.node_group:
        return active
    for modifier in obj.modifiers:
        if modifier.type == "NODES" and modifier.node_group:
            return modifier
    return None


def copy_slot(source, target, name_suffix=""):
    target.name = (source.name or "预设") + name_suffix
    target.node_group = source.node_group
    target.enabled = source.enabled
    target.expanded = source.expanded
    target.modifier_name = ""
    target.stored_values = getattr(source, "stored_values", "")


def clear_slots(group):
    for index in reversed(range(len(group.preset_slots))):
        group.preset_slots.remove(index)
    group.preset_slot_index = -1


def library_slots_from_group(group, context=None):
    if not group:
        return []
    hair_curves.save_group_preset_slot_values(group)
    slots = []
    for index, slot in enumerate(group.preset_slots):
        modifier = preset_slot_modifier(group, slot)
        node_group = getattr(modifier, "node_group", None) or getattr(slot, "node_group", None)
        if not node_group:
            continue
        stored_values = hair_curves.modifier_id_property_values(modifier) if modifier else hair_curves.deserialize_modifier_values(getattr(slot, "stored_values", ""))
        if modifier:
            if getattr(slot, "node_group", None) != node_group:
                slot.node_group = node_group
            slot.modifier_name = modifier.name
            slot.stored_values = hair_curves.serialize_modifier_values(stored_values)
        slots.append(
            {
                "name": slot.name or getattr(modifier, "name", "") or node_group.name or f"预设 {index + 1}",
                "node_group": node_group.name,
                "node_tree": node_group,
                "enabled": bool(slot.enabled),
                "expanded": bool(slot.expanded),
                "stored_values": hair_curves.serialize_modifier_values(stored_values),
            }
        )
    if not slots and context:
        modifier = active_node_modifier(context)
        node_group = getattr(modifier, "node_group", None)
        if node_group:
            stored_values = hair_curves.modifier_id_property_values(modifier)
            slots.append(
                {
                    "name": getattr(modifier, "name", "") or node_group.name,
                    "node_group": node_group.name,
                    "node_tree": node_group,
                    "enabled": True,
                    "expanded": True,
                    "stored_values": hair_curves.serialize_modifier_values(stored_values),
                }
            )
    return slots


def add_library_slots_to_group(group, slot_data, preset_label=""):
    added = 0
    missing = []
    single_slot_label = preset_label if preset_label and len(slot_data) == 1 else ""
    for data in slot_data:
        node_group_name = data.get("node_group", "")
        node_group, message = preset_library.load_node_group_for_slot(data)
        if not node_group:
            missing.append(message)
            continue
        slot = group.preset_slots.add()
        slot_label = data.get("name") or node_group.name or f"预设 {len(group.preset_slots)}"
        if single_slot_label and slot_label == getattr(node_group, "name", ""):
            slot_label = single_slot_label
        slot.name = slot_label
        slot.enabled = bool(data.get("enabled", True))
        slot.expanded = bool(data.get("expanded", True))
        slot.modifier_name = ""
        slot.stored_values = data.get("stored_values", "") or ""
        slot.node_group = node_group
        group.preset_slot_index = len(group.preset_slots) - 1
        added += 1
    return added, missing


def refresh_group_if_enabled(context, settings, group, slot_values=None):
    if not group or not getattr(group, "preset_enabled", False):
        return None
    obj, _message = hair_curves.refresh_group_preset_preview(context, settings, group)
    if obj and slot_values:
        restore_group_slot_values(group, slot_values)
    return obj


class SURFACE_HAIR_OT_refresh_group_preset_preview(bpy.types.Operator):
    bl_idname = "surface_hair_curve.refresh_group_preset_preview"
    bl_label = ui_t("刷新当前分组预设预览")
    bl_description = ui_t("按当前分组的源曲线刷新 Hair Curves 预览，并应用预设节点组")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有当前分组"))
            return {"CANCELLED"}
        group.preset_enabled = True
        obj, message = hair_curves.refresh_group_preset_preview(context, settings, group)
        if not obj:
            self.report({"WARNING"}, ui_t(message))
            settings.live_status = message
            return {"CANCELLED"}
        settings.live_status = message
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(message))
        return {"FINISHED"}


class SURFACE_HAIR_OT_clear_group_preset_preview(bpy.types.Operator):
    bl_idname = "surface_hair_curve.clear_group_preset_preview"
    bl_label = ui_t("清除当前分组预设预览")
    bl_description = ui_t("删除当前分组的临时 Hair Curves 预览对象，并关闭预设")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有当前分组"))
            return {"CANCELLED"}
        group.preset_enabled = False
        settings.live_status = f"已关闭分组预设：{group.name}"
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(settings.live_status))
        return {"FINISHED"}


class SURFACE_HAIR_OT_add_preset_slot(bpy.types.Operator):
    bl_idname = "surface_hair_curve.add_preset_slot"
    bl_label = ui_t("添加分组预设槽")
    bl_description = ui_t("给当前分组添加一个可折叠的 Geometry Nodes 预设槽")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有当前分组"))
            return {"CANCELLED"}
        slot = group.preset_slots.add()
        slot.name = f"预设 {len(group.preset_slots)}"
        slot.enabled = True
        slot.expanded = True
        group.preset_slot_index = len(group.preset_slots) - 1
        group.preset_enabled = True
        settings.live_status = f"已添加预设槽：{slot.name}"
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_add_library_preset(bpy.types.Operator):
    bl_idname = "surface_hair_curve.add_library_preset"
    bl_label = ui_t("从预设库添加")
    bl_description = ui_t("从预设库载入一个或多个 Geometry Nodes 预设槽，并添加到当前分组")
    bl_options = {"REGISTER", "UNDO"}

    preset_id: bpy.props.StringProperty(name=ui_t("预设"), default="")

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有当前分组"))
            return {"CANCELLED"}
        selected_id = getattr(settings, "library_preset_id", "")
        preset_id = selected_id if preset_library.preset_definition(selected_id) else self.preset_id
        if not preset_library.preset_definition(preset_id):
            preset_id = preset_library.first_preset_id()
        if not preset_id:
            preset_id = "suifa"
        label = preset_library.preset_label(preset_id)
        slot_data = preset_library.preset_slots(preset_id)
        if not slot_data:
            message = f"预设库为空：{label}"
            self.report({"WARNING"}, ui_t(message))
            settings.live_status = message
            tag_redraw_all_view3d(context)
            return {"CANCELLED"}
        was_enabled = bool(group.preset_enabled)
        if was_enabled:
            group.preset_enabled = False
        added, missing = add_library_slots_to_group(group, slot_data, preset_label=label)
        if not added:
            if was_enabled:
                group.preset_enabled = True
            message = missing[0] if missing else f"无法添加预设：{label}"
            self.report({"WARNING"}, ui_t(message))
            settings.live_status = message
            tag_redraw_all_view3d(context)
            return {"CANCELLED"}
        group.preset_enabled = True
        settings.library_preset_id = preset_id
        if missing:
            settings.live_status = f"已添加预设库：{label}（跳过 {len(missing)} 个缺失节点组）"
        else:
            settings.live_status = f"已添加预设库：{label}"
        tag_redraw_all_view3d(context, rebuild=True)
        self.report({"INFO"}, ui_t(settings.live_status))
        return {"FINISHED"}


class SURFACE_HAIR_OT_save_library_preset(bpy.types.Operator):
    bl_idname = "surface_hair_curve.save_library_preset"
    bl_label = ui_t("保存到预设库")
    bl_description = ui_t("把当前分组的预设槽、节点组和参数保存为插件根目录下的 .blend/.json 预设")
    bl_options = {"REGISTER", "UNDO"}

    preset_id: bpy.props.StringProperty(name=ui_t("预设"), default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            self.report({"WARNING"}, ui_t("没有当前分组"))
            return {"CANCELLED"}
        slots = library_slots_from_group(group, context=context)
        if not slots:
            message = "当前分组没有可保存的预设槽"
            self.report({"WARNING"}, ui_t(message))
            settings.live_status = message
            return {"CANCELLED"}
        selected_id = getattr(settings, "library_preset_id", "") or self.preset_id
        selected_is_user = preset_library.is_user_preset(selected_id)
        custom_name = getattr(settings, "library_preset_name", "").strip()
        label = custom_name or (preset_library.preset_label(selected_id) if selected_is_user else group.name) or "自定义预设"
        target_id = selected_id if selected_is_user else ""
        preset_id, message = preset_library.save_user_preset(target_id, label, slots)
        if not preset_id:
            self.report({"WARNING"}, ui_t(message))
            settings.live_status = message
            return {"CANCELLED"}
        settings.library_preset_id = preset_id
        settings.library_preset_name = label
        settings.live_status = message
        tag_redraw_all_view3d(context)
        self.report({"INFO"}, ui_t(message))
        return {"FINISHED"}


class SURFACE_HAIR_OT_delete_library_preset(bpy.types.Operator):
    bl_idname = "surface_hair_curve.delete_library_preset"
    bl_label = ui_t("删除用户预设")
    bl_description = ui_t("删除当前下拉栏选中的用户 .blend/.json 预设；内置预设不会被删除")
    bl_options = {"REGISTER", "UNDO"}

    preset_id: bpy.props.StringProperty(name=ui_t("预设"), default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        preset_id = getattr(settings, "library_preset_id", "") or self.preset_id
        ok, message = preset_library.delete_user_preset(preset_id)
        if not ok:
            self.report({"WARNING"}, ui_t(message))
            settings.live_status = message
            return {"CANCELLED"}
        fallback_id = preset_library.first_preset_id()
        if fallback_id:
            settings.library_preset_id = fallback_id
        settings.library_preset_name = ""
        settings.live_status = message
        tag_redraw_all_view3d(context)
        self.report({"INFO"}, ui_t(message))
        return {"FINISHED"}


class SURFACE_HAIR_OT_remove_preset_slot(bpy.types.Operator):
    bl_idname = "surface_hair_curve.remove_preset_slot"
    bl_label = ui_t("删除分组预设槽")
    bl_description = ui_t("删除当前分组中的一个预设槽")
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            return {"CANCELLED"}
        idx = self.index if self.index >= 0 else group.preset_slot_index
        if idx < 0 or idx >= len(group.preset_slots):
            return {"CANCELLED"}
        name = group.preset_slots[idx].name
        group.preset_slots.remove(idx)
        group.preset_slot_index = min(idx, len(group.preset_slots) - 1)
        if not group.preset_slots:
            group.preset_slot_index = -1
        refresh_group_if_enabled(context, settings, group)
        settings.live_status = f"已删除预设槽：{name}"
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_move_preset_slot(bpy.types.Operator):
    bl_idname = "surface_hair_curve.move_preset_slot"
    bl_label = ui_t("移动分组预设槽")
    bl_description = ui_t("调整当前分组预设槽顺序")
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1)
    direction: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            return {"CANCELLED"}
        idx = self.index if self.index >= 0 else group.preset_slot_index
        new_idx = idx + int(self.direction)
        if idx < 0 or idx >= len(group.preset_slots) or new_idx < 0 or new_idx >= len(group.preset_slots):
            return {"CANCELLED"}
        values = snapshot_group_slot_values(group)
        value = values.pop(idx) if idx < len(values) else None
        if value is not None:
            values.insert(new_idx, value)
        group.preset_slots.move(idx, new_idx)
        group.preset_slot_index = new_idx
        refresh_group_if_enabled(context, settings, group, values)
        settings.live_status = "已调整预设顺序"
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_duplicate_preset_slot(bpy.types.Operator):
    bl_idname = "surface_hair_curve.duplicate_preset_slot"
    bl_label = ui_t("复制分组预设槽")
    bl_description = ui_t("复制当前分组中的一个预设槽，并尽量保留节点输入参数")
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            return {"CANCELLED"}
        idx = self.index if self.index >= 0 else group.preset_slot_index
        if idx < 0 or idx >= len(group.preset_slots):
            return {"CANCELLED"}
        values = snapshot_group_slot_values(group)
        source = group.preset_slots[idx]
        slot = group.preset_slots.add()
        copy_slot(source, slot, name_suffix=" 副本")
        new_idx = len(group.preset_slots) - 1
        group.preset_slots.move(new_idx, idx + 1)
        group.preset_slot_index = idx + 1
        if idx < len(values):
            values.insert(idx + 1, dict(values[idx]))
        refresh_group_if_enabled(context, settings, group, values)
        settings.live_status = f"已复制预设槽：{source.name}"
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


class SURFACE_HAIR_OT_set_preset_slots_expanded(bpy.types.Operator):
    bl_idname = "surface_hair_curve.set_preset_slots_expanded"
    bl_label = ui_t("展开或折叠全部预设")
    bl_description = ui_t("一次展开或折叠当前分组中的所有预设槽")
    bl_options = {"REGISTER", "UNDO"}

    expanded: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        group = props.active_group(settings)
        if not group:
            return {"CANCELLED"}
        for slot in group.preset_slots:
            slot.expanded = self.expanded
        tag_redraw_all_view3d(context)
        return {"FINISHED"}


class SURFACE_HAIR_OT_copy_preset_stack_to_groups(bpy.types.Operator):
    bl_idname = "surface_hair_curve.copy_preset_stack_to_groups"
    bl_label = ui_t("预设栈应用到全部分组")
    bl_description = ui_t("把当前分组的预设开关、实时更新和预设槽复制到其他分组")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_or_report(self, context)
        if not settings:
            return {"CANCELLED"}
        source = props.active_group(settings)
        if not source:
            return {"CANCELLED"}
        source_values = snapshot_group_slot_values(source)
        changed = 0
        for group in settings.groups:
            if group == source:
                continue
            was_enabled = bool(group.preset_enabled)
            if was_enabled:
                group.preset_enabled = False
            clear_slots(group)
            if group.preset_live_update != source.preset_live_update:
                group.preset_live_update = source.preset_live_update
            if group.preset_node_group != source.preset_node_group:
                group.preset_node_group = source.preset_node_group
            for slot_index, source_slot in enumerate(source.preset_slots):
                target_slot = group.preset_slots.add()
                copy_slot(source_slot, target_slot)
                if slot_index == source.preset_slot_index:
                    group.preset_slot_index = slot_index
            if group.preset_slots and group.preset_slot_index < 0:
                group.preset_slot_index = 0
            if group.preset_enabled != source.preset_enabled:
                group.preset_enabled = source.preset_enabled
            if group.preset_enabled:
                obj = hair_curves.find_group_preset_preview(group)
                if obj:
                    restore_group_slot_values(group, source_values)
            changed += 1
        settings.live_status = f"已将预设栈应用到 {changed} 个分组"
        tag_redraw_all_view3d(context, rebuild=True)
        return {"FINISHED"}


classes = (
    SURFACE_HAIR_OT_refresh_group_preset_preview,
    SURFACE_HAIR_OT_clear_group_preset_preview,
    SURFACE_HAIR_OT_add_preset_slot,
    SURFACE_HAIR_OT_add_library_preset,
    SURFACE_HAIR_OT_save_library_preset,
    SURFACE_HAIR_OT_delete_library_preset,
    SURFACE_HAIR_OT_remove_preset_slot,
    SURFACE_HAIR_OT_move_preset_slot,
    SURFACE_HAIR_OT_duplicate_preset_slot,
    SURFACE_HAIR_OT_set_preset_slots_expanded,
    SURFACE_HAIR_OT_copy_preset_stack_to_groups,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
