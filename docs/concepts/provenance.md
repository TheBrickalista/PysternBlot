# Provenance and integrity

Provenance is the documented history of how a final figure was derived from a raw
acquisition. Pystern Blot's central job is to capture that history automatically
and make it verifiable. This page explains the mechanisms.

## SHA-256 fingerprinting

When an image is imported, Pystern Blot computes a **SHA-256 cryptographic hash**
of the file and records it in the operation log. A hash is a fixed-length
fingerprint: any change to the file — even a single pixel, even metadata — yields
a completely different hash.

This gives two guarantees:

- **Identity.** The hash uniquely identifies the exact bytes that were imported.
  The same original file always produces the same hash, so a figure can be tied
  back to a specific source acquisition beyond dispute.
- **Tamper-evidence.** If a source file is later altered, its hash no longer
  matches the one recorded at import. Checksums are re-verified when a project
  archive is opened, so silent corruption or substitution is detected.

The source file itself is **never modified**. Pystern Blot treats every
acquisition as read-only and records adjustments separately, so the original
bytes — and therefore the original hash — remain stable for the life of the
project.

## The operation log

Pystern Blot maintains a timestamped log of every operation that shapes a figure,
written continuously as you work rather than assembled after the fact. Recorded
events include:

- The SHA-256 hash and bit depth of each source file at import
- Every display adjustment — black point, white point, gamma — with full
  parameter values
- Crop coordinates, in pixels relative to the original image
- Rotations and flips
- Band and molecular-weight marker placements, with antibody and target names
- Export events, with format, timestamp, and output path
- Archive and restore events

Because the log records *parameters* rather than baking changes into pixels, the
path from raw image to final figure is fully reconstructable. Nothing about how
the published picture was produced is lost.

## Non-destructive display

A 16-bit acquisition holds 65,536 intensity levels and cannot be shown directly
on an 8-bit screen or page. Producing a viewable figure always requires a display
transform. Pystern Blot applies these transforms **for display only**: the black
point, white point, and gamma you set change how the image is rendered, not the
underlying data. All adjustments operate on the full-depth source, so no
information is discarded and any setting can be revised at any time.

This is the digital equivalent of choosing how to expose and print a piece of
film while keeping the negative intact.

## Bit-depth integrity

Bit depth is tracked explicitly because it determines whether an image can
support quantification.

- **16-bit** sources carry the full quantitative range of the acquisition and
  are recommended for any figure where band intensities will be compared.
- **8-bit** sources (often from legacy scanners) are accepted, but flagged: an
  8-bit badge appears on the blot, the bit depth is recorded in the integrity
  report, and a warning fires at export so the limitation can be disclosed.
- **JPEG is refused** outright — lossy compression permanently alters pixel
  values and is incompatible with quantitative work.

## The gamma flag

Gamma adjustment is non-linear: it changes midtone contrast in a way that can
make faint bands more or less prominent without touching the extremes. Because a
non-linear adjustment to a quantitative image is exactly the kind of change that
should be disclosed, Pystern Blot raises a dedicated **integrity flag** when
gamma departs from linear on a blot or NIR channel — an amber badge in the
interface and a corresponding entry in the integrity report. The adjustment is
still permitted; it is simply never silent.

## Integrity as a consequence, not a feature

Everything above runs in the background of ordinary figure preparation. As a
result, the unprocessed originals and adjustment disclosures that publishers
require are already captured by the time a figure is finished — producing them is
an export, not a separate documentation effort. See the
[Figure tab](../guide/figure.md) for the integrity-report export buttons, and the
[PBArchive format](pbarchive-format.md) for how a complete provenance bundle is
packaged and shared.
