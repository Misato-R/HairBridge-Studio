from .i18n import t as ui_t, localized_layout
import bpy

from . import curve_data, modifier_compat, preset_library, preset_ops, props


PANEL_CATEGORY = "表面头发"


class SURFACE_HAIR_UL_groups(bpy.types.UIList):
    bl_idname = "SURFACE_HAIR_UL_groups"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        settings = props.get_settings(context)
        count = curve_data.group_curve_count(settings, item.group_id) if settings else 0
        row = layout.row(align=True)
        row.prop(item, "color", text="")
        row.prop(item, "name", text="", emboss=False)
        row.label(text=str(count), icon="CURVE_BEZCURVE")
        row.prop(item, "preset_enabled", text="", icon="NODETREE", emboss=False)
        row.prop(item, "visible", text="", icon="HIDE_OFF" if item.visible else "HIDE_ON", emboss=False)
        row.prop(item, "solo", text="", icon="SOLO_ON" if item.solo else "SOLO_OFF", emboss=False)
        row.prop(item, "locked", text="", icon="LOCKED" if item.locked else "UNLOCKED", emboss=False)


class SURFACE_HAIR_UL_curves(bpy.types.UIList):
    bl_idname = "SURFACE_HAIR_UL_curves"

    def filter_items(self, context, data, propname):
        settings = props.get_settings(context)
        items = getattr(data, propname)
        flags = []
        order = []
        active_group = props.active_group(settings)
        active_group_id = active_group.group_id if active_group else ""
        for item in items:
            visible = bool(item.group_id == active_group_id or not active_group_id)
            flags.append(self.bitflag_filter_item if visible else 0)
        return flags, order

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "selected", text="", icon="RESTRICT_SELECT_OFF" if item.selected else "RESTRICT_SELECT_ON", emboss=False)
        row.prop(item, "name", text="", emboss=False, icon="CURVE_BEZCURVE")
        row.prop(item, "hidden", text="", icon="HIDE_ON" if item.hidden else "HIDE_OFF", emboss=False)
        row.prop(item, "locked", text="", icon="LOCKED" if item.locked else "UNLOCKED", emboss=False)


def settings_or_error(layout, context):
    settings = props.get_settings(context)
    if not settings:
        layout.label(text=ui_t("设置未注册"), icon="ERROR")
        return None
    return settings


def draw_tool_buttons(layout):
    row = layout.row(align=True)
    row.operator("surface_hair_curve.enter_modal", text=ui_t("开始"), icon="GREASEPENCIL")
    row.operator("surface_hair_curve.finish_modal", text="", icon="CHECKMARK")
    row.operator("surface_hair_curve.cancel_modal", text="", icon="CANCEL")


def draw_active_group_strip(layout, settings):
    group = props.active_group(settings)
    if not group:
        layout.label(text=ui_t("无当前分组"), icon="GROUP")
        return
    row = layout.row(align=True)
    row.prop(group, "color", text="")
    row.prop(group, "name", text="")
    row.prop(group, "visible", text="", icon="HIDE_OFF" if group.visible else "HIDE_ON", emboss=False)
    row.prop(group, "solo", text="", icon="SOLO_ON" if group.solo else "SOLO_OFF", emboss=False)
    row.prop(group, "locked", text="", icon="LOCKED" if group.locked else "UNLOCKED", emboss=False)


def modifier_socket_items(modifier, node_group):
    if not modifier or not node_group:
        return []
    modifier_keys = set(modifier_compat.modifier_input_keys(modifier))
    items = []
    for item in node_group.interface.items_tree:
        if getattr(item, "item_type", "") == "PANEL":
            continue
        if getattr(item, "item_type", "") != "SOCKET":
            continue
        if getattr(item, "in_out", "") != "INPUT":
            continue
        identifier = getattr(item, "identifier", "")
        if not identifier or identifier not in modifier_keys:
            continue
        if modifier_compat.modifier_input_ui_property(modifier, identifier) is None:
            continue
        if getattr(item, "hide_in_modifier", False) or getattr(item, "hide_value", False):
            continue
        items.append(item)
    return items


