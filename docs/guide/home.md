# Home tab

The **Home** tab is the landing screen shown when Pystern Blot starts. It
provides the application logo, version and license information, and quick-access
buttons for the most common starting actions.

## Quick-action buttons

The button row offers quick access to the most common starting actions. Most
mirror an equivalent toolbar action, but **Open Project** does not — see the
note below.

| Button | Action |
|---|---|
| **New Project** | Create a new project (one project corresponds to one final figure) |
| **Open Project** | Switch to the [Library tab](library.md), refreshing its list of workspace projects first |
| **Import Blot** | Import a chemiluminescence (ECL) blot image |
| **Export Library…** | Bundle selected projects into a portable `.pbarchive` file |
| **Import Library…** | Open a received `.pbarchive`, verifying checksums on load |

A separate **About / License** button jumps directly to the [About tab](about.md).

```{note}
Home's **Open Project** browses projects already in the current workspace via
the [Library tab](library.md), which only lists non-archived projects. The
toolbar's **Open Project…** still opens a file dialog, and remains the way to
open a project stored *outside* the workspace (a colleague's project, a copy on
an external drive, a restored backup) or a project that has been archived.
```

## What the Home screen shows

Beneath the logo, the Home tab displays the application version and a short
description of Pystern Blot's purpose — provenance tracking, audit logging, and
integrity reporting for Western blot figure preparation — along with the
copyright notice and a reminder that the software is distributed under the GPLv3.

```{note}
The toolbar at the top of the window provides the full set of import actions —
including **Import NIR Blot…** and **Import Membrane…** — which are described in
the [Library tab](library.md) and [Quickstart](../quickstart.md) pages.
```
