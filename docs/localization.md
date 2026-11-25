# English and Chinese workflow

The browser defaults to English, with a persistent top-bar language selector.
Product terminology distinguishes regions, editable guides, cross-sections and
built hair geometry. Source files, node identifiers, JSON fields, task IDs and
user-authored names/notes are not renamed during translation.

`public/i18n.mjs` applies the shared vocabulary at rendering boundaries. Canonical
text is retained on DOM nodes, allowing already-mounted editor panels to switch
back to Chinese. Locale changes refresh the presentation and current task views,
while retaining the project, selection, editor objects and editable form values.

`lib/locale.mjs` uses asynchronous request context so concurrent English and
Chinese requests cannot change one another's prompt language. Task messages are
generated in both languages; GET views select a copy without modifying the saved
task or its identity. Template interpolation values remain opaque, preserving
paths, IDs and notes. Legacy single-language messages use the vocabulary when
displayed. The CLI defaults to English; set `HAIRBRIDGE_LANG=zh` to request Chinese.

Project-package opening instructions follow the download request's language.
New Blender build jobs include `uiLanguage`; the companion saves that selection
in the scene. Both author-developed add-ons include the compiled vocabulary and
provide language controls without changing Blender's global preferences. SHP and
other third-party add-ons are not modified.

The English sources are `public/locales/en.tsv` and `blender-en.tsv`. Run
`npm run build:locales` after editing them. The compiled JSON files are included
for a dependency-free startup; temporary parser tooling used during migration is
outside this application and is not a runtime dependency.

Verification covers bilingual task creation, opaque interpolation values,
concurrent language contexts, HTTP task identity preservation, browser switching,
retained unsaved notes and section values, language persistence after reload,
and isolated Blender install/build/edit-restore/reopen checks. The complete
automated suite currently has 34 passing tests. Browser observations and package
hashes are recorded in the corresponding validation files.
