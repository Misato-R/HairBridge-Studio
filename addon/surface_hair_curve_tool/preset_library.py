import json
import os
import re
import time
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parent
ADDONS_DIR = ADDON_DIR.parent
PRESET_ROOT = ADDON_DIR
PRESET_SOURCE_PROP = "sht_preset_source"
DEFAULT_PRESET_IDS = ("束", "suifa")
_PRESET_DEFINITIONS_CACHE = None
_PRESET_ITEMS_CACHE = None
_NODE_GROUP_NAMES_CACHE = {}
_PRESET_CACHE_CHECK_TIME = 0.0
_PRESET_CACHE_SIGNATURE = None
_PRESET_CACHE_TTL = 1.5
_NODE_ASSET_LIBRARY_CACHE = None

PRESET_DEFINITIONS = {
    "suifa": {
        "label": "碎发",
        "source": "BUILTIN",
        "node_group": "碎发",
        "files": (
            "suifa.blend",
            "碎发.blend",
            os.path.join("presets", "suifa.blend"),
            os.path.join("presets", "碎发.blend"),
            os.path.join("assets", "suifa.blend"),
            os.path.join("assets", "碎发.blend"),
        ),
    },
}


def preset_root():
    return PRESET_ROOT


def invalidate_preset_cache():
    global _PRESET_DEFINITIONS_CACHE, _PRESET_ITEMS_CACHE, _PRESET_CACHE_CHECK_TIME, _PRESET_CACHE_SIGNATURE
    _PRESET_DEFINITIONS_CACHE = None
    _PRESET_ITEMS_CACHE = None
    _PRESET_CACHE_CHECK_TIME = 0.0
    _PRESET_CACHE_SIGNATURE = None
    _NODE_GROUP_NAMES_CACHE.clear()


def _node_asset_library_paths():
    global _NODE_ASSET_LIBRARY_CACHE
    if _NODE_ASSET_LIBRARY_CACHE is not None:
        return list(_NODE_ASSET_LIBRARY_CACHE)
    paths = []
    try:
        datafiles = Path(bpy.utils.system_resource("DATAFILES"))
    except Exception:
        datafiles = Path()
    nodes_dir = datafiles / "assets" / "nodes"
    if nodes_dir.exists():
        preferred = (
            "procedural_hair_node_assets.blend",
            "geometry_nodes_essentials.blend",
            "shading_nodes_essentials.blend",
            "compositing_nodes_essentials.blend",
        )
        for name in preferred:
            path = nodes_dir / name
            if path.exists():
                paths.append(path)
        for path in sorted(nodes_dir.glob("*.blend")):
            if path not in paths:
                paths.append(path)
    _NODE_ASSET_LIBRARY_CACHE = tuple(paths)
    return list(_NODE_ASSET_LIBRARY_CACHE)


def _normal_path(path):
    return str(Path(path).resolve())


def _file_signature(path):
    try:
        stat = Path(path).stat()
    except OSError:
        return "missing"
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _source_key(filepath, node_group_name):
    return f"{_normal_path(filepath)}::{_file_signature(filepath)}::{node_group_name}"


def _preset_id_for_path(path):
    rel = Path(path).resolve().relative_to(PRESET_ROOT.resolve())
    return rel.with_suffix("").as_posix()


def _preset_path_for_id(preset_id):
    if not preset_id:
        return None
    path = PRESET_ROOT / f"{preset_id}.blend"
    try:
        path.resolve().relative_to(PRESET_ROOT.resolve())
    except ValueError:
        return None
    return path


def _metadata_path_for_blend(path):
    return Path(path).with_suffix(".json")


def _safe_filename(label):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (label or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "自定义预设"


def _read_metadata(path):
    meta_path = _metadata_path_for_blend(path)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_metadata(path, data):
    meta_path = _metadata_path_for_blend(path)
    tmp_path = meta_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, meta_path)


def _normalize_slot(slot, blend_path=None):
    slot = slot if isinstance(slot, dict) else {}
    data = {
        "name": str(slot.get("name", "") or slot.get("node_group", "") or "预设"),
        "node_group": str(slot.get("node_group", "") or ""),
        "enabled": bool(slot.get("enabled", True)),
        "expanded": bool(slot.get("expanded", True)),
        "stored_values": str(slot.get("stored_values", "") or ""),
    }
    if blend_path:
        data["blend_path"] = _normal_path(blend_path)
    return data


