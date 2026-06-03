# Contributing to Pystern Blot

Thank you for your interest in Pystern Blot. The project is currently maintained
by a single author (Etienne Boulter, IRCAN). Bug reports, feature suggestions,
and pull requests are welcome — please read this short guide first.

## Ways to contribute

- **Report a bug** — open an issue using the *Bug report* template.
- **Request a feature** — open an issue using the *Feature request* template.
- **Submit a fix or improvement** — open a pull request (see below).
- **Share instrument test files** — multichannel TIFFs from instruments not yet
  covered (e.g. LI-COR Odyssey) are especially useful; see *Test data* below.

For anything large or potentially disruptive, please open an issue to discuss it
before starting work, so we can agree on the approach.

## Development setup

Pystern Blot requires **Python ≥ 3.10**. Clone the repository and install in
editable mode with the development extras:

```bash
git clone https://github.com/TheBrickalista/PysternBlot.git
cd PysternBlot
pip install -e ".[dev]"
```

Run the application:

```bash
python -m pysternblot
```

## Running the tests

The test suite must pass before a pull request can be merged. The same suite runs
automatically on every pull request via GitHub Actions.

```bash
# Run the full suite
pytest tests/ -v

# Run a single file or test
pytest tests/test_image_utils.py -v
pytest tests/test_image_utils.py::TestSaveUint16Tiff::test_roundtrip -v

# Treat deprecation warnings as errors (recommended before submitting)
pytest tests/ -v -W error::DeprecationWarning
```

If you add or change behaviour, please add or update tests to cover it. There is
no separate lint or format step configured; please match the style of the
surrounding code.

## Design invariants

Pystern Blot exists to treat the Western blot image as an informatic object with
documented provenance. A few invariants protect that guarantee and **must not be
broken** by a contribution. Please keep these in mind, and call out in your PR
description if you believe one needs to change:

- **Never silently reduce bit depth.** Source images are preserved as imported;
  internal processing is uint16 throughout. Any conversion to a lower-precision
  output format must be explicit and recorded.
- **Never modify a source asset after import.** The SHA-256 of every source file
  is its identity; the stored original is read-only by contract.
- **JPEG is hard-rejected** at all import entry points — lossy compression
  invalidates quantitative analysis.
- **Every state mutation that should appear in an integrity report must be
  logged** via `log_operation(...)`. Provenance is a primary output, not an
  optional extra.
- **Add new model fields with defaults.** Existing `project.json` files must
  continue to load; backward compatibility is maintained through Pydantic
  defaults.

A fuller description of the codebase is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Make your change, with tests.
3. Ensure `pytest tests/ -v` passes locally.
4. Open a pull request against `main` with a clear description of what changed
   and why. Reference any related issue.

Continuous integration will run the test suite and CodeQL analysis on your PR.

## Test data

Some tests depend on real instrument files (e.g. Cytiva Typhoon channel TIFFs in
`tests/`). LI-COR Odyssey import is currently stubbed and its tests are skipped
pending a sample file. If you can contribute sanitised instrument output for an
unsupported platform, please open an issue — it directly enables new format
support. Please ensure any shared file is free of confidential or personally
identifying information before submitting.

## Licensing of contributions

Pystern Blot is licensed under the **GNU General Public License v3.0
(GPL-3.0-only)**. By submitting a contribution, you agree that it will be
licensed under the same terms. Please do not submit code you are not entitled to
license under GPL-3.0.