def draw_modifier_socket_inputs(layout, modifier, node_group, items=None):
    if not modifier or not node_group:
        layout.label(text=ui_t("选择节点组后可调节参数"), icon="INFO")
        return
    if items is None:
        items = modifier_socket_items(modifier, node_group)
    if not items:
        layout.label(text=ui_t("这个节点组没有暴露可调输入"), icon="INFO")
        return
    current_panel = None
    col = layout.column(align=True)
    for item in items:
        try:
            identifier = getattr(item, "identifier", "")
            if not identifier:
                continue
            parent = getattr(item, "parent", None)
            parent_name = getattr(parent, "name", "") if parent else ""
            if parent_name and parent_name != current_panel:
                current_panel = parent_name
                col.label(text=current_panel)
            row = col.row(align=True)
            prop_target = modifier_compat.modifier_input_ui_property(modifier, identifier)
            if not prop_target:
                continue
            data, property_name = prop_target
            row.prop(data, property_name, text=getattr(item, "name", identifier))
        except Exception:
            continue


def draw_preset_slot(layout, group, slot, index):
    node_group = getattr(slot, "node_group", None)
    modifier = preset_ops.preset_slot_modifier(group, slot)
    socket_items = modifier_socket_items(modifier, node_group)
    input_count = len(socket_items)
    header = layout.row(align=True)
    header.prop(slot, "expanded", text="", icon="TRIA_DOWN" if slot.expanded else "TRIA_RIGHT", emboss=False)
    header.prop(slot, "enabled", text="", icon="CHECKBOX_HLT" if slot.enabled else "CHECKBOX_DEHLT", emboss=False)
    title = slot.name or getattr(node_group, "name", "") or f"预设 {index + 1}"
    header.label(text=f"{index + 1}. {title}", icon="NODETREE")
    tools = layout.row(align=True)
    tools.label(text=f"{input_count} 项" if node_group else "未指定")
    move_up = tools.operator("surface_hair_curve.move_preset_slot", text="", icon="TRIA_UP", emboss=False)
    move_up.index = index
    move_up.direction = -1
    move_down = tools.operator("surface_hair_curve.move_preset_slot", text="", icon="TRIA_DOWN", emboss=False)
    move_down.index = index
    move_down.direction = 1
    duplicate = tools.operator("surface_hair_curve.duplicate_preset_slot", text="", icon="DUPLICATE", emboss=False)
    duplicate.index = index
    remove = tools.operator("surface_hair_curve.remove_preset_slot", text="", icon="CANCEL", emboss=False)
    remove.index = index
    if not slot.expanded:
        layout.separator(factor=0.35)
        return
    inner = layout.column(align=True)
    inner.enabled = bool(slot.enabled)
    inner.prop(slot, "node_group", text=ui_t("节点组"))
    if node_group and not modifier:
        inner.label(text=ui_t("刷新预览后显示参数"), icon="FILE_REFRESH")
    draw_modifier_socket_inputs(inner, modifier, node_group, socket_items)
    layout.separator(factor=0.35)


class SURFACE_HAIR_PT_main(bpy.types.Panel):
    bl_label = ui_t("表面头发曲线")
    bl_idname = "SURFACE_HAIR_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_order = 0

    def draw(self, context):
        layout = localized_layout(self.layout)
        language_property = "hairbridge_language" if hasattr(context.scene, "hairbridge_language") else "surface_hair_language"
        layout.prop(context.scene, language_property, expand=True)
        settings = settings_or_error(layout, context)
        if not settings:
            return
        layout.use_property_split = False

        draw_tool_buttons(layout)

        box = layout.box()
        row = box.row(align=True)
        row.prop(settings, "tool", text="")
        row.prop(settings, "draw_mode", text="")


