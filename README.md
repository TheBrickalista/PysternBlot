# Pystern Blot

**Assemble publication-ready Western blot figures — with scientific integrity built in.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## What it is

Western blot figures typically go through Photoshop for levels adjustments, then Illustrator for layout and annotation — a multi-step process with no record of what was changed or when. Pystern Blot replaces that pipeline with a single desktop application that handles everything from raw image import to final figure export.

All processing stays in 16-bit throughout, so no dynamic range is lost when you adjust contrast. Every crop, rotation, and levels change is logged with SHA256 checksums of the original files, giving you a complete provenance record you can attach to a submission.

---

## Key features

- **True 16-bit pipeline** — images never get silently downsampled to 8-bit at any step
- **Shared crop template** — all blots in a panel are cropped to the same size; resize once and all blots follow
- **Levels, gamma, and invert controls** — non-destructive adjustments applied per blot, stored in the project file
- **Overlay protein ladder** — assign kDa values to band positions by clicking; ticks and labels appear automatically in the final figure
- **Include / exclude per blot** — import multiple exposures and choose which one goes into the final figure without deleting the others
- **Integrity report** — one-click export of a JSON or HTML report with SHA256 hashes, operation log, and crop/rotation metadata for every blot
- **Export to SVG, PDF, and PNG** — SVG and PDF preserve text as editable objects for final tweaks in Illustrator or Affinity Designer

---

## Screenshots

<!-- Add screenshots here -->

---

## Requirements

- Python ≥ 3.10
- [PySide6](https://pypi.org/project/PySide6/) ≥ 6.6
- [Pydantic](https://pypi.org/project/pydantic/) ≥ 2.6
- [NumPy](https://pypi.org/project/numpy/) ≥ 1.24
- [scikit-image](https://pypi.org/project/scikit-image/) ≥ 0.21 (pulls in Pillow automatically)

---

## Installation

```bash
git clone https://github.com/your-username/PysternBlot.git
cd PysternBlot

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e .

python -m pysternblot
```

The workspace is stored at `~/.pysternblot/` — projects, assets, and ladder presets all live there.

---

## Project structure

```
pysternblot/
├── models.py          — Pydantic data model (Project, Panel, Blot, CropTemplate, …)
├── storage.py         — Workspace I/O: asset import, project save/load, crop preview cache
├── render.py          — QGraphicsScene builders for the final figure and provenance view
├── image_utils.py     — 16-bit image pipeline (load, levels, rotate, crop, save)
├── integrity.py       — SHA256 provenance and integrity report generation
└── ui/
    ├── main_window.py          — Main window, tab layout, display controls
    ├── project_io_mixin.py     — Project create/open/import
    ├── marker_set_mixin.py     — Protein ladder preset editor
    ├── overlay_ladder_mixin.py — Ladder assignment and kDa annotation
    ├── export_mixin.py         — PNG/PDF/SVG/TIFF/integrity report export
    ├── legend_tab.py           — Legend editor tab
    └── crop_rect_item.py       — Interactive crop rectangle (move + resize)
tests/                 — pytest test suite
```

---

## Roadmap

Pystern Blot is under active development. Planned work includes a structured scene composition model, high-fidelity 16-bit TIFF export, and further annotation improvements. See [pysternblot/Roadmap.md](pysternblot/Roadmap.md) for the full plan.

---

## License

Pystern Blot is released under the [GNU General Public License v3.0](LICENSE).
