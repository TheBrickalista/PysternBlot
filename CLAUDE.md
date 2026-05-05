# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app
python -m pysternblot

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_image_utils.py -v

# Run a single test by name
pytest tests/test_image_utils.py::TestSaveUint16Tiff::test_roundtrip -v

# Run tests and treat deprecation warnings as errors
pytest tests/ -v -W error::DeprecationWarning
```

There is no separate build, lint, or format step configured.

## Architecture

### Entry point

`main.py` → `app.py` → creates `Workspace`, instantiates `MainWindow(ws)`, runs Qt event loop. The workspace root is `~/.pysternblot/`.

### Data model (models.py)

All domain state is Pydantic v2 models. The hierarchy is:

```
Project
└── Panel
    ├── style (Style)
    ├── crop_template (CropTemplate: w, h) — shared crop size for all blots
    ├── blots: list[Blot]
    │   ├── crop (Crop: x, y — position only; w/h kept for backward compat)
    │   ├── display (DisplaySettings: levels, invert, rotation, overlay)
    │   ├── protein_label
    │   ├── ladder (Blot-level calibration)
    │   ├── overlay_ladder (optional OverlayLadder)
    │   └── included_in_final: bool = True
    ├── layout (order: list[blot_id])
    ├── legend
    └── lane_layout (header_block, groups)
```

`Project` also holds `assets: dict[sha256, AssetEntry]`, `marker_sets`, and `operation_log`.

Key model invariants:
- `Crop.w` and `Crop.h` are kept in the model for backward compatibility but are **ignored** at render and storage time — the authoritative size is `Panel.crop_template`.
- `Blot.included_in_final` controls whether a blot appears in `build_panel_scene`. Excluded blots remain fully editable and visible in the blot selector.

### Workspace / storage (storage.py)

`Workspace` manages `~/.pysternblot/`:
- `assets/<sha256>/original.<ext>` — SHA256-deduplicated imported files
- `assets/<sha256>/preview_crop.tif` — cached 16-bit TIFF after rotation+crop+levels
- `projects/<project_id>/project.json` — full Pydantic model dump
- `presets/` — marker sets, legend/protein label suggestion lists

`import_asset()` hashes the source file and hard-links/copies to the assets store. `ensure_blot_crop_preview(blot, panel)` applies rotation → levels → crop and caches the result as a per-blot TIFF (`preview_crop_<id>.tif`). Crop position comes from `blot.crop.x/y`; crop size comes from `panel.crop_template.w/h`. Render code reads this cache; callers must call `ensure_blot_crop_preview` before rendering.

### Image pipeline (image_utils.py)

**All processing stays in uint16. No 8-bit promotion anywhere.**

- `load_image_uint16` — rejects anything that isn't native 16-bit grayscale (`I;16`, `I;16L`, `I;16B`)
- `apply_levels_uint16` — black/white/gamma/invert in float32, clipped back to uint16
- `rotate_uint16` — Pillow `"I"` mode (int32) rotation, clipped back to uint16
- `crop_uint16` — clamped array slice
- `uint16_to_qimage` — zero-copy wrap as `QImage.Format_Grayscale16`

When saving uint16 TIFFs use `Image.frombuffer("I;16", (w, h), arr.tobytes(), "raw", "I;16", 0, 1)` — `Image.fromarray(arr, mode="I;16")` is deprecated since Pillow 9.1 and will be removed in Pillow 13.

### Rendering (render.py)

`build_panel_scene(project, workspace_root)` and `build_provenance_scene(project, workspace_root, blot_id, on_crop_commit, on_crop_resize_commit, show_grid)` both return a `QGraphicsScene`. The scene is rebuilt from scratch on every refresh — no incremental update. Callers must call `ensure_blot_crop_preview(blot, panel)` for each blot before calling these functions.

`build_panel_scene` only stacks blots where `blot.included_in_final` is `True`. The panel uses a fixed column layout: ladder column (left) → image column → protein label column (right).

`build_provenance_scene` places an interactive `CropRectItem` over the full original image. Moving the rect updates `blot.crop.x/y` and calls `on_crop_commit(blot)`. Resizing updates `panel.crop_template.w/h` (affecting all blots) and calls `on_crop_resize_commit()`.

### UI (pysternblot/ui/)

`MainWindow` is assembled via Python mixins (no Qt multiple inheritance complications — mixins carry no Qt base class):

```
MainWindow(_ProjectIOMixin, _MarkerSetMixin, _OverlayLadderMixin, _ExportMixin, QMainWindow)
```

- **`main_window.py`** — `__init__` builds all tabs and widgets; owns the rendering/refresh pipeline, display controls, and blot navigation
- **`project_io_mixin.py`** — project create/open/import, operation logging (`log_operation`)
- **`marker_set_mixin.py`** — protein ladder preset CRUD
- **`overlay_ladder_mixin.py`** — overlay ladder assignment dialog, protein label controls, `eventFilter` for click-to-assign
- **`export_mixin.py`** — PNG/PDF/SVG/TIFF/integrity report exports
- **`crop_rect_item.py`** — interactive `QGraphicsItem` for the crop rectangle in the provenance view
- **`legend_tab.py`** — standalone `QWidget` for legend editing, emits `changed` signal

### Operation logging

Every mutation that should appear in integrity reports must call `self.log_operation(operation, *, target_type, target_id, field, old_value, new_value, ...)`. Old/new values are stored via `_plain_log_value()` which JSON-serializes or falls back to `str()`.

### Project persistence

`workspace.save_project(project)` serialises the full Pydantic model to JSON. `workspace.load_project(path)` deserialises with `Project.model_validate(json.loads(...))`. Migrations for missing optional fields are handled by Pydantic defaults — always add new fields with a default to preserve backward compatibility with existing `project.json` files.
