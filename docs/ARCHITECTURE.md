# Pystern Blot — Architecture

This document describes how Pystern Blot is structured internally, for
contributors and maintainers. For how to set up a development environment and
submit changes, see [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

## Overview

Pystern Blot is a cross-platform desktop application (Python ≥ 3.10,
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
    ├── crop_template (CropTemplate: w, h) — shared crop size for all blots
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
    ├── legend
    └── lane_layout (header_block, groups)
```

`Project` also holds `assets: dict[sha256, AssetEntry]`, `marker_sets`, and
`operation_log`. `ProjectMeta` (the lightweight record stored alongside each
project) carries `is_archived: bool = False`, which soft-hides a project from
the library while leaving it on disk.

**Key invariants:**

- `Crop.w` / `Crop.h` are retained on the model for backward compatibility but
  are **ignored** at render and storage time — the authoritative crop size is
  `Panel.crop_template`. Each blot contributes only its own position
  (`Crop.x`, `Crop.y`).
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
unchanged. `ensure_blot_crop_preview(blot, panel)` applies rotation → levels →
crop and caches the result as a per-blot TIFF; crop position comes from
`blot.crop.x/y`, crop size from `panel.crop_template.w/h`. **Render code reads
this cache** — callers must call `ensure_blot_crop_preview` for each blot before
rendering.

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
(right). `build_provenance_scene` overlays an interactive `CropRectItem` on the
full original image: moving it updates `blot.crop.x/y`; resizing it updates
`panel.crop_template.w/h` (affecting all blots).

## Crop handles (`ui/crop_rect_item.py`)

`CropRectItem` implements Inkscape-style resize handles: 4 corners (resize both
axes) and 4 edge midpoints (resize one axis), each with a small visual square and
a larger invisible hit zone, and cursor changes per zone.

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
A detailed variant embeds the full chronological operation log.

## Operation logging

Every mutation that should appear in an integrity report calls
`log_operation(operation, *, target_type, target_id, field, old_value,
new_value, ...)`, appending an `OperationLogEntry` to `project.operation_log`.
Old/new values are serialised via `_plain_log_value()` (JSON-serialise Pydantic
models, else `str()`). The log is persisted as part of `project.json`.

## NIR multichannel fluorescence

Western blot membranes probed with NIR-conjugated secondaries produce one 16-bit
grayscale TIFF per spectral channel. Unlike ECL, NIR signal is stable and
ratiometric, so there is no multiple-exposure audit requirement; the channels of
one acquisition share a physical crop region and ladder calibration but each
carries its own antibody, protein label, and display settings.

**`BlotChannel`** holds `asset_sha256`, `channel_index`, `wavelength_nm`,
`filter_name`, `fluorophore`, `antibody_name`, `protein_label`, `display`, and an
optional per-channel `crop` (falling back to the blot crop). `Blot` is extended
with `modality` (defaults to `"ecl"`) and `channels` (empty for ECL).

**Storage:** `parse_typhoon_tag270()` parses Cytiva Typhoon / Amersham TYPHOON
TIFF Tag 270 metadata (wavelength, filter, scan number, pixel size, etc.);
`import_nir_blot_typhoon()` imports one or two channel files and populates
`BlotChannel` entries. LI-COR Odyssey import is currently a stub
(`import_nir_blot_odyssey` raises `NotImplementedError`) pending a sample file.

**Image utilities:** `detect_tiff_channel_encoding()` classifies a TIFF as
`multipage`, `rgb_interleaved`, or `single`; `load_multichannel_tiff()` returns
one uint16 array per channel accordingly.

**UI / rendering:** `NirImportDialog` handles one- or two-channel import with
Tag 270 metadata shown on selection. NIR blots render as stacked per-channel
greyscale rows, with the ladder column on the first row only; there is no
false-colour composite in the final figure (greyscale per channel), though a
composite is available in the Original Image tab for orientation.

## Test data

Real instrument files live in `tests/` (e.g. the Typhoon channel TIFFs). The
Odyssey path has tests skipped until a sample file is available. See
[`../CONTRIBUTING.md`](../CONTRIBUTING.md) for how to contribute sanitised
instrument output.
