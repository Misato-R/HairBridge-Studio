# Rain study test materials

Start with `references/source.png`. The four separate reference images are
`front.png`, `left.png`, `right.png` and `back.png` in the same folder. Left and
right refer to **the character's own sides**, not the viewer's. These are the
five images used in the recorded experiment, not newly generated replacements.

The input is a render of Blender Studio's Rain v3 character. The four views were
prepared using Codex's built-in ImageGen during this project's reference stage.
The front view's framing and the left view's ponytail were revised against the
other views. They are
interpretations of the input; they are not official Blender Studio turnarounds
or exact renders of the original model.

**Attribution:** Rain Rig (CC) Blender Foundation | studio.blender.org.
[Original character and CC-BY notice](https://studio.blender.org/characters/rain/v3/).
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
LU WENXUAN prepared the project test materials with Codex assistance. Retain
the original character attribution when reusing these materials. Generated views,
Tripo geometry and extracted/fitted guides are identified as project derivatives;
they do not imply endorsement by Blender Studio.

## Two ways to use the example

**Start from images:** create a new image project, upload `source.png`, upload the
four views to their matching slots, review each, and approve the set. Subsequent
model generation uses your own Tripo account and credits.

**Inspect existing guides without new model generation:** run `npm run example`
from the repository root, then open the URL printed by the command. Alternatively,
use the workspace's existing Rain demo loader. Each import creates a fresh local
copy and never overwrites another project. The copy includes the five images,
the selected whole/head/hair GLBs, an auxiliary closed measurement mesh, seven
guides, region assignments and section settings. Reference and guide reviews are
historical sample state. No final result is pre-approved, and no Blend result is
included: build it locally with the separately installed SHP dependency.

`point-flow-fixture.json` contains the study-specific surface and guide data
needed by the interactive region/guide tools. This makes the recorded Rain
example reproducible; it does not establish automatic fitting for any hairstyle.
The closed measurement mesh is an approximation, as documented in
[the validation record](../../docs/submission-validation.zh-CN.md).

`manifest.json` records SHA-256 and size for all functional inputs. Run
`npm run verify:bundle` to check them. `project.hairbridge` is a clean example
template with historical task text, personal paths, run logs and version history
removed. The original working project is not included or changed.
