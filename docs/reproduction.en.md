# Reproduce the submitted prototype

## Included components

| Component | Supplied material | Purpose |
|---|---|---|
| HairBridge Studio | Browser/server source and `installers/hairbridge_studio.zip` | Review workflow and Blender companion; includes the internal JSON bridge |
| Surface Hair Curve Tool | Source and `installers/surface_hair_curve_tool.zip` | Editable guides, grouping, surface operations and presets |
| Node verification | `tests/`, `npm test` | State, geometry math, localization, HTTP boundaries and example installation |
| Bundle verification | `scripts/verify_bundle.py` | Image inputs, sample and installer hashes, source/ZIP agreement and Python syntax |
| Blender verification | `verify_installers.ps1` / `.py`, `verify_blender.py`, `validate_strand_edit.py` | Isolated installation/build/reopen and selected-strand review checks |
| Integration utilities | `scripts/project.mjs`, `verify_studio_registration.mjs` | Agent artifact registration and optional historical integration reproduction |
| Rain study | `examples/rain-study/` | Initial image, four reference views and an existing seven-guide working sample |

SHP 4.3.1 is required for the demonstrated geometry path. Obtain it separately
from [Dean Zarkov](https://deanzarkov.gumroad.com/l/stylized_hair_pro), then follow
[installation instructions](installation.en.md). HairMesh and the privately
provided Hair Curve Toolkit are historical comparison tools; their links are in
[source notices](../THIRD_PARTY_NOTICES.md). Neither is required for this sample.
Draw-hair refinement is future work. No third-party private add-on, service
credential, model weights or Python environment is distributed here.

## Fresh checkout

Use Node.js 22+ and Python 3.10+. Install both supplied add-ons and SHP in Blender
(recorded validation: Blender 5.3.0). Copy `local-config.example.json` to
`local-config.json` and set your Blender executable. Then run:

```powershell
npm test
npm run verify:bundle
npm run example
npm start
```

Open the example URL printed by `npm run example`. It is ready for inspecting
regions, guides and cross-sections, and for a new local Blender build. Your
`data/` directory and configuration remain local. For an image-to-model trial,
use the five reference files in a new project instead. The prepared example does
not submit model-generation requests or spend service credits.

## Isolated Blender installer check (Windows)

Supply your own SHP ZIP. This creates a fresh profile under ignored
`data/verification/`; it does not use or save your personal preferences.

```powershell
& .\scripts\verify_installers.ps1 -Blender 'C:\Path\To\blender.exe' -ShpZip 'C:\Path\To\stylized_hair_pro-4.3.1.zip'
```

The JSON report records installation, module locations, language switching,
language persistence, synthetic SHP geometry, point edit/restore and reopening.
It tests a synthetic strand, not hairstyle quality. The profile and results are
retained for inspection. Do not pass a personal Blender configuration as a test
profile.

For checks on an existing generated Blend, use the other tools in a separate
Blender process and with a **disposable project copy**. `verify_blender.py` can
write a review copy and register it with the local workspace; it is not read-only.
`verify_studio_registration.mjs` is a legacy integration script requiring the
original local Rain HairDeck experiment directory; it is retained as development
evidence and is not part of the portable checks above.

## Rebuild installers

```powershell
npm run package:addon
npm run verify:bundle
```

The build recreates both installers, the locale catalogs and
`installers/manifest.json`. GitHub Actions runs Node checks and bundle validation
on a clean Ubuntu checkout. Blender/SHP tests require a local Blender installation
and the separate dependency; CI does not claim to run those tests.
