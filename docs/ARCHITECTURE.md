# Pystern Blot — Architecture

This document describes how Pystern Blot is structured internally, for
contributors and maintainers. For how to set up a development environment and
submit changes, see the [contributing guide](https://pysternblot.readthedocs.io/en/stable/contributing.html).

## Overview

Pystern Blot is a cross-platform desktop application (Python ≥ 3.11,
PySide6 / Qt 6) that treats a Western blot image as an informatic object with a
documented origin and processing history. All domain state is held in Pydantic
v2 models and persisted as JSON; source images are stored content-addressed by
SHA-256; every state mutation is recorded to an operation log.

## Entry point

`main.py` → `app.py` → creates a `Workspace`, instantiates `MainWindow(ws)`, and
runs the Qt event loop. The workspace root is `~/.pysternblot/`.

## Data model (`models.py`)

All domain state is Pydantic v2 models. The hierarchy is:

```
Project
└── Panel
    ├── style (Style)
    ├── crop_template (CropTemplate: w, h) — shared crop size, in reference pixels
    ├── reference_pixel_size_um (Optional[float]) — finest scaling pixel size
    ├── blots: list[Blot]
    │   ├── crop (Crop: x, y — position only; w/h kept for backward compat)
    │   ├── display (DisplaySettings: levels, invert, rotation, flips, overlay)
    │   ├── protein_label
    │   ├── ladder (Blot-level calibration)
    │   ├── overlay_ladder (optional OverlayLadder)
    │   ├── included_in_final: bool = True
    │   ├── modality: "ecl" | "nir_fluorescence"
    │   └── channels: list[BlotChannel]   # NIR only; empty for ECL blots
    ├── layout (order: list[blot_id])
    ├── legend (upper_rows / lower_rows: LegendRow — cells, cell_groups, parent_groups)
    └── lane_layout (header_block, groups)
```

`Project` also holds `assets: dict[sha256, AssetEntry]`, `marker_sets`, and
`operation_log`. `ProjectMeta` (the lightweight record stored alongside each
project) carries `is_archived: bool = False`, which soft-hides a project from
the library while leaving it on disk.

**Key invariants:**

- `Crop.w` / `Crop.h` are retained on the model for backward compatibility but
  are **ignored** at render and storage time — the authoritative crop size is
  `Panel.crop_template`, expressed in **reference pixels** (see *Physical scale*
  below). Each blot contributes only its own position (`Crop.x`, `Crop.y`), in
  its own native pixels; its crop size in native pixels is
  `physical_scale.native_crop_size(project, blot)`.
- `Blot.included_in_final` controls whether a blot appears in the rendered
  panel. Excluded blots remain fully stored, editable, and visible in the blot
  selector — this is how alternative exposures are documented rather than
  deleted.
- New fields must be added with defaults so that existing `project.json` files
  continue to load.

## Workspace / storage (`storage.py`)

`Workspace` manages `~/.pysternblot/`:

- `assets/<sha256>/original.<ext>` — SHA-256-deduplicated imported source files
- `assets/<sha256>/preview_crop*.tif` — cached 16-bit TIFF after
  rotation + levels + crop
- `projects/<project_id>/project.json` — full Pydantic model dump
- `presets/` — marker sets and suggestion lists

`import_asset()` hashes the source file and copies it into the asset store
unchanged. `ensure_blot_crop_preview(blot, panel, project=project)` applies
rotation → levels → crop and caches the result as a per-blot TIFF in native
pixels (never resampled); crop position comes from `blot.crop.x/y`, crop size
from `panel.crop_template` converted to the blot's native pixels (without
`project=` it falls back to the template as-is). **Render code reads this
cache** — callers must call `ensure_blot_crop_preview` for each blot before
rendering.

`load_project()` migrates older projects: it seeds `crop_template` for projects
that predate it, re-reads ImageQuant 800 metadata from stored originals that
have none (`parse_iq800_metadata`, logged as `iq800_metadata_backfilled`), and
reconciles `reference_pixel_size_um`. Changes are made in memory and logged;
nothing is written until the project is saved.

Every JSON file Pystern Blot writes with `json.dumps` goes through
`jsonsafe.dumps_strict()`: strict RFC 8259 output, non-finite floats written as
`null` (`project.json` itself is written by Pydantic, which does the same).

The portable `.pbarchive` format is a ZIP containing a manifest, the project
JSON(s), and all referenced assets. Import is two-pass: every asset is
SHA-256-verified against its path component *before* anything is written to the
receiving workspace; already-present content is skipped (idempotent); imported
projects receive an `imported_from_archive` log entry.

## Image pipeline (`image_utils.py`)

Two loaders exist — use the correct one:

- **`load_image_uint16(path)`** — strict; accepts only native 16-bit grayscale
  (`I;16`, `I;16L`, `I;16B`). Use for any path that must guarantee 16-bit input.
