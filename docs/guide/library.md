# Library tab

The **Library** tab lists every project in your workspace and is where projects
are opened, refreshed, and archived.

## The projects table

Projects are shown in a table with the following columns:

| Column | Meaning |
|---|---|
| **Name** | The project name |
| **Project ID** | The internal unique identifier |
| **Created** | Creation timestamp |
| **Modified** | Last-modified timestamp |
| **# Blots** | Number of blots in the project |
| **Path** | Location of the project folder on disk |

**Double-click any row** to open that project.

## Toolbar actions

Two buttons sit above the table:

| Button | Action |
|---|---|
| **Manage Archives…** | Opens the archive manager — a two-column view of active and archived projects, with arrow buttons to move projects between the two |
| **Refresh Library** | Re-scans the workspace and updates the table |

## Archiving projects (soft-hide)

Archiving hides a project from the main library list **without deleting any data**
— the project remains intact on disk and can be restored at any time.

- **Right-click** any project row and choose **Archive…** to hide it immediately.
- Use **Manage Archives…** to move projects between the active and archived
  columns.

```{note}
Archiving is distinct from exporting. **Export Library…** (in the toolbar and on
the Home tab) creates a portable `.pbarchive` file for backup or sharing;
archiving simply hides a project locally. See the
[PBArchive format](../concepts/pbarchive-format.md) for details on the export
format.
```
