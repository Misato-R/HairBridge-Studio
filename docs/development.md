# Development record

## 2026-11-23 — Independent workflow integration

The project was created under IIS/HairBridge_Studio at the user's request so it can later become a public submission repository. Existing experiments remain in assignment/A2_Hair_Bridge. No existing scene, result or reference application was moved or overwritten.

The user selected a local web workspace plus Blender companion and a Tripo Studio browser-and-agent connection. The architecture therefore uses a local Node service to manage project state, calls the existing HairDeck environment for local generation, and uses explicit task handoffs for Studio. It does not substitute an API integration or create paid Tripo jobs in the background.

Five stages connect reference confirmation, draft generation, guide review, Blender editing and result saving. Input changes invalidate current downstream approvals. Historical assets remain inspectable. Project archives contain the manifest and assets rather than an unusable manifest alone.

The existing HairDeck JSON Bridge is reused inside the companion. It preserves source samples, fits editable Bézier guides, maps source dimensions into SHP custom geometry and supports tip adjustment. Source modules are copied into this independent project so the submitted code does not depend on the earlier experiment directory.

A limited nearest-surface correction was added for selected guides after manual coarse-mesh alignment. This is deliberately distinguished from hair-flow inference and the Rain-specific reconstruction scripts. It offers distance limits, strength, offset, root retention and Blender Undo; the user must inspect whether the result follows the intended clump.

Blender processing uses a fresh background scene and writes a new file. The live user scene is not changed by web builds. The plugin returns separate review copies and checks that their input stamp still matches the current project. Returning files never implies final visual approval.

Charakuru informed the checkpoint and persistent-project interaction. Its application code, agent skills, character assets and project format were not copied. Separately licensed Three.js files were reused with their MIT notice.

## Curve system and module responsibilities

Surface Hair Curve Tool is an author-developed core of the Blender curve layer, providing native curves, sampling and grouping. The bridge fits sampled paths and checks conversion deviation. Web modules handle surface-constrained paths, anchor-preserving fairing and region review; the refinement companion transports cross-sections after guide edits. These related improvements belong to the overall curve system and should not all be attributed to the Surface Hair add-on directory. See [technical design and experiment links](curve-system.zh-CN.md).

On 2026-11-25, Surface Hair Curve Tool 0.1.0 source and its two node presets were copied from the author's working installation into `addon/surface_hair_curve_tool/`. The packaging script now builds two independent installers under `installers/`, with versions and SHA-256 checksums. The companion ZIP still contains only HairBridge and its internal bridge; Surface Hair remains separately installed and enabled. The public project does not depend on an unprovided local copy of the author-written curve module.

SHP remains a separately installed dependency. A local `teacher-verification/` attachment is excluded from Git and retains SHP's original MIT license and copyright. The requested assessment-only use is distinguished from the author's license. The original installed add-ons and current Blender scene were not changed during packaging. Installation and validation instructions are recorded separately.

## AI assistance and authorship

LU WENXUAN is the author of the project dataset preparation and construction, and of Surface Hair Curve Tool 0.1.0, developed with Codex assistance. This attribution was explicitly confirmed by the author on 2026-11-25. Dataset preparation includes the project materials and derived records; Rain source assets, external model weights and third-party software retain their original credits. Codex is acknowledged as an assistance tool.

Codex assisted with inspecting the earlier bridge and local environment, interpreting the user's integration proposal, authoring the new UI/server/adapters, identifying stale-input cases and running validation. The user chose the combined interface and Studio connection. The earlier experimental bridge and HairDeck frame math are identified separately from the new orchestration code.

Examples of review and adaptation include replacing a misleading linear “HairDeck then Tripo optimisation” description with explicit branches; distinguishing pending Studio requests from executed jobs; making imported sample results require reference confirmation; and retaining manual alignment as a prerequisite for coarse-surface correction.

Do not describe successful file conversion, tests or numerical checks as evidence of aesthetic quality, general reconstruction accuracy, lower editing cost or participant evaluation. Record the checks actually performed in validation.md.

## 2026-11-25 — Completed selected-example submission scope

The author confirmed the selected-example workflow is complete. The report now uses actual mask-cleanup regression evidence, seven-strand replacement/adoption and saved output records, and the final project approval. The original E1/E3 design evidence remains; later UV-section comparisons explain tradeoffs between visible coverage and outward depth, without claiming every quality measure improves. Three illustrated storyboards distinguish web screenshots, offline geometry views and different trial runs.

The 28-test suite was rerun successfully. A stale bridge entry in the installer was rebuilt from current source; the updated ZIP passed a fresh isolated Blender install/build/edit-restore/reopen check. The ignored teacher bundle and checksums were synchronised. Draw-hair seam and shape refinement is future scope. No live scene or existing project was edited during this report update. Public repository publication and English word-count finalisation remain hand-in tasks.

## 2026-11-25 — English-facing bilingual product

At the author's request, the workflow was localised for English-speaking modelling artists. The browser starts in English with an English/Chinese selector. Shared source vocabulary drives the UI, agent handoff text, errors and both author-developed Blender add-ons. Request-local language contexts keep simultaneous requests independent, and saved tasks retain bilingual instructions. UI switching retains editing state and freeform input; names, paths, IDs and geometry are not migrated. Project exports include opening instructions in the chosen language.

The add-on UI wrappers translate visible labels and RNA display names without renaming node groups or saved data keys. The generated build receives the selected UI language. No third-party add-on code or global Blender language preference is changed. The updated installers and private teacher bundle are included; existing desktop installations must install the new ZIPs. A copied project was used for browser checks, and the final 32-test suite and isolated Blender language/build check passed.

## 2026-11-25 — Portable GitHub hand-in

Added a five-image Rain input set and a cleaned seven-guide project template, study-specific surface fixture, geometry and section state. Fresh imports use new project IDs; private task text and final approvals are excluded. The sample no longer needs the original assignment directory. Installer downloads use the committed ZIPs. Added bundle verification, a disposable Blender verification launcher and GitHub checks. A Git-index-only export passed all 34 automated checks, bundle verification and isolated Blender installation/build/edit-restore/reopen. See release-verification.json for the exact scope.

## 2026-11-25 — Report evidence reconciliation after v0.1.0-a2

The report review identified a documentation gap: the later local/cloud closure
comparison was supplied with the report source, outside the fixed release.
Added an English comparison note, the original numerical records, and its
English-labelled figure and provenance. The note distinguishes a 5.5305%
relative reduction in rear-left exposed scalp from a 0.2492 percentage-point
absolute reduction, and retains the remaining openings and depth trade-off.
No runtime code, installers or fixed release tag were changed.

The sample provenance now names Codex's built-in ImageGen and the recorded
framing/ponytail revisions. The current 34 Node checks and bundle verification
passed again. The original isolated Blender check is retained as historical
evidence; this documentation review did not rerun Blender or paid generation.
