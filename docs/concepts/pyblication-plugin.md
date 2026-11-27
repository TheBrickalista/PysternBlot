# Pyblication plugin

[Pyblication](https://github.com/TheBrickalista/Pyblication) keeps the
figures of a manuscript traceable: every panel in a figure is linked to the
exact files it was made from. PysternBlot ships a Pyblication plugin, so
that when you put a PysternBlot export into a Pyblication workspace,
Pyblication recognises which PysternBlot project produced it and records
that project with the panel.

PysternBlot works exactly as before without Pyblication. The plugin is only
an entry point that Pyblication looks for. PysternBlot does not depend on
Pyblication and never imports it.

## How an export is recognised

Every export PysternBlot writes (final figure as PNG, PDF or SVG, annotated
TIFFs, legend-zone PNGs) is recorded in the project's operation log as an
`export_generated` entry with the file's SHA-256 (see
[Provenance](provenance.md)). This entry is saved to `project.json` before
the export dialog says "Exported", so the file can be recognised straight
away.

When Pyblication asks about a file, the plugin:

1. computes the file's SHA-256;
2. looks through `projects/*/project.json` in the workspace for an
   `export_generated` entry with that hash;
3. returns that project, or nothing if no project logged the file.

If several projects logged the same file (for example a copied project),
the most recent entry wins, and the other projects are listed.

The plugin only reads. It never changes a project, an asset or any other
file in the workspace.

## What Pyblication records

For the recognised project, the plugin lists the files the figure is made
from:

| Name in Pyblication | File | Why |
|---|---|---|
| `project.json` | `projects/<id>/project.json` | Panel layout, crops, display settings, labels, marker sets and the operation log |
| `assets/<sha256>/original.<ext>` | the stored original of every image the project uses | Each blot image, each membrane overlay, each NIR channel |

Marker sets are stored inside `project.json`, so the workspace preset
library (`presets/protein_ladders.json`) is not part of a figure. Crop
previews (`assets/<sha256>/preview_crop_*.tif`) are rebuilt from the
originals and are not listed either. Fonts are system fonts.

The plugin also gives Pyblication a short provenance record: the project
id and name, the export's log entry (time, format, size and its hash in the
log chain), the result of verifying the log chain, and the PysternBlot
version.

## Opening a project from Pyblication

`pyb edit <panel>` in Pyblication starts PysternBlot on the right project:

```sh
pysternblot --project <project-id>
```

The same option can be used directly. Without `--project`, PysternBlot
starts as usual, on its Home tab.

## Workspace location

The workspace is `~/.pysternblot`. Set the `PYSTERNBLOT_WORKSPACE`
environment variable to use another folder, for the app and for the
plugin alike.
