# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
On-disk format migrations of project.json, applied to the raw JSON dict
before Pydantic validation.

Each step takes the dict at version N and returns it at version N + 1. A
project whose version is newer than PROJECT_FORMAT_VERSION is never
migrated, loaded or saved over: check_supported() refuses it.

Version history
---------------
0       Projects written before versioning (no ``project.format_version``).
0 -> 1  Only the version stamp is added; nothing else changes, so the step
        is not recorded in the operation log. A later step that changes
        data should be logged by the loader.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from .models import PROJECT_FORMAT_VERSION


class ProjectFormatTooNewError(ValueError):
    """project.json was written by a newer PysternBlot than this one."""

    def __init__(self, version: int, path: str | Path | None = None):
        self.version = version
        self.path = path
        where = f"{path}\n\n" if path else ""
        super().__init__(
            f"{where}This project was saved by a newer PysternBlot "
            f"(project format {version}; this version supports up to "
            f"{PROJECT_FORMAT_VERSION}). Please update PysternBlot to open it."
        )


def read_format_version(data: Any) -> int:
    """project.format_version of a raw project dict; 0 when absent."""
    meta = data.get("project") if isinstance(data, dict) else None
    value = meta.get("format_version", 0) if isinstance(meta, dict) else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        # An unreadable stamp cannot be proven old: treat it as too new.
        return PROJECT_FORMAT_VERSION + 1


def check_supported(data: Any, path: str | Path | None = None) -> int:
    """Raise ProjectFormatTooNewError if data is newer than this app."""
    version = read_format_version(data)
    if version > PROJECT_FORMAT_VERSION:
        raise ProjectFormatTooNewError(version, path)
    return version


def _v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
    return data


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    0: _v0_to_v1,
}


def migrate_project_dict(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Bring a raw project dict up to PROJECT_FORMAT_VERSION.

    Returns (migrated copy, original version). Versions at or above this
    app's are returned unchanged (the loader refuses newer ones)."""
    version = read_format_version(data)
    if version >= PROJECT_FORMAT_VERSION:
        return data, version
    out = copy.deepcopy(data)
    v = max(version, 0)
    while v < PROJECT_FORMAT_VERSION:
        out = MIGRATIONS[v](out)
        v += 1
    if isinstance(out.get("project"), dict):
        out["project"]["format_version"] = PROJECT_FORMAT_VERSION
    return out, version
