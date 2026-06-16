# NIR fluorescence and the Typhoon

Near-infrared (NIR) fluorescence detection, typified by the Cytiva Typhoon laser
scanner, has a workflow distinct from chemiluminescence. Pystern Blot handles its
particular requirements — multiple channels and instrument metadata — as
first-class features. This page explains what is specific to NIR and how the tool
captures it.

## How NIR differs from chemiluminescence

In chemiluminescence (ECL), an enzyme produces light that a camera captures as a
single image. In NIR fluorescence, a laser excites fluorescent dyes and the
emitted light is read at specific wavelengths. Two properties follow:

- **Multiple channels.** Different targets are labelled with dyes that emit at
  different wavelengths and read on separate channels — commonly two for a
  Typhoon. Each channel is its own image, and a single blot is the combination of
  them.
- **Linear, quantitative signal.** NIR detection has a wide linear dynamic range,
  which is part of why it is favoured for quantitative Western blots — and why
  preserving the original 16-bit data without destructive adjustment matters so
  much.

## Dual-channel import

Pystern Blot imports NIR blots through a dedicated **Import NIR Blot…** dialog
with two slots:

- **Channel 1 (required)** — typically the shorter-wavelength acquisition
- **Channel 2 (optional)** — the second channel, where a second target was probed

Each channel is registered as a **separate asset with its own SHA-256 hash**,
then associated as a single dual-channel blot within the project. This keeps the
provenance of each channel independent and verifiable while treating them as one
logical blot for figure assembly.

The per-channel integrity flags described in
[Provenance and integrity](provenance.md) — including the gamma flag — apply to
each NIR channel individually, so a non-linear adjustment on one channel is
recorded for that channel specifically.

## Instrument metadata: TIFF Tag 270

Typhoon acquisitions embed acquisition context in the TIFF file's
**ImageDescription field, tag number 270**. Pystern Blot reads this tag
automatically on import and parses the channel information — such as wavelength
and filter — displaying it directly beneath each file path in the import dialog
so you can confirm you have loaded the right channel.

Capturing this metadata is part of preserving the original acquisition context:
the conditions under which the image was produced travel with the provenance
record rather than being lost at import.

## The .inf sidecar

Some Typhoon workflows produce an accompanying **`.inf` sidecar file** alongside
the image — a separate file carrying additional instrument and scan parameters.
Where present, Pystern Blot captures this sidecar information so that the fuller
acquisition context is retained with the blot. For NIR workflows in particular,
this strengthens the record of exactly how the source image was generated.

## Why this is built in

NIR is one of the most common modalities for quantitative Western blotting, and
its multi-channel, metadata-rich nature is precisely where ad-hoc digital
workflows tend to lose information — channels get merged early, instrument
context is discarded, and the path back to the raw data is broken. Treating NIR
channels and their metadata as first-class, individually-verifiable assets keeps
that information intact from acquisition through to the final figure.

See the [Quickstart](../quickstart.md) for a worked dual-channel NIR import using
the included example project.
