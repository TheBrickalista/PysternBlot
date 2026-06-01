# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Commands

```bash
# Run the app
python -m pysternblot

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_image_utils.py -v

# Run a single test by name
pytest tests/test_image_utils.py::TestSaveUint16Tiff::test_roundtrip -v

# Run tests and treat deprecation warnings as errors
pytest tests/ -v -W error::DeprecationWarning
```

There is no separate build, lint, or format step configured.

## Architecture

The full architecture — data model, storage layout, image pipeline, rendering,
UI mixins, integrity reporting, and NIR multichannel support — is documented in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Read it before making structural
changes.

When working in this codebase, the following invariants must not be broken (see
ARCHITECTURE.md for the reasoning behind each):

- **Never silently reduce bit depth.** Source images are preserved as imported;
  internal processing is uint16 throughout. Any conversion to a lower-precision
  output format must be explicit and logged.
- **Never modify a source asset after import.** A source file's SHA-256 is its
  identity; the stored original is read-only by contract.
- **Two image loaders exist — use the correct one.** `load_image_uint16` is
  strict (native 16-bit grayscale only); `load_image_as_uint16` is permissive
  (also accepts 8-bit, used for display and crop-preview generation). Always
  call either on the original asset, never on a preview or working copy.
- **JPEG is hard-rejected** at all import entry points.
- **Crop size is authoritative on `Panel.crop_template`**, not `Crop.w/h` (which
  are kept only for backward compatibility and ignored at render/storage time).
  Each blot contributes only its position (`Crop.x`, `Crop.y`).
- **Log every state mutation** that should appear in an integrity report via
  `log_operation(...)`.
- **Add new model fields with defaults** so existing `project.json` files
  continue to load.

> When saving uint16 TIFFs, use
> `Image.frombuffer("I;16", (w, h), arr.tobytes(), "raw", "I;16", 0, 1)`.
> `Image.fromarray(arr, mode="I;16")` is deprecated and removed in Pillow 13.
