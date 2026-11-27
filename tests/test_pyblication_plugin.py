# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""The Pyblication plugin (pysternblot/plugin.py, protocol v1).

identify() finds the project whose operation log records an export by its
SHA-256 and lists the files that make up the project; it never writes to
the workspace. open_project() only launches the app. The module must import
without Qt (Pyblication's CLI is headless).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pysternblot import __version__, paths, plugin
from pysternblot.logchain import append_log_entry
from pysternblot.models import (
    AssetEntry,
    Blot,
    BlotChannel,
    CalibrationPoint,
    ConditionRow,
    Crop,
    Group,
    HeaderBlock,
    Ladder,
    LaneLayout,
    Layout,
    OperationLogEntry,
    Panel,
    Project,
    ProjectMeta,
    ProteinLabel,
)

ROOT = Path(__file__).resolve().parents[1]


# -- a small workspace ------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset(ws: Path, data: bytes, ext: str = ".tif") -> str:
    sha = _sha(data)
    d = ws / "assets" / sha
    d.mkdir(parents=True, exist_ok=True)
    (d / f"original{ext}").write_bytes(data)
    return sha


def _blot(blot_id: str, sha: str, overlay: str | None = None, channels=()) -> Blot:
    return Blot(
        id=blot_id,
        asset_sha256=sha,
        overlay_asset_sha256=overlay,
        crop=Crop(x=0, y=0, w=10, h=10),
        ladder=Ladder(
            lane_index=0,
            marker_set_id="ms1",
            calibration_points=[CalibrationPoint(y_px=1, kda=55), CalibrationPoint(y_px=5, kda=36)],
        ),
        protein_label=ProteinLabel(text=blot_id),
        channels=list(channels),
    )


def _project(pid: str, name: str, blots: list[Blot], assets: dict | None = None) -> Project:
    n = max(len(blots), 1)
    return Project(
        project=ProjectMeta(id=pid, name=name, created_utc="2026-11-27T08:00:00Z", app_version="1.3.0"),
        assets=assets or {},
        panel=Panel(
            lane_layout=LaneLayout(
                header_block=HeaderBlock(
                    left_title="kDa",
                    groups=[Group(label="All", n_lanes=n)],
                    condition_rows=[ConditionRow(values=[""] * n)],
                )
            ),
            blots=blots,
            layout=Layout(order=[b.id for b in blots]),
        ),
    )


def _log_export(project: Project, export: Path, when: str, fmt: str = "svg") -> None:
    append_log_entry(
        project,
        OperationLogEntry(
            timestamp_utc=when,
            operation="export_generated",
            target_type="export",
            target_id=project.project.id,
            field=f"final_{fmt}",
            new_value={
                "path": str(export),
                "format": fmt,
                "sha256": _sha(export.read_bytes()),
                "size_bytes": export.stat().st_size,
            },
        ),
    )


def _save(ws: Path, project: Project) -> Path:
    d = ws / "projects" / project.project.id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "project.json"
    path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    return path


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "pysternblot-ws"
    (root / "projects").mkdir(parents=True)
    (root / "presets").mkdir()
    (root / "presets" / "protein_ladders.json").write_text('{"items": []}')
    monkeypatch.setenv(paths.WORKSPACE_ENV, str(root))
    return root


@pytest.fixture
def exported(ws, tmp_path):
    """A project with two blots and an overlay, and one logged SVG export."""
    a1 = _asset(ws, b"blot one pixels")
    a2 = _asset(ws, b"blot two pixels", ".png")
    ov = _asset(ws, b"membrane overlay", ".jpg")
    blots = [_blot("b1", a1, overlay=ov), _blot("b2", a2)]
    assets = {a1: AssetEntry(sha256=a1, stored_original_path=str(ws / "assets" / a1 / "original.tif"))}
    project = _project("proj_abc", "Actin study", blots, assets)
    export = tmp_path / "out" / "figure.svg"
    export.parent.mkdir()
    export.write_text("<svg>figure</svg>")
    _log_export(project, export, "2026-11-27T09:00:00+00:00")
    path = _save(ws, project)
    return project, path, export, (a1, a2, ov)


# -- identify ---------------------------------------------------------------------------------


def test_identify_members_and_provenance(ws, exported):
    project, path, export, (a1, a2, ov) = exported
    r = plugin.identify(str(export))
    assert (r["project_id"], r["project_name"]) == ("proj_abc", "Actin study")
    members = {m["name"]: m for m in r["members"]}
    assert set(members) == {
        "project.json",
        f"assets/{a1}/original.tif",
        f"assets/{a2}/original.png",
        f"assets/{ov}/original.jpg",
    }
    assert members["project.json"] == {"path": str(path), "role": "project", "name": "project.json"}
    for sha, ext in ((a1, ".tif"), (a2, ".png"), (ov, ".jpg")):
        m = members[f"assets/{sha}/original{ext}"]
        assert m["role"] == "raw" and m["sha256"] == sha
        assert m["path"] == str(ws / "assets" / sha / f"original{ext}")
        assert _sha(Path(m["path"]).read_bytes()) == sha
    # No preset member: rendering reads project.marker_sets, not presets/.
    assert not any(n.startswith("presets/") for n in members)

    prov = r["provenance"]
    entry = project.operation_log[-1]
    assert prov["export"] == {
        "timestamp_utc": "2026-11-27T09:00:00+00:00",
        "format": "svg",
        "size_bytes": export.stat().st_size,
        "field": "final_svg",
        "path": str(export),
        "entry_hash": entry.entry_hash,
        "prev_hash": entry.prev_hash,
    }
    assert prov["log_chain"]["status"] == "ok"
    assert prov["pysternblot_version"] == __version__
    assert "also_logged_in" not in prov


def test_unknown_or_missing_file_is_none(ws, exported, tmp_path):
    other = tmp_path / "other.svg"
    other.write_text("<svg>not exported by PysternBlot</svg>")
    assert plugin.identify(str(other)) is None
    assert plugin.identify(str(tmp_path / "does-not-exist.svg")) is None


def test_empty_or_absent_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.WORKSPACE_ENV, str(tmp_path / "nowhere"))
    f = tmp_path / "a.svg"
    f.write_text("<svg/>")
    assert plugin.identify(str(f)) is None


