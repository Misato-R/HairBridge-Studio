"""Verify the public sample, installer payloads and Python syntax without Blender."""
from pathlib import Path
from zipfile import ZipFile
import ast, hashlib, json, struct

root=Path(__file__).resolve().parent.parent
sample=root/'examples/rain-study'
manifest=json.loads((sample/'manifest.json').read_text(encoding='utf-8'))
for entry in manifest['files']:
    file=(sample/entry['file']).resolve()
    assert file.is_relative_to(sample.resolve()), entry['file']
    data=file.read_bytes()
    assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256'], entry['file']
for name in ('source','front','left','right','back'):
    data=(sample/'references'/f'{name}.png').read_bytes()
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    assert min(struct.unpack('>II',data[16:24]))>=512
project=json.loads((sample/'project.hairbridge').read_text(encoding='utf-8'))
for asset in project['assets']:
    data=(sample/asset['file']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==asset['sha256'], asset['file']
for addon in json.loads((root/'installers/manifest.json').read_text())['addons']:
    file=root/'installers'/addon['file']
    assert hashlib.sha256(file.read_bytes()).hexdigest()==addon['sha256']
    with ZipFile(file) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==addon['files']
        for name in archive.namelist():
            assert (root/'addon'/name).read_bytes()==archive.read(name), name
for directory in (root/'scripts',root/'addon'):
    for file in directory.rglob('*.py'): ast.parse(file.read_text(encoding='utf-8'),filename=str(file))
print(f'Bundle verified: {len(manifest["files"])} sample files, five reference PNGs, two complete installers and Python syntax.')
