# Legend tab

The **Legend** tab composes the text legend that accompanies your figure — panel
labels, per-lane annotations, and grouped condition labels. Rows are split into
those displayed above the figure panels (**upper rows**) and those below
(**lower rows**).

## Top controls

| Control | Function |
|---|---|
| **Mode** | **Protein** for Western blot figures, or **DNA** for nucleic-acid gels |
| **# Upper rows** | Number of legend rows above the panels (0–30) |
| **# Lower rows** | Number of legend rows below the panels (0–30) |

## Row editors

Each row has three zones plus per-row settings:

| Zone | Use |
|---|---|
| **Left** | Typically a panel label (e.g. *A*, *B*) or antibody name |
| **Center cells** | Per-lane annotations — set **# cells** to match your lane count |
| **Right** | A trailing annotation (e.g. molecular weight or condition) |

Per row you can also set:

- **# cells** — number of center cells (lanes) in the row (0–30)
- **Font** — row font size in points (6.0–30.0)

All text fields are editable dropdowns with autocomplete drawn from values
entered elsewhere in the project, so antibody names and condition labels only
need to be typed once. (The list of remembered entries is managed on the
[Preferences tab](preferences.md).)

## Grouping lanes under shared labels

Beneath each center cell is a small **group #** spinbox (0–20). The grouping rule:

- **0** means ungrouped — no underline, label stays at its own lane position.
- Cells sharing the **same non-zero group number** that are **adjacent** form a
  group. A group of two or more cells draws an underline spanning those lanes.
- An **upper-row** cell carrying the same group number is centred as the label
  over that group.
- A group number placed on **non-adjacent** cells will not draw an underline; the
  spinbox is tinted amber as a warning.

**Worked example — Total / Elution / Beads across 6 lanes:**

1. Set **# Upper rows** to 1, **# Lower rows** to 1, and **# cells** to 6 in each.
2. In the **lower row**, enter the per-lane labels and set group numbers
   `1 1 2 2 3 3`.
3. In the **upper row**, enter `Total`, `Elution`, `Beads` on the first three
   cells with group numbers `1`, `2`, `3`.
4. Each upper label is automatically centred over its lane pair, with an underline
   beneath it.

```{tip}
Leaving a single lane ungrouped (group 0) draws no underline, which supports
asymmetric layouts — for example, a lone marker lane beside grouped conditions.
```

## Three-level headers

With three or more upper rows, a top-row cell can label several middle-row
cells. Middle rows (any upper row with a row above it that is not the lane
reference) show a second spinbox under each cell, **Parent #** (shown as
`P 0`). Adjacent cells with the same non-zero Parent # are grouped under the
cell that carries that number as its **Group #** in the row directly above;
that label is centred on all their lanes, and a group of two or more cells
gets an underline at that level. Numbering is per level: a Parent # only
refers to the row directly above.

**Worked example — Serum starved / Growing over two treatments over 9 lanes:**

1. Set **# Upper rows** to 3 (and **# Lower rows** to 0).
2. **Row 3** (lane reference, 9 cells): `0 10 0 10 0 10 0 10 Pos. control`,
   group numbers `2 2 3 3 4 4 5 5 0`.
3. **Row 2** (4 cells): `Control`, `JPH203 1uM`, `Control`, `JPH203 1uM`, group
   numbers `2 3 4 5` (each centred on its lane pair) and Parent # `1 1 2 2`.
4. **Row 1** (2 cells): `Serum starved`, `Growing`, group numbers `1` and `2`.

`Serum starved` is centred over lanes 1–4 and `Growing` over lanes 5–8, each
with an underline above its two treatments. A Parent # used on non-adjacent
cells is tinted amber and does not group them. Legends without Parent #
numbers render exactly as before.
