# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
NIR log entries name the channel that changed.

Convention (as nir_channel_imported and the NIR export entries already do):
asset_sha256 is the channel's own asset, and the note says
"NIR channel <i> (Ch<i+1>)" with i = channel_index. Field names are the
same as for ECL. ECL entries are unchanged.

The two NIR channels here use different real TIFFs, so the asset hash
alone tells which channel an entry names.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pysternblot.logchain import append_log_entry, verify_log_chain
from pysternblot.models import (
    AssetEntry, OperationLogEntry, Blot, BlotChannel, Crop, CropTemplate, DisplaySettings, ProteinLabel,
)
from pysternblot.storage import Workspace
from pysternblot.ui.main_window import MainWindow

from test_refresh_scope_staleness import _activate, _crop_move_commit
from test_source_export import _minimal_ladder, _minimal_project, _write_asset

ROOT = Path(__file__).resolve().parent.parent
CHEMI = ROOT / "examples" / "Chemi_16.tif"
RHOA = ROOT / "tests" / "rhoa 20260220_131003_Ch_Chemi.tif"
IRLONG = ROOT / "tests" / "20260507-142651-[IRlong].tif"

ECL, NIR = "blot_ecl", "blot_nir"
ECL_NOTE = "Crop rectangle committed after user interaction."


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def win(qapp, tmp_path):
    ws_dir = tmp_path / "ws"
    sha = {p: _write_asset(ws_dir, p.read_bytes(), ".tif") for p in (CHEMI, RHOA, IRLONG)}
    assets = {
        s: AssetEntry(sha256=s, stored_original_path=str(ws_dir / "assets" / s / "original.tif"))
        for s in sha.values()
    }
    blots = [
        Blot(id=ECL, asset_sha256=sha[CHEMI], crop=Crop(x=300, y=400, w=400, h=150),
             ladder=_minimal_ladder(), protein_label=ProteinLabel(text="E")),
        Blot(id=NIR, asset_sha256=sha[IRLONG], crop=Crop(x=500, y=900, w=400, h=150),
             ladder=_minimal_ladder(), protein_label=ProteinLabel(text="N"),
             modality="nir_fluorescence",
             channels=[
                 BlotChannel(channel_index=0, asset_sha256=sha[IRLONG],
                             display=DisplaySettings(levels_black=900)),
                 BlotChannel(channel_index=1, asset_sha256=sha[RHOA],
                             crop=Crop(x=200, y=600, w=400, h=150),
                             display=DisplaySettings(levels_gamma=1.8)),
             ]),
    ]
    project = _minimal_project(blots, assets=assets)
    project.panel.crop_template = CropTemplate(w=400.0, h=150.0)
    ws = Workspace(root=ws_dir)
    ws.ensure()
    w = MainWindow(ws)
    w.current_project = project
    w.active_blot_id = ECL
    ws.save_project(project)
    w.refresh_previews()
    w.channel_sha = {0: sha[IRLONG], 1: sha[RHOA]}
    w.ecl_sha = sha[CHEMI]
    return w


def _blot(win, blot_id):
    return next(b for b in win.current_project.panel.blots if b.id == blot_id)


def _last(win, operation):
    entries = [e for e in win.current_project.operation_log if e.operation == operation]
    assert entries, f"no {operation} entry"
    return entries[-1]


def _channel_note(i):
    return f"NIR channel {i} (Ch{i + 1})"


def test_fixture_channels_have_distinct_assets(win):
    assert win.channel_sha[0] != win.channel_sha[1]


# --------------------------------------------------------------------------
# 3a: crop_committed
# --------------------------------------------------------------------------
@pytest.mark.parametrize("channel", [0, 1])
def test_nir_crop_commit_logs_the_moved_channels_crop(win, channel):
    _activate(win, NIR, channel=channel)
    blot = _blot(win, NIR)
    other = 1 - channel
    other_before = blot.get_channel_crop(other).model_dump()
    fallback_before = blot.crop.model_dump()

    _crop_move_commit(win, dx=37.0, dy=-21.0)

    moved = blot.get_channel_crop(channel)
    entry = _last(win, "crop_committed")
    assert entry.target_id == NIR and entry.field == "crop"
    assert entry.asset_sha256 == win.channel_sha[channel]
    assert entry.new_value == moved.model_dump()
    assert entry.new_value != fallback_before          # not the blot's fallback crop
    assert _channel_note(channel) in entry.note and entry.note.startswith(ECL_NOTE)
    # Only that channel's crop moved; the fallback blot.crop is untouched.
    assert blot.get_channel_crop(other).model_dump() == other_before
    assert blot.crop.model_dump() == fallback_before
    assert verify_log_chain(win.current_project).status == "ok"


def test_ecl_crop_commit_entry_is_unchanged(win):
    _activate(win, ECL)
    _crop_move_commit(win, dx=12.0, dy=8.0)
    blot = _blot(win, ECL)
    entry = _last(win, "crop_committed")
    assert entry.asset_sha256 == win.ecl_sha
    assert entry.new_value == blot.crop.model_dump()
    assert entry.note == ECL_NOTE
    assert entry.old_value is None


def test_old_style_nir_crop_entries_still_verify_as_written(win):
    # An entry written before this fix (blot asset, fallback crop, no channel
    # in the note) stays in the log as it is and still verifies.
    blot = _blot(win, NIR)
    append_log_entry(win.current_project, OperationLogEntry(
        timestamp_utc="2026-11-01T10:00:00+00:00", operation="crop_committed",
        target_type="blot", target_id=NIR, asset_sha256=blot.asset_sha256, field="crop",
        old_value=None, new_value=blot.crop.model_dump(), note=ECL_NOTE,
    ))
    _activate(win, NIR, channel=1)
    _crop_move_commit(win)                              # a new-style entry after it
    win._save_project()
    path = win.workspace.projects_dir / win.current_project.project.id / "project.json"
    reloaded = win.workspace.load_project(str(path))
    assert verify_log_chain(reloaded).status == "ok"
    old, new = [e for e in reloaded.operation_log if e.operation == "crop_committed"][-2:]
    assert old.note == ECL_NOTE and old.asset_sha256 == blot.asset_sha256
    assert _channel_note(1) in new.note and new.asset_sha256 == win.channel_sha[1]
