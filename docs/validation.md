# Validation

Initial validation: 2026-11-23. P2.0 preparation regression checks updated 2026-11-24; installer distribution checks added 2026-11-25. This file distinguishes functional checks from visual acceptance.

## Completed automated checks

- The initial 12 Node tests covered guide data, reference invalidation, persistent HTTP checkpoints and project export, and local access boundaries. The suite reached 28 checks at the workflow completion stage, 32 at the bilingual stage and 34 for the public release. The P2.0 checks use fixture GLBs to exercise CLI registration, three-file publication, preservation of reviewed assets during a replacement, stale task rejection and the review gate for guides. They also exercise existing GLB imports and legacy requests.
- Node syntax checks passed for the server, browser controller and 3D viewer.
- Python compilation passed for worker, build script and companion code.
- Installable companion ZIP was generated with only source and license files.

## Observed integration checks

- The local browser interface loaded the Rain reference and real guide data, required reference confirmation, displayed a running HairDeck task, then displayed its actual result. Selecting strand 1 showed 26 samples and the four-sided section type. The generated SHP geometry loaded in the 3D result viewer. See [workspace screenshot](workspace.jpg).
- One new HairDeck run completed on the installed local environment with seed 0, 50 steps, CFG 2 and chains disabled. It produced 52 cards. The model-reported processing total was 21.204 seconds, excluding environment/model startup; this is not end-to-end user task time.
- Blender 5.3.0 built an independent file containing 52 editable guides and 4,388 evaluated vertices. The generated file was reopened in another background process.
- Moving a guide control by 5 mm moved its evaluated mesh by approximately 5.085 mm at the maximum measured point. Restoring the control restored the geometry with measured maximum error 0 mm in this check.
- A synthetic reference plane tested the coarse-alignment gate and bounded surface-correction operator. Correction was unavailable before alignment confirmation and executed after confirmation. These synthetic changes were restored before saving the return copy.
- The companion saved a separate Blend/GLB review copy, returned it to the running local service, and the browser showed the received result awaiting user review. No final appearance approval was recorded.
- Existing Rain Tripo GLB registration was tested through the same agent CLI used by a Studio handoff. This registered a previously generated model; it did not submit a new Studio generation. The subsequent Blender build also succeeded: the coarse model was imported as a hidden reference alongside 52 editable guides. Its report explicitly recorded that alignment had not been performed.
- Both an exported project archive and the companion ZIP passed Python ZIP CRC checks. The companion contains its entry point, the three bridge source modules and the retained HairDeck license, with no compiled cache files or proprietary hair-tool add-ons.

The compact machine-readable Blender check is retained in [blender-functional-check.json](blender-functional-check.json). Runtime logs, source hashes and full job records remain under ignored data/projects/.

## Limits

The initial integration checks did not submit a new paid Tripo generation. Later Test 2 uses the actual saved Smart Mesh P2.0 candidate and workflow records; this is separate evidence. Preparing a handoff is distinct from operating Studio and obtaining a model. No user study, editing-time comparison or broad hairstyle benchmark has been conducted. Manual alignment and aesthetic acceptance remain human tasks.

## 2026-11-25 — Source packaging and isolated installation

Surface Hair Curve Tool 0.1.0 now has checked-in source, node presets and its own installer. `scripts/package_addon.py` builds only the two author-developed add-ons; `installers/manifest.json` records their versions, sizes, file counts and SHA-256. The HairBridge ZIP contains seven files; Surface Hair contains fifteen files, including its documentation and preset assets. SHP remains separately installed and is excluded from public source and installers.

A new Blender 5.3.0 background process used `BLENDER_USER_RESOURCES` pointing to a temporary directory under the workspace `tmp/`, rather than the existing personal profile. Blender's installation operators installed the two project ZIPs and the separately rebuilt SHP 4.3.1 extension ZIP. Every imported add-on path was asserted to be inside that temporary profile, so the check did not rely on the previous Blender 5.2 installation.

