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
  matches the one recorded at import. Checksums are re-verified when a
  `.pbarchive` is opened, so silent corruption or substitution is detected.
  The operation log itself carries the same property — see
  [The operation log hash chain](#the-operation-log-hash-chain) below.

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

## The operation log hash chain

Recording events is not, on its own, tamper-evident: a log that can be edited
freely is just a list of claims. Each operation-log entry therefore carries two
extra fields — `prev_hash`, the hash of the entry immediately before it, and
`entry_hash`, the hash of the entry itself — computed from every field of the
entry (including `prev_hash`) via SHA-256 over a canonical, deterministic
serialisation. Changing any field of any entry, or reordering, deleting, or
inserting an entry, breaks the hash relationship with whatever comes after it.

The integrity report shows the result of verifying this chain as one line next
to the operation log, in one of four states:

- **Verified (`ok`)** — every entry's hash matches, and each entry's
  `prev_hash` matches the hash of the one before it. The log is internally
  consistent from end to end.
- **Not chained (`not_chained`)** — no entry carries a hash. This is the
  normal, expected state for a project created before this feature existed; it
  is not a warning, and never implies tampering. See
  [Backward compatibility](#backward-compatibility) below.
- **Partial (`partial`)** — the log begins unchained (a pre-existing project)
  and becomes chained from some point onward, reported as the index where
  chaining starts. Everything from that index forward is verified as normal;
  everything before it is, correctly, unverifiable.
- **Broken (`broken`)** — a hash does not match, reported with the index of
  the first entry where the inconsistency appears. This is the state that
  actually indicates a problem: an edited, deleted, reordered, or inserted
  entry, or corruption of the stored project file.

**This is tamper-evident, not tamper-proof.** The chain detects accidental
corruption and edits made without regenerating the chain — which covers every
ordinary failure mode, including a bad merge, a manual JSON edit, or a
corrupted archive transfer. It does not, and cannot, stop someone with access
to the application source from editing an entry and recomputing a consistent
chain from that point forward. Treat a verified chain as evidence that nothing
was changed *casually* or *accidentally* — not as a cryptographic guarantee
against a deliberate, competent forgery.

(backward-compatibility)=
### Backward compatibility

A project saved by an earlier version of Pystern Blot has an operation log
with no `prev_hash`/`entry_hash` on any entry. Opening or re-saving it does not
retroactively hash the old entries — the chain begins at whatever point new,
hash-carrying entries start being appended, and the log correctly reports
`not_chained` or `partial` rather than `broken`. The same applies to `.pbarchive`
project-state verification (see [PBArchive format](pbarchive-format.md)) and to
clipping detection below: an asset imported before this feature existed reports
as *not assessed*, never as *clean* — the two are not the same claim, and the
report says which one applies.

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

## Clipping (saturation) detection

A saturated pixel — one sitting at the sensor's full scale (255 for an 8-bit
source, 65535 for 16-bit) — has an unknown true intensity: whatever signal
produced it, the acquisition could not record any more, so the value is
clipped, not measured. A band with saturated pixels cannot be reliably
quantified, which is why detecting saturation matters for the same reason bit
depth and gamma do.

The naive version of this check — flag any image containing a full-scale
pixel — would fire constantly and for the wrong reason: a single hot pixel
from sensor noise, dust, or a fibre on the glass is common and harmless, and
is not the same problem as a genuinely clipped band. A flag that fires on
every image with one bright speck becomes noise, and noise trains users to
ignore it — which is worse than not having the flag at all.

Pystern Blot distinguishes the two with a **3×3 binary erosion** of the
saturation mask: a pixel survives erosion only if all eight of its neighbours
are also saturated, so an isolated speck or a one-pixel-wide line vanishes
under erosion while a solid, contiguous saturated region survives. The
integrity report accordingly separates the raw saturated pixel count from the
count that survives erosion, and only a nonzero surviving ("solid") count is
treated as a warning; isolated saturation is reported as an informational
note, not flagged.

Saturation is assessed on the **source array exactly as imported** — before
any levels, gamma, rotation, or flip — because saturation is a property of the
acquisition, not of how it is currently displayed. The integrity report shows
two results for each blot:

- **Whole image** — the fixed assessment recorded at import. This does not
  change as the project is edited.
- **Crop region** — recomputed live from the current crop rectangle each time
  a report is generated, since only the cropped region actually reaches the
  published figure, and re-cropping can move saturated pixels in or out of
  frame.

A blot whose only saturated region sits outside the current crop shows a
whole-image warning but a clean crop region — an honest reflection of what is
actually in the figure, not just what is in the source file. As with every
other integrity check in Pystern Blot, saturation is reported for the
researcher's judgement; it never blocks import or export.

## Integrity as a consequence, not a feature

Everything above runs in the background of ordinary figure preparation. As a
result, the unprocessed originals and adjustment disclosures that publishers
require are already captured by the time a figure is finished — producing them is
an export, not a separate documentation effort. See the
[Figure tab](../guide/figure.md) for the integrity-report export buttons, and the
[PBArchive format](pbarchive-format.md) for how a complete provenance bundle is
packaged and shared.
