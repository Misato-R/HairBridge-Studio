# Blender installers

- `surface_hair_curve_tool.zip`: Surface Hair Curve Tool 0.1.0, authored by LU WENXUAN with Codex assistance.
- `hairbridge_studio.zip`: HairBridge Studio 0.1.1, including the internal HairDeck JSON Bridge and its retained HairDeck notice.
- `manifest.json`: versions, file counts and SHA-256 checksums generated with the ZIPs.

These two installers are included in the project for the coursework hand-in.
Rebuild both from the checked-in `addon/` sources with:

```powershell
python scripts/package_addon.py
```

Install Surface Hair Curve Tool, separately obtained Stylized Hair PRO 4.3.1,
and then HairBridge Studio. Do not install an old standalone HairDeck JSON Bridge
alongside the new companion. Full steps: [installation guide](../docs/installation.zh-CN.md).

SHP is a paid third-party product, not included in this directory or the public
repository. An assessment-only attachment is prepared separately; see
[teacher verification instructions](../docs/teacher-verification.zh-CN.md).