def _builtin_paths():
    paths = set()
    for data in PRESET_DEFINITIONS.values():
        for relative in data.get("files", ()):
            paths.add(_normal_path(ADDON_DIR / relative))
            paths.add(_normal_path(ADDONS_DIR / relative))
    return paths


def _builtin_definition_for_path(path):
    normal = _normal_path(path)
    for preset_id, data in PRESET_DEFINITIONS.items():
        candidates = {
            _normal_path(ADDON_DIR / relative)
            for relative in data.get("files", ())
        }
        candidates.update(_normal_path(ADDONS_DIR / relative) for relative in data.get("files", ()))
        if normal in candidates:
            definition = dict(data)
            definition["id"] = preset_id
            return definition
    return None


def _scan_preset_blends():
    if not PRESET_ROOT.exists():
        return []
    paths = []
    for path in PRESET_ROOT.rglob("*.blend"):
        if "__pycache__" in path.parts:
            continue
        paths.append(path)
    return sorted(paths, key=lambda item: item.as_posix().lower())


def _preset_root_signature():
    if not PRESET_ROOT.exists():
        return ()
    signature = []
    for path in PRESET_ROOT.rglob("*"):
        if "__pycache__" in path.parts or path.suffix.lower() not in {".blend", ".json"}:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((_normal_path(path), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(signature))


def _preset_cache_is_current():
    global _PRESET_CACHE_CHECK_TIME, _PRESET_CACHE_SIGNATURE
    if _PRESET_DEFINITIONS_CACHE is None:
        return False
    now = time.monotonic()
    if now - _PRESET_CACHE_CHECK_TIME < _PRESET_CACHE_TTL:
        return True
    signature = _preset_root_signature()
    _PRESET_CACHE_CHECK_TIME = now
    if signature == _PRESET_CACHE_SIGNATURE:
        return True
    _PRESET_CACHE_SIGNATURE = signature
    return False


def _slots_from_metadata(meta, blend_path):
    slots = meta.get("slots")
    if isinstance(slots, list):
        return [_normalize_slot(slot, blend_path) for slot in slots if _normalize_slot(slot).get("node_group")]
    node_group = str(meta.get("node_group", "") or "")
    if node_group:
        return [_normalize_slot({"name": meta.get("label", node_group), "node_group": node_group}, blend_path)]
    return []


def _entry_for_blend(path):
    preset_id = _preset_id_for_path(path)
    meta = _read_metadata(path)
    builtin = _builtin_definition_for_path(path)
    label = str(meta.get("label", "")).strip() or (builtin.get("label") if builtin else "") or path.stem
    source = "BUILTIN" if builtin else "USER"
    slots = _slots_from_metadata(meta, path)
    if not slots and builtin and builtin.get("node_group"):
        slots = [_normalize_slot({"name": label, "node_group": builtin["node_group"]}, path)]
    return {
        "id": preset_id,
        "label": label,
        "source": source,
        "blend_path": _normal_path(path),
        "slots": slots,
    }


def all_preset_definitions():
    global _PRESET_DEFINITIONS_CACHE, _PRESET_ITEMS_CACHE, _PRESET_CACHE_CHECK_TIME, _PRESET_CACHE_SIGNATURE
    if _preset_cache_is_current():
        return _PRESET_DEFINITIONS_CACHE
    definitions = {}
    for path in _scan_preset_blends():
        try:
            entry = _entry_for_blend(path)
        except Exception:
            continue
        definitions[entry["id"]] = entry
    _PRESET_DEFINITIONS_CACHE = definitions
    _PRESET_ITEMS_CACHE = None
    _PRESET_CACHE_CHECK_TIME = time.monotonic()
    _PRESET_CACHE_SIGNATURE = _preset_root_signature()
    return definitions


def preset_items():
    global _PRESET_ITEMS_CACHE
    entries = all_preset_definitions()
    if _PRESET_ITEMS_CACHE is not None:
        return _PRESET_ITEMS_CACHE
    def sort_key(item):
        preset_id = item.get("id", "")
        try:
            preferred = DEFAULT_PRESET_IDS.index(preset_id)
        except ValueError:
            preferred = len(DEFAULT_PRESET_IDS)
        return (preferred, item.get("source") != "BUILTIN", item.get("label", ""))

    ordered = sorted(entries.values(), key=sort_key)
    _PRESET_ITEMS_CACHE = tuple(
        (entry["id"], entry["label"], f"从插件根目录预设库添加 {entry['label']}")
        for entry in ordered
    )
    return _PRESET_ITEMS_CACHE


def preset_definition(preset_id):
    return all_preset_definitions().get(preset_id)


def preset_label(preset_id):
    data = preset_definition(preset_id)
    return data["label"] if data else preset_id


def is_user_preset(preset_id):
    data = preset_definition(preset_id)
    return bool(data and data.get("source") != "BUILTIN")


def is_builtin_preset(preset_id):
    data = preset_definition(preset_id)
    return bool(data and data.get("source") == "BUILTIN")


def first_preset_id():
    items = preset_items()
    return items[0][0] if items else ""


def node_group_names_in_blend(filepath):
    if not filepath:
        return []
    path = Path(filepath)
    if not path.exists():
        return []
    try:
        cache_key = (_normal_path(path), path.stat().st_mtime_ns)
    except OSError:
        cache_key = (_normal_path(path), 0)
    cached = _NODE_GROUP_NAMES_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    try:
        with bpy.data.libraries.load(str(path), link=False) as (data_from, _data_to):
            names = list(getattr(data_from, "node_groups", []))
    except Exception:
        return []
    _NODE_GROUP_NAMES_CACHE.clear()
    _NODE_GROUP_NAMES_CACHE[cache_key] = tuple(names)
    return names


def append_node_group_from_asset_libraries(node_group_name):
    if not node_group_name:
        return None
    for filepath in _node_asset_library_paths():
        try:
            with bpy.data.libraries.load(str(filepath), link=False) as (data_from, data_to):
                available = list(getattr(data_from, "node_groups", []))
                if node_group_name not in available:
                    continue
                data_to.node_groups = [node_group_name]
        except Exception:
            continue
        loaded = [
            group
            for group in getattr(data_to, "node_groups", [])
            if group and getattr(group, "bl_idname", "") == "GeometryNodeTree"
        ]
        if loaded:
            try:
                loaded[0][PRESET_SOURCE_PROP] = _source_key(filepath, node_group_name)
            except Exception:
                pass
            return loaded[0]
    return None


def preset_slots(preset_id):
    data = preset_definition(preset_id)
    if not data:
        return []
    blend_path = data.get("blend_path")
    slots = [_normalize_slot(slot, blend_path) for slot in data.get("slots", [])]
    if slots:
        names = node_group_names_in_blend(blend_path)
        if names:
            resolved = []
            for index, slot in enumerate(slots):
                slot = dict(slot)
                stored_name = slot.get("node_group", "")
                if stored_name not in names:
                    replacement = names[index] if index < len(names) else (names[0] if len(names) == 1 else "")
                    if replacement:
                        slot["node_group"] = replacement
                resolved.append(slot)
            slots = resolved
        return slots
    return [
        _normalize_slot({"name": name, "node_group": name}, blend_path)
        for name in node_group_names_in_blend(blend_path)
    ]


def candidate_paths(preset_id):
    data = PRESET_DEFINITIONS.get(preset_id)
    if data:
        paths = []
        for relative in data["files"]:
            paths.append(str(ADDON_DIR / relative))
            paths.append(str(ADDONS_DIR / relative))
        return paths
    path = _preset_path_for_id(preset_id)
    return [str(path)] if path else []


def find_preset_blend(preset_id):
    for path in candidate_paths(preset_id):
        if os.path.exists(path):
            return path
    data = preset_definition(preset_id)
    return data.get("blend_path", "") if data else ""


def builtin_preset_id_for_node_group(node_group_name):
    for preset_id, data in PRESET_DEFINITIONS.items():
        if data.get("node_group") == node_group_name:
            return preset_id
    return ""


def existing_node_group(name):
    group = bpy.data.node_groups.get(name)
    if group and getattr(group, "bl_idname", "") == "GeometryNodeTree":
        return group
    return None


def existing_node_group_from_source(filepath, node_group_name):
    key = _source_key(filepath, node_group_name)
    for group in bpy.data.node_groups:
        if getattr(group, "bl_idname", "") == "GeometryNodeTree" and group.get(PRESET_SOURCE_PROP) == key:
            return group
    return None


def append_node_group_from_blend(filepath, node_group_name, force_load=False):
    if not filepath or not os.path.exists(filepath):
        return None, f"找不到预设库文件：{os.path.basename(filepath) if filepath else node_group_name}"
    if not force_load:
        group = existing_node_group(node_group_name)
        if group:
            return group, ""
    else:
        group = existing_node_group_from_source(filepath, node_group_name)
        if group:
            return group, ""
    before = set(bpy.data.node_groups)
    try:
        with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
            available = list(getattr(data_from, "node_groups", []))
            target_name = node_group_name if node_group_name in available else (available[0] if available else "")
            if not target_name:
                return None, f"{os.path.basename(filepath)} 里没有节点组"
            data_to.node_groups = [target_name]
    except Exception as exc:
        return None, f"读取预设库失败：{exc}"
    loaded = [
        candidate
        for candidate in bpy.data.node_groups
        if candidate not in before and getattr(candidate, "bl_idname", "") == "GeometryNodeTree"
    ]
    group = next((candidate for candidate in loaded if candidate.name == target_name), None)
    if not group:
        group = next((candidate for candidate in loaded if candidate.name.startswith(f"{target_name}.")), None)
    if not group:
        group = existing_node_group(target_name) or existing_node_group(node_group_name)
    if not group and loaded:
        group = loaded[0]
    if group:
        try:
            group[PRESET_SOURCE_PROP] = _source_key(filepath, node_group_name)
        except Exception:
            pass
        return group, ""
    return None, f"无法追加节点组：{node_group_name}"


def load_preset_node_group(preset_id):
    data = PRESET_DEFINITIONS.get(preset_id)
    if not data:
        return None, f"未知内置预设：{preset_id}"
    node_group_name = data["node_group"]
    group = existing_node_group(node_group_name)
    if group:
        return group, ""
    filepath = find_preset_blend(preset_id)
    if not filepath:
        filenames = " / ".join(sorted({os.path.basename(path) for path in candidate_paths(preset_id)}))
        return None, f"找不到预设库文件，请把 {filenames} 放到插件目录"
    return append_node_group_from_blend(filepath, node_group_name)


def load_node_group_by_name(node_group_name, blend_path=""):
    if blend_path:
        return append_node_group_from_blend(blend_path, node_group_name, force_load=True)
    group = existing_node_group(node_group_name)
    if group:
        return group, ""
    preset_id = builtin_preset_id_for_node_group(node_group_name)
    if preset_id:
        return load_preset_node_group(preset_id)
    return None, f"当前文件里没有节点组：{node_group_name}"


def load_node_group_for_slot(slot_data):
    return load_node_group_by_name(slot_data.get("node_group", ""), slot_data.get("blend_path", ""))


def node_group_available(node_group_name, blend_path=""):
    if blend_path and Path(blend_path).exists():
        return True
    if existing_node_group(node_group_name):
        return True
    preset_id = builtin_preset_id_for_node_group(node_group_name)
    return bool(preset_id and find_preset_blend(preset_id))


def preset_available(preset_id):
    data = preset_definition(preset_id)
    if not data:
        return False
    blend_path = data.get("blend_path", "")
    if not blend_path or not Path(blend_path).exists():
        return False
    slots = data.get("slots", [])
    if not slots:
        return True
    return all(node_group_available(slot.get("node_group", ""), blend_path) for slot in slots)


def _path_is_builtin(path):
    return _normal_path(path) in _builtin_paths()


def _unique_user_blend_path(label, allow_path=None):
    base = _safe_filename(label)
    path = PRESET_ROOT / f"{base}.blend"
    if allow_path and _normal_path(path) == _normal_path(allow_path):
        return path
    if not path.exists() and not _path_is_builtin(path):
        return path
    index = 2
    while True:
        candidate = PRESET_ROOT / f"{base}_{index}.blend"
        if not candidate.exists() and not _path_is_builtin(candidate):
            return candidate
        index += 1


def _temp_blend_path(blend_path):
    return blend_path.with_name(f".{blend_path.stem}.sht_tmp_{os.getpid()}.blend")


def _write_preset_blend(path, node_groups, required_names):
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
    bpy.data.libraries.write(str(path), set(node_groups), fake_user=True)
    names = node_group_names_in_blend(path)
    if not names:
        return False, names, f"{path.name} 写入后没有节点组"
    missing = [name for name in required_names if name and name not in names]
    if missing:
        return False, names, f"{path.name} 写入后缺少节点组：{', '.join(missing)}"
    return True, names, ""


def _append_missing_asset_slots(slot_records, existing_names):
    changed = False
    existing_names = set(existing_names or [])
    for record in slot_records:
        normalized = record["normalized"]
        node_group_name = normalized.get("node_group", "")
        if not node_group_name or node_group_name in existing_names:
            continue
        node_tree = append_node_group_from_asset_libraries(node_group_name)
        if not node_tree:
            continue
        record["node_tree"] = node_tree
        normalized["node_group"] = node_tree.name
        changed = True
    return changed


def save_user_preset(preset_id, label, slots):
    label = (label or "").strip() or "自定义预设"
    slot_records = []
    for slot in slots:
        normalized = _normalize_slot(slot)
        node_tree = slot.get("node_tree")
        if not normalized.get("node_group") or not node_tree:
            continue
        slot_records.append({"normalized": normalized, "node_tree": node_tree})
    if not slot_records:
        return "", "没有可保存的节点组预设"

    old_entry = preset_definition(preset_id) if is_user_preset(preset_id) else None
    old_path = Path(old_entry["blend_path"]) if old_entry else None
    keep_old_name = bool(old_entry and (not label or label == old_entry.get("label")))
    blend_path = old_path if keep_old_name else _unique_user_blend_path(label, allow_path=old_path)
    if _path_is_builtin(blend_path):
        blend_path = _unique_user_blend_path(f"{label}_自定义")
    temp_path = _temp_blend_path(blend_path)
    try:
        node_groups = {record["node_tree"] for record in slot_records if record.get("node_tree")}
        required_names = [record["normalized"].get("node_group", "") for record in slot_records]
        ok, written_names, message = _write_preset_blend(temp_path, node_groups, required_names)
        if not ok and _append_missing_asset_slots(slot_records, written_names):
            node_groups = {record["node_tree"] for record in slot_records if record.get("node_tree")}
            required_names = [record["normalized"].get("node_group", "") for record in slot_records]
            ok, written_names, message = _write_preset_blend(temp_path, node_groups, required_names)
        if not ok:
            return "", f"保存预设失败：{message}"
        normalized_slots = [record["normalized"] for record in slot_records]
        os.replace(temp_path, blend_path)
        _write_metadata(
            blend_path,
            {
                "version": 1,
                "label": label,
                "slots": normalized_slots,
            },
        )
    except Exception as exc:
        return "", f"保存预设失败：{exc}"
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass

    if old_path and _normal_path(old_path) != _normal_path(blend_path):
        for path in (old_path, _metadata_path_for_blend(old_path)):
            try:
                if path.exists() and not _path_is_builtin(path):
                    path.unlink()
            except Exception:
                pass
    invalidate_preset_cache()
    return _preset_id_for_path(blend_path), f"已保存预设：{label}"


def delete_user_preset(preset_id):
    data = preset_definition(preset_id)
    if not data:
        return False, "没有找到这个预设"
    if data.get("source") == "BUILTIN":
        return False, "内置预设不能删除"
    blend_path = Path(data.get("blend_path", ""))
    deleted = False
    for path in (blend_path, _metadata_path_for_blend(blend_path)):
        try:
            if path.exists() and not _path_is_builtin(path):
                path.unlink()
                deleted = True
        except Exception as exc:
            return False, f"删除预设失败：{exc}"
    if deleted:
        invalidate_preset_cache()
    return (True, f"已删除预设：{data.get('label', preset_id)}") if deleted else (False, "没有找到可删除的预设文件")
