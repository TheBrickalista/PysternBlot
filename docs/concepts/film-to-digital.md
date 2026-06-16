# The film-to-digital gap

Pystern Blot exists to close a gap that opened quietly when Western blot
detection moved from film to digital acquisition. Understanding that gap
explains every design decision in the tool.

## Film was self-documenting

For decades, a Western blot was detected by pressing a sheet of X-ray film
against the membrane. The film *was* the record. A researcher pulled it from the
cassette, wrote on it in marker — the date, the antibody, the molecular-weight
ladder positions, which lane was which — and filed it in a drawer. The annotated
film was a physical object with an unbroken chain of custody: the exposure, the
handwriting, and the developing artifacts were all fused into one artifact that
could be pulled out years later and read directly.

Crucially, the film recorded the *full dynamic range* of the exposure. Nothing
was thresholded away at acquisition. If a reviewer or a future student wanted to
re-examine a faint band, the original was right there, exactly as exposed.

## Digital acquisition broke the chain

Digital imagers — CCD systems for chemiluminescence, laser scanners like the
Typhoon for fluorescence — replaced film with enormous gains in sensitivity,
linearity, and quantitative range. A modern 16-bit acquisition captures 65,536
intensity levels, far beyond what film or the human eye can resolve, and does so
linearly enough to support quantification.

But the move to pixels silently severed the documentation chain that film had
provided for free:

- **The annotations left the image.** Lane identities, antibody names, and
  ladder positions now live in a lab notebook, a file name, or a researcher's
  memory — not on the image itself.
- **The display became detached from the data.** A 16-bit image cannot be shown
  directly on an 8-bit screen or printed page. Every figure is the result of a
  *display transform* — black point, white point, gamma — chosen by a human.
  That transform is usually applied in general-purpose software and then
  discarded, leaving no record of how the published picture was derived from the
  raw data.
- **The original is easy to lose.** The raw acquisition file sits in an
  instrument folder, gets renamed, gets separated from the figure it produced.
  The provenance link between "the TIFF off the imager" and "panel B in the
  paper" is maintained, if at all, by manual discipline.

None of this was malicious. It was the ordinary friction of a workflow that lost
its built-in record-keeping and never replaced it.

## Why this matters now

The consequences of the broken chain are visible across the literature. Image
integrity concerns — undisclosed adjustments, spliced lanes, reused panels,
over-aggressive contrast that erases context — are among the most common reasons
papers are corrected or retracted. Most are not fraud; they are the predictable
result of a documentation gap, where the path from raw image to published figure
was never recorded and could not be reconstructed.

Publishers have responded with policy. Springer Nature, EMBO Press, eLife, and
PLOS now require authors to supply unprocessed original images and to disclose
any adjustments. But policy describes *what* is required without providing the
*means* to produce it. The burden falls back on manual discipline — the very
thing that failed when film disappeared.

## What Pystern Blot restores

Pystern Blot re-establishes film's self-documenting property in a digital
workflow. It does not ask researchers to be more careful; it makes the record a
byproduct of normal work.

- The **original 16-bit acquisition is preserved untouched**, hashed with
  SHA-256 at import so its identity is fixed and verifiable.
- Every **display transform is recorded** — black, white, gamma, crop, rotation
  — as parameters in an operation log, never baked irreversibly into the only
  surviving copy.
- **Annotations live with the image again** — antibody, target protein, ladder
  positions, lane identities — exactly as a researcher once wrote on film.
- The whole bundle travels as a single **portable archive** with verifiable
  checksums, so the chain of custody from raw image to final figure stays intact
  when a project is shared, reviewed, or revisited years later.

Integrity reporting falls out of this naturally. Because the path from
acquisition to figure is recorded as it happens, producing the unprocessed
originals and the adjustment disclosure that publishers ask for is not extra
work — it is an export button. The integrity record is a *consequence* of the
design, not its headline feature.

The headline is simpler: a digital blot should document itself as well as a sheet
of film once did.
