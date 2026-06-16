# Original Image tab

The **Original Image** tab is where individual blots are reviewed, adjusted,
annotated, and exported as marked-up originals. It is the most control-rich tab
in Pystern Blot. All display adjustments here are **non-destructive** — the
source image is never modified, and every adjustment is recorded in the operation
log.

## Blot selection and ordering

The top row controls which blot is active and its position in the figure:

| Control | Function |
|---|---|
| **Blot** | Dropdown selecting the active blot |
| **Up** / **Down** | Move the active blot earlier or later in the figure panel order |
| **Rename…** | Set a cosmetic display name for the blot (does not affect the source file or integrity report) |

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

Navigation: **scroll to pan**, **Shift+scroll to zoom**, **double-click to fit**.

## Annotation

The second control row sets the blot's identifying information:

| Control | Function |
|---|---|
| **Protein** | Target protein name (editable dropdown with autocomplete from previous entries) |
| **Antibody** | Antibody used (editable dropdown with autocomplete) |
| **Size** | Font size for the protein label (4–48) |
| **Include in final figure** | Whether this blot appears in the exported figure |

For multi-channel NIR blots, a **channel selector** appears at the start of this
row; it is hidden for single-channel ECL blots. See
[NIR fluorescence and the Typhoon](../concepts/nir-typhoon.md).

An **⚠ 8-bit** badge appears next to the current-blot label when the source image
is 8-bit.

## Display panel

The **Display** frame controls on-screen rendering only. All adjustments run on
the full-depth source data — nothing is discarded.

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

## Exports

| Button | Output |
|---|---|
| **Export Original TIFF** | The current blot's unmodified 16-bit source, with crop frame and band markers overlaid |
| **Export All Originals** | Every blot in the project exported in one step |

Exporting marked-up originals satisfies the raw-image submission requirements of
Springer Nature, EMBO Press, eLife, and PLOS.