- **`load_image_as_uint16(path)`** — permissive; accepts 16-bit grayscale
  (unchanged) and 8-bit sources (`L`, `P`, `RGB`, `RGBA`, converted to grayscale
  and cast to uint16 with values kept in the 0–255 range, no upscaling). Use for
  display rendering and crop-preview generation. Always call it on the original
  asset, never on a preview or working-copy TIFF.

Bit-depth helpers: `is_jpeg(path)` (magic-byte detection) and
`get_bit_depth(path)`.

8-bit handling: the original asset is never converted; internal processing is
uint16 throughout, with 8-bit values occupying the 0–255 range of the uint16
space; `levels_white` defaults to 255 for 8-bit sources and 65535 for 16-bit.
JPEG is hard-rejected at every import entry point.

Processing functions are all uint16-in / uint16-out:
`apply_levels_uint16` (black/white/gamma/invert in float32, clipped back to
uint16), `rotate_uint16` (Pillow `"I"` int32 rotation, clipped back),
`crop_uint16` (clamped slice), and `uint16_to_qimage` (zero-copy
`QImage.Format_Grayscale16`).

> **Pillow note:** save uint16 TIFFs with
> `Image.frombuffer("I;16", (w, h), arr.tobytes(), "raw", "I;16", 0, 1)`.
> `Image.fromarray(arr, mode="I;16")` is deprecated and removed in Pillow 13.

## Rendering (`render.py`)

`build_panel_scene(project, workspace_root)` and `build_provenance_scene(...)`
each return a `QGraphicsScene` rebuilt from scratch on every refresh (no
incremental update). Callers must call `ensure_blot_crop_preview` for each blot
first. Image loading here uses the permissive `load_image_as_uint16` so 8-bit
sources display.

`build_panel_scene` stacks only blots where `included_in_final` is `True`, in a
fixed column layout: ladder column (left) → image column → protein label column
(right). Each crop is drawn at its blot's display scale (`1 / f`, see *Physical
scale*), so the image column width and row heights come from the displayed
size; overlay-ladder markers are placed at `(y_px − crop_y) × display scale`.
`build_provenance_scene` overlays an interactive `CropRectItem` on the full
original image, sized to the blot's native crop: moving it updates only
`blot.crop.x/y`; resizing it writes `panel.crop_template` back in reference
pixels (affecting all blots).

Upper legend rows are laid out by the pure function
`compute_upper_legend_layout()` and drawn by `_draw_upper_legend_block()`, the
single path used by both the Figure tab and the legend export zone
(`draw_legend_into_scene`). Each upper cell's id is resolved bottom-up: a run of
the same `parent_groups` id in the row below (multi-level headers), else a lane
group of the lane-reference row, else the cell's even slot. With empty
`parent_groups` this is exactly the two-level layout. Lower rows use
`_draw_legend_row_core`.

## Physical scale (`physical_scale.py`)

Some instruments export a fixed pixel grid whatever area was imaged (ImageQuant
800: always 2400 × 3296 px), so pixel size varies per file. Only instruments
opted in by `scaling_pixel_size_um(asset)` drive scaling — today ImageQuant 800
metadata whose XResolution passed the Image Area cross-check; Typhoon and LI-COR
pixel sizes are informational.

- `Panel.reference_pixel_size_um` = the finest scaling pixel size among **all**
  blots (included or not), kept in step by `reconcile_reference_pixel_size()`.
  When it changes between two known values, `crop_template` is rescaled by
  `old / new` to keep its physical size; every change is logged.
- Per blot, `f = reference / pixel size` (≤ 1 for coarser images; 1 when either
  is unknown). Native crop = template × f; the crop is drawn at `1 / f`
  (bilinear, display only).
- `scale_warnings()` reports panels that mix known and unknown pixel sizes and
  membrane overlays whose pixel size differs from their blot's; they are shown
  above the figure and in the integrity reports (`physical_scale` per blot).

## Crop handles (`ui/crop_rect_item.py`)

`CropRectItem` implements Inkscape-style resize handles: 4 corners (resize both
axes) and 4 edge midpoints (resize one axis), each with a small visual square and
a larger invisible hit zone, and cursor changes per zone. Its callbacks receive
`crop_scene_rect()`, the rectangle itself in scene coordinates, not
`sceneBoundingRect()` (which includes half the pen width on each side).

## UI (`pysternblot/ui/`)

`MainWindow` is assembled via Python mixins (the mixins carry no Qt base class,
so there is no Qt multiple-inheritance):

```
MainWindow(_ProjectIOMixin, _MarkerSetMixin, _OverlayLadderMixin, _ExportMixin, QMainWindow)
```

- **`main_window.py`** — builds tabs and widgets; owns the refresh pipeline,
  display controls, and blot navigation. Levels controls adapt their range to
  the active blot's bit depth.
- **`project_io_mixin.py`** — project create/open/import, operation logging
  (`log_operation`), 8-bit/JPEG gating, archive manager.
