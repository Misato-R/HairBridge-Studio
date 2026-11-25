"""Run in background Blender with BLENDER_USER_RESOURCES set to a disposable profile.

Arguments after `--`: --profile PATH --shp-zip PATH --report PATH.
Never runs against a personal Blender profile or saves user preferences.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import addon_utils
import bpy
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--profile', type=Path, required=True)
parser.add_argument('--shp-zip', type=Path, required=True)
parser.add_argument('--report', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
root = Path(__file__).resolve().parent.parent
profile = args.profile.resolve()
assert profile == Path(bpy.utils.resource_path('USER')).resolve(), 'Refusing to use a different Blender profile'
assert any(profile.is_relative_to(base) for base in (root / 'data' / 'verification', root.parent / 'tmp')), 'Use a disposable workspace verification profile'

def installed_module(name):
    module = next(m for key, m in tuple(sys.modules.items()) if key.split('.')[-1] == name and m is not None)
    assert Path(module.__file__).resolve().is_relative_to(profile), f'{name} loaded outside verification profile'
    return module

def install_legacy(name):
    result = bpy.ops.preferences.addon_install(filepath=str(root / 'installers' / f'{name}.zip'), enable_on_install=True)
    assert result == {'FINISHED'}, result
    addon_utils.enable(name, default_set=False, persistent=False)
    return installed_module(name)

surface = install_legacy('surface_hair_curve_tool')
repo_dir = profile / 'extensions' / 'a2_verification'
repo_dir.mkdir(parents=True, exist_ok=True)
assert bpy.ops.preferences.extension_repo_add(name='A2 verification', type='LOCAL',
    use_custom_directory=True, custom_directory=str(repo_dir)) == {'FINISHED'}
repo = next(r for r in bpy.context.preferences.extensions.repos if Path(r.directory).resolve() == repo_dir)
assert bpy.ops.extensions.package_install_files(filepath=str(args.shp_zip.resolve()), repo=repo.module,
    enable_on_install=True) == {'FINISHED'}
shp = installed_module('stylized_hair_pro')
companion = install_legacy('hairbridge_studio')
assert companion.bridge.hair_tools() == (surface, shp)
scene = bpy.context.scene
scene.hairbridge_language = 'en'
assert companion.i18n.t('截面调整') == 'Cross-section controls'
assert surface.i18n.t('曲线半径') == 'Curve radius'
scene.hairbridge_language = 'zh'
assert companion.i18n.t('Cross-section controls') == '截面调整'
assert surface.i18n.t('Curve radius') == '曲线半径'
scene.hairbridge_language = 'en'

# A synthetic card tests the bridge and geometry without private models or data.
work = profile / 'verification'
work.mkdir(exist_ok=True)
t = np.linspace(0, 1, 25)
rows = np.column_stack((.015 * np.sin(t * np.pi), .15 * t, .004 * np.sin(t * 2 * np.pi),
                        .012 - .006 * t, .004 - .002 * t, np.ones(len(t)), np.zeros(len(t)), np.zeros(len(t))))
cards = work / 'synthetic-cards.json'
cards.write_text(json.dumps([{'shape': 'square', 'seq': rows.tolist()}]), encoding='utf-8')
guides = companion.bridge.import_cards(bpy.context, cards)
assert len(guides) == 1
guide = guides[0]
assert guide.type == 'CURVE' and guide.data.splines[0].type == 'BEZIER'
settings = bpy.context.scene.surface_hair_curve_tool
assert len(settings.curves) == 1 and settings.curves[0].object == guide
group_id = guide[surface.curve_data.GROUP_ID_PROP]
assert any(group.group_id == group_id for group in settings.groups)
assert any(collection.get(surface.curve_data.COLLECTION_GROUP_ID_PROP) == group_id for collection in guide.users_collection)
registered_groups = len(settings.groups)
from hairbridge_studio.hairdeck_bridge.mapping import geometry
before, triangles = geometry(guide)
point = guide.data.splines[0].bezier_points[len(guide.data.splines[0].bezier_points) // 2]
original = point.co.copy()
point.co.x += .003
guide.update_tag()
bpy.context.view_layer.update()
after, _ = geometry(guide)
movement = float(np.linalg.norm(after - before, axis=1).max())
assert movement > .0001
point.co = original
guide.update_tag()
bpy.context.view_layer.update()
restored, _ = geometry(guide)
restore_error = float(np.linalg.norm(restored - before, axis=1).max())
assert restore_error < 1e-6

# Both shipped preset libraries must be readable, not just present in the ZIP.
presets = {}
for filename in ('束.blend', 'suifa.blend'):
    with bpy.data.libraries.load(str(Path(surface.__file__).parent / filename), link=False) as (source, target):
        presets[filename] = len(source.node_groups)
        assert presets[filename] > 0

blend = work / 'synthetic-build.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
guide_name = guide.name
bpy.ops.wm.open_mainfile(filepath=str(blend))
assert bpy.context.scene.hairbridge_language == 'en'
reopened, _ = geometry(bpy.data.objects[guide_name])
assert reopened.shape == before.shape and np.max(np.abs(reopened - before)) < 1e-6

packages = {}
for path in (root / 'installers' / 'surface_hair_curve_tool.zip',
             root / 'installers' / 'hairbridge_studio.zip', args.shp_zip):
    with ZipFile(path) as archive:
        assert archive.testzip() is None
    packages[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
report = {'success': True, 'blender': bpy.app.version_string,
          'isolated_user_profile': True, 'installed_via_blender_operators': True,
          'modules_from_isolated_profile': True,
          'english_chinese_catalog_switch': True, 'language_saved_in_scene': True,
          'guides': len(guides), 'registered_groups': registered_groups,
          'guide_group_and_collection_match': True,
          'evaluated_vertices': len(before), 'triangles': len(triangles),
          'guide_edit_mesh_max_move_mm': movement * 1000,
          'restore_max_error_mm': restore_error * 1000, 'save_and_reopen': True,
          'readable_preset_node_groups': presets, 'package_sha256': packages,
          'limits': 'One synthetic strand; background installation, grouping, SHP build, direct edit/restore and file reopen only. No GUI interaction, project return, latest guide-generation acceptance or aesthetic evaluation.'}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print('INSTALLER_VERIFICATION', json.dumps(report), flush=True)
