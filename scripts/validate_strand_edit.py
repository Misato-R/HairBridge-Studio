"""Validate the selected-strand edit workflow in background Blender."""

import json
from pathlib import Path
import struct
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "addon"))
import hairbridge_studio as studio
from hairbridge_studio.hairdeck_bridge.mapping import geometry, select_only
from hairbridge_studio.strand_edit import current_profile, profile_data


def equal_geometry(obj, reference):
    actual = geometry(obj)
    np.testing.assert_array_equal(actual[0], reference[0])
    np.testing.assert_array_equal(actual[1], reference[1])


def signature(obj):
    return np.asarray([[tuple(b.co), tuple(b.handle_left), tuple(b.handle_right)]
                       for b in obj.data.splines[0].bezier_points])


def section_distances(mesh, rings, rows):
    return [np.linalg.norm(ring[:, None] - ring[None, :], axis=2)
            for row in range(len(rings)) if len(ring := mesh[0][rows == row]) > 1]


def glb_nodes(path):
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    length, tag = struct.unpack_from("<I4s", data, 12)
    assert tag == b"JSON"
    return json.loads(data[20:20 + length])["nodes"]


def trial(source, output, kind):
    studio.register()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    context = bpy.context
    surface, shp = studio.bridge.hair_tools()
    if kind == "rain":
        scene = bpy.data.scenes["03 Ear pair - matched SHP rims"]
        context.window.scene = scene
        active, other = (scene.objects[f"Ear shared rim strand {i}"] for i in (4, 0))
        for obj, strand_id in ((active, "4"), (other, "0")):
            obj["hairbridge_strand_id"] = strand_id
            obj["hairbridge_flow_review"] = '{"state":"confirmed"}'
    else:
        scene = context.scene
        candidates = [obj for obj in scene.objects if obj.get("hairdeck_card_json")]
        active, other = candidates[:2]
    context.view_layer.update()
    select_only(active)
    original = geometry(active)
    unaffected = geometry(other)
    original_guide = signature(active)
    reference_profile = current_profile(active, shp)
    _, old_stations, old_rows, _ = profile_data(reference_profile)

    # Cancel must recover the exact original curve data and resulting shell.
    assert bpy.ops.hairbridge.begin_path_edit() == {"FINISHED"}
    assert context.mode == "EDIT_CURVE"
    assert bpy.ops.hairbridge.finish_path_edit(discard=True) == {"FINISHED"}
    np.testing.assert_array_equal(signature(active), original_guide)
    equal_geometry(active, original)

    # Exercise the same edit-mode Translate operator as moving one point by hand.
    point_index = 8 if kind == "rain" else len(active.data.splines[0].bezier_points) // 2
    for i, point in enumerate(active.data.splines[0].bezier_points):
        point.select_left_handle = point.select_right_handle = False
        point.select_control_point = i == point_index
    assert bpy.ops.hairbridge.begin_path_edit() == {"FINISHED"}
    assert bpy.ops.transform.translate(value=(.0015, 0, .003)) == {"FINISHED"}
    assert bpy.ops.hairbridge.finish_path_edit() == {"FINISHED"}
    edited_guide = signature(active)
    assert np.linalg.norm(edited_guide[point_index, 0] - original_guide[point_index, 0]) > .003
    np.testing.assert_array_equal(edited_guide[[0, -1]], original_guide[[0, -1]])
    edited = geometry(active)
    adjusted_profile = current_profile(active, shp)
    assert adjusted_profile != reference_profile
    _, new_stations, new_rows, _ = profile_data(adjusted_profile)
    np.testing.assert_array_equal(old_rows, new_rows)
    old_dist = section_distances(original, old_stations, old_rows)
    new_dist = section_distances(edited, new_stations, new_rows)
    error = float(np.max([np.max(np.abs(a - b)) for a, b in zip(old_dist, new_dist)]))
    assert error < 5e-6, error
    equal_geometry(other, unaffected)

    assert bpy.ops.hairbridge.adjust_section(width=80) == {"FINISHED"}
    np.testing.assert_array_equal(signature(active), edited_guide)
    width_adjusted = geometry(active)
    movement = float(np.max(np.linalg.norm(width_adjusted[0] - edited[0], axis=1)))
    assert movement > 5e-5
    equal_geometry(other, unaffected)
    assert bpy.ops.hairbridge.restore_section() == {"FINISHED"}
    np.testing.assert_array_equal(signature(active), edited_guide)
    equal_geometry(active, edited)
    equal_geometry(other, unaffected)

    assert bpy.ops.hairbridge.adjust_section(width=93, thickness=91, rotation=.12, tip=90) == {"FINISHED"}
    tracked_profile = current_profile(active, shp)
    select_only(active)
    view_layer = context.view_layer
    original_selected = tuple(context.selected_objects)
    glb_path = output.with_suffix(".glb")
    studio.export_guides_glb(context, [active, other], glb_path)
    assert context.window.scene == scene and context.view_layer == view_layer
    assert tuple(context.selected_objects) == original_selected
    nodes = glb_nodes(glb_path)
    assert len(nodes) == 2 and all(node.get("mesh") is not None for node in nodes)
    key = "hairbridge_strand_id" if kind == "rain" else "hairdeck_card_index"
    assert {node["extras"][key] for node in nodes} == {obj[key] for obj in (active, other)}
    assert all(set(node["extras"]) == {key} for node in nodes)
    assert current_profile(active, shp) == tracked_profile

    output.write_text(json.dumps({
        "kind": kind, "blender": bpy.app.version_string, "slot_count": len(old_stations),
        "locked_first_and_last_control_points_and_handles_exact": True,
        "section_pairwise_distance_max_error_mm": error * 1000,
        "neighbor_world_mesh_and_topology_exact": True,
        "local_undo_preserves_path_and_restores_mesh_exact": True,
        "cancel_restores_curve_and_mesh_exact": True,
        "maximum_mesh_motion_from_80_percent_width_mm": movement * 1000,
        "preview_export_requested_ids": sorted(node["extras"][key] for node in nodes),
        "preview_scene_and_selection_restored": True,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    source, output, kind = sys.argv[sys.argv.index("--") + 1:]
    trial(Path(source), Path(output), kind)