class SURFACE_HAIR_PT_draw_snap(bpy.types.Panel):
    bl_label = ui_t("绘制与吸附")
    bl_idname = "SURFACE_HAIR_PT_draw_snap"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_order = 30

    def draw(self, context):
        layout = localized_layout(self.layout)
        settings = settings_or_error(layout, context)
        if not settings:
            return

        box = layout.box()
        box.label(text=ui_t("绘制"), icon="GREASEPENCIL")
        row = box.row(align=True)
        row.prop(settings, "draw_mode", text="")
        row.prop(settings, "continuous_draw", text=ui_t("连续"))
        row.prop(settings, "auto_select_new_curve", text=ui_t("选中新线"))
        row = box.row(align=True)
        row.prop(settings, "brush_radius", text=ui_t("刷子"))
        box.prop(settings, "sample_spacing", text=ui_t("采样间距"))

        box = layout.box()
        box.label(text=ui_t("表面吸附"), icon="SNAP_ON")
        row = box.row(align=True)
        row.prop(settings, "snap_enabled", text=ui_t("启用"))
        row.prop(settings, "snap_element", text="")
        box.prop(settings, "surface_filter", text=ui_t("目标"))
        row = box.row(align=True)
        row.prop(settings, "scalp_root_snap", text=ui_t("发根吸头皮"))
        row.enabled = bool(settings.snap_enabled)
        scalp_row = box.row(align=True)
        scalp_row.enabled = bool(settings.snap_enabled and settings.scalp_root_snap)
        scalp_row.prop(settings, "scalp_object", text=ui_t("头皮对象"))


class SURFACE_HAIR_PT_shape_edit(bpy.types.Panel):
    bl_label = ui_t("编辑整形")
    bl_idname = "SURFACE_HAIR_PT_shape_edit"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_order = 40

    def draw(self, context):
        layout = localized_layout(self.layout)
        settings = settings_or_error(layout, context)
        if not settings:
            return

        box = layout.box()
        box.label(text=ui_t("尾端平滑"), icon="MOD_SMOOTH")
        box.prop(settings, "smooth_strength", text=ui_t("平滑强度"))
        box.prop(settings, "smooth_surface_lock", text=ui_t("平滑后贴面"))

        box = layout.box()
        box.label(text=ui_t("中段收缩"), icon="FULLSCREEN_EXIT")
        row = box.row(align=True)
        row.prop(settings, "shrink_strength", text=ui_t("收缩强度"))
        row.prop(settings, "shrink_tail_fixed_points", text=ui_t("尾端固定"))

        box = layout.box()
        box.label(text=ui_t("手柄与曲线编辑"), icon="IPO_BEZIER")
        row = box.row(align=True)
        row.prop(settings, "handle_snap", text=ui_t("弯曲吸附"))
        row.prop(settings, "smart_handles", text=ui_t("智能弯曲"))


class SURFACE_HAIR_PT_ik_surface(bpy.types.Panel):
    bl_label = ui_t("IK 与贴面")
    bl_idname = "SURFACE_HAIR_PT_ik_surface"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 50

    def draw(self, context):
        layout = localized_layout(self.layout)
        settings = settings_or_error(layout, context)
        if not settings:
            return

        box = layout.box()
        box.label(text=ui_t("IK 拖动"), icon="CONSTRAINT_BONE")
        row = box.row(align=True)
        row.prop(settings, "ik_enabled", text=ui_t("启用"))
        row.prop(settings, "ik_snap", text=ui_t("吸附"))
        row = box.row(align=True)
        row.prop(settings, "ik_falloff_points", text=ui_t("影响点数"))
        row.prop(settings, "falloff_strength", text=ui_t("强度"))
        box.prop(settings, "falloff_radius", text=ui_t("衰减半径"))

        box = layout.box()
        box.label(text=ui_t("贴面锁定"), icon="MOD_SHRINKWRAP")
        row = box.row(align=True)
        row.prop(settings, "surface_lock", text=ui_t("贴面"))
        row.prop(settings, "root_lock", text=ui_t("发根"))


