# Pystern Blot — Development Roadmap

This roadmap defines the implementation strategy for improving the application in a structured and scalable way. The goal is to:

- Clean up UI and workflow
- Extend the project model
- Build a robust figure composition system
- Implement high-quality export (raster + editable)
- Add advanced annotation features (protein ladder system)
- Extend metadata and provenance documentation
- Support data management and long-term archival

The roadmap is organized from simplest to most complex tasks to minimize instability and rework.

---

## ✅ Phase 4 — Export System *(Completed)*

Both export pipelines are implemented:

- **4.1 Raster Export** — 16-bit TIFF and PNG, fully flattened, preserving dynamic range
- **4.2 Editable Export** — SVG (priority), PDF, and EPS; each blot as an independent raster object, text and shapes as editable vector objects

---

## ✅ Phase 5 — Protein Ladder System *(Completed)*

Full ladder annotation workflow is integrated:

- Ladder preset management (name, MW values, edit/delete/reorder)
- Ladder assignment per blot
- Click-to-place overlay marker positioning, stored as image coordinate → MW value mapping
- Final figure display with ticks and labels; user controls marker visibility

---

## ✅ UI Fixes *(Completed this session)*

Two correctness fixes to the Original Image tab UI:

- **Window resize regression** — main window was not resizable despite resize handles appearing on hover; fixed by setting an explicit `minimumSize(900, 600)` before `resize()` so the layout's computed `minimumSizeHint` cannot lock the window after `show()`
- **Original Image toolbar split into two rows** — single-row toolbar was overflowing (causing the resize regression); navigation and image controls are now on row 1, metadata and annotation fields (Protein, Antibody, Size, Include in final) on row 2

---

## ✅ Phase 1 — UI Cleanup *(Completed)*

- [x] ✅ Home tab redesigned: app name + version, description, copyright, GPLv3 mention, About/License button, scrollable layout
- [x] ✅ About tab added with Legal/Copyright/Repository placeholder buttons
- [x] ✅ Original Image toolbar split into two rows (navigation row + metadata row)
- [x] ✅ Window resize regression fixed

---

## Phase 2 — Project Model Extension

**Goals**
- Prepare data model for future features
- Add flexibility to blot handling

### ✅ 2.1 Hidden / Non-displayed Blots *(Completed)*

- [x] ✅ `included_in_final` flag per blot — model field, UI checkbox in Original Image tab Row 2, audit logging, project persistence
- [x] ✅ Blots remain stored in project, fully editable, toggleable; blot selector shows ⊘ prefix for excluded blots

### 2.2 Left-side Annotation Field

- [ ] Add optional text field per blot, positioned left of blot, vertically centered
- [ ] Must be future-compatible with ladder system

### 2.3 Extended Metadata Fields *(new)*

The following fields should be added to the blot data model to enable complete experimental documentation — the digital equivalent of writing on the film:

**Reagent fields:**
- [x] ✅ Antibody name per blot (writable dropdown combobox in Original Image tab, persisted in project file, logged in audit trail, suggestion history, not rendered in figure)
- [ ] Antibody catalogue number and supplier
- [ ] Antibody lot number
- [ ] Primary antibody dilution and diluent (e.g. 1:1000 in 5% BSA/TBST)
- [ ] Secondary antibody identity, dilution, and conjugate (e.g. HRP anti-rabbit 1:5000)
- [ ] Blocking conditions (blocker type, concentration, duration)
- [ ] Primary and secondary incubation conditions (duration, temperature, buffer)

**Detection fields:**
- [ ] Detection modality: ECL / NIR fluorescence / visible fluorescence
  - ECL: greyscale, time-dependent signal; audit log should record all available exposures and selection rationale
  - NIR (e.g. LI-COR Odyssey, Azure 600): multichannel, stable ratiometric signal — multichannel handling is a Phase 6 item
  - Modality field should trigger modality-specific validation warnings (e.g. warn if ECL image has no alternative exposures recorded)

**Experimental context fields:**
- [ ] Cell line / organism / tissue / passage number
- [ ] Treatment and time point
- [ ] Experiment identifier
- [ ] Protocol reference (DOI, ELN URL, or internal protocol code)
- [ ] Free-text protocol notes (deviations, troubleshooting)
- [ ] Gel percentage and running conditions (buffer, voltage/time)
- [ ] Transfer conditions (wet/semi-dry/dry, membrane type PVDF/nitrocellulose)
- [ ] Membrane stripping and re-probing history (previous antibodies, stripping conditions)

