# The .pbarchive format

A `.pbarchive` is Pystern Blot's portable project format — a single file that
bundles everything needed to reproduce, verify, and continue working on a figure.
It is how projects are backed up, shared with collaborators, and submitted
alongside a manuscript.

## What it contains

A `.pbarchive` packages the complete provenance bundle for one or more projects:

- The **original source images**, byte-for-byte as imported
- The **operation log** — every adjustment, crop, annotation, and export event
- The **integrity report**, including SHA-256 hashes and bit-depth flags
- Project structure and metadata — names, panel order, legend layout, ladder
  presets

Because the originals travel inside the archive, a recipient does not need access
to the original instrument files or the lab's storage. The archive is
self-contained.

## Checksum verification on import

Every source image in a `.pbarchive` carries the SHA-256 hash that was recorded
when it was first imported. When an archive is opened, Pystern Blot recomputes
those hashes and verifies them against the stored values. A mismatch indicates
the file was altered or corrupted after the archive was created, and is surfaced
rather than passed over silently. This makes the archive not just portable but
*verifiable* — the chain of custody is checked, not merely asserted.

## Why JSON, not a database

The `.pbarchive` format is built on human-readable JSON rather than a binary
database. This is a deliberate choice aligned with the tool's purpose:

- **Transparency.** An integrity tool whose own records are opaque would
  undermine its point. JSON can be opened and read by anyone, with no special
  software, now or in the future.
- **Longevity.** A plain-text structure is far more likely to remain readable
  decades from now than a proprietary binary format — which matters for a record
  meant to outlive the project that created it.
- **Portability.** The format moves cleanly across machines and operating
  systems, and plays well with version control and archival systems.

The access pattern also fits JSON well: work is *project-centric* rather than
query-centric, and the data within any one project is bounded in size. A database
would add complexity without a corresponding benefit at this scale. (Should that
change for very large workspaces, a migration path to indexed storage is
well-defined — but it is not needed for the format's intended use.)

## Using archives

Archives are created and opened from the toolbar:

- **Export Library…** bundles selected projects into a
  `PysternBlot_export_YYYYMMDD.pbarchive` file.
- **Import Library…** opens a received archive, verifying checksums as it loads.

See the [Quickstart](../quickstart.md) for a step-by-step archive-and-share
walkthrough, and [Provenance and integrity](provenance.md) for how the hashes
inside an archive are generated and what they guarantee.