class SURFACE_HAIR_PT_groups(bpy.types.Panel):
    bl_label = ui_t("分组与曲线")
    bl_idname = "SURFACE_HAIR_PT_groups"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_order = 10

    def draw(self, context):
        layout = localized_layout(self.layout)
        settings = settings_or_error(layout, context)
        if not settings:
            return

        draw_active_group_strip(layout, settings)
        row = layout.row(align=True)
        row.operator("surface_hair_curve.add_group", text="", icon="ADD")
        row.operator("surface_hair_curve.remove_group", text="", icon="REMOVE")
        row.operator("surface_hair_curve.assign_selected_to_group", text="", icon="FORWARD")
        row.operator("surface_hair_curve.merge_group_curves", text="", icon="AUTOMERGE_ON")
        row.operator("surface_hair_curve.convert_group_to_hair_curves", text="", icon="OUTLINER_OB_CURVES")
        layout.prop(settings, "hair_curve_point_count", text=ui_t("转发丝点数"))
        layout.template_list(
            SURFACE_HAIR_UL_groups.bl_idname,
            "",
            settings,
            "groups",
            settings,
            "group_index",
            rows=5,
        )
        group = props.active_group(settings)
        if group:
            layout.prop(group, "curve_radius", text=ui_t("当前分组曲线半径"))

        layout.separator(factor=0.5)
        row = layout.row(align=True)
        row.operator("surface_hair_curve.duplicate_selected", text="", icon="DUPLICATE")
        row.operator("surface_hair_curve.interpolate_selected", text="", icon="IPO_BEZIER")
        row.operator("surface_hair_curve.rebuild_overlay_cache", text="", icon="FILE_REFRESH")
        row.operator("surface_hair_curve.delete_selected", text="", icon="TRASH")
        layout.template_list(
            SURFACE_HAIR_UL_curves.bl_idname,
            "",
            settings,
            "curves",
            settings,
            "curve_index",
            rows=5,
        )


class SURFACE_HAIR_PT_presets(bpy.types.Panel):
    bl_label = ui_t("预设预览")
    bl_idname = "SURFACE_HAIR_PT_presets"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_order = 20

    def draw(self, context):
        layout = localized_layout(self.layout)
        settings = settings_or_error(layout, context)
        if not settings:
            return
        group = props.active_group(settings)
        if not group:
            layout.label(text=ui_t("无当前分组"), icon="GROUP")
            return

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(group, "preset_enabled", text=ui_t("启用"))
        row.prop(group, "preset_live_update", text=ui_t("实时"))
        row.operator("surface_hair_curve.refresh_group_preset_preview", text="", icon="FILE_REFRESH")
        row.operator("surface_hair_curve.clear_group_preset_preview", text="", icon="TRASH")

        row = col.row(align=True)
        row.operator("surface_hair_curve.add_preset_slot", text="", icon="ADD")
        row.operator("surface_hair_curve.set_preset_slots_expanded", text="", icon="TRIA_DOWN").expanded = True
        row.operator("surface_hair_curve.set_preset_slots_expanded", text="", icon="TRIA_RIGHT").expanded = False
        row.operator("surface_hair_curve.copy_preset_stack_to_groups", text="", icon="DUPLICATE")
        preview_name = group.preview_object_name if group.preview_object_name else "未生成"
        row.label(text=preview_name, icon="OUTLINER_OB_CURVES")

        lib_box = col.box()
        lib_box.label(text=ui_t("预设库"), icon="ASSET_MANAGER")
        lib_row = lib_box.row(align=True)
        lib_row.prop(settings, "library_preset_id", text="")
        lib_op = lib_row.operator("surface_hair_curve.add_library_preset", text="", icon="ADD")
        lib_op.preset_id = settings.library_preset_id
        save_op = lib_row.operator("surface_hair_curve.save_library_preset", text="", icon="FILE_TICK")
        save_op.preset_id = settings.library_preset_id
        delete_cell = lib_row.row(align=True)
        delete_cell.enabled = preset_library.is_user_preset(settings.library_preset_id)
        delete_op = delete_cell.operator("surface_hair_curve.delete_library_preset", text="", icon="TRASH")
        delete_op.preset_id = settings.library_preset_id
        lib_box.prop(settings, "library_preset_name", text=ui_t("名称"))
        if not preset_library.preset_available(settings.library_preset_id):
            lib_box.label(text=ui_t("部分节点组不在当前文件或内置库"), icon="ERROR")

        col.separator(factor=0.5)
        if not group.preset_slots:
            col.label(text=ui_t("添加预设后选择节点组"), icon="INFO")
            return
        for index, slot in enumerate(group.preset_slots):
            draw_preset_slot(col, group, slot, index)


