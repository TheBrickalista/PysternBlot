# Quick Start — Pystern Blot

This guide walks you through installing Pystern Blot and preparing your first publication-ready Western blot figure, from raw image import to integrity-verified export.

> **Try it immediately — no image required.**
> A fully annotated example project is included in [`examples/tutorial_example.pbarchive`](examples/tutorial_example.pbarchive).
> Once Pystern Blot is installed, click **Import Library…** in the toolbar to open it and explore a pre-annotated dual-channel NIR blot without needing your own image.
>
> Raw example TIFFs are also available in `examples/` if you want to follow this guide step by step from scratch.

---

## Requirements

- macOS or Windows
- 16-bit TIFF images from your Western blot acquisition system (ECL or NIR/Typhoon) — or use the example files above

---

## 1. Installation

### Standalone app — no Python required (recommended)

Download the latest release for your platform from the [Releases page](https://github.com/TheBrickalista/PysternBlot/releases):

- **macOS** — download `PysternBlot-macOS.zip`, unzip, and move `PysternBlot.app` to your Applications folder.
- **Windows** — download `PysternBlot-Windows.zip`, unzip, and run `PysternBlot.exe`.

> **macOS — first launch warning:** Because the app is not yet notarized, macOS Gatekeeper will block it on first open. To bypass: right-click (or Control-click) `PysternBlot.app` → **Open** → **Open** in the confirmation dialog. You only need to do this once.

> **Windows — first launch warning:** Windows SmartScreen may show an "Unknown publisher" warning. Click **More info** → **Run anyway** to proceed. You only need to do this once.

### For Python users

If you already have Python 3.10 or later installed:

```bash
pip install pysternblot
pysternblot
```

Or from source:

```bash
git clone https://github.com/TheBrickalista/PysternBlot.git
cd PysternBlot
pip install -e .
pysternblot
```

---

## 2. Create a new project

On launch you will see the **Home** tab.

1. Click **New Project…** in the toolbar.
2. Enter a name for your project when prompted.
3. Pystern Blot creates a project folder containing your source image store, operation log, and integrity reports.

> **What is a project?** A project corresponds to one final figure — it can contain as many blot images as needed to assemble that figure, regardless of whether they come from different membranes, stripping/reprobing cycles, or different acquisition systems.

---

## 3. Import your blot image

### ECL (chemiluminescence)

1. Click **Import Blot…** in the toolbar.
2. Select your 16-bit TIFF acquisition (e.g. from Cytiva ImageQuant TL or Bio-Rad Image Lab).
3. Pystern Blot computes a **SHA-256 hash** of the file on import and records it in the operation log. The source file is never modified.

### NIR fluorescence (Cytiva Typhoon) — used in the example

1. Click **Import NIR Blot…** in the toolbar.
2. The **Import NIR Blot** dialog opens with two slots:
   - **Channel 1 (required)** — click **Browse…** and select `Example[IRshort].tif`
   - **Channel 2 (optional)** — click **Browse…** and select `Example[IRlong].tif`
3. Pystern Blot reads the acquisition metadata from **TIFF Tag 270** automatically (wavelength, filter). The parsed channel info is displayed immediately below each file path.
4. Click **Import** to confirm.

Both channels are registered as separate assets with individual SHA-256 hashes and added to the project as a single dual-channel blot.

---

## 4. Adjust image display

The **Display** panel at the top of the window controls how the image is rendered on screen. All adjustments run in **16-bit** — no pixel data is lost regardless of how aggressively you set the levels.

| Control | What it does |
|---|---|
| **Black** | Sets the minimum display threshold |
| **White** | Sets the maximum display threshold |
| **Gamma** | Adjusts midtone contrast |
| **Invert** | Inverts the image (useful for dark-background ECL acquisitions) |
| **↺ / ↻** | Rotates 90° counter-clockwise / clockwise |
| **⇔** | Flips horizontal (mirror left-right) |
| **↕** | Flips vertical (mirror top-bottom) |

> **Important:** These controls affect display only. The source image is never modified. The original 16-bit data is always preserved.

> **Overlay (ECL + membrane only):** The **Overlay** checkbox and **Alpha** slider are available for Cytiva ImageQuant acquisitions where the ECL signal and the membrane image were acquired simultaneously in separate channels. This lets you visualise both channels superimposed while annotating.

---

## 5. Define your crop region

In the **Original Image** tab:

1. Drag on the canvas to draw a crop rectangle around the region you want in your figure.
2. The crop handles can be adjusted at any time — the operation is non-destructive.
3. The **same crop box size is applied across all blots** in the project, ensuring consistent panel dimensions in the final figure.
4. Crop coordinates (pixels, relative to the original image) are recorded in the operation log automatically.

---

## 6. Annotate bands and molecular weight markers

### Set up the protein ladder

1. Go to the **Preferences** tab.
2. Under **Protein ladder presets**, select an existing preset or click **New** to create one.
3. Use **Add band** to add each marker weight (kDa), then click **Save**.

### Annotate the blot

Back in the **Original Image** tab:

1. Under **Overlay ladder**, select your ladder preset from the dropdown.
2. The ladder bands are overlaid on the canvas — drag each marker line to the correct position on your ladder lane.
3. In the **Protein** and **Antibody** fields, enter the target protein name and antibody used.
4. Use the **Include in final figure** checkbox to control whether this blot appears in the exported figure.

---

## 7. Build the figure legend

Go to the **Legend** tab to compose the text legend that will appear with your figure.

- **Mode** — set to **Protein** for Western blot figures.
- **# Upper rows** — number of legend rows to display above the figure panels.
- **# Lower rows** — number of legend rows to display below the figure panels.

Each row has three editable zones:

| Zone | Use |
|---|---|
| **Left** | Typically the panel label (e.g. *A*, *B*) or antibody name |
| **Center cells** | Per-lane annotations — set **# cells** to match your lane count, one cell per lane |
| **Right** | Any trailing annotation (e.g. molecular weight, condition) |

Per row you can also set **Font** size (pt) and toggle **Underline** for header rows.

All text fields have autocomplete from previously entered values across the project, so antibody names and condition labels only need to be typed once.

---

## 8. Compose the final figure

Go to the **Figure** tab:

1. Your blot panels appear in the layout in the order they were imported.
2. Use the **Up** / **Down** buttons to reorder panels.
3. Set figure width, label font size, and inter-panel spacing as needed.
4. Click **Refresh** to update the figure preview.

---

## 9. Export

All export buttons are in the **Figure** tab.

### Publication figure

| Button | Output |
|---|---|
| **Export PNG** | Raster image — for presentations or preprints |
| **Export PDF** | Vector — ready for submission |
| **Export SVG** | Fully editable in Inkscape or Illustrator — recommended for final layout |

### Integrity reports

| Button | Output |
|---|---|
| **Export Integrity Report** | JSON + HTML provenance record — SHA-256 hashes, crop coordinates, levels, and operation log |
| **Export Detailed Report** | Extended version with full per-operation detail |

### Original image with markers (required by most journals)

In the **Original Image** tab:

| Button | Output |
|---|---|
| **Export Original TIFF** | Current blot's unmodified 16-bit source with crop frame and band markers overlaid |
| **Export All Originals** | All blots in the project exported in one step |

Exporting the original image satisfies the raw image submission requirements of Springer Nature, EMBO Press, eLife, and PLOS.

---

## 10. Archive and share your project

Click **Export Library…** in the toolbar.

1. Select which projects to include in the archive.
2. Choose a save location — the file is named `PysternBlot_export_YYYYMMDD.pbarchive` by default.

A `.pbarchive` bundles your source images, operation log, and integrity report into a single portable file. SHA-256 checksums are verified on import.

To open a received archive: click **Import Library…** in the toolbar and select the `.pbarchive` file.

---

## What gets recorded automatically

Pystern Blot builds a timestamped operation log continuously as you work — no manual steps required:

- SHA-256 hash of each source file at import
- Every levels, gamma, crop, rotation, and flip operation with full parameter values
- Band and MW marker placements with antibody names
- Export events (format, timestamp, output path)

---

## Next steps

- Read the full [README](README.md) for a complete feature reference.
- To report a bug or request a feature, open an issue on the [GitHub repository](https://github.com/TheBrickalista/PysternBlot/issues).
- For questions about journal submission requirements, see the [Integrity report guide](docs/integrity_report.md) *(coming soon)*.
