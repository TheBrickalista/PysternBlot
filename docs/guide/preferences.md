# Preferences tab

The **Preferences** tab manages reusable settings that apply across projects:
protein ladder presets and the saved autocomplete entries used in dropdowns.

## Protein ladder presets

A ladder preset is a named set of molecular-weight marker bands that can be
overlaid on any blot from the [Original Image tab](original-image.md).

Preset management:

| Control | Function |
|---|---|
| **Preset** | Select an existing ladder preset |
| **New** | Create a new empty preset |
| **Duplicate** | Copy the selected preset |
| **Delete** | Remove the selected preset |
| **Save** | Save edits to the current preset |

Each preset's bands are edited in a table with these columns:

| Column | Meaning |
|---|---|
| **kDa** | Marker molecular weight |
| **Label** | Text shown for the band |
| **Visible** | Whether the band is shown |
| **Highlight** | Flags the band for the "Only highlighted" overlay option |
| **Show 685** | Restrict the band to the 685 nm channel only |
| **Show 785** | Restrict the band to the 785 nm channel only |

Leaving both **Show 685** and **Show 785** unchecked shows the band on all
channels. Below the table, **Add band** and **Remove selected band** edit the
list of bands.

## Saved dropdown entries

Pystern Blot remembers text you enter in legend and annotation fields so it can
offer it as autocomplete elsewhere. This section manages those remembered values.

The **History** dropdown selects which list to manage:

- **Legend text**
- **Protein labels**
- **Antibody names**

The entries appear in a reorderable list. Controls:

| Control | Function |
|---|---|
| **Delete selected** | Remove the selected entry |
| **Rename selected** | Rename the selected entry |
| **Move up** / **Move down** | Reorder entries |

Entries can also be reordered by dragging. Changes save immediately.