**Outcome**

Blots become richer project objects with full experimental provenance. All fields stored in project file, embedded in exported TIFF metadata, and included in the audit report.

---

## Phase 3 — Final Figure Composition Architecture

**Goals**
- Move from simple rendering to structured composition
- Prepare for export system

### 3.1 Structured Scene Model

- [ ] Final figure composed of independent elements:
  - Image objects (blots)
  - Text objects
  - Lines
  - Rectangles / frames

### 3.2 Left-side Layout Zone

- [ ] Define dedicated area per blot for side annotation text and future MW ladder labels
- [ ] Avoid overlap between annotation and ladder
- [ ] Allow spacing and alignment control

**Outcome**

A robust internal representation of the figure enabling clean export and future compositing features.

---

## Phase 6 — Multichannel Fluorescence Support *(Substantially Complete)*

NIR fluorescence platforms (LI-COR Odyssey, Cytiva Typhoon) produce multichannel images. This phase extends Pystern Blot to handle them correctly.

### 6.1 Multichannel Image Loading

- [x] ✅ `detect_tiff_channel_encoding` and `load_multichannel_tiff` implemented in `image_utils.py`
- [x] ✅ `parse_typhoon_tag270` — standalone Tag 270 XML parser for Typhoon wavelength/filter metadata (`storage.py`)
- [x] ✅ `import_nir_blot_typhoon` on `Workspace` — imports 1 or 2 Typhoon TIFFs, populates `BlotChannel` entries with instrument metadata
- [x] ✅ `BlotChannel` model and `Blot` extension (`modality`, `channels`) in `models.py`; backward compatible with existing ECL projects
- [ ] LI-COR Odyssey import — stub exists (`import_nir_blot_odyssey` raises `NotImplementedError`); awaiting `tests/licor_odyssey_sample.tif`

### 6.2 Channel Merge Documentation

*Not applicable.* Final figures use greyscale-only per-channel rendering (Option A decision); no false-colour composite is produced in the final figure. False-colour composite is available in the Original Image tab preview only, for orientation. Audit log entry for false-colour merge is not applicable.

### 6.3 Per-channel Crop, Display, and Annotation

- [x] ✅ `NirImportDialog` — 1 or 2 channel import UI; second channel optional; Tag 270 metadata displayed on file selection
- [x] ✅ Channel selector radio buttons in Original Image tab Row 2
- [x] ✅ Per-channel display settings dispatched via `_active_display()`
- [x] ✅ Per-channel crop via `get_channel_crop` / `set_channel_crop`; falls back to `blot.crop`
- [x] ✅ Per-channel preview cache (`preview_crop_<id>_ch<i>.tif`)
- [x] ✅ NIR blots render as per-channel greyscale rows in `build_panel_scene`; ladder bands respect per-channel wavelength tags
- [x] ✅ `MarkerBand.channels: list[int]` — per-band channel restriction field; backward compatible (default `[]` = show on all channels)
- [x] ✅ `_band_visible_on_channel` in `render.py` — gates band rendering by channel wavelength
- [x] ✅ `_ladder_row_for_blot` — determines which channel row the ladder column renders on based on band wavelength tags
- [x] ✅ Bands with `channels == []` render on all NIR channel rows; explicit channel tags render only on the matching wavelength row
- [x] ✅ Show 685 / Show 785 checkboxes in marker set preset table (replaces free-text Channels column)
- [x] ✅ `test_render_ladder.py` — test suite for `_band_visible_on_channel` and `_ladder_row_for_blot`
- [x] ✅ 90° rotation buttons (↺ ↻) in Original Image toolbar Row 1
- [x] ✅ Flip buttons (⇔ ↕) in Original Image toolbar Row 1; display-time transforms, cache stores un-flipped image

**Outcome**

Full support for Cytiva Typhoon alongside existing ECL workflow; LI-COR Odyssey pending instrument file.

---

## Phase 7 — Data Management and Archival *(new)*

Addresses the recovery of existing image libraries and long-term data availability requirements from journals and funders.

### 7.1 Batch Import of Existing Libraries

