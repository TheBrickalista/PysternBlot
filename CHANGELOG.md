# Changelog

All notable changes to PysternBlot are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [1.1.0] — 2026-09-02

### Added
- **Legend export zone** — an optional second selection rectangle in the Original Image tab
  (blue, dashed), using the same sizing and handle mechanism as the crop rectangle. It defines
  a region of the original image to export with the panel legend drawn above it, reusing the
  same legend renderer as the Figure tab. Off by default each session; once drawn, the zone's
  geometry, marker visibility, and marker side are saved per blot. A new
  "Export Zone + Legend" action writes a 2x-scale PNG. The legend aligns to the figure crop
  box rather than the drawn zone, so captions land on the correct lanes regardless of how the
  zone is sized; the exported region is automatically expanded to always contain the full crop
  box.
- **MW markers on the legend-zone export** — molecular-weight ticks and labels are drawn on the
  exported zone, reusing the blot's existing overlay-ladder assignments and calibration. Every
  assigned band is drawn regardless of the figure's own curation (`show_in_final` and
  "only highlighted" are not applied to this export), with a per-zone left/right side toggle.
  NIR per-channel band filtering still applies, since a band tagged to another channel is not
  calibrated for the displayed image.
- **Resizable Original Image tab** — a draggable splitter between the control area and the
  image canvas.
- **Collapsible Display section** — the Display frame in the Original Image tab folds to a
  header, freeing vertical space for the canvas.
- **CI archive verification step** — unpacks the finished macOS archive and fails the build if
  symbolic links were lost or if `codesign` reports an ambiguous bundle format.

### Fixed
- **macOS application bundle corruption during CI packaging** — the archiving step used `zip`,
  which dereferences symbolic links and flattened the bundled Qt framework structures, causing
  macOS Gatekeeper to reject the application at launch despite it being correctly signed,
  notarized and stapled. The archive is now created with `ditto`, which preserves symbolic links.

### Changed
- **Original Image tab layout** — controls reorganised into three themed rows (blot identity and
  channel selector; export controls; image transforms and blot metadata) separated by vertical
  dividers, resolving button clipping at default window widths. The pan/zoom hint moved from the
  toolbar to a canvas tooltip.
- **Home tab "Open Project"** now switches to the Library tab instead of opening a file dialog.
  The toolbar's "Open Project…" action still opens the dialog, which remains the way to open
  projects stored outside the workspace or projects that have been archived.
- **macOS download size** — reduced from approximately 200 MB to approximately 50 MB, as a
  consequence of the archiving fix (the previous method stored every framework binary twice).

### Provenance
- Operation vocabulary extended from 28 to 31 verbs. New: `legend_zone_changed`,
  `legend_zone_markers_changed`, `legend_zone_side_changed`. Consumers of `.pbarchive`
  operation logs should be aware of the additions.
- `legend_zone_changed` records the zone geometry (`x`, `y`, `w`, `h`) in `new_value`.

### Compatibility
- `Blot.legend_zone` is a new optional field. Existing `project.json` files load unchanged.
  Projects saved by 1.1.0 remain loadable by 1.0.x, which ignores the unknown field — but note
  that re-saving such a project under 1.0.x will discard the legend zone.

## [1.0.4] — 2026-06-03

### Added
- **Asymmetric legend grouping** — legend cells can be grouped via per-cell group numbers;
  contiguous same-group cells (≥ 2) draw an underline with the group label centred over
  the span. Supports mixed group sizes and ungrouped singletons. Replaces the old
  all-or-nothing per-row underline flag.
- **Levels histogram** — live pixel-intensity histogram in the Original Image tab alongside
  the levels sliders, with log/linear scale toggle, adaptive x-axis zoom to the gate
  window, draggable gate lines linked to the sliders, and 1024 bins. Sliders relabeled
  "Min"/"Max" (from "Black"/"White") for correctness under inversion.
- **Gamma integrity flag** — non-default gamma is flagged in the integrity report
  (per-blot and per-NIR-channel) and shown as a live amber badge in the UI, with a
  note that gamma adjustment must be disclosed per journal image-integrity guidelines
  (Nature, JCB).
- **Blot display name** — blots can be given a cosmetic display label; the original
  filename is preserved in the integrity report and tooltip. Rename is logged as an
  operation.
- **Typhoon `.inf` sidecar capture** — on NIR Typhoon import, the sibling `.inf` sidecar
  is parsed and key acquisition fields (scale type, scan mode, PMT/laser settings,
  corrections) are stored per-asset and surfaced in the integrity report (scale type
  shown prominently).
- **Saved-dropdown-entries manager** — Preferences tab includes a manager to delete,
  rename, and reorder entries in the legend / protein-label / antibody-name autocomplete
  histories.
- **Library tab** — the project list moved from Preferences into its own "Library" tab
  (immediately after Home). Tab order reworked to
  Home → Library → Figure → Original Image → Legend → Preferences → About.
- **PyPI metadata** — `pyproject.toml` now includes `authors`, `keywords`, `classifiers`,
  and `[project.urls]` for a complete PyPI page.

### Fixed
- **Windows ellipsis truncation** — legend and blot dropdown popups no longer truncate
  long filenames with an ellipsis on Windows.

### Removed
- **`scikit-image` dependency** — declared in `pyproject.toml` but never imported; removed.
- **Per-row "Underline" checkbox** — dead checkbox removed from the legend row editor;
  rendering is now driven entirely by `cell_groups`. `LegendRow.underline` is retained
  in the model for backward compatibility with existing `project.json` files.

### Documentation
- Added `CONTRIBUTING.md` and `docs/ARCHITECTURE.md`.
- `Roadmap.md` moved from the package directory to the repository root (no longer
  shipped in the wheel).
- Legacy `HeaderBlock`, `Group`, `ConditionRow`, and `SpanRow` structures documented
  as retained-for-compat in `models.py`.

### Internal
- Dead imports (`load_image_uint16`, duplicate `QFrame`, duplicate `typing` import)
  and unused locals (`protein_w`, `crop_h_scene`) cleaned up.

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
