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
    │   ├── display (DisplaySettings: levels, invert, rotation, flip_horizontal, flip_vertical, overlay)
    │   ├── protein_label
    │   ├── ladder (Blot-level calibration)
    │   ├── overlay_ladder (optional OverlayLadder)
    │   ├── included_in_final: bool = True
    │   ├── modality: "ecl" | "nir_fluorescence"
    │   └── channels: list[BlotChannel]  # NIR only; empty for ECL blots
    │       ├── asset_sha256, channel_index, wavelength_nm, filter_name
    │       ├── fluorophore, antibody_name, protein_label
    │       ├── display (DisplaySettings)
    │       └── crop (optional per-channel Crop override; falls back to blot.crop)
    ├── layout (order: list[blot_id])
    ├── legend
    └── lane_layout (header_block, groups)
```

`Project` also holds `assets: dict[sha256, AssetEntry]`, `marker_sets`, and `operation_log`.

`ProjectMeta` (the lightweight record stored alongside each project) has `is_archived: bool = False` — soft-hide from library; project remains on disk; default `False` ensures backward compatibility with existing `project.json` files.

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

**Two loaders exist — use the correct one:**
- `load_image_uint16(path)` — strict: only accepts native 16-bit grayscale (`I;16`, `I;16L`, `I;16B`). Use for NIR multichannel import and any path that must guarantee 16-bit input. Do not modify.
- `load_image_as_uint16(path)` — permissive: accepts 16-bit grayscale (unchanged) and 8-bit sources (`L`, `P`, `RGB`, `RGBA` modes — converted to grayscale `L`, then cast to uint16 with values in 0–255 range). Use for display rendering and crop preview generation. Always call on the original asset file, never on preview or working-copy TIFFs.

**Bit-depth helpers:**
- `is_jpeg(path)` — detects JPEG by magic bytes (`FF D8`)
- `get_bit_depth(path)` — returns 16 for `I;16` family, 8 for `L`/`RGB`/`RGBA`/`P`/`1`, 0 for unknown

**8-bit pipeline rules:**
- Original asset is never converted — `import_asset()` copies bytes as-is
- Internal processing uses uint16 throughout; 8-bit values occupy 0–255 range of the uint16 space — no upscaling to 65535
- `levels_white` is set to 255 for 8-bit sources, 65535 for 16-bit, at import time
- JPEG is hard-rejected at all import entry points

**Processing functions (all uint16 in, uint16 out):**
- `apply_levels_uint16` — black/white/gamma/invert in float32, clipped back to uint16
- `rotate_uint16` — Pillow `"I"` mode (int32) rotation, clipped back to uint16
- `crop_uint16` — clamped array slice
- `uint16_to_qimage` — zero-copy wrap as `QImage.Format_Grayscale16`

When saving uint16 TIFFs use `Image.frombuffer("I;16", (w, h), arr.tobytes(), "raw", "I;16", 0, 1)` — `Image.fromarray(arr, mode="I;16")` is deprecated since Pillow 9.1 and will be removed in Pillow 13.

### Crop handles (crop_rect_item.py)

`CropRectItem` implements Inkscape-style resize handles:
- `HANDLE_VISUAL = 8.0` — drawn square size in scene coords
- `HANDLE_HIT = 20.0` — grabbable hit zone (larger, invisible)
- 8 handle zones: 4 corners (resize both axes) + 4 edge midpoints (resize one axis)
- `_handle_rects()` — returns hit-area rects, used by `_pick_handle()`
- `_handle_visual_rects()` — returns visual rects, used by `paint()`
- Cursor changes per zone: diagonal for corners, horizontal/vertical for edges

### Rendering (render.py)

`build_panel_scene(project, workspace_root)` and `build_provenance_scene(project, workspace_root, blot_id, on_crop_commit, on_crop_resize_commit, show_grid)` both return a `QGraphicsScene`. The scene is rebuilt from scratch on every refresh — no incremental update. Callers must call `ensure_blot_crop_preview(blot, panel)` for each blot before calling these functions.

Image loading in render uses `load_image_as_uint16` (permissive) — never `load_image_uint16` — to support 8-bit sources.

`build_panel_scene` only stacks blots where `blot.included_in_final` is `True`. The panel uses a fixed column layout: ladder column (left) → image column → protein label column (right).

`build_provenance_scene` places an interactive `CropRectItem` over the full original image. Moving the rect updates `blot.crop.x/y` and calls `on_crop_commit(blot)`. Resizing updates `panel.crop_template.w/h` (affecting all blots) and calls `on_crop_resize_commit()`.

### UI (pysternblot/ui/)

`MainWindow` is assembled via Python mixins (no Qt multiple inheritance complications — mixins carry no Qt base class):

```
MainWindow(_ProjectIOMixin, _MarkerSetMixin, _OverlayLadderMixin, _ExportMixin, QMainWindow)
```

- **`main_window.py`** — `__init__` builds all tabs and widgets; owns the rendering/refresh pipeline, display controls, and blot navigation; levels sliders adapt their range to the active blot's bit depth via `_active_blot_bit_depth()`; Black and White fields are `QLineEdit` (editable), not `QLabel`; `_sync_controls_from_project()` is called after every import to ensure controls reflect the new blot's actual values and range
- **`project_io_mixin.py`** — project create/open/import, operation logging (`log_operation`); 8-bit/JPEG gating at all three import entry points; project archive manager (`_open_archive_manager`)
- **`marker_set_mixin.py`** — protein ladder preset CRUD
- **`overlay_ladder_mixin.py`** — overlay ladder assignment dialog, protein label controls, `eventFilter` for click-to-assign
- **`export_mixin.py`** — PNG/PDF/SVG/TIFF/integrity report exports; pre-export 8-bit warning via `_has_8bit_blots()`
- **`crop_rect_item.py`** — interactive `QGraphicsItem` for the crop rectangle in the provenance view (see Crop handles section above)
- **`legend_tab.py`** — standalone `QWidget` for legend editing, emits `changed` signal

### Project archiving

Projects have `is_archived: bool = False` in `ProjectMeta` (default `False` — backward compatible). `Workspace.set_project_archived(path, archived)` flips the flag and saves. `refresh_library()` filters out archived projects from the library view. The archive manager dialog shows a two-column active/archived view with arrow buttons to move projects between columns. The right-click context menu on any project includes an **Archive** action.

### Integrity report

`_asset_info()` uses `get_bit_depth()` on the original asset file. For 8-bit assets, a `bit_depth_warning` field is added to the report JSON. The HTML report highlights 8-bit rows in amber.

### Operation logging

Every mutation that should appear in integrity reports must call `self.log_operation(operation, *, target_type, target_id, field, old_value, new_value, ...)`. Old/new values are stored via `_plain_log_value()` which JSON-serializes or falls back to `str()`.

### Project persistence

`workspace.save_project(project)` serialises the full Pydantic model to JSON. `workspace.load_project(path)` deserialises with `Project.model_validate(json.loads(...))`. Migrations for missing optional fields are handled by Pydantic defaults — always add new fields with a default to preserve backward compatibility with existing `project.json` files.

### Phase 6 — NIR Multichannel Fluorescence

**Supported instruments:**
- **Cytiva Typhoon** — two separate single-channel TIFFs with wavelength encoded in the filename; parsed via `parse_typhoon_tag270` in `storage.py`; instrument test files present at `tests/20260507-142651-[IRlong].tif` and `tests/20260507-142651-[IRshort].tif`
- **LI-COR Odyssey** — stub only (`import_nir_blot_odyssey` raises `NotImplementedError`); 2 tests skipped awaiting `tests/licor_odyssey_sample.tif`

**Key difference from ECL:**
- NIR signal is stable and ratiometric — no multiple-exposure audit requirement
- Two independent 16-bit grayscale channels per membrane acquisition (typically 700 nm and 800 nm)
- Both channels share the same physical crop region and the same ladder calibration
- Each channel has its own antibody, protein label, and display settings

**`BlotChannel` model** (in `models.py`):
```
BlotChannel
├── asset_sha256: str
├── channel_index: int            # 0-based
├── wavelength_nm: Optional[int]  # e.g. 700, 800
├── filter_name: Optional[str]    # e.g. "IRshort 720BP20"
├── fluorophore: Optional[str]    # user-editable, e.g. "IRDye 800CW"
├── antibody_name: str
├── protein_label: ProteinLabel
├── display: DisplaySettings
└── crop: Optional[Crop]          # per-channel override; falls back to blot.crop
```

**`Blot` extension:**
- `modality: Literal["ecl", "nir_fluorescence"] = "ecl"` — defaults to ECL for full backward compatibility
- `channels: list[BlotChannel] = []` — empty for ECL blots; each NIR channel is one entry
- `get_channel_crop(channel_index)` / `set_channel_crop(channel_index, crop)` — per-channel crop with blot-level fallback
- `get_display_channel(channel_index)` — returns `(asset_sha256, DisplaySettings)` for ECL or NIR channel

**Storage (`storage.py`):**
- `parse_typhoon_tag270(path)` — standalone function; parses Typhoon TIFF Tag 270 XML for scan metadata (wavelength, filter name, scan date)
- `import_nir_blot_typhoon(paths, ...)` on `Workspace` — imports 1 or 2 Typhoon TIFFs, populates `BlotChannel` entries with instrument metadata
- Per-channel preview cache: `preview_crop_<id>_ch<i>.tif` (one file per channel per blot)

**Image utilities (`image_utils.py`):**
- `detect_tiff_channel_encoding(path) -> Literal["multipage", "rgb_interleaved", "single"]`
- `load_multichannel_tiff(path) -> list[np.ndarray]`

**UI:**
- `NirImportDialog` (`pysternblot/ui/nir_import_dialog.py`) — 1 or 2 channel import; second channel optional; Tag 270 metadata displayed on file selection
- Channel selector radio buttons in Original Image tab Row 2
- Per-channel display dispatch via `_active_display()`; per-channel crop via `get_channel_crop` / `set_channel_crop`
- Rotation (↺ ↻) and flip (⇔ ↕) buttons in Original Image toolbar Row 1; flips are display-time transforms applied after loading from cache — the cache always stores the un-flipped cropped image

**Rendering:**
- NIR blots render as per-channel greyscale rows in `build_panel_scene`; ladder column appears on the first channel row only
- ECL rendering path unchanged; `build_panel_scene` dispatches by `blot.modality`
- No false-colour composite in the final figure (greyscale per channel only); false-colour composite available in the Original Image tab preview for orientation

**Instrument test files:**
- `tests/20260507-142651-[IRlong].tif` and `tests/20260507-142651-[IRshort].tif` — Typhoon channel files (present)
- `tests/licor_odyssey_sample.tif` — awaited; 2 tests skipped until available