def test_same_export_in_two_projects_picks_most_recent(ws, exported):
    _, _, export, (a1, _, _) = exported
    later = _project("proj_zzz", "Copy", [_blot("b1", a1)])
    _log_export(later, export, "2026-11-27T10:00:00Z")
    _save(ws, later)
    earlier = _project("proj_old", "Old", [_blot("b1", a1)])
    _log_export(earlier, export, "2026-11-26T10:00:00Z")
    _save(ws, earlier)
    r = plugin.identify(str(export))
    assert r["project_id"] == "proj_zzz"
    assert r["provenance"]["also_logged_in"] == ["proj_abc", "proj_old"]


def test_missing_asset_is_still_listed(ws, exported):
    _, _, export, (a1, a2, _) = exported
    (ws / "assets" / a2 / "original.png").unlink()
    (ws / "assets" / a1 / "original.tif").unlink()
    (ws / "assets" / a1).rmdir()
    names = {m["name"]: m for m in plugin.identify(str(export))["members"]}
    # a2: the asset folder is there, its file is not: name and hash kept.
    assert f"assets/{a2}/original" in names and names[f"assets/{a2}/original"]["sha256"] == a2
    # a1: the folder is gone too; the extension comes from its AssetEntry.
    assert names[f"assets/{a1}/original.tif"]["path"] == str(ws / "assets" / a1 / "original.tif")


