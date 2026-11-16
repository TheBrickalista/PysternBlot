# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
One way to find the active NIR channel.

_active_nir_channel holds a channel_index (the channel selector's button ids
are channel_index values). Every path (the Original Image view, display and
label edits, crop moves, log entries, gesture keys, the legend-zone export)
must resolve it to the same BlotChannel, also when the blot's channels are
not numbered 0..n-1.

Such a blot comes from the real import: a single Typhoon file whose Tag 270
"Scan number" is 2/2 (tests/20260507-142651-[IRshort].tif) is imported as
channel_index 1 alone. [1, 2] and [0, 2] need a 3-channel scan (no fixture);
[2, 0] (out of order) never comes from an import and is checked defensively.
"""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QDialog, QGraphicsPixmapItem

from pysternblot import render
from pysternblot.models import AssetEntry, Blot, BlotChannel, Crop, CropTemplate, DisplaySettings, ProteinLabel
from pysternblot.storage import Workspace
from pysternblot.ui import export_mixin as export_mixin_module
from pysternblot.ui import nir_import_dialog as nir_import_dialog_module
from pysternblot.ui.main_window import MainWindow

from test_commit_old_values import _crop_item, _drag
from test_source_export import _minimal_ladder, _minimal_project, _write_asset
from test_view_zoom_preserved import _show_tab_of

ROOT = Path(__file__).resolve().parent.parent
IRLONG = ROOT / "tests" / "20260507-142651-[IRlong].tif"      # Scan number 1/2
IRSHORT = ROOT / "tests" / "20260507-142651-[IRshort].tif"    # Scan number 2/2
NIR = "blot_nir"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _show(win):
    win.resize(1200, 900)
    win.show()
    _show_tab_of(win, win.prov_view)
    return win


def _window_with_channels(tmp_path, indices) -> MainWindow:
    """A NIR blot whose channels have these channel_index values, in this
    list order, each with its own display, crop and (alternating) asset."""
    ws_dir = tmp_path / "ws"
    files = [IRLONG, IRSHORT]
    shas = [_write_asset(ws_dir, f.read_bytes(), ".tif") for f in files]
    assets = {s: AssetEntry(sha256=s, stored_original_path=str(ws_dir / "assets" / s / "original.tif"))
              for s in shas}
    channels = [
        BlotChannel(
            channel_index=i, asset_sha256=shas[k % 2],
            display=DisplaySettings(levels_black=500 + 300 * i, levels_gamma=1.0 + 0.3 * i,
                                    rotation_deg=0.5 * i, invert=bool(i % 2)),
            crop=Crop(x=100 + 60 * i, y=300 + 80 * i, w=400, h=150),
        )
        for k, i in enumerate(indices)
    ]
    blot = Blot(id=NIR, asset_sha256=shas[0], crop=Crop(x=20, y=20, w=400, h=150),
                ladder=_minimal_ladder(), protein_label=ProteinLabel(text="N"),
                modality="nir_fluorescence", channels=channels)
    project = _minimal_project([blot], assets=assets)
    project.panel.crop_template = CropTemplate(w=400.0, h=150.0)
    ws = Workspace(root=ws_dir)
    ws.ensure()
    win = MainWindow(ws)
    win.current_project = project
    win.active_blot_id = NIR
    ws.save_project(project)
    win.refresh_previews(fit_figure=True, fit_original=True)
    return _show(win)


def _window_from_real_single_file_import(tmp_path) -> MainWindow:
    """Import IRshort alone (Scan number 2/2) through the real UI handler."""
    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    win = MainWindow(ws)
    proj_path = ws.create_new_project("single channel")
    win.current_project = ws.load_project(str(proj_path))
    win.refresh_previews()

    class FakeDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

        channel1_path = IRSHORT
        channel2_path = None

    with patch.object(nir_import_dialog_module, "NirImportDialog", FakeDialog), \
         patch("pysternblot.ui.project_io_mixin.QMessageBox"):
        win._on_import_nir_blot()
    return _show(win)


def _select(win, channel_index):
    if win._nir_ch_btn_group is not None:
        win._on_nir_channel_changed(channel_index)


def _channel(blot, channel_index):
    return next(c for c in blot.channels if c.channel_index == channel_index)


def _view_image(win):
    items = [i for i in win.prov_view.scene().items()
             if isinstance(i, QGraphicsPixmapItem) and i.opacity() == 1.0]
    assert len(items) == 1
    return items[0].pixmap().toImage()


def _expected_image(win, ch):
    d = ch.display
    pm = render._load_rotated_display_pixmap(
        win.workspace.root, ch.asset_sha256, d.rotation_deg, black=d.levels_black,
        white=d.levels_white, gamma=d.levels_gamma, invert=d.invert,
        flip_horizontal=d.flip_horizontal, flip_vertical=d.flip_vertical)
    return pm.toImage()


def _check_channel_consistency(win, ch_index):
    """Everything about the active channel resolves to channel ch_index."""
    blot = win._get_active_blot()
    ch = _channel(blot, ch_index)
    others = {c.channel_index: (c.display.model_dump(), c.crop.model_dump() if c.crop else None)
              for c in blot.channels if c.channel_index != ch_index}

    # The view shows this channel with its own display settings.
    assert _view_image(win) == _expected_image(win, ch), "view does not show the channel"
    # Controls read this channel.
    assert win._active_display() is ch.display
    assert win._get_active_channel_or_blot() is ch

    # A display edit changes this channel, the view follows, the log names it.
    n = len(win.current_project.operation_log)
    win.black_value_edit.setText(str(ch.display.levels_black + 777))
    win._on_black_value_edited()
    (lv,) = [e for e in win.current_project.operation_log[n:] if e.operation == "levels_changed"]
    assert ch.display.levels_black == lv.new_value["black"]
    assert lv.asset_sha256 == ch.asset_sha256
    assert f"NIR channel {ch_index} (Ch{ch_index + 1})" in lv.note
    assert _view_image(win) == _expected_image(win, ch), "view did not follow the edit"

    # A gesture is keyed on this channel.
    win.levels_gamma_slider.setValue(win.levels_gamma_slider.value() + 7)
    assert win._gesture_committer._pending["key"][4] == ch_index
    win._gesture_committer.flush()

    # A crop drag moves this channel's crop and logs it.
    crop0 = blot.get_channel_crop(ch_index).model_dump()
    n = len(win.current_project.operation_log)
    _drag(win.prov_view, _crop_item(win).crop_scene_rect().center(), QPointF(23, 17))
    crop1 = blot.get_channel_crop(ch_index).model_dump()
    assert (crop1["x"], crop1["y"]) == (crop0["x"] + 23, crop0["y"] + 17), "crop did not move"
    (cc,) = [e for e in win.current_project.operation_log[n:] if e.operation == "crop_committed"]
    assert cc.asset_sha256 == ch.asset_sha256 and cc.new_value == crop1
    assert f"NIR channel {ch_index} (Ch{ch_index + 1})" in cc.note

    # The legend-zone export draws this channel.
    seen = {}
    real = export_mixin_module._load_rotated_display_pixmap

    def spy(root, sha, *a, **k):
        seen["sha"], seen["black"] = sha, k.get("black")
        return real(root, sha, *a, **k)

    win.legend_zone_cb.setChecked(True)
    out = win.workspace.root.parent / f"zone_{ch_index}.png"
    with ExitStack() as stack:
        stack.enter_context(patch.object(export_mixin_module, "_load_rotated_display_pixmap", spy))
        stack.enter_context(patch.object(
            export_mixin_module.QFileDialog, "getSaveFileName", return_value=(str(out), "")))
        stack.enter_context(patch.object(export_mixin_module.QMessageBox, "information"))
        critical = stack.enter_context(patch.object(export_mixin_module.QMessageBox, "critical"))
        win.export_legend_zone_png()
    assert not critical.called, critical.call_args
    assert (seen["sha"], seen["black"]) == (ch.asset_sha256, ch.display.levels_black)
    win.legend_zone_cb.setChecked(False)

    # The other channels were not touched.
    for c in blot.channels:
        if c.channel_index != ch_index:
            assert (c.display.model_dump(), c.crop.model_dump() if c.crop else None) == \
                others[c.channel_index]


# --------------------------------------------------------------------------
# A blot from the real import: IRshort alone -> channel_index [1]
# --------------------------------------------------------------------------
def test_real_single_file_import_gives_a_channel_set_not_starting_at_0(qapp, tmp_path):
    win = _window_from_real_single_file_import(tmp_path)
    blot = win._get_active_blot()
    assert blot.is_nir() and [c.channel_index for c in blot.channels] == [1]


def test_real_single_file_import_resolves_one_channel_everywhere(qapp, tmp_path):
    win = _window_from_real_single_file_import(tmp_path)
    assert win._active_nir_channel == 1                 # normalised to the only channel
    _check_channel_consistency(win, 1)


# --------------------------------------------------------------------------
# Constructed channel sets
# --------------------------------------------------------------------------
@pytest.mark.parametrize("indices,select", [
    ([1, 2], 1), ([1, 2], 2),
    ([0, 2], 0), ([0, 2], 2),
    ([2, 0], 0), ([2, 0], 2),
], ids=["12-1", "12-2", "02-0", "02-2", "20-0", "20-2"])
def test_each_selected_channel_is_the_one_edited_rendered_cropped_and_logged(
        qapp, tmp_path, indices, select):
    win = _window_with_channels(tmp_path, indices)
    _select(win, select)
    assert win._active_nir_channel == select
    _check_channel_consistency(win, select)


def test_no_matching_channel_falls_back_to_the_lowest_index(qapp, tmp_path):
    # e.g. switching from a blot with channel 0 to one with channels [1, 2]
    win = _window_with_channels(tmp_path, [2, 1])
    blot = win._get_active_blot()
    win._active_nir_channel = 0                         # stale: no such channel
    assert win._active_channel(blot) is _channel(blot, 1)
    win._sync_controls_from_project()                   # selector rebuilt -> normalised
    assert win._active_nir_channel == 1
