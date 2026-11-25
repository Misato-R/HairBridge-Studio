"""Build the two author-developed add-ons; never collect installed third-party code."""
import ast
import hashlib
import json
import shutil
import runpy
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

root = Path(__file__).resolve().parent.parent
runpy.run_path(str(root / "scripts" / "build_locales.py"))
installers = root / "installers"
installers.mkdir(exist_ok=True)
(root / "dist").mkdir(exist_ok=True)
manifest = {"schema_version": 1, "addons": []}
for name in ("hairbridge_studio", "surface_hair_curve_tool"):
    source = root / "addon" / name
    info = next(ast.literal_eval(node.value) for node in ast.parse((source / "__init__.py").read_text(encoding="utf-8")).body
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets))
    output = installers / f"{name}.zip"
    files = [file for file in sorted(source.rglob("*"))
             if file.is_file() and "__pycache__" not in file.parts and file.suffix not in {".pyc", ".blend1"}]
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for file in files:
            entry = ZipInfo(file.relative_to(root / "addon").as_posix(), date_time=(2026, 11, 25, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, file.read_bytes())
    shutil.copyfile(output, root / "dist" / output.name)
    manifest["addons"].append({
        "module": name, "version": ".".join(map(str, info["version"])),
        "file": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "bytes": output.stat().st_size, "files": len(files),
    })
    print(output)
(installers / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