def test_nir_channel_assets_are_members(ws, tmp_path):
    c1 = _asset(ws, b"700 nm channel")
    c2 = _asset(ws, b"800 nm channel")
    blot = _blot("nir", c1, channels=[
        BlotChannel(asset_sha256=c1, channel_index=0),
        BlotChannel(asset_sha256=c2, channel_index=1),
    ])  # fmt: skip
    blot.modality = "nir_fluorescence"
    project = _project("proj_nir", "NIR", [blot])
    export = tmp_path / "nir.png"
    export.write_bytes(b"\x89PNG nir")
    _log_export(project, export, "2026-11-27T09:00:00Z", "png")
    _save(ws, project)
    names = {m["name"] for m in plugin.identify(str(export))["members"]}
    assert {f"assets/{c1}/original.tif", f"assets/{c2}/original.tif"} <= names


def test_broken_chain_is_reported(ws, exported):
    _, path, export, _ = exported
    data = json.loads(path.read_text())
    data["operation_log"][0]["note"] = "tampered"  # changes a hashed field
    path.write_text(json.dumps(data))
    assert plugin.identify(str(export))["provenance"]["log_chain"]["status"] == "broken"


def test_invalid_project_still_identifies(ws, exported):
    _, path, export, _ = exported
    data = json.loads(path.read_text())
    del data["panel"]["layout"]  # no longer a valid Project
    path.write_text(json.dumps(data))
    r = plugin.identify(str(export))
    assert r["project_id"] == "proj_abc"
    assert r["provenance"]["log_chain"] == {"status": "unreadable"}


def test_unreadable_project_json_is_skipped(ws, exported):
    _, _, export, _ = exported
    bad = ws / "projects" / "proj_bad"
    bad.mkdir()
    (bad / "project.json").write_text("{ not json")
    assert plugin.identify(str(export))["project_id"] == "proj_abc"


def _snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.stat()
        out[str(p)] = (st.st_mtime_ns, st.st_size, _sha(p.read_bytes()) if p.is_file() else None)
    return out


def test_identify_never_writes_to_the_workspace(ws, exported):
    _, _, export, _ = exported
    before = _snapshot(ws)
    assert plugin.identify(str(export)) is not None
    assert plugin.identify(str(export) + ".nope") is None
    assert _snapshot(ws) == before


# -- open_project ----------------------------------------------------------------------------


def test_open_project_launches_the_app_only(ws, exported):
    _, path, _, _ = exported
    before = _snapshot(ws)
    with patch.object(plugin.subprocess, "Popen") as popen:
        assert plugin.open_project("proj_abc", str(path)) is None
    (cmd,), kwargs = popen.call_args
    assert cmd == [sys.executable, "-m", "pysternblot", "--project", "proj_abc"]
    assert kwargs["env"][paths.WORKSPACE_ENV] == str(ws)
    assert kwargs["start_new_session"] is True
    assert _snapshot(ws) == before


def test_open_project_without_path_keeps_environment(ws, monkeypatch):
    monkeypatch.setenv(paths.WORKSPACE_ENV, "/somewhere/else")
    with patch.object(plugin.subprocess, "Popen") as popen:
        plugin.open_project("proj_abc", None)
    assert popen.call_args.kwargs["env"][paths.WORKSPACE_ENV] == "/somewhere/else"


# -- paths / no Qt -------------------------------------------------------------------------------


def test_default_workspace(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.WORKSPACE_ENV, raising=False)
    assert paths.default_workspace() == Path.home() / ".pysternblot"
    monkeypatch.setenv(paths.WORKSPACE_ENV, str(tmp_path / "w"))
    assert paths.default_workspace() == tmp_path / "w"


def test_plugin_imports_without_qt(ws, exported):
    """Pyblication runs headless: loading the plugin and identifying an
    export must not import PySide6."""
    _, _, export, _ = exported
    code = (
        "import sys, pysternblot.plugin as p\n"
        "d = p.describe()\n"
        f"r = p.identify({str(export)!r})\n"
        "assert r is not None and r['project_id'] == 'proj_abc', r\n"
        "assert not [m for m in sys.modules if m.split('.')[0] == 'PySide6'], 'Qt imported'\n"
        "print('ok')\n"
    )
    env = dict(os.environ, **{paths.WORKSPACE_ENV: str(ws)})
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
