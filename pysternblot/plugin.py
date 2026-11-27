# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""Pyblication plugin (plugin protocol v1).

Pyblication tracks the figures of a manuscript. When a panel export written
by PysternBlot lands in a Pyblication workspace, Pyblication asks this
plugin which project produced it, and which files make up that project, so
it can snapshot them with every revision of the panel.

Registered as an entry point (metadata only; PysternBlot never imports
Pyblication)::

    [project.entry-points."pyblication.plugins"]
    pysternblot = "pysternblot.plugin:describe"

The protocol is specified in Pyblication's docs/plugin-protocol.md.

Guarantees:

* No Qt: this module imports only the standard library and PysternBlot's
  pydantic models and log chain, so Pyblication's headless CLI can load it.
* Read-only: identify() reads project.json files and hashes files; it never
  writes to the workspace. open_project() only launches the app.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .paths import WORKSPACE_ENV, default_workspace

PROTOCOL = 1
_CHUNK = 1 << 20


def describe() -> dict[str, Any]:
    return {
        "name": "pysternblot",
        "version": __version__,
        "protocol": PROTOCOL,
        "app_name": "PysternBlot",
        "extensions": [".svg", ".pdf", ".png"],
        "identify": identify,
        "open_project": open_project,
    }


# -- identify -------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _when(timestamp: Any) -> datetime:
    """A log timestamp as an aware datetime; unparseable ones sort first."""
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_projects(workspace: Path):
    """(project.json path, parsed dict) for every readable project."""
    projects_dir = workspace / "projects"
    if not projects_dir.is_dir():
        return
    for path in sorted(projects_dir.glob("*/project.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            yield path, data


def _export_entries(data: dict, digest: str):
    """(log index, entry) of every export_generated entry for ``digest``."""
    log = data.get("operation_log")
    if not isinstance(log, list):
        return
    for index, entry in enumerate(log):
        if not isinstance(entry, dict) or entry.get("operation") != "export_generated":
            continue
        value = entry.get("new_value")
        if isinstance(value, dict) and value.get("sha256") == digest:
            yield index, entry


def _project_id(path: Path, data: dict) -> str:
    meta = data.get("project")
    if isinstance(meta, dict) and isinstance(meta.get("id"), str) and meta["id"]:
        return meta["id"]
    return path.parent.name


def _project_name(data: dict, fallback: str) -> str:
    meta = data.get("project")
    name = meta.get("name") if isinstance(meta, dict) else None
    return name if isinstance(name, str) and name.strip() else fallback


def _referenced_assets(data: dict) -> list[str]:
    """Every asset sha256 the project references: project.assets, each
    blot's asset and overlay asset, and each NIR channel's asset (rendering
    reads all of these)."""
    shas: set[str] = set()
    assets = data.get("assets")
    if isinstance(assets, dict):
        shas.update(k for k in assets if isinstance(k, str))
    panel = data.get("panel")
    blots = panel.get("blots") if isinstance(panel, dict) else None
    for blot in blots if isinstance(blots, list) else []:
        if not isinstance(blot, dict):
            continue
        for key in ("asset_sha256", "overlay_asset_sha256"):
            if isinstance(blot.get(key), str) and blot[key]:
                shas.add(blot[key])
        channels = blot.get("channels")
        for ch in channels if isinstance(channels, list) else []:
            if isinstance(ch, dict) and isinstance(ch.get("asset_sha256"), str):
                shas.add(ch["asset_sha256"])
    return sorted(s for s in shas if len(s) == 64 and all(c in "0123456789abcdef" for c in s))


def _asset_member(workspace: Path, data: dict, sha: str) -> dict[str, Any]:
    """assets/<sha>/original.<ext>, listed even when the file is missing
    (Pyblication reports it)."""
    asset_dir = workspace / "assets" / sha
    originals = sorted(asset_dir.glob("original.*")) if asset_dir.is_dir() else []
    if originals:
        path = originals[0]
    else:
        entry = (data.get("assets") or {}).get(sha)
        stored = entry.get("stored_original_path") if isinstance(entry, dict) else None
        suffix = Path(stored).suffix.lower() if isinstance(stored, str) else ""
        path = asset_dir / f"original{suffix}"
    return {
        "path": str(path.absolute()),
        "role": "raw",
        "name": f"assets/{sha}/{path.name}",
        "sha256": sha,  # assets are stored under the sha256 of their original
    }


def _log_chain(data: dict) -> dict[str, Any]:
    try:
        from .logchain import verify_log_chain
        from .models import Project

        result = verify_log_chain(Project.model_validate(data))
    except Exception:  # an invalid project still identifies its export
        return {"status": "unreadable"}
    return {
        "status": result.status,
        "n_entries": result.n_entries,
        "n_chained": result.n_chained,
        "first_broken_index": result.first_broken_index,
    }


def identify(export_path: str) -> dict[str, Any] | None:
    """The PysternBlot project whose operation log records this export.

    Searches workspace/projects/*/project.json for an ``export_generated``
    entry whose ``new_value.sha256`` is the file's SHA-256. None if the file
    isn't a PysternBlot export of this workspace. Read-only.
    """
    try:
        digest = _sha256(Path(export_path))
    except OSError:
        return None
    workspace = default_workspace()
    matches = []  # (when, index, project id, path, data, entry)
    for path, data in _read_projects(workspace):
        pid = _project_id(path, data)
        for index, entry in _export_entries(data, digest):
            matches.append((_when(entry.get("timestamp_utc")), index, pid, path, data, entry))
    if not matches:
        return None
    # Most recent entry; ties: later in its log, then project id.
    matches.sort(key=lambda m: (m[0], m[1], m[2]))
    _, _, pid, path, data, entry = matches[-1]
    others = sorted({m[2] for m in matches} - {pid})

    value = entry.get("new_value") or {}
    provenance: dict[str, Any] = {
        "project_id": pid,
        "project_name": _project_name(data, pid),
        "export": {
            "timestamp_utc": entry.get("timestamp_utc"),
            "format": value.get("format"),
            "size_bytes": value.get("size_bytes"),
            "field": entry.get("field"),
            "path": value.get("path"),
            "entry_hash": entry.get("entry_hash"),
            "prev_hash": entry.get("prev_hash"),
        },
        "log_chain": _log_chain(data),
        "pysternblot_version": __version__,
    }
    if others:
        provenance["also_logged_in"] = others

    members = [{"path": str(path.absolute()), "role": "project", "name": "project.json"}]
    members += [_asset_member(workspace, data, sha) for sha in _referenced_assets(data)]
    return {
        "project_id": pid,
        "project_name": provenance["project_name"],
        "members": members,
        "provenance": provenance,
    }


# -- open_project -------------------------------------------------------------------


def _command(project_id: str) -> list[str]:
    return [sys.executable, "-m", "pysternblot", "--project", project_id]


def open_project(project_id: str, project_path: str | None) -> None:
    """Launch PysternBlot on the project, as a separate process (no Qt in
    the caller's process). The workspace is the one holding project_path
    (…/projects/<id>/project.json), else the default one."""
    env = dict(os.environ)
    if project_path:
        p = Path(project_path)
        if p.name == "project.json" and p.parent.parent.name == "projects":
            env[WORKSPACE_ENV] = str(p.parent.parent.parent)
    subprocess.Popen(
        _command(project_id),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
