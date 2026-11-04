# Figure tab

The **Figure** tab assembles your blot panels into the final figure and is where
all publication and integrity exports are performed. The composed figure is shown
in the preview area below the controls.

## Layout controls

| Control | Function |
|---|---|
| **Outline** | Toggles a border around each panel |
| **Width** | Sets the outline width (1–10) |
| **Refresh** | Regenerates the figure preview after changes |

Panels appear in the order the blots were imported. To reorder them, use the
**Up** / **Down** buttons on the [Original Image tab](original-image.md), which
controls panel order across the figure. Whether a given blot appears in the
figure at all is controlled by its **Include in final figure** checkbox, also on
the Original Image tab.

## Publication exports

| Button | Output |
|---|---|
| **Export PNG** | Raster image — suitable for presentations and preprints |
| **Export PDF** | Vector output — ready for submission |
| **Export SVG** | Fully editable vector — open in Inkscape or Illustrator for final layout |

## Integrity exports

| Button | Output |
|---|---|
| **Export Integrity Report** | A provenance record covering SHA-256 hashes, crop coordinates, display levels, the operation log, and bit-depth flags |
| **Export Detailed Report** | An extended report with full per-operation detail |

See [Provenance and integrity](../concepts/provenance.md) for what these reports
contain and why, and the [About tab](about.md) for version and citation
information to accompany a submission.

Both reports include an **Exported files** table. Each figure, legend-zone PNG,
annotated context TIFF and source file you exported is listed with the SHA-256
recorded when it was written, re-checked against the file at that path:
**ok** (unchanged), **changed** (the file was edited after export), **missing**
(moved, renamed, or the report was made on another computer; verify by hash),
**superseded** (a later export overwrote the same path) or **not recorded**
(exported by an earlier version, before hashes were kept). A file re-encoded
downstream, for example by a journal's submission system, will not match its
recorded hash.

```{note}
If any blot in the project was imported from an 8-bit source, a warning is shown
before export, reminding you to disclose the bit depth in any journal submission.
```
