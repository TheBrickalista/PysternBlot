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

## Phase 1 — UI Cleanup & Workflow Reorganization

**Goals**
- Improve usability
- Align with PyMicRheo style
- Clarify workflow structure

**Tasks**

- [ ] Redesign Home tab:
  - App name
  - Description
  - Copyright
  - License
  - Version / repository (optional)
- [ ] Rename tabs to better reflect workflow
- [ ] Move outline/cropping tools to Final Result tab
- [ ] Harmonize font size behavior across:
  - Protein names
  - Legend tab

**Outcome**

Cleaner, more intuitive UI with minimal risk to core functionality.

---

## Phase 2 — Project Model Extension

**Goals**
- Prepare data model for future features
- Add flexibility to blot handling

### 2.1 Hidden / Non-displayed Blots

- [ ] Add flag per blot: `included_in_final = true/false`
- [ ] Blots remain stored in project, editable, and toggleable for inclusion

### 2.2 Left-side Annotation Field

- [ ] Add optional text field per blot, positioned left of blot, vertically centered
- [ ] Must be future-compatible with ladder system

### 2.3 Extended Metadata Fields *(new)*

The following fields should be added to the blot data model to enable complete experimental documentation — the digital equivalent of writing on the film:

**Reagent fields:**
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

## Phase 6 — Multichannel Fluorescence Support *(new)*

NIR fluorescence platforms (LI-COR Odyssey, Azure 600, Bio-Rad ChemiDoc MP) produce multichannel images. This phase extends Pystern Blot to handle them correctly.

**Depends on:** Phase 2.3 detection modality field

### 6.1 Multichannel Image Loading

- [ ] Correctly read and separate channels from multichannel TIFF files (LI-COR, Azure, Bio-Rad formats)
- [ ] Per-channel metadata: each channel carries its own antibody, target, dilution, and modality

### 6.2 Channel Merge Documentation

- [ ] Record false-colour assignment and relative scaling in audit log when channels are merged for display

### 6.3 Per-channel Crop and Annotation

- [ ] Support channel-specific MW marker positions (images may not be perfectly co-registered)

**Outcome**

Full support for the most common fluorescence-based WB platforms alongside existing ECL workflow.

---

## Phase 7 — Data Management and Archival *(new)*

Addresses the recovery of existing image libraries and long-term data availability requirements from journals and funders.

### 7.1 Batch Import of Existing Libraries

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
| **Batch 1 — UI** | Home tab, tab renaming, move outline tools, font harmonization | 1 |
| **Batch 2 — Data Model** | Hidden blots, left annotation field, extended metadata fields | 2 |
| **Batch 5 — Composition** | Structured scene model, left-side layout zone | 3 |
| **Batch 6 — Multichannel** | NIR/multichannel image support | 6 |
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