**Archive export/import:**
- [x] ✅ Export/import library archive (`.pbarchive` format — plain zip): `export_archive` and `import_archive` on `Workspace`; project selection dialog with Select All / Deselect All; SHA256 integrity verification of every asset before any file is written; `imported_from_archive` operation log entry on import; skips projects and assets already present (idempotent); full test coverage (5 tests)

For researchers inheriting a dataset or bringing historical data into compliance:

- [ ] Batch import mode: accept a directory of raw instrument images, generate a metadata record for each, pre-populate fields from available instrument metadata, flag incomplete fields for manual completion
- [ ] Legacy annotation parser: extract metadata from instrument-generated filenames (ChemiDoc, ImageQuant conventions), TIFF metadata tags, and sidecar files
- [ ] Interactive annotation GUI: work through an unannotated library image-by-image, with shared-value application across groups (same antibody, same experiment)
- [ ] Provenance flagging: imported images without a Pystern Blot processing history are marked "legacy data" in reports, with a description of what provenance is and is not available

### 7.2 Repository and ELN Integration

- [ ] Repository export package: structured ZIP (raw image + annotated figure + crop-marked original + audit log + report) formatted for Zenodo, Figshare, or institutional repositories
- [ ] BioImage Archive compatibility: map Pystern Blot metadata fields to BioImage Archive submission schema
- [ ] OME-TIFF output: export annotated images as OME-TIFF with metadata mapped to the OME schema (community standard for bioimaging data)
- [ ] ELN connectors: direct upload to Benchling, LabArchives, Labguru; auto-populate experiment record fields from Pystern Blot metadata

**Outcome**

Pystern Blot data is findable, accessible, and reusable in compliance with FAIR data principles and emerging journal/funder data availability requirements.

---

## Phase 8 — Manuscript Integration *(new)*

Auto-generation of text components from audit log and metadata.

### 8.1 Methods Text Generation

- [ ] Generate ready-to-paste Methods paragraph from the audit log, covering: acquisition instrument, bit depth, adjustments applied (with parameters), MW marker source and annotation method, export format
- [ ] Configurable for target journal style

### 8.2 Figure Legend Generation

- [ ] Generate figure legend entry for each blot panel from metadata: antibody identity, target, dilution, detection modality
- [ ] Editable by user before insertion into manuscript

**Outcome**

Reduces transcription errors between the metadata record and the published manuscript; ensures consistency between what was done and what is reported.

---

## Implementation Batches

| Batch | Content | Phase(s) |
|-------|---------|----------|
| ~~Batch 4 — Ladder System~~ | ~~Ladder presets, assignment, marker placement, final rendering~~ | ~~5~~ |
| ~~Batch 3 — Rendering & Export~~ | ~~Structured composition, raster export (16-bit), SVG export~~ | ~~4~~ |
| ~~Batch 1 — UI~~ | ~~Home tab redesign, About tab, toolbar split, resize fix~~ | ~~1~~ |
| **Batch 2 — Data Model** | Hidden blots (2.1 ✅), left annotation field, extended metadata fields | 2 |
| **Batch 5 — Composition** | Structured scene model, left-side layout zone | 3 |
| **Batch 6 — Multichannel** | NIR/multichannel image support (per-channel ladder filtering ✅) | 6 |
| **Batch 7 — Archival** | Batch import, repository/ELN integration | 7 |
| **Batch 8 — Manuscript** | Methods and legend auto-generation | 8 |

---

## Key Design Principles

- Separate data model, rendering, and export
- Treat final figure as a scene of objects, not a flat image
- Keep raster and editable exports conceptually distinct
- Design left-side layout early to avoid conflicts with ladder
- Implement complex systems (multichannel, archival) only after foundations are stable
- All new features must generate appropriate audit log entries
- Backward compatibility with existing project files must be maintained

---

## Final Goal

A workflow where the user can:

1. Prepare and annotate blots with full experimental metadata
2. Assemble the final figure inside the app
3. Export:
   - A 16-bit high-quality raster image
   - An editable SVG/PDF for Illustrator/Affinity Designer
   - A structured audit report and provenance package for journal submission
4. Optionally deposit raw data directly to a repository or ELN

Replacing the traditional Photoshop → Illustrator pipeline with a single integrated tool that also satisfies modern data integrity and reproducibility requirements.
