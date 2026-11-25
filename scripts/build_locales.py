"""Compile the shared product vocabulary for the browser and both Blender add-ons."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
catalog = {}
for name in ('en.tsv', 'blender-en.tsv'):
    for line in (root / 'public/locales' / name).read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        source, english = line.split('\t', 1)
        catalog[source] = english
data = json.dumps(catalog, ensure_ascii=False, indent=2) + '\n'
for output in (root / 'public/locales/en.json',
               root / 'addon/hairbridge_studio/i18n.en.json',
               root / 'addon/surface_hair_curve_tool/i18n.en.json'):
    output.write_text(data, encoding='utf-8')
print(f'Compiled {len(catalog)} English translations for browser and Blender.')
