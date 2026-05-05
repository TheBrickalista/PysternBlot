Pystern Blot — Development Roadmap

Overview

This roadmap defines the implementation strategy for improving the application in a structured and scalable way. The goal is to:
	•	Clean up UI and workflow
	•	Extend the project model
	•	Build a robust figure composition system
	•	Implement high-quality export (raster + editable)
	•	Add advanced annotation features (protein ladder system)

The roadmap is organized from simplest to most complex tasks to minimize instability and rework.

⸻

Phase 1 — UI Cleanup & Workflow Reorganization

Goals
	•	Improve usability
	•	Align with PyMicRheo style
	•	Clarify workflow structure

Tasks
	•	Redesign Home tab:
	•	App name
	•	Description
	•	Copyright
	•	License
	•	Version / repository (optional)
	•	Rename tabs to better reflect workflow
	•	Move outline/cropping tools to Final Result tab
	•	Harmonize font size behavior across:
	•	Protein names
	•	Legend tab

Outcome

Cleaner, more intuitive UI with minimal risk to core functionality.

⸻

Phase 2 — Project Model Extension

Goals
	•	Prepare data model for future features
	•	Add flexibility to blot handling

Tasks

2.1 Hidden / Non-displayed Blots
	•	Add flag per blot:
	•	included_in_final = true/false
	•	Blots remain:
	•	Stored in project
	•	Editable
	•	Toggleable for inclusion

2.2 Left-side Annotation Field
	•	Add optional text field per blot
	•	Positioned:
	•	Left of blot
	•	Vertically centered
	•	Must be future-compatible with ladder system

Outcome

Blots become richer project objects with more flexibility.

⸻

Phase 3 — Final Figure Composition Architecture

Goals
	•	Move from simple rendering to structured composition
	•	Prepare for export system

Tasks

3.1 Structured Scene Model

Final figure should be composed of independent elements:
	•	Image objects (blots)
	•	Text objects
	•	Lines
	•	Rectangles / frames

3.2 Left-side Layout Zone

Define a dedicated area per blot for:
	•	Side annotation text
	•	Future MW ladder labels

Design considerations:
	•	Avoid overlap between annotation and ladder
	•	Allow spacing and alignment control

Outcome

A robust internal representation of the figure, enabling clean export.

⸻

Phase 4 — Export System

Goals
	•	Support both scientific image export and editable layout export

⸻

4.1 Raster Export (High Fidelity)

Purpose
	•	Presentations
	•	Publications
	•	Archival

Formats
	•	16-bit TIFF (priority)
	•	16-bit PNG

Characteristics
	•	Fully flattened image
	•	Preserves dynamic range

⸻

4.2 Editable Export (Layout)

Purpose
	•	Final adjustments in Illustrator / Affinity Designer

Formats
	•	SVG (priority)
	•	PDF (optional)
	•	EPS (optional)

Requirements
	•	Independent objects:
	•	Each blot = separate image object
	•	Text = editable text
	•	Shapes = vector objects

Notes
	•	Blots remain raster (expected)
	•	Goal is layout editability, not vectorizing images

⸻

Outcome

Two complementary export pipelines:
	•	Scientific raster output
	•	Editable figure layout

⸻

Phase 5 — Protein Ladder System

Goals
	•	Enable precise MW annotation
	•	Provide reusable ladder definitions

⸻

5.1 Ladder Preset Management

New Tab (Preferences-style)
	•	Define ladder presets:
	•	Name
	•	MW values
	•	Edit / delete / reorder

⸻

5.2 Ladder Assignment per Blot

In provenance/source tab:
	•	Assign ladder preset to blot

⸻

5.3 Overlay Marker Placement

User interaction:
	•	Click positions on blot
	•	Associate with MW values

Stored as:
	•	Mapping between image coordinates and MW values

⸻

5.4 Final Figure Display

In Final Result:
	•	Display selected MW markers:
	•	Ticks + labels
	•	Not all markers required
	•	User controls visibility

⸻

Outcome

Full ladder annotation workflow integrated into the app.

⸻

Implementation Batches

Batch 1 — UI
	•	Home tab
	•	Tab renaming
	•	Move outline tools
	•	Font harmonization

Batch 2 — Data Model
	•	Hidden blots
	•	Left annotation field

Batch 3 — Rendering & Export
	•	Structured composition
	•	Raster export (16-bit)
	•	SVG export

Batch 4 — Ladder System
	•	Ladder presets
	•	Assignment
	•	Marker placement
	•	Final rendering

⸻

Key Design Principles
	•	Separate data model, rendering, and export
	•	Treat final figure as a scene of objects, not a flat image
	•	Keep raster and editable exports conceptually distinct
	•	Design left-side layout early to avoid conflicts
	•	Implement complex systems (ladder) only after foundations are stable

⸻

Final Goal

A workflow where the user can:
	1.	Prepare and annotate blots
	2.	Assemble the final figure inside the app
	3.	Export:
	•	A 16-bit high-quality image
	•	An editable SVG for Illustrator/Affinity

Replacing the traditional Photoshop → Illustrator pipeline with a single integrated tool.