class SURFACE_HAIR_PT_interpolate(bpy.types.Panel):
    bl_label = ui_t("插值补线")
    bl_idname = "SURFACE_HAIR_PT_interpolate"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 60

    def draw(self, context):
        layout = localized_layout(self.layout)
        settings = settings_or_error(layout, context)
        if not settings:
            return

        row = layout.row(align=True)
        row.operator("surface_hair_curve.interpolate_selected", text=ui_t("从选中曲线插值"), icon="IPO_BEZIER")
        box = layout.box()
        box.label(text=ui_t("生成参数"), icon="IPO_EASE_IN_OUT")
        row = box.row(align=True)
        row.prop(settings, "interpolate_count", text=ui_t("数量"))
        row.prop(settings, "interpolate_point_count", text=ui_t("点数"))
        box.prop(settings, "interpolate_surface_lock", text=ui_t("插值贴面"))


class SURFACE_HAIR_PT_display_settings(bpy.types.Panel):
    bl_label = ui_t("显示")
    bl_idname = "SURFACE_HAIR_PT_display_settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 90

    def draw(self, context):
        layout = localized_layout(self.layout)
        settings = settings_or_error(layout, context)
        if not settings:
            return

        box = layout.box()
        box.label(text=ui_t("视口状态"), icon="OVERLAY")
        row = box.row(align=True)
        row.prop(settings, "show_hud", text="HUD")
        row.prop(settings, "xray", text="X-Ray")
        row.prop(settings, "show_control_points", text=ui_t("控制点"))

        box = layout.box()
        box.label(text=ui_t("导引线视觉"), icon="CURVE_BEZCURVE")
        row = box.row(align=True)
        row.prop(settings, "line_width", text=ui_t("线宽"))
        row.prop(settings, "point_size", text=ui_t("点大小"))
        row = box.row(align=True)
        row.prop(settings, "unselected_display_scale", text=ui_t("未选中缩放"))
        row.prop(settings, "overlay_alpha", text=ui_t("透明度"))
        box.prop(settings, "overlay_fast_mode", text=ui_t("性能模式"))
        box.prop(settings, "show_handles", text=ui_t("调试显示手柄"))


