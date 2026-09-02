# Installation

Pystern Blot runs on macOS and Windows. There are three ways to install it,
depending on whether you already use Python and how much you want to manage
yourself.

| Method | Best for | Python needed? |
|---|---|---|
| **Standalone app** | Most users — bench scientists who just want to run it | No |
| **PyPI (`pip install`)** | Python users who want it in their environment | Yes (≥ 3.10) |
| **From source** | Contributors and people who want the development version | Yes (≥ 3.10) |

If you are not sure, choose the **standalone app** — it bundles everything and
requires no setup.

## Option 1 — Standalone app (recommended)

No Python installation is required. Download the latest build for your platform
from the [Releases page](https://github.com/TheBrickalista/PysternBlot/releases/latest).

**macOS** — download `PysternBlot-vX.X.X-macOS.zip`, unzip it, and move
`PysternBlot.app` to your Applications folder.

**Windows** — download `PysternBlot-vX.X.X-Windows.exe` and run it.

### First launch

**macOS** — the application is code-signed with an Apple Developer ID
certificate, notarized by Apple, and the notarization ticket is stapled to the
bundle. macOS may show a dialog on first open confirming that the app was
checked for malicious software; click **Open**. No right-click workaround is
needed, and the app works offline because the ticket travels with it.

**Windows (SmartScreen)** — the Windows executable is not yet code-signed, so
Windows may show a blue "Windows protected your PC" window on first run. Click
**More info** → **Run anyway**. This appears because the executable does not
carry a publisher signature, not because anything is wrong with the download.
Windows code signing is planned for a future release.

## Option 2 — PyPI

If you already have Python 3.10 or later, install the published package:

```bash
pip install pysternblot
pysternblot
```

`pysternblot` is the command that launches the application. The equivalent
`python -m pysternblot` also works if you prefer the module form.

To upgrade to the latest release later:

```bash
pip install --upgrade pysternblot
```

Installing inside a virtual environment is recommended so Pystern Blot's
dependencies stay isolated from other projects:

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
pip install pysternblot
pysternblot
```

## Option 3 — From source

Use this if you want the development version or intend to contribute. See the
[contributing guide](contributing.md) for the full development setup.

```bash
git clone https://github.com/TheBrickalista/PysternBlot.git
cd PysternBlot
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
pip install -e .
pysternblot
```

The `-e` flag installs in *editable* mode, so changes you make to the source are
picked up the next time you launch.

## Requirements

The requirements below apply only to the PyPI and from-source methods. The
standalone builds bundle everything, including Python itself.

- Python ≥ 3.10
- PySide6 ≥ 6.6
- Pydantic ≥ 2.6
- NumPy ≥ 1.24
- Pillow ≥ 10.0

Dependencies are installed automatically by `pip`; you do not need to install
them by hand.

## Verifying the installation

When Pystern Blot launches successfully you will see the **Home** tab. To
confirm which version you are running, open the **About** tab.

From a Python install you can also check the version on the command line:

```bash
pip show pysternblot
```

## Workspace location

On first launch Pystern Blot creates a workspace folder in your home directory.
This is where projects, the imported image store, operation logs, and integrity
reports are kept.

- **macOS:** `~/.pysternblot/`
- **Windows:** `C:\Users\<username>\.pysternblot\`

## Troubleshooting

**The `pysternblot` command is not found after `pip install`.** The install
location may not be on your `PATH`. Try launching with `python -m pysternblot`,
or ensure your Python scripts directory is on your `PATH`.

**`pip install` fails on the Python version.** Confirm you are on Python 3.10 or
later with `python --version`. On systems with both Python 2 and 3, you may need
`python3` and `pip3`.

**macOS reports the app is damaged or cannot be opened.** Make sure you unzipped
the download with Finder or `ditto` rather than a third-party archive tool; some
tools do not preserve the symbolic links inside the application bundle, which
corrupts it. Re-download and unzip by double-clicking the `.zip` in Finder.

**Still stuck?** Open an issue on the
[GitHub repository](https://github.com/TheBrickalista/PysternBlot/issues).

## Next steps

Once installed, the [Quickstart](quickstart.md) walks you through preparing your
first figure — and you can explore a pre-annotated example project without
needing your own images.
