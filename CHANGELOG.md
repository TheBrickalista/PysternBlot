# Changelog

All notable changes to PysternBlot are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [1.2.0] — 2026-09-07

This release collects five stages of provenance and security work: a hash-chained operation
log, `.pbarchive` manifest binding, byte-exact source export, full-scale clipping detection, and
resource limits on untrusted archive input.

### Added
- **Hash-chained operation log** — every operation-log entry now carries `prev_hash` and
  `entry_hash`, binding it to the one before it (`pysternblot/logchain.py`). All five append
  sites (`log_operation()`, `set_project_archived()`, `rename_project()`, NIR channel import,
  archive import) route through a single `append_log_entry()` helper, so no entry can be added
  outside the chain. Verification reports one of four states — `ok`, `not_chained`, `partial`
  (a pre-chain log that starts being chained partway through), or `broken` (with the index of
  the first inconsistency) — surfaced as a line in the integrity report next to the operation
  log.
- **Archive integrity verification** — a `.pbarchive`'s manifest now records the SHA-256 of each
  project's serialised `project.json` (`format_version` 2), computed and written from the exact
  same bytes so the hash can never describe content that was never actually written. On import,
  each `project.json` is hashed before parsing and before the `imported_from_archive` entry is
  appended, so the recorded hash always describes the archive's contents, not the imported
  result. A mismatch skips that project and is reported; nothing is written for it.
- **Byte-exact source file export** — "Export Source File" / "Export All Source Files" copy the
  stored source asset with `shutil.copyfile`, untouched by any image library, then re-hash the
  written copy and compare it against the asset's stored SHA-256 before reporting success. A
  failed verification deletes the written file and reports the failure rather than leaving a
  silently corrupted copy on disk. This sits alongside the existing annotated-context export as
  a third, more literal level: source file, annotated context, published panel.
- **Clipping (saturation) detection** — every imported asset is assessed for pixels at full
  scale (255 for 8-bit, 65535 for 16-bit) on the source array, before any display transform.
  A 3×3 binary erosion of the saturation mask distinguishes a solid, coherent saturated region
  (a genuine acquisition problem) from isolated hot pixels or dust (harmless and common), so the
  flag does not become noise that trains users to ignore it. The integrity report shows both the
  whole-image result (a fixed fact about the acquisition, recorded at import) and the
  current crop-region result (recomputed live, since it changes as the figure is re-cropped).
- **Resource limits on untrusted archive input** — `import_archive()` now bounds per-member
  uncompressed size, total uncompressed size across the archive, member count, and (for binary
  assets only) compression ratio, and caps the manifest's own size. The update checker caps the
  GitHub API response it reads. Both size checks — the declared header and the actual streamed
  bytes — are enforced independently, since the declared size is attacker-controlled and can
  understate the real payload.

### Fixed
- **Annotated-context TIFF export on Linux.** PySide6 6.11.1's Qt TIFF plugin linked against
  the system `libtiff.so.5`, which current distributions (Ubuntu 24.04 and later) no longer
  ship, only the incompatible `libtiff.so.6`. On a clean Linux install this made "Export
  Annotated Context TIFF" fail with an unexplained `Could not save TIFF` — silently, since
  every other Qt image-format plugin loaded normally and PNG (used by the byte-exact source
  export) is compiled into QtGui rather than being a plugin. The minimum PySide6 version is
  now **6.11.2**, whose TIFF plugin no longer depends on a system `libtiff` at all. If the
  plugin still fails to load for any other reason, the error now names the cause and the
  remedy instead of a bare failure message.

### Changed
- **"Export Original TIFF" / "Export All Originals"** renamed to **"Export Annotated Context
  TIFF"** / **"Export All Annotated Context"**, with tooltips clarifying that these apply the
  current display settings and burn in the crop rectangle and MW markers — they were never the
  unmodified source, and the old names implied otherwise.
- **Integrity report schema** bumped to `pysternblot.integrity_report.v2` and
  `pysternblot.detailed_integrity_report.v2` — both reports gain a top-level
  `operation_log_chain` field; the blot provenance table gains a Saturation column alongside the
  existing bit-depth and gamma warning columns.
- **`.pbarchive` archives are now written at `format_version` 2.** Version 1 archives remain
  fully readable — see Compatibility below.
- **Compression-ratio check restricted to binary assets.** `manifest.json` and `project.json`
  are exempt: measured against real data, a Typhoon TIFF compresses at roughly 1.7:1 while a
  realistic, log-heavy `project.json` can reach several hundred to one on repeated field names,
  timestamps, and hashes — a ratio heuristic tuned for image data would reject a legitimate,
  merely long-running project for no security benefit, since the absolute size caps already
  bound every member.

### Security
- **Archive member path validation and workspace containment.** Every `.pbarchive` member name
  is checked before being dispatched by prefix — no leading `/`, no backslash, no `.`/`..` path
  component — and every path component (asset SHA-256, project id, filename) is restricted to
  `[A-Za-z0-9._-]`. Destination paths are additionally resolved and checked against the
  workspace root as defence in depth. A rejected member is never written and is recorded in
  `integrity_errors`.
- **Project id / archive path agreement.** A project whose `project.json` declares an id
  different from the (already-validated) directory it was stored under in the archive is
  rejected. `save_project()` derives its write location from the JSON payload's own declared
  id, not from the archive path, so without this check a safely-named archive member could
  still smuggle a traversal id through the JSON content itself.
- **Decompression, member-count, and compression-ratio limits** on archive import (see Added
  above), plus a **response size cap** on the update checker and **identifier sanitisation** for
  the preview-cache filenames derived from `blot.id` and channel index — a malformed id falls
  back to a SHA-256-derived name rather than making an otherwise valid project unopenable.
- **The operation log is tamper-evident, not tamper-proof.** The hash chain detects accidental
  corruption, a dropped or reordered entry, or an edit made without recomputing the downstream
  chain. It does not, and cannot, stop someone with access to the source from editing an entry
  and regenerating a consistent chain from that point forward. Treat it as making silent,
  unintentional divergence visible — not as a cryptographic guarantee against a deliberate,
  competent forgery.

### Compatibility
Projects and archives created by earlier versions remain fully readable under 1.2.0, and none of
the checks above are retroactive accusations of tampering:
- An operation log written before this release has no `entry_hash` on any entry. It is reported
  as **`not_chained`**, never as `broken` — that status exists specifically so a pre-chain
  history is not misread as evidence of corruption.
- A **`format_version` 1** archive imports normally, without project-level hash verification
  (`project_integrity_verified` is `False` rather than an error). Asset-level SHA-256 checking,
  present since 1.0.x, is unchanged.
- An asset imported before this release has no recorded saturation assessment. It is reported as
  **"not assessed,"** never as "clean" — the distinction matters because a genuinely clean
  assessment and the absence of one look identical unless the report says which it is.

### Provenance
- Operation vocabulary extended from 35 to 37 verbs. New: `source_asset_exported`,
  `saturation_assessed`.

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
