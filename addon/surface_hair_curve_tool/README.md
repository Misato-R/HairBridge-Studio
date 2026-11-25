# Surface Hair Curve Tool 0.1.0

Author: Developer, with Codex assistance.

This is the author-developed Blender curve component used by HairBridge Studio.
It creates and samples editable Bézier guides, manages curve groups and stable
identifiers, provides surface snapping, and supports hair-curve preset previews.
The guide fitting error checks live in HairBridge's bridge, rather than this module.

The source was copied from the author's working Blender 5.2 installation on
2026-11-25. The node preset files retain their contents from that
installation. User-facing Python UI and reports were subsequently localised for
English and Chinese; data identifiers and geometry operations are retained. `束.blend` and its JSON describe a Duplicate Hair Curves preset;
`suifa.blend` contains the project's 碎发 node setup and its saved working copies.
These setups reuse Blender hair node assets; those built-in node groups are not
claimed as newly invented algorithms. Neither preset is SHP or a replacement for it.

The add-on declares Blender 5.0 as its minimum version. HairBridge Studio and the
selected SHP 4.3.1 require Blender 5.2 or later; the submission checks use 5.3.0.
This does not establish compatibility with every Blender release.

From the project root, run `python scripts/package_addon.py`. Install
`installers/surface_hair_curve_tool.zip` using Preferences → Add-ons → Install from
Disk, then enable **Surface Hair Curve Tool**. The panel appears under **Surface
Hair** in the 3D View sidebar. Install SHP separately and then HairBridge Studio.
See `docs/installation.zh-CN.md` in the repository for the complete workflow.

The project has not selected a new license for its author-written code. Original
Blender and third-party credits remain applicable to reused material.
