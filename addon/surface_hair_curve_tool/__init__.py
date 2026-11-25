bl_info = {
    "name": "Surface Hair Curve Tool",
    "author": "LU WENXUAN (with Codex assistance)",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Surface Hair",
    "description": "Fast surface-snapped Bezier/Hair curve creation with realtime viewport UI.",
    "category": "Curve",
}

from importlib import reload

from . import curve_data, draw, modifier_compat, hair_curves, operators, preset_library, preset_ops, props, snap, ui

if "bpy" in locals():
    for _mod in (props, snap, curve_data, modifier_compat, hair_curves, draw, preset_library, preset_ops, operators, ui):
        reload(_mod)


def register():
    props.register()
    operators.register()
    preset_ops.register()
    ui.register()


def unregister():
    ui.unregister()
    preset_ops.unregister()
    operators.unregister()
    props.unregister()