- **`marker_set_mixin.py`** — protein-ladder preset CRUD.
- **`overlay_ladder_mixin.py`** — overlay-ladder assignment and protein-label
  controls.
- **`export_mixin.py`** — PNG/PDF/SVG/TIFF and integrity-report exports, with a
  pre-export 8-bit warning.
- **`legend_tab.py`** — standalone legend-editing widget.

## Integrity reporting (`integrity.py`)

`build_integrity_report()` constructs project metadata, panel layout, and a
per-blot provenance record. For each blot, `_asset_info()` opens the stored
original, re-verifies its SHA-256, and records bit depth, dimensions, and mode;
8-bit assets get a `bit_depth_warning`, highlighted amber in the HTML report.
A detailed variant embeds the full chronological operation log. The schema is
`pysternblot.integrity_report.v3` (`…detailed_integrity_report.v3`).

`collect_exports()` derives the report's `exports` from the operation log:
every `export_generated` entry (which records `path`, `format`, `sha256` and
`size_bytes` of the written file) and every `source_asset_exported` entry is
re-hashed against the file now at its path and given a status (`ok`,
`changed`, `missing`, `unreadable`, `not_recorded`, `superseded`);
`exports_summary` counts them, and the HTML report lists them in an "Exported
files" table.

## Operation logging

Every mutation that should appear in an integrity report calls
`log_operation(operation, *, target_type, target_id, field, old_value,
new_value, ...)`, appending an `OperationLogEntry` to `project.operation_log`.
Old/new values pass through `_plain_log_value()`: Pydantic models are stored as
their `model_dump()` dict, JSON-serialisable values as-is, anything else as
`str()`; non-finite floats (NaN, ±Infinity) become `None` before the entry is
hashed, so the stored value is exactly what the chain hashed. The log is
persisted as part of `project.json`; each entry is hash-chained to the previous
one (`logchain.py`).

## NIR multichannel fluorescence

Western blot membranes probed with NIR-conjugated secondaries produce one 16-bit
grayscale TIFF per spectral channel. Unlike ECL, NIR signal is stable and
ratiometric, so there is no multiple-exposure audit requirement; the channels of
one acquisition share a physical crop region and ladder calibration but each
carries its own antibody, protein label, and display settings.

**`BlotChannel`** holds `asset_sha256`, `channel_index`, `wavelength_nm`,
`filter_name`, `channel_label` (the instrument's channel name, e.g. LI-COR
"700"/"800"; not a wavelength), `fluorophore`, `antibody_name`,
`protein_label`, `display`, `included_in_final` (whether the channel appears in
the final figure), and an optional per-channel `crop` (falling back to the blot
crop). `Blot` is extended
with `modality` (defaults to `"ecl"`) and `channels` (empty for ECL).

**Storage:** `parse_typhoon_tag270()` parses Cytiva Typhoon / Amersham TYPHOON
TIFF Tag 270 metadata (wavelength, filter, scan number, pixel size, etc.);
`import_nir_blot_typhoon()` imports one or two channel files and populates
`BlotChannel` entries. LI-COR Odyssey (Image Studio) TIFFs go through the same
import paths — NIR import and single-image "Import blot" — for both float16
Image Studio exports and older uint16 exports. `parse_licor_metadata()`, gated
on the TIFF Make tag, reads the channel (700/800, stored as
`BlotChannel.channel_label`; `wavelength_nm` stays unset), instrument model,
software, serial, date/time and pixel size. `load_tiff_source()` always reads
the full-resolution page, never a pyramid level, and a float source is shown
through a disclosed linear mapping to uint16 (`bridge_float_to_uint16()`); the
stored file and its hash are untouched.

**Image utilities:** `detect_tiff_channel_encoding()` classifies a TIFF as
`multipage`, `rgb_interleaved`, or `single`; `load_multichannel_tiff()` returns
one uint16 array per channel accordingly.

**UI / rendering:** `NirImportDialog` handles one- or two-channel import with
Tag 270 metadata shown on selection. NIR blots render as stacked per-channel
greyscale rows. Ladder bands are drawn on every row where they are visible —
all rows for a band with no channel restriction, otherwise only the rows whose
channel matches (`_band_visible_on_channel`, keyed by `_marker_channel_key`) —
with no first-row special case. There is no
false-colour composite in the final figure (greyscale per channel), though a
composite is available in the Original Image tab for orientation.

## Test data

Real instrument files live in `tests/` (e.g. the Typhoon channel TIFFs). LI-COR
import is covered by synthetic fixtures built in-process with tifffile to match
a real Odyssey CLx export (float16 tiled pyramid, and a legacy uint16 file, with
the LI-COR baseline tags): `tests/test_licor_float_import.py` and
`tests/test_licor_marker_channels.py`. See the [contributing guide](https://pysternblot.readthedocs.io/en/stable/contributing.html) for how to
contribute sanitised instrument output.
