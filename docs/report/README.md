# HairBridge Studio A2 report source

`HairBridge_Studio_A2_Report.md` is the editable report source.
`HairBridge_Studio_A2_Report.pdf` is the seven-page review/submission copy.
Keep `figures_en/` and `evidence/` beside the Markdown so its relative links work.

The comparison images use original experiment renders and viewport extracts.
English labels and schematic controls are typeset separately; source geometry
has not been generated or repainted. Provenance is recorded in
`figures_en/provenance.json`.

## Editing and export

Edit the Markdown, then run on Windows with Python and the ReportLab and Pillow
packages installed, and the Calibri and Microsoft YaHei fonts available:

```powershell
python tools/render_markdown_pdf.py HairBridge_Studio_A2_Report.md HairBridge_Studio_A2_Report.pdf
```

`<div class="page-break"></div>` controls print pagination. The renderer reads
the Markdown directly and does not require Word. Large text edits may change
pagination, so check the resulting PDF. Markdown editors can preview the same
source and images without running the PDF renderer.

The report keeps the fixed v0.1.0-a2 code release separate from the published
documentation supplement. Figure 4's web links are pinned to documentation
commit ed3c27b6880f0c02220deaf92617b16db83e13b7; offline copies of its two JSON
records are also included in `evidence/`. See `publication.json` for version
details.

## Submission and images

The archived A2 brief specifies a project report, without prescribing Markdown,
PDF or Word. The PDF embeds all illustrations and is ready to read on its own.
For offline editing, download the repository as a ZIP and open the Markdown in
this directory. Keep `figures_en/` beside the Markdown so the images load.
