# Development record

The first public commit bundles work I tested in separate Blender and HairDeck projects earlier in November. The dates below come from the oldest prototype files and saved test records I could verify. The links point to code or evidence available in this repository.

## 2–3 November — Blender hair-tool prototypes

A1 gave me the problem of selecting an artist's intended lock when generated hair joins it to a neighbour or splits it into several pieces. Before building a workspace, I tried making individual locks editable in Blender. The earliest preserved copy of my Surface Hair Curve Tool dates to 2 November. It contained a viewport tool for drawing and snapping guides to a surface, native Bézier editing, curve groups and two node presets. Some of that source, including the curve data and snapping modules, carries through to the public package.

On 3 November I checked three tools separately in a Blender 5.2.3 scratch scene. Surface Hair Curve Tool created a managed three-point Bézier guide in a group. Hair Curve Toolkit 0.24.18 generated a section-based strand, and increasing its length sampling changed the evaluated mesh from 1,152 to 1,200 vertices. Stylized Hair PRO 4.3.1 evaluated a test Bézier setup to 760 vertices. I removed the temporary objects after the checks. That gave me three things to test separately as I developed the workflow: the path, the section and the resulting strand mesh.

[Surface Hair Curve Tool source](../addon/surface_hair_curve_tool/) · [Technical notes](curve-system.zh-CN.md) · [Tool credits](../THIRD_PARTY_NOTICES.md)

## 4–6 November — Local HairDeck setup and tests

I pinned the upstream HairDeck code, configured staged GPU offload for the Windows machine and added a command-line test harness. On 4 November, I ran three images with two seeds each at 50 steps and guidance scale 2, with chains disabled. All six runs produced non-empty card data and loadable GLBs. I also checked that the local web interface returned both GLB and JSON. Several outputs had gaps around the crown or back, and one interpreted a hair accessory as pointed hair.

By 6 November I had added an examples launcher that accepted my own input images, avoided duplicates by comparing their contents and rebuilt the examples list at startup. I used the upstream model weights throughout. The early changes were to setup, input handling, test runs and exports. The JSON samples let me inspect each path and its dimensions, which led to a separate Blender import tool.

