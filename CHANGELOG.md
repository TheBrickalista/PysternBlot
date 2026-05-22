# Changelog

All notable changes to PysternBlot are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [1.0.3] — 2026-05-21

### Added
- **8-bit TIFF support** — legacy 8-bit images (grayscale, palette `P`,
  and RGB modes) are now accepted at all import entry points. A mandatory
  acknowledgement dialog fires on import. Bit depth is recorded in the
  integrity report (with amber highlighting in HTML) and flagged at export.
  `levels_white` is automatically set to 255 for 8-bit sources.
- **JPEG rejection** — JPEG files are hard-rejected at import with a
  scientific explanation (lossy compression, DCT artefacts, unquantifiable
  prior processing). File filter updated to exclude .jpg/.jpeg.
- **`load_image_as_uint16()`** — permissive image loader in `image_utils.py`
  accepting 16-bit and 8-bit sources (L, P, RGB, RGBA modes). The strict
  `load_image_uint16()` is unchanged.
- **`is_jpeg()` and `get_bit_depth()`** helper functions in `image_utils.py`.
- **Inkscape-style crop handles** — `CropRectItem` now has separate visual
  (8 px) and hit (20 px) zones. 4 corner handles resize both axes; 4 edge
  handles resize one axis. Cursor changes per zone.
- **Project archiving** — projects can be soft-hidden from the library
  without deletion. `ProjectMeta.is_archived` flag (default `False`,
  backward compatible). Archive manager dialog (two-column active/archived
  view). Right-click Archive action on library rows.
  `Workspace.set_project_archived()` method.
- **Editable levels fields** — Black and White value fields are now
  `QLineEdit` (type a value and press Enter/Tab). Dynamic range adapts to
  source bit depth: 0–255 for 8-bit, 0–65535 for 16-bit.
- **`Pillow>=10.0`** added as explicit dependency in `pyproject.toml`
  (was previously an undeclared transitive dependency).

### Fixed
- Version string in Home tab title and About tab now read dynamically from
  installed package metadata via `importlib.metadata`, eliminating stale
  hardcoded version strings.
- `create_new_project()` default `app_version` parameter updated from the
  stale `"0.1.0"` to the current `__version__` at runtime.
- Levels slider range and edit field validator now update correctly
  immediately after importing a new blot, not only when switching blots.

### Tests
- Added `tests/test_8bit_import.py` (17 tests covering JPEG detection,
  bit-depth detection, palette/RGB mode loading, levels range, integrity
  report flagging)
- Added `tests/test_crop_rect_item.py` (12 test functions, 36 parametrized
  cases covering hit tolerance, MOVE/NONE zones, resize math)
- Total: 210 tests pass, 2 skipped (LI-COR Odyssey pending sample file)

---

## [1.0.2] — 2026-05-12

### Added
- NIR fluorescence support (Cytiva Typhoon dual-channel import)
- Per-channel display, crop, and annotation for NIR blots
- Show 685 / Show 785 per-band checkboxes in marker set presets
- Library archive export/import (`.pbarchive` format)
- Integrity report HTML export with SHA-256 provenance

---

## [1.0.1] — 2026-04-xx

### Added
- Initial public release
- ECL western blot figure assembly
- 16-bit TIFF pipeline
- Protein ladder overlay with kDa annotation
- PNG, PDF, SVG, TIFF export
- Operation log and integrity report
