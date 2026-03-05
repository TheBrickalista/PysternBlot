# Pystern Blot --- Multi-Blot Panel Roadmap

This document summarizes the planned evolution of **Pystern Blot** to
support:

-   Multiple blots in a single panel
-   Shared crop template
-   Global legends
-   Per-blot side labels
-   Flexible styling controls

The roadmap is organized into phases to minimize refactoring and keep
the codebase stable while adding features.

------------------------------------------------------------------------

# Target Panel Behavior

## Panel layout

A **Panel** can contain **multiple blots** stacked vertically, forming a
classical Western blot panel.

Upper legend (global)

Blot 1 \| left label image right label Blot 2 \| left label image right
label Blot 3 \| left label image right label

Lower legend (global)

Key principles:

-   Upper legend and lower legend are **global**
-   Blots are **stacked vertically**
-   Each blot can have **independent side labels**
-   Blot order is **user-defined**

------------------------------------------------------------------------

# Cropping Model

## Shared crop template

All blots use the **same crop size**.

The crop rectangle can be **moved per blot**, but the **width and height
remain identical**.

This ensures perfectly aligned panels.

Example:

  Blot     Crop position   Crop size
  -------- --------------- -----------
  Blot A   x,y specific    shared
  Blot B   x,y specific    shared
  Blot C   x,y specific    shared

### Data model concept

Panel ├── crop_template (w,h) └── blots ├── blot1 crop_pos (x,y) ├──
blot2 crop_pos (x,y) └── blot3 crop_pos (x,y)

Resizing the crop box updates the **template size**, which applies to
all blots.

Moving the box updates only the **current blot position**.

------------------------------------------------------------------------

# Rendering Model

Final Result rendering pipeline:

1.  Draw optional title
2.  Draw **upper legend** (once)
3.  Loop through blots (in layout order)
    -   draw cropped image
    -   draw side labels
4.  Draw **lower legend** (once)

------------------------------------------------------------------------

# UI Organization

## Provenance Tab

Purpose: crop definition.

Controls:

Active blot: \[ blot_01 ▼ \]

Selecting a blot swaps the displayed image.

Actions:

-   Move crop box → updates blot position
-   Resize crop box → updates global crop template

------------------------------------------------------------------------

## Final Result Tab

Purpose: preview of the panel.

Features:

-   stacked blots
-   global legends
-   optional outlines

No editing happens here.

------------------------------------------------------------------------

## Legend Tab

Purpose: edit **global legends**

Contains:

-   Upper legend rows
-   Lower legend rows
-   underline toggles
-   cell editing

Legends apply to the **entire panel stack**.

------------------------------------------------------------------------

## Blots Tab (future)

Purpose: edit **per-blot metadata**

Example:

## Blot list

blot_01 blot_02 blot_03

## Selected blot settings

Left label: \[ pERK ▼ \] Right label: \[ GAPDH ▼ \]

------------------------------------------------------------------------

## Style / Panel Tab (future)

Purpose: global styling parameters.

Settings:

Blot rendering - show blot outline - outline width

Legends - font family - font size - bold / italic

Underlines - underline thickness - gap length

Display toggles - show title - show protein labels

------------------------------------------------------------------------

# Feature Roadmap

## Phase 0 --- Codebase Cleanup

Goal: stabilize schema.

Tasks:

-   Remove duplicate `LegendRow` class in `models.py`
-   Ensure only one definition exists including the `underline` field.

Outcome:

-   predictable Pydantic schema
-   fewer runtime surprises

------------------------------------------------------------------------

# Phase 1 --- Multi-Blot Cropping

Goal: support multiple blots with shared crop size.

### Models

Introduce crop template:

CropTemplate w h

Update blot crop to store only position:

Blot.crop_pos x y

Add to Panel:

panel.crop_template

### Provenance Tab

Add blot selector dropdown.

Selecting a blot updates the displayed image.

### Crop behavior

Moving crop box:

update blot.crop_pos

Resizing crop box:

update panel.crop_template

Clamp crop positions if needed.

### Preview generation

Preview images must use:

x,y from blot\
w,h from panel.crop_template

------------------------------------------------------------------------

# Phase 2 --- Multi-Blot Panel Rendering

Goal: stack cropped blots vertically.

Rendering order:

title upper legend

for blot in layout.order draw cropped image draw side labels

lower legend

Spacing controlled by:

gap_between_blots_px

------------------------------------------------------------------------

# Phase 3 --- Per-Blot Side Labels

Goal: labels specific to each blot.

Examples:

-   protein names
-   antibody names
-   exposure conditions

### Model

SideLabels left right

Add to Blot:

Blot.side_labels

### Rendering

draw left label\
draw image\
draw right label

Labels vertically centered relative to the blot image.

------------------------------------------------------------------------

# Phase 4 --- Styling Controls

Goal: polish output.

Blot outlines - blot_outline_enabled - blot_outline_width_px

Underline styling - underline_thickness_px - underline_gap_px

Legend font - legend_font_family - legend_font_size_pt - legend_bold -
legend_italic

Title control - show_title

Protein label control - show_protein_labels

------------------------------------------------------------------------

# Recommended Implementation Order

1.  Phase 1 --- Multi-blot cropping
2.  Phase 2 --- Multi-blot rendering
3.  Phase 3 --- Side labels
4.  Phase 4 --- Styling

------------------------------------------------------------------------

# Design Principles

-   Separation of structure and styling
-   Global panel logic vs per-blot metadata
-   Minimal duplication of data
-   Predictable rendering pipeline
