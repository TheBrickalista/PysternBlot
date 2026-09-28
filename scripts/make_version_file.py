# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""Generate a PyInstaller Windows version-file from pyproject.toml's version.

pyproject.toml is the single source of truth for the app version; nothing
here hard-codes it. The macOS build's inline PlistBuddy step shares
parse_version() with this script (see build-macos.yml), so both platforms
reject the same non-conforming versions the same way.

Usage:
    python scripts/make_version_file.py [PYPROJECT_PATH] [OUT_PATH]

Defaults: PYPROJECT_PATH=pyproject.toml, OUT_PATH=build/version_file.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 has no stdlib tomllib
    import tomli as tomllib  # type: ignore[no-redef]

# Strictly x.y.z, integers only -- no pre-release/build suffix (e.g. "1.3.0rc1"
# or "1.3.0+build.1"), and no 2- or 4-part forms. The OS-level version fields
# this feeds (CFBundleShortVersionString/CFBundleVersion, FileVersion/
# ProductVersion) all expect a plain numeric version; anything else is a
# build-time error, not something to silently coerce.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class InvalidVersionError(ValueError):
    pass


def parse_version(pyproject_path: str | Path) -> tuple[int, int, int]:
    """Read and validate project.version from pyproject.toml.

    Raises InvalidVersionError (never silently coerces) if it is missing or
    is not strictly x.y.z with integer components.
    """
    path = Path(pyproject_path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        raw = data["project"]["version"]
    except KeyError as exc:
        raise InvalidVersionError(f"No [project].version found in {path}") from exc

    match = _VERSION_RE.match(str(raw))
    if not match:
        raise InvalidVersionError(
            f"pyproject.toml version {raw!r} is not a plain x.y.z version "
            f"(integers only, no pre-release or build suffix). OS bundle/version "
            f"metadata requires exactly three integer components."
        )
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def render_version_file(version: tuple[int, int, int]) -> str:
    """Render a PyInstaller --version-file document for the given x.y.z."""
    x, y, z = version
    version_str = f"{x}.{y}.{z}.0"
    return f"""# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({x}, {y}, {z}, 0),
    prodvers=({x}, {y}, {z}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'PysternBlot contributors'),
        StringStruct(u'FileDescription', u'PysternBlot — western blot panel builder'),
        StringStruct(u'FileVersion', u'{version_str}'),
        StringStruct(u'InternalName', u'PysternBlot'),
        StringStruct(u'LegalCopyright', u'GPL-3.0-or-later'),
        StringStruct(u'OriginalFilename', u'PysternBlot.exe'),
        StringStruct(u'ProductName', u'PysternBlot'),
        StringStruct(u'ProductVersion', u'{version_str}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pyproject_path = argv[0] if len(argv) > 0 else "pyproject.toml"
    out_path = Path(argv[1] if len(argv) > 1 else "build/version_file.txt")

    try:
        version = parse_version(pyproject_path)
    except InvalidVersionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_version_file(version), encoding="utf-8")
    print(f"Wrote version file for {'.'.join(map(str, version))} to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
