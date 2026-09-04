# Original Image tab

The **Original Image** tab is where individual blots are reviewed, adjusted,
annotated, and exported as marked-up originals. It is the most control-rich tab
in Pystern Blot. All display adjustments here are **non-destructive** — the
source image is never modified, and every adjustment is recorded in the operation
log.

## Blot selection and ordering

The controls above the canvas are arranged in three rows: the top row holds
blot identity (and, for multi-channel NIR blots, the channel selector); the
second row holds export actions; and the third row holds image transforms and
blot metadata. This section covers the first row.

| Control | Function |
|---|---|
| **Blot** | Dropdown selecting the active blot |
| **Up** / **Down** | Move the active blot earlier or later in the figure panel order |
| **Rename…** | Set a cosmetic display name for the blot (does not affect the source file or integrity report) |

For multi-channel NIR blots, a **channel selector** follows in this same row,
separated from the identity controls by a vertical divider; both the divider
and the selector are hidden for ECL blots and single-channel NIR blots. See
[NIR fluorescence and the Typhoon](../concepts/nir-typhoon.md).

## Orientation

| Control | Function |
|---|---|
| **Rotate** dial | Fine rotation from −10.0° to +10.0° |
| Rotation field | Type an exact angle (−10.0 to +10.0) instead of using the dial |
| **↺** / **↻** | Rotate 90° counter-clockwise / clockwise |
| **⇔** | Flip horizontal (mirror left-right) |
| **↕** | Flip vertical (mirror top-bottom) |

## View aids

| Control | Function |
|---|---|
| **Grid** | Overlays a grid to help with alignment |
| **Fit** | Fits the image in the view (or double-click the canvas) |

These gestures also work directly on the canvas — hover over it to see them
summarised in a tooltip: **scroll to pan**, **Shift+scroll to zoom**,
**double-click to fit**.

A draggable splitter separates the control rows above from the image canvas
below — drag it to trade control-row space for canvas space, or vice versa.

## Annotation

This part of the third control row sets the blot's identifying information:

| Control | Function |
|---|---|
| **Protein** | Target protein name (editable dropdown with autocomplete from previous entries) |
| **Antibody** | Antibody used (editable dropdown with autocomplete) |
| **Size** | Font size for the protein label (4–48) |
| **Include in final figure** | Whether this blot appears in the exported figure |

An **⚠ 8-bit** badge appears next to the current-blot label when the source image
is 8-bit.

## Display panel

The **Display** frame controls on-screen rendering only. All adjustments run on
the full-depth source data — nothing is discarded.

Click the **⌄ Display** header to collapse the frame to just its header (it
becomes **› Display**) and return the freed vertical space to the canvas below;
click again to re-expand. The panel is expanded by default each time Pystern
Blot starts — the collapsed state is a session-only UI convenience and is not
saved with the project.

| Control | Function |
|---|---|
| **Overlay** + **Alpha** | Superimpose a paired membrane channel and set its blend (ECL + membrane acquisitions only) |
| **Invert** | Invert the image (useful for dark-background ECL) |
| **Gamma** | Adjust midtone contrast (0.10–3.00) |
| **Min** / **Max** | Set the black and white display thresholds |

Both the Min and Max fields are directly editable — type a value and press Enter
or Tab. The slider ranges adapt to bit depth: 0–65535 for 16-bit sources, 0–255
for 8-bit.

```{warning}
When gamma departs from 1.00, a **⚠ γ≠1 (disclose)** badge appears. Gamma is a
non-linear adjustment: it is permitted for display but must be disclosed in the
figure legend or Methods per journal image-integrity guidelines, and is not
suitable for densitometric quantification.
```

### Live histogram

Below the Display controls, a live pixel-intensity histogram shows the current
blot's distribution. The Min, Max, and gamma gate lines can be dragged directly
on the histogram. A **Log scale** checkbox (on by default) toggles logarithmic
scaling of the histogram's vertical axis.

## Overlay ladder

The **Overlay ladder** frame places molecular-weight markers on the blot:

