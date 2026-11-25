# Install and use HairBridge Studio

HairBridge Studio is a local workspace for reviewing generated hair and turning
selected strands into editable Blender guides and geometry. The interface starts
in English. Use **中文 / English** in the top bar to switch languages; the choice
is remembered in this browser.

## Install the Blender components

Use Blender 5.3.0 to reproduce the recorded checks. The companion and selected
SHP release require Blender 5.2 or later.

In **Edit → Preferences → Add-ons → Install from Disk**, install and enable:

1. [Surface Hair Curve Tool](../installers/surface_hair_curve_tool.zip), the
   author-developed guide and group component.
2. **Stylized Hair PRO 4.3.1**, obtained separately from
   [Dean Zarkov](https://deanzarkov.gumroad.com/l/stylized_hair_pro).
3. [HairBridge Studio](../installers/hairbridge_studio.zip), including its internal
   JSON bridge. An older standalone HairDeck JSON Bridge is unnecessary.

Select each ZIP directly; do not extract the Python files individually. Save
preferences. In the 3D View, press **N** and open **HairBridge**. Its Language
control also selects English or Chinese for the project tools. The Surface Hair
panel uses that choice when the companion is enabled and has its own control
when used alone. Third-party add-ons retain their own language support.

SHP is not included in the public installers. Assessment copies are provided in
a separate teacher attachment with the original copyright and MIT license.
HairMesh and Hair Curve Toolkit were used in earlier experiments and are not
required to run the completed workflow.

## Start the workspace

Install Node.js 22 or later. No npm runtime dependencies are required.

Copy `local-config.example.json` to `local-config.json`, then set `blender` to
the executable used above. Restart the service after changing configuration.
From the repository root, run:

```powershell
npm start
```

Open the local address printed by the service, normally
`http://127.0.0.1:8787`. On Windows, `Start_HairBridge.bat` also starts the app.
If upgrading an already-running instance, restart the service and refresh the
page to load both the new interface and task-generation code.

## Review and refine a project

1. **Import references.** Start from an image or an existing rough-model GLB.
   For the image route, prepare a reference-view task, copy it to your Codex
   chat, then review and confirm front, left, right and back images. Left and
   right always refer to the character's own sides.
2. **Rough model and separation.** Prepare a task for Tripo Studio. Review the
   full model, head without hair and separate hair from the same candidate.
   Keep their original coordinate frame and check the overlay before approving.
3. **Create guides.** Review suggested regions, edit face selections, compare
   selection cleanup, and confirm each region. Inspect its guides or request a
   replacement proposal. Compare the proposal before adopting it.
4. **Adjust cross-sections.** Select strands and inspect their root-to-tip flow.
   Adjust width, thickness, profile, range and scalp-end inset as needed. A live
   preview and the built SHP geometry are distinct; build and review the result.
5. **Refine in Blender.** Open the generated Blend file, or use **Load workspace
   project** with `project.hairbridge`. Keep its adjacent `assets` folder. Edit
   guides, check neighbouring strands and return a review copy to the workspace.
6. **Save result.** Compare versions from matching cameras, approve the chosen
   result and export the complete project package.

Switching language preserves the current project and local editing state. User
project names, notes, file paths, task IDs and geometry data retain their original
values. New tasks contain English and Chinese instructions; the displayed and
copied version follows the selected language. Language changes do not submit
model-generation jobs or approve results.

Tripo uses your own signed-in session. Optional local HairDeck generation needs
its separately installed Python environment and model weights; building from
existing guides does not require inference. Some region/guide operations are
validated on the supplied study mesh; see [scope and evidence](submission-validation.zh-CN.md).

## Rebuild and verify

```powershell
npm run build:locales
npm test
npm run package:addon
```

The locale build compiles the browser and Blender catalogs from the two TSV
sources in `public/locales/`. Packaging rebuilds the catalogs automatically and
generates the two ZIPs and SHA-256 manifest in `installers/`. Install the updated
ZIPs to use the translated Blender tools; the website alone does not update an
already-installed add-on.
