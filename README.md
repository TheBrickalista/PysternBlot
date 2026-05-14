# Pystern Blot

**Assemble publication-ready Western blot figures — with scientific integrity built in.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)]()

---

## What it is

Western blot figures typically go through Photoshop for levels adjustments, then Illustrator for layout and annotation — a multi-step process with no record of what was changed or when. Pystern Blot replaces that pipeline with a single desktop application that handles everything from raw image import to final figure export. Both ECL and NIR fluorescence modalities are supported.

All processing stays in 16-bit throughout, so no dynamic range is lost when you adjust contrast. Every crop, rotation, and levels change is logged with SHA256 checksums of the original files, giving you a complete provenance record you can attach to a submission.

---

## Key features

- **True 16-bit pipeline** — images never get silently downsampled to 8-bit at any step
- **ECL and NIR fluorescence western blot support** — Typhoon dual-channel (685 nm / 785 nm), per-channel display settings, levels, invert, flip, rotation
- **Per-channel greyscale rendering in final figure** — each NIR channel appears as an independent row
- **Per-band wavelength routing for NIR ladders** — Show 685 / Show 785 per band in ladder presets
- **Shared crop template with per-channel independent crop for NIR** — resize once and all blots follow; per-channel override available for NIR
- **Levels, gamma, invert, 90° rotation, horizontal/vertical flip** — all non-destructive, per channel for NIR
- **Overlay protein ladder with per-band wavelength assignment** — Show 685 / Show 785 checkboxes per preset band; ticks and labels appear automatically in the final figure
- **Include / exclude per blot and per NIR channel** — import multiple exposures or channels and choose which appear in the final figure without deleting the others
- **Library archive** — export and import `.pbarchive` files for lab handover and long-term storage, with SHA256 integrity verification of every asset
- **Antibody name field per blot** — persisted in project file and audit log
- **Integrity report** — one-click export of a JSON or HTML report with SHA256 hashes, operation log, and crop/rotation metadata for every blot
- **Export to SVG, PDF, PNG, and 16-bit TIFF** — SVG and PDF preserve text as editable objects for final tweaks in Illustrator or Affinity Designer

---

## Screenshots

<!-- Add screenshots here -->

---

## Requirements

- Python ≥ 3.10
- PySide6 ≥ 6.6
- Pydantic ≥ 2.0
- NumPy
- Pillow
- scikit-image

> **Note:** requirements only apply to the source/PyPI install methods. Standalone ports bundle everything.

---

## Installation

### Option 1 — PyPI

```bash
pip install pysternblot
python -m pysternblot
```

### Option 2 — From source *(all platforms)*

```bash
git clone https://github.com/TheBrickalista/PysternBlot.git
cd PysternBlot
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
pip install -e .
python -m pysternblot
```

### Option 3 — Standalone app *(macOS and Windows)*

No Python required. Download the latest build for your platform directly from the **[Releases page](https://github.com/TheBrickalista/PysternBlot/releases/latest)**.

- **macOS:** download `PysternBlot-vX.X.X-macOS.zip`, unzip and open `PysternBlot.app`
- **Windows:** download `PysternBlot-vX.X.X-Windows.exe` and run it

---

**Workspace location:**
- macOS: `~/.pysternblot/`
- Windows: `C:\Users\<username>\.pysternblot\`

---

## Project structure

```
pysternblot/
├── models.py               — Pydantic data model (Project, Panel, Blot, BlotChannel, …)
├── storage.py              — Workspace I/O, asset import, archive export/import, Typhoon NIR import
├── render.py               — QGraphicsScene builders for final figure and provenance view
├── image_utils.py          — 16-bit image pipeline; multichannel TIFF loading and encoding detection
├── integrity.py            — SHA256 provenance and integrity report generation
└── ui/
    ├── main_window.py          — Main window, tab layout, display controls
    ├── project_io_mixin.py     — Project create/open/import, library archive export/import
    ├── marker_set_mixin.py     — Protein ladder preset editor (Show 685/785 per band)
    ├── overlay_ladder_mixin.py — Ladder assignment and kDa annotation
    ├── export_mixin.py         — PNG/PDF/SVG/TIFF/integrity report export
    ├── nir_import_dialog.py    — NIR blot import dialog (1 or 2 channel Typhoon)
    ├── legend_tab.py           — Legend editor tab
    ├── widgets.py              — Shared UI widgets
    ├── zoomable_graphics_view.py — Zoomable/pannable graphics view
    └── crop_rect_item.py       — Interactive crop rectangle (move + resize)
tests/                      — pytest test suite (130+ tests)
```

---

## Supported instruments

| Instrument | Type | Import |
|---|---|---|
| Any ECL imager (ChemiDoc, ImageQuant, etc.) | Single-channel 16-bit TIFF | Import Blot… |
| Cytiva Typhoon | NIR fluorescence, dual-channel | Import NIR Blot… |
| LI-COR Odyssey | NIR fluorescence, dual-channel | Planned |

---

## Roadmap

Pystern Blot is under active development. Completed phases include the full export system, protein ladder system, NIR fluorescence support, and library archive. Upcoming work includes extended experimental metadata fields, structured figure composition, LI-COR Odyssey support, and repository/ELN integration. See [pysternblot/Roadmap.md](pysternblot/Roadmap.md) for the full plan.

---

## License

Pystern Blot is released under the [GNU General Public License v3.0](LICENSE).