| Control | Function |
|---|---|
| **Preset** | Select a protein ladder preset (defined on the [Preferences tab](preferences.md)) |
| **Show labels** | Show or hide the kDa labels |
| **Only highlighted** | Show only bands flagged as highlighted in the preset |
| **Markers on right** | Place markers on the right side of the blot instead of the left |
| **Save options** | Save the current overlay-ladder display options |
| **Edit assignments…** | Open a dialog to assign ladder bands to positions |
| **MW label size** | Font size of the molecular-weight labels (4–72 pt) |

## Legend export zone

An optional second selection rectangle can be drawn over the blot to export a
region of the original image with the panel legend — the same content edited
on the [Legend tab](legend.md) — drawn above it.

- **Legend export zone** — off by default. Ticking it shows a second,
  independent rectangle (blue, dashed) over the blot image, resized and moved
  with the same corner/edge drag handles as the crop rectangle. Its position
  and size are stored per blot, separately from the crop.
- **Export Zone + Legend** — exports the zone as a 2x-scale PNG, with the
  panel legend drawn above the cropped image. The legend is aligned to the
  **figure crop box**, not to the drawn zone, so captions land over the
  correct lanes regardless of how the zone itself is sized or positioned.

  ```{note}
  The exported region is automatically expanded to fully contain the figure
  crop box, even if the zone you drew is smaller than or offset from it — so
  the exported PNG can be wider than the rectangle shown on screen. This is
  deliberate: it guarantees the legend always lines up with the lanes it
  describes.
  ```

- **MW markers** — on by default once the zone is enabled; draws
  molecular-weight ticks and labels on the export, reusing the blot's
  overlay-ladder band assignments and calibration.

  ```{warning}
  Unlike the ladder in the final figure, this export always draws every
  assigned band — the Overlay ladder's **Only highlighted** option and each
  band's **include in final figure** curation are not applied, because the
  export is meant as a complete reference ladder. The NIR per-channel
  wavelength filter still applies: a band assigned to a different channel is
  not calibrated for the image being exported.
  ```

- **Left / Right** — an independent side toggle for where the MW markers are
  drawn on this export, unrelated to the Overlay ladder's own
  **Markers on right** setting.

The **MW markers** checkbox and the side dropdown are enabled only while
**Legend export zone** is ticked.

## Exports

Pystern Blot can hand over the original image at three different levels, from raw
instrument output to the finished figure:

- **Source file** — the exact bytes imported from the instrument: untouched, with
  no display settings, no annotations, and no format conversion. Every export
  re-hashes the written copy and verifies it against the asset's stored SHA-256
  before reporting success.
- **Annotated context TIFF** — the original image rendered with the *current*
  display settings (levels, gamma, rotation, invert) applied, with the crop
  rectangle and MW markers burned in. Useful for reviewers who want to see the
  whole source alongside what was cropped for the figure.
- **Published panel** — the final composed figure, exported from the **Figure**
  tab (PNG/PDF/SVG); see the [Figure tab](figure.md) guide.

```{warning}
"Annotated context TIFF" applies whatever display settings (levels, gamma,
rotation, invert) are currently active on the blot — it is a presentation
artefact, not the source. If you need the file exactly as the instrument
produced it, use "Export Source File" / "Export All Source Files" instead.
```

| Button | Output |
|---|---|
| **Export Zone + Legend** | The selected legend export zone, exported as a 2x-scale PNG with the panel legend drawn above it and MW markers on the chosen side |
| **Export Annotated Context TIFF** | The current blot's image with the current display settings applied and the crop frame and band markers burned in |
| **Export All Annotated Context** | Every blot in the project exported in one step |
| **Export Source File** | The current blot's source file, copied byte for byte with no display settings, annotations, or format conversion applied |
| **Export All Source Files** | Every blot's source file exported in one step, each verified independently |

Exporting the source file or the annotated context TIFF satisfies the raw-image
submission requirements of Springer Nature, EMBO Press, eLife, and PLOS.