class SURFACE_HAIR_PT_help(bpy.types.Panel):
    bl_label = ui_t("快捷键")
    bl_idname = "SURFACE_HAIR_PT_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = PANEL_CATEGORY
    bl_parent_id = "SURFACE_HAIR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1000

    def draw(self, context):
        layout = localized_layout(self.layout)
        labels = props.shortcut_labels()
        increase_label = labels.get("increase", "+")
        decrease_label = labels.get("decrease", "-")
        ctrl_increase = increase_label if increase_label.startswith("Ctrl+") else f"Ctrl+{increase_label}"
        ctrl_decrease = decrease_label if decrease_label.startswith("Ctrl+") else f"Ctrl+{decrease_label}"
        col = layout.column(align=True)
        col.label(text=ui_t(f"{labels.get('cycle_tool', 'Tab')}：循环绘制、编辑、插值、选择"))
        col.label(
            text=(
                ui_t(f"{labels.get('draw_tool', 'D')} / "
                f"{labels.get('control_tool', 'E')}({labels.get('control_tool_alt', 'G')}) / "
                f"{labels.get('interpolate_tool', 'L')} / {labels.get('select_tool', 'A')}：直达模式")
            )
        )
        col.separator()
        col.label(text=ui_t("左键：添加/选择/拖拽"))
        col.label(text=ui_t("右键：完成当前线"))
        col.label(text=ui_t(f"{labels.get('delete_last', 'Backspace')}：删除最后一点"))
        col.label(text=ui_t("Ctrl + 单击线段：加入控制点"))
        col.label(text=ui_t("Alt + 单击控制点：删除控制点"))
        col.label(text=ui_t("Shift + 单击尾部点：按当前强度平滑一次"))
        col.label(text=ui_t("Ctrl+Shift + 单击尾部点：收缩中间点，锁定点不动"))
        col.separator()
        col.label(text=ui_t(f"{labels.get('smooth_strength', 'Shift+滚轮')}：调整平滑强度"))
        col.label(text=ui_t(f"{labels.get('shrink_strength', 'Ctrl+Shift+滚轮')}：调整收缩强度"))
        col.label(text=ui_t(f"{labels.get('shrink_tail', 'Alt+Shift+滚轮')}：调整尾端固定点数"))
        col.label(text=ui_t(f"{labels.get('group_cycle', 'Alt+滚轮')}：切换当前分组"))
        col.label(text=ui_t(f"{labels.get('snap_cycle', 'Ctrl+滚轮')}：切吸附元素"))
        col.label(text=ui_t(f"{labels.get('guide_box_select', 'B')} / {labels.get('guide_brush_select', 'C')}：框选 / 刷选导引线"))
        col.separator()
        col.label(text=ui_t(f"{labels.get('toggle_paint', 'P')}：单击点/按住绘制"))
        col.label(text=ui_t(f"{labels.get('toggle_snap', 'S')}：吸附开关"))
        col.label(text=ui_t(f"{labels.get('toggle_ik', 'I')} / {labels.get('toggle_ik_snap', 'Ctrl+I')}：IK 模式 / IK 吸附"))
        col.label(text=ui_t(f"{labels.get('toggle_surface_lock', 'K')} / {labels.get('toggle_root_lock', 'R')}：贴面锁定 / 发根锁定"))
        col.label(text=ui_t(f"{labels.get('ik_points_up', 'PageUp')} / {labels.get('ik_points_down', 'PageDown')}：IK 影响点数"))
        col.label(text=ui_t(f"{labels.get('toggle_handle_snap', 'B')}：弯曲吸附"))
        col.label(text=ui_t(f"{labels.get('toggle_hud', 'H')}：快捷 HUD"))
        col.label(text=f"{labels.get('toggle_xray', 'Alt+Z')}：X-Ray")
        col.label(text=ui_t(f"{labels.get('add_group', 'Ctrl+G')} / {labels.get('assign_group', 'M')}：新建分组 / 移入当前分组"))
        col.label(text=ui_t(f"{labels.get('merge_group', 'Ctrl+J')}：合并当前分组头发"))
        col.label(text=ui_t(f"{labels.get('convert_group_hair', 'Ctrl+Shift+J')}：当前分组转换为发丝"))
        col.label(text=ui_t(f"{labels.get('toggle_group_visible', 'V')} / {labels.get('toggle_group_solo', 'O')}：当前分组显示 / 独显"))
        col.label(text=ui_t(f"{increase_label} / {decrease_label}：插值点数"))
        col.label(text=ui_t(f"{ctrl_increase} / {ctrl_decrease}：插值数量"))
        col.label(text=ui_t(f"{labels.get('duplicate_selected', 'Shift+D')}：复制"))
        col.label(text=ui_t(f"Delete / {labels.get('delete_selected', 'X')}：删除"))
        col.label(text=ui_t(f"{labels.get('finish', 'Enter')}：确认当前操作并退出工具"))
        col.label(text=ui_t(f"{labels.get('cancel', 'Esc')}：退出工具"))


classes = (
    SURFACE_HAIR_UL_groups,
    SURFACE_HAIR_UL_curves,
    SURFACE_HAIR_PT_main,
    SURFACE_HAIR_PT_groups,
    SURFACE_HAIR_PT_presets,
    SURFACE_HAIR_PT_draw_snap,
    SURFACE_HAIR_PT_shape_edit,
    SURFACE_HAIR_PT_ik_surface,
    SURFACE_HAIR_PT_interpolate,
    SURFACE_HAIR_PT_display_settings,
    SURFACE_HAIR_PT_help,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