[HairDeck credits](../THIRD_PARTY_NOTICES.md) · [HairBridge's later local worker](../scripts/hairdeck_worker.py)

## 16–17 November — Standalone HairDeck JSON Bridge

I first converted three saved HairDeck cards into editable Surface Hair guides with live SHP geometry to see whether moving a control point changed just the intended strand. A 15 mm test move left the other two meshes unchanged, and restoring the control returned the mesh to its measured starting positions.

I then made a standalone Blender import add-on for HairDeck card JSON. It read each sample's position, dimensions and direction, fitted a native Bézier guide with a sampled deviation check, created a separate group for each import and mapped the source dimensions to SHP sections. The project retained HairDeck's credited tangent and frame calculations as well as the original samples and section profiles. The add-on also exposed separate tip-width and tip-thickness controls.

I checked two saved seeds in Blender 5.3.0. On the first, I swept a fringe guide sideways in Edit Mode and set its tip width to 80%. Undo restored the width while keeping the new path and the other 73 meshes. The second run verified that changing tip thickness preserved the width. I reopened the saved work to check the editable guides. I later brought the importer and its fitting and section code into the HairBridge companion.

[Bridge code carried into HairBridge](../addon/hairbridge_studio/hairdeck_bridge/) · [Later 52-guide integration check](blender-functional-check.json)

## 18–22 November — Comparing HairDeck drafts with Rain reconstruction

I kept the 52 guides from an early single-image Rain draft and edited the scalp fit, temple sweep and ponytail in stages. Rendering from fixed cameras after each stage helped me see where a guide edit improved the outline and where the strand needed a different section instead.

I used the original Rain v3 mesh to see whether the guide-and-section representation could reproduce a stylised shape when I had good source geometry. I took cross-sections at successive UV positions, joined their centres into 17 guides and reconstructed the hair with measured section outlines. Keeping the guides fixed and using 16-point profiles in place of four-point profiles raised front-view silhouette overlap from 82.23% to 94.38%. Both cases used the original geometry to derive their guides and sections.

I also tried conditioning HairDeck on a 10,000-point sample of the Rain hair surface, using two seeds under the same settings. The front-view overlaps were 65.50% and 67.47%, while the side-view results were 60.94% and 56.27%. The side view made it clear why I needed to check a candidate in several views before adopting it. In a later trial on the generated rough mesh, only one HairDeck guide passed screening for the long over-ear strand and none passed for the S-shaped fringe. I kept HairDeck as a candidate source and gave the modeller control over the root, tip and main bends.

I also compared a patched Tripo-derived front guide with a continuous path through the front, above the ear and towards the ponytail tie. I kept the cameras and neighbouring strands fixed. A strong ridge could carry the guide too high, so I kept the path as a proposal for the modeller to inspect before building the strand.

[Rain reconstruction figures and measurements](report/HairBridge_Studio_A2_Report.md#figure-1-reconstruction-from-the-original-mesh) · [Fringe comparison](report/HairBridge_Studio_A2_Report.md#figure-2-smoothing-and-preserving-the-main-bend) · [Anchor preservation test](../tests/anchored-guide-edit.test.mjs)

## By 23 November — Guide editing and section prototypes

Moving a guide exposed a second problem. SHP placed sections by normalised length, so shortening part of a curve could move sections outside the area I edited. I tried placing the original profiles along the new arc length, rotating them to follow the new tangent and keeping their physical dimensions. This became part of the strand-editing work in the Blender companion.

Two separate add-on trials helped me check the handoff. With HairMesh 1.1.1 I moved one anchor on a Rain guide by 3 mm, exported it, then rebuilt it with SHP. The endpoints, radius and tilt were retained and the neighbouring strand's mesh stayed the same. With Hair Curve Toolkit I held a guide fixed and compared elliptical and rounded trapezoid-to-ellipse profiles. Those experiments helped me decide which guide and section edits the HairBridge workspace should let modellers make independently.

[Blender strand editing implementation](../addon/hairbridge_studio/strand_edit.py) · [Earlier HairBridge edit, undo and return check](evidence/earlier-workflow-verification.json)

## 2026-11-23 — Independent workflow integration

I brought the separate prototypes into one web workspace with a Blender companion. I kept the original experiment scenes and results so I could compare the integrated workflow with the earlier trials.

The user selected a local web workspace plus Blender companion and a Tripo Studio browser-and-agent connection. The architecture therefore uses a local Node service to manage project state, calls the existing HairDeck environment for local generation, and uses explicit task handoffs for Studio. It does not substitute an API integration or create paid Tripo jobs in the background.

Five stages connect reference confirmation, draft generation, guide review, Blender editing and result saving. Input changes invalidate current downstream approvals. Historical assets remain inspectable. Project archives contain the manifest and assets rather than an unusable manifest alone.

The existing HairDeck JSON Bridge is reused inside the companion. It preserves source samples, fits editable Bézier guides, maps source dimensions into SHP custom geometry and supports tip adjustment. Source modules are copied into this independent project so the submitted code does not depend on the earlier experiment directory.

A limited nearest-surface correction was added for selected guides after manual coarse-mesh alignment. This is deliberately distinguished from hair-flow inference and the Rain-specific reconstruction scripts. It offers distance limits, strength, offset, root retention and Blender Undo; the user must inspect whether the result follows the intended clump.

Blender processing uses a fresh background scene and writes a new file. The live user scene is not changed by web builds. The plugin returns separate review copies and checks that their input stamp still matches the current project. Returning files never implies final visual approval.

Charakuru informed the checkpoint and persistent-project interaction. Its application code, agent skills, character assets and project format were not copied. Separately licensed Three.js files were reused with their MIT notice.

## 2026-11-24 — Tripo Smart Mesh P2.0 handoff

I submitted the Test 2 rough-model request to Tripo Studio on 24 November. The saved candidate was used in the later seven-guide Rain study. In separate regression tests, I used fixture GLBs to check that the agent CLI registers the whole model, head and hair together. The checks also covered retaining the reviewed assets while a replacement is pending, rejecting stale results and requiring separation review before guide creation.

[Preparation regression checks](validation.md#completed-automated-checks) · [Later Rain study record](evidence/final-workflow.json)

## Curve system and module responsibilities

Surface Hair Curve Tool is an author-developed core of the Blender curve layer, providing native curves, sampling and grouping. The bridge fits sampled paths and checks conversion deviation. Web modules handle surface-constrained paths, anchor-preserving fairing and region review; the refinement companion transports cross-sections after guide edits. These related improvements belong to the overall curve system and should not all be attributed to the Surface Hair add-on directory. See [technical design and experiment links](curve-system.zh-CN.md).

On 2026-11-25, Surface Hair Curve Tool 0.1.0 source and its two node presets were copied from the author's working installation into `addon/surface_hair_curve_tool/`. The packaging script now builds two independent installers under `installers/`, with versions and SHA-256 checksums. The companion ZIP still contains only HairBridge and its internal bridge; Surface Hair remains separately installed and enabled. The public project does not depend on an unprovided local copy of the author-written curve module.

SHP remains a separately installed dependency. A local `teacher-verification/` attachment is excluded from Git and retains SHP's original MIT license and copyright. The requested assessment-only use is distinguished from the author's license. The original installed add-ons and current Blender scene were not changed during packaging. Installation and validation instructions are recorded separately.

## AI assistance and authorship

The developer prepared the project dataset and authored Surface Hair Curve Tool 0.1.0 with Codex assistance. The developer confirmed this attribution on 25 November 2026. Dataset preparation includes the project materials and derived records; Rain source assets, external model weights and third-party software retain their original credits. Codex is acknowledged as an assistance tool.

Codex assisted with inspecting the earlier bridge and local environment, interpreting the user's integration proposal, authoring the new UI/server/adapters, identifying stale-input cases and running validation. The user chose the combined interface and Studio connection. The earlier experimental bridge and HairDeck frame math are identified separately from the new orchestration code.

Examples of review and adaptation include replacing a misleading linear “HairDeck then Tripo optimisation” description with explicit branches; distinguishing pending Studio requests from executed jobs; making imported sample results require reference confirmation; and retaining manual alignment as a prerequisite for coarse-surface correction.

Do not describe successful file conversion, tests or numerical checks as evidence of aesthetic quality, general reconstruction accuracy, lower editing cost or participant evaluation. Record the checks actually performed in validation.md.

## 2026-11-25 — Completed selected-example submission scope

The author confirmed the selected-example workflow is complete. The report now uses actual mask-cleanup regression evidence, seven-strand replacement/adoption and saved output records, and the final project approval. The original E1/E3 design evidence remains; later UV-section comparisons explain tradeoffs between visible coverage and outward depth, without claiming every quality measure improves. Three illustrated storyboards distinguish web screenshots, offline geometry views and different trial runs.

The 28-test suite passed at this stage. The installer was rebuilt from current bridge source and passed an isolated Blender install, build, edit, restore and reopen check. The teacher bundle and checksums were synchronised. Draw-hair seam and shape refinement is future work. [Region cleanup checks](evidence/region-regression.json) · [Seven-guide project record](evidence/final-workflow.json) · [Isolated installer check](installer-functional-check.json).

## 2026-11-25 — English-facing bilingual product

At the author's request, the workflow was localised for English-speaking modelling artists. The browser starts in English with an English/Chinese selector. Shared source vocabulary drives the UI, agent handoff text, errors and both author-developed Blender add-ons. Request-local language contexts keep simultaneous requests independent, and saved tasks retain bilingual instructions. UI switching retains editing state and freeform input; names, paths, IDs and geometry are not migrated. Project exports include opening instructions in the chosen language.

The add-on UI wrappers translate visible labels and RNA display names without renaming node groups or saved data keys. The generated build receives the selected UI language. No third-party add-on code or global Blender language preference is changed. The updated installers and private teacher bundle are included; existing desktop installations must install the new ZIPs. A copied project was used for browser checks, and all 32 tests at this stage and the isolated Blender language and build check passed. [Language verification](i18n-functional-check.json).

## 2026-11-25 — Portable GitHub hand-in

Added a five-image Rain input set and a cleaned seven-guide project template, study-specific surface fixture, geometry and section state. Fresh imports use new project IDs; private task text and final approvals are excluded. The sample no longer needs the original assignment directory. Installer downloads use the committed ZIPs. Added bundle verification, a disposable Blender verification launcher and GitHub checks. A clean export passed all 34 automated checks, bundle verification and isolated Blender installation, build, edit, restore and reopen. [Release commit](https://github.com/Misato-R/HairBridge-Studio/commit/5df5f1383f38d87e0148a34529e5b7cb841050a2) · [Verification results](release-verification.json).

## 2026-11-25 — Report evidence reconciliation after v0.1.0-a2

I measured the local-closure and Quick Cap comparison on the afternoon of
25 November. After tagging `v0.1.0-a2`, I prepared the English figure and
published it with the original measurements and provenance that evening.
The note distinguishes a 5.5305%
relative reduction in rear-left exposed scalp from a 0.2492 percentage-point
absolute reduction, and retains the remaining openings and depth trade-off.
No runtime code, installers or fixed release tag were changed.

The sample provenance now names Codex's built-in ImageGen and the recorded
framing/ponytail revisions. The current 34 Node checks and bundle verification
passed again. The original isolated Blender check is retained as historical
evidence; this documentation review did not rerun Blender or paid generation.
[Closure evidence commit](https://github.com/Misato-R/HairBridge-Studio/commit/ed3c27b6880f0c02220deaf92617b16db83e13b7) · [Comparison and limitations](evidence/closure-comparison.md).

The final report links to the repository on its first page and to the tested code release alongside the evidence. [Report PDF](report/HairBridge_Studio_A2_Report.pdf) · [Illustrated Markdown](report/HairBridge_Studio_A2_Report.md) · [Tested code release](https://github.com/Misato-R/HairBridge-Studio/tree/v0.1.0-a2)
