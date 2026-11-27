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

## Several PysternBlot windows or installations

You may run more than one PysternBlot on the same workspace (`~/.pysternblot`)
at the same time: two windows, or a standalone install and the copy bundled in
Pyblication, possibly at different versions. Two safeguards keep projects
intact.

**Project format version.** Each `project.json` records a `format_version`
(currently 1; projects saved before this existed count as 0 and open as
before). A project saved by a newer PysternBlot that uses a format this version
doesn't know is refused with *"This project was saved by a newer PysternBlot …
Please update PysternBlot to open it."* It is never partly loaded and never
saved over. In the library it is listed as *(needs a newer PysternBlot)*, and
archive import skips it. Fields added by a newer version that keeps the same
format are kept when you save, not dropped.

**Edit lock.** Opening a project for editing creates a `.lock` file in its
folder, recording which computer, process and PysternBlot version opened it, and
when. Closing the project, opening another one, or quitting removes it. If the
project is already open elsewhere, you are asked:

| Choice | What happens |
|---|---|
| **Open read-only** (default) | You can look at the project, but nothing is saved or logged. A yellow banner and the window title say *read-only*. The first change you make tells you once that it is not saved. Imports and exports are disabled. |
| **Open anyway** | You take over editing. If the other window then tries to save, it does not save. It switches to read-only and tells you *"Another PysternBlot took over editing this project; your last change was not saved."* |
| **Cancel** | The project you had open stays open. |

A lock left behind by a crash (same computer, process no longer running) is
taken over without asking. Renaming or archiving, from the library, a project
that is being edited elsewhere is refused.

The lock only guards editing. Reading never needs it. The library, the
Pyblication plugin and **Export Library…** ignore it, and it is never part of a
`.pbarchive`. Saves are atomic: `project.json` is written to a temporary file
and then swapped in, so a crash mid-save leaves the previous version intact,
and other readers never see a half-written file.
