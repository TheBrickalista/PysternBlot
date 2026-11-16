# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Narrowed refresh scopes never leave a stale crop preview.

Each handler whose refresh scope was narrowed ("none", "active", or the
Original Image view only) is triggered on a window with three real-TIFF
blots: two ECL blots and one NIR blot with two channels. Afterwards, every
preview_crop_*.tif on disk must be pixel-identical to a fresh
ensure_blot_crop_preview of the current model.

The tests also record which previews the handler regenerated, so a scope
that drifts back to "all" (or to the wrong blot) is caught.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from pysternblot.models import (
    AssetEntry, Blot, BlotChannel, Crop, CropTemplate, DisplaySettings, ProteinLabel,
)
from pysternblot.storage import Workspace
from pysternblot.ui import overlay_ladder_mixin as overlay_ladder_module
from pysternblot.ui.main_window import MainWindow

from test_source_export import _minimal_ladder, _minimal_project, _write_asset

ROOT = Path(__file__).resolve().parent.parent
CHEMI = ROOT / "examples" / "Chemi_16.tif"
RHOA = ROOT / "tests" / "rhoa 20260220_131003_Ch_Chemi.tif"
IRLONG = ROOT / "tests" / "20260507-142651-[IRlong].tif"

ECL_A, ECL_B, NIR = "blot_01", "blot_02", "blot_03"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _window(tmp_path) -> MainWindow:
    ws_dir = tmp_path / "ws"
    shas = {p: _write_asset(ws_dir, p.read_bytes(), ".tif") for p in (CHEMI, RHOA, IRLONG)}
    assets = {
        sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.tif"))
        for sha in shas.values()
    }
    blots = [
        Blot(id=ECL_A, asset_sha256=shas[CHEMI], crop=Crop(x=300, y=400, w=400, h=150),
             ladder=_minimal_ladder(), protein_label=ProteinLabel(text="A"),
             display=DisplaySettings(rotation_deg=1.5, levels_white=30000)),
        Blot(id=ECL_B, asset_sha256=shas[RHOA], crop=Crop(x=250, y=700, w=400, h=150),
             ladder=_minimal_ladder(), protein_label=ProteinLabel(text="B"),
             display=DisplaySettings(rotation_deg=-2.0, levels_black=800)),
        Blot(id=NIR, asset_sha256=shas[IRLONG], crop=Crop(x=500, y=900, w=400, h=150),
             ladder=_minimal_ladder(), protein_label=ProteinLabel(text="N"),
             modality="nir_fluorescence",
             channels=[
                 BlotChannel(channel_index=0, asset_sha256=shas[IRLONG],
                             display=DisplaySettings(levels_black=900, levels_white=40000)),
                 BlotChannel(channel_index=1, asset_sha256=shas[IRLONG],
                             crop=Crop(x=520, y=1300, w=400, h=150),
                             display=DisplaySettings(rotation_deg=3.0, levels_gamma=1.8)),
             ]),
    ]
    project = _minimal_project(blots, assets=assets)
    project.panel.crop_template = CropTemplate(w=400.0, h=150.0)
    ws = Workspace(root=ws_dir)
    ws.ensure()
    win = MainWindow(ws)
    win.current_project = project
    win.active_blot_id = ECL_A
    ws.save_project(project)
    win.refresh_previews()          # all previews exist and are fresh
    return win


def _activate(win, blot_id, channel=None):
    win.prov_blot_combo.setCurrentIndex(win.prov_blot_combo.findData(blot_id))
    assert win.active_blot_id == blot_id
    if channel is not None:
        win._on_nir_channel_changed(channel)


@contextmanager
def _regenerated():
    """Record (blot_id, channel_index) for every preview the code regenerates."""
    calls = []
    real = Workspace.ensure_blot_crop_preview

    def wrapper(self_ws, blot, panel, channel_index=-1, **kw):
        calls.append((blot.id, channel_index))
        return real(self_ws, blot, panel, channel_index=channel_index, **kw)

    with patch.object(Workspace, "ensure_blot_crop_preview", wrapper):
        yield calls


def _assert_previews_fresh(win):
    ws, project = win.workspace, win.current_project
    on_disk = {
        p.relative_to(ws.assets_dir): tifffile.imread(p)
        for p in ws.assets_dir.glob("*/preview_crop_*.tif")
    }
    expected = set()
    for blot in project.panel.blots:
        indices = [ch.channel_index for ch in blot.channels] if blot.is_nir() else [-1]
        for idx in indices:
            path = ws.ensure_blot_crop_preview(blot, project.panel, channel_index=idx, project=project)
            key = path.relative_to(ws.assets_dir)
            expected.add(key)
            assert key in on_disk, f"missing preview {key}"
            fresh = tifffile.imread(path)
            assert on_disk[key].shape == fresh.shape, key
            assert np.array_equal(on_disk[key], fresh), f"stale preview {key}"
    assert set(on_disk) == expected


ALL_NIR = [(NIR, 0), (NIR, 1)]


# (name, setup, action, regenerated previews expected from the action)
def _rotate_label(win):
    win.prov_rotate_label.setText("4.5")
    win._on_rotate_label_edited()           # -> _apply_rotation_immediately


def _typed_black(win):
    win.black_value_edit.setText("2500")
    win._on_black_value_edited()            # non-gesture branch of _on_levels_changed