The check imported one synthetic 25-sample card through the actual bridge, created one native Bézier guide, and verified its registered group and collection identity. SHP produced 100 evaluated vertices and 196 triangles. A 3 mm control-point move caused approximately 2.980 mm maximum mesh movement; restoring the control produced 0 mm measured geometry error. Saving and reopening the synthetic Blend preserved the evaluated geometry. Both Surface Hair preset libraries were readable, with four and twenty-one node groups respectively. All three installer ZIPs passed CRC checks.

Machine-readable results and tested package hashes: [installer-functional-check.json](installer-functional-check.json). Reproduction script: [verify_installers.py](../scripts/verify_installers.py). The script refuses to run unless the caller explicitly points Blender at a matching temporary profile under the workspace `tmp/` directory; it does not save personal preferences or touch an open Blender session.

The check was repeated after synchronising the final bridge source into the installer, in a fresh fourth temporary profile. The current machine-readable record identifies the tested package hashes.

This is a background installer and synthetic build check. It does not verify mouse-driven installation, preset appearance, restarting Blender with saved preferences, a full web-project return, latest guide generation or aesthetic quality. The existing full-project checks above remain separate evidence.

The local teacher attachment is in ignored `teacher-verification/`; its SHP source, assets, original README, manifest and MIT license are retained. Its assessment-only use request is distinguished from the original license. Public instructions are in [teacher-verification.zh-CN.md](teacher-verification.zh-CN.md).

## 2026-11-25 — Submission workflow completion

The selected-example workflow is complete. The real Test 2 project retains adoption of seven replacement guides, successful Blender construction (seven guides, 16 section points each, 7,280 evaluated vertices), saved Blend/GLB outputs with matching hashes, and final approval at 15:58:59 UTC. Earlier real-material checks separately support edit/undo, review return and version restoration. These are different runs, not one newly executed end-to-end check.

The `npm test` run at this stage passed all 28 tests. Face cleanup, anchored edits, section fitting, endpoint controls and state/export behaviour are covered. The first sandbox run could not connect to its temporary loopback HTTP port (`EACCES`); the authorised rerun with loopback access passed without code changes. Full evidence, image provenance, quality tradeoffs and draw-hair future scope are in [submission-validation.zh-CN.md](submission-validation.zh-CN.md).

SHP remains the completed geometry path. Draw-hair trials are recorded as further work; they do not establish resolved seams or intersections. General hairstyle applicability, editing-time benefits and participant usability remain untested.

## 2026-11-25 — English and Chinese workflow

The interface now defaults to English and provides a persistent top-bar language selector. The shared vocabulary covers 1,315 product and Blender UI phrases. Reference, rough-model, region and guide-task instructions are generated in both languages; interpolation values preserve paths, IDs and notes. English project-package opening instructions were checked in an actual export.

All 32 tests passed, including four language-specific checks for opaque values, concurrent request contexts, product copy and HTTP task identity preservation. Browser checks on copied data verified both languages, persistence after reload, retained unsaved notes and an unnamed region-name input, a retained 135% section value, and exact copying of the displayed English task. Desktop and narrow layouts were inspected. [Language verification](i18n-functional-check.json), [English screenshot](english-workflow.jpg), [English guide](installation.en.md).

Both author-developed add-ons were rebuilt and checked in another isolated Blender profile. English/Chinese catalog switching and scene language persistence passed alongside synthetic geometry creation, control-point restoration and reopening. The current manifest contains nine HairBridge files and seventeen Surface Hair files. Teacher ZIPs/checksums were synchronised; SHP was not modified. This does not claim that every third-party UI or user asset name is translated.

## 2026-11-25 — Public repository package

The public Rain study bundles five input/reference images, the existing whole/head/hair and closed-measurement GLBs, seven guides, region/section state and the study-specific surface fixture. A new import creates a fresh UUID, retains the historical reference/guide checks and excludes final approval, old results, run logs and personal task text. No new generation is implied. Source paths are replaced by repository-local inputs. The companion download now uses the committed installer directory, so it works without ignored build output.

The publication suite has 34 checks, including independent sample imports and the HTTP demo/installer download paths. Bundle verification checks sample sizes/hashes, five PNG inputs, installer/source agreement and Python syntax. See [reproduction](reproduction.en.md) and the [release record](release-verification.json). Historical numerical and browser checks above retain their original scope and counts.