def _crop_changed(win):
    blot = win._get_active_blot()
    blot.crop.x += 37
    blot.crop.y -= 21
    win._on_crop_changed(blot)


def _protein_label(win):
    win.protein_label_combo.setCurrentText("RhoA")
    win._on_protein_label_changed()


ACTIVE_CASES = [
    ("rotate_ccw", lambda w: w._on_rotate_ccw()),
    ("rotate_cw", lambda w: w._on_rotate_cw()),
    ("flip_horizontal", lambda w: w._flip_h_btn.click()),
    ("flip_vertical", lambda w: w._on_flip_vertical()),
    ("invert", lambda w: w.invert_cb.setChecked(not w.invert_cb.isChecked())),
    ("typed_rotation", _rotate_label),
    ("typed_levels", _typed_black),
]


@pytest.mark.parametrize("name,action", ACTIVE_CASES, ids=[c[0] for c in ACTIVE_CASES])
def test_active_scope_ecl(qapp, tmp_path, name, action):
    win = _window(tmp_path)
    _activate(win, ECL_B)                   # not the first blot
    with _regenerated() as calls:
        action(win)
    assert calls == [(ECL_B, -1)]
    _assert_previews_fresh(win)


@pytest.mark.parametrize("name,action", ACTIVE_CASES, ids=[c[0] for c in ACTIVE_CASES])
def test_active_scope_nir_channel(qapp, tmp_path, name, action):
    win = _window(tmp_path)
    _activate(win, NIR, channel=1)          # edits channel 1's display
    with _regenerated() as calls:
        action(win)
    assert calls == ALL_NIR
    _assert_previews_fresh(win)


NONE_CASES = [
    ("active_blot_changed", lambda w: _activate(w, NIR), []),
    ("nir_channel_changed", lambda w: (_activate(w, NIR), w._on_nir_channel_changed(1)), []),
    ("crop_changed", _crop_changed, [(ECL_B, -1)]),          # its own [blot] regeneration
    ("move_up", lambda w: w._move_active_blot_up(), []),
    ("move_down", lambda w: w._move_active_blot_down(), []),
    ("toggle_overlay", lambda w: w.overlay_cb.setChecked(not w.overlay_cb.isChecked()), []),
    ("prov_grid", lambda w: w.prov_grid_cb.setChecked(not w.prov_grid_cb.isChecked()), []),
    ("legend_zone", lambda w: w.legend_zone_cb.setChecked(not w.legend_zone_cb.isChecked()), []),
    ("protein_label", _protein_label, []),
    ("overlay_ladder_options", lambda w: w._save_overlay_ladder_options(), []),
]


@pytest.mark.parametrize("name,action,expected", NONE_CASES, ids=[c[0] for c in NONE_CASES])
def test_narrow_scope_handlers(qapp, tmp_path, name, action, expected):
    win = _window(tmp_path)
    _activate(win, ECL_B)
    with _regenerated() as calls:
        action(win)
    assert calls == expected
    _assert_previews_fresh(win)


def test_move_reorders_but_previews_are_per_blot_id(qapp, tmp_path):
    win = _window(tmp_path)
    _activate(win, ECL_B)
    win._move_active_blot_up()
    assert win.current_project.panel.layout.order[:2] == [ECL_B, ECL_A]
    _assert_previews_fresh(win)


def test_overlay_ladder_band_assign_clear_and_visibility(qapp, tmp_path):
    win = _window(tmp_path)
    _activate(win, ECL_B)
    kda = float(win.marker_set_library.items[0].bands[0].kda)

    with _regenerated() as calls:
        win._save_overlay_ladder_options()
        win.pending_overlay_ladder_kda = kda
        win._assign_pending_overlay_ladder_band(120.0)
    assert calls == []
    assert [b.kda for b in win._get_active_blot().overlay_ladder.bands] == [kda]
    _assert_previews_fresh(win)

    with patch.object(overlay_ladder_module.QMessageBox, "warning"):
        win._open_overlay_ladder_dialog()
    dialog, table = win.overlay_ladder_dialog, win.overlay_ladder_assignment_table
    assert dialog is not None and table is not None

    row = next(r for r in range(table.rowCount()) if float(table.item(r, 0).text()) == kda)
    with _regenerated() as calls:
        # Untick "show in final": itemChanged -> _sync_overlay_ladder_visibility_from_table
        table.item(row, 4).setCheckState(Qt.Unchecked)
        assert win._get_active_blot().overlay_ladder.bands[0].show_in_final is False
        table.setCurrentCell(row, 0)
        (clear_btn,) = [b for b in dialog.findChildren(QPushButton)
                        if b.text() == "Clear selected assignment"]
        clear_btn.click()                   # clear_selected
    assert calls == []
    assert win._get_active_blot().overlay_ladder.bands == []
    ops = [e.operation for e in win.current_project.operation_log]
    assert "overlay_ladder_visibility_changed" in ops
    assert ops[-1] == "overlay_ladder_assignment_cleared"
    _assert_previews_fresh(win)
    dialog.close()


def test_after_several_narrow_actions_everything_is_fresh(qapp, tmp_path):
    win = _window(tmp_path)
    _activate(win, ECL_B)
    win._on_rotate_cw()
    _typed_black(win)
    _activate(win, NIR, channel=1)
    win._on_flip_horizontal()
    win._move_active_blot_up()
    _activate(win, ECL_A)
    win.invert_cb.setChecked(True)
    _crop_changed(win)
    _assert_previews_fresh(win)
