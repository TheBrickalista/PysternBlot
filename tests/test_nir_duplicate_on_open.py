# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Projects with NIR blots whose channels share a channel_index (written before
NIR imports refused them) are flagged when opened or imported from an
archive. The user chooses "Renumber channels" (unique indices in file order,
one logged entry per blot, previews rebuilt) or "Leave as is" (no change).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem

from pysternblot.logchain import verify_log_chain
from pysternblot.models import (
    AssetEntry, Blot, BlotChannel, Crop, CropTemplate, DisplaySettings, ProteinLabel,
)
from pysternblot.render import build_panel_scene
from pysternblot.storage import ImportArchiveResult, Workspace
from pysternblot.ui import project_io_mixin as project_io_module
from pysternblot.ui.main_window import MainWindow

from test_source_export import _minimal_ladder, _minimal_project, _write_asset

ROOT = Path(__file__).resolve().parent.parent
IRLONG = ROOT / "tests" / "20260507-142651-[IRlong].tif"
IRSHORT = ROOT / "tests" / "20260507-142651-[IRshort].tif"
NIR = "blot_nir"
TEMPLATE_W = 400.0


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _write_duplicate_project(ws: Workspace):
    """A project as an older version could write it: a NIR blot with two
    channel 0s, from two different files."""
    shas = [_write_asset(ws.root, f.read_bytes(), ".tif") for f in (IRLONG, IRSHORT)]
    assets = {
        s: AssetEntry(sha256=s, stored_original_path=str(ws.assets_dir / s / "original.tif"),
                      original_source_path=str(f))
        for s, f in zip(shas, (IRLONG, IRSHORT))
    }
    channels = [
        BlotChannel(channel_index=0, asset_sha256=shas[0], wavelength_nm=785,
                    display=DisplaySettings(levels_black=900),
                    crop=Crop(x=100, y=300, w=TEMPLATE_W, h=150)),
        BlotChannel(channel_index=0, asset_sha256=shas[1], wavelength_nm=685,
                    display=DisplaySettings(levels_black=1500, invert=True),
                    crop=Crop(x=250, y=500, w=TEMPLATE_W, h=150)),
    ]
    blot = Blot(id=NIR, asset_sha256=shas[0], crop=Crop(x=20, y=20, w=TEMPLATE_W, h=150),
                ladder=_minimal_ladder(), protein_label=ProteinLabel(text="N"),
                modality="nir_fluorescence", channels=channels)
    project = _minimal_project([blot], assets=assets)
    project.panel.crop_template = CropTemplate(w=TEMPLATE_W, h=150.0)
    ws.save_project(project)
    return project, ws.projects_dir / project.project.id / "project.json", shas


@pytest.fixture
def setup(qapp, tmp_path):
    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    project, path, shas = _write_duplicate_project(ws)
    win = MainWindow(ws)
    win.resize(1200, 900)
    win.show()
    return win, project, path, shas


def _open(win, path, choice: bool):
    shown = []

    def ask(text):
        shown.append(text)
        return choice

    win._ask_renumber_channels = ask
    with patch.object(project_io_module.QFileDialog, "getOpenFileName", return_value=(str(path), "")), \
         patch.object(project_io_module.QMessageBox, "information"), \
         patch.object(project_io_module.QMessageBox, "critical") as critical:
        win.open_project()
    assert not critical.called, critical.call_args
    return shown


def _figure_row_widths(win):
    scene = build_panel_scene(win.current_project, win.workspace.root)
    return sorted(i.pixmap().width() for i in scene.items() if isinstance(i, QGraphicsPixmapItem))


# --------------------------------------------------------------------------
def test_warning_names_the_blot_files_and_channel(setup):
    win, project, path, _ = setup
    (text,) = _open(win, path, choice=False)
    assert NIR in text
    assert IRLONG.name in text and IRSHORT.name in text
    assert "Ch1 used more than once" in text
    assert "Only the first of these channels can be selected and edited" in text
    assert "figure row shows its whole, uncropped image" in text


def test_leave_as_is_changes_nothing(setup):
    win, project, path, _ = setup
    before = path.read_bytes()
    n = len(project.operation_log)
    _open(win, path, choice=False)
    blot = win._get_active_blot()
    assert [c.channel_index for c in blot.channels] == [0, 0]
    assert len(win.current_project.operation_log) == n
    assert path.read_bytes() == before
    # ... and the problem is as described: the second file's row is uncropped.
    assert _figure_row_widths(win) == sorted([int(TEMPLATE_W), 1500])


def test_renumber_gives_unique_indices_logs_once_and_rebuilds_previews(setup):
    win, project, path, shas = setup
    n = len(project.operation_log)
    (text,) = _open(win, path, choice=True)

    blot = win._get_active_blot()
    assert [c.channel_index for c in blot.channels] == [0, 1]
    assert [c.asset_sha256 for c in blot.channels] == shas          # file order kept
    entries = win.current_project.operation_log[n:]
    renum = [e for e in entries if e.operation == "nir_channels_renumbered"]
    assert len(renum) == 1
    (e,) = renum
    assert (e.target_id, e.field, e.old_value, e.new_value) == (
        NIR, "channels.channel_index", [0, 0], [0, 1])
    assert IRLONG.name in e.note and IRSHORT.name in e.note

    # Saved, and the chain verifies on the reloaded file.
    reloaded = win.workspace.load_project(str(path))
    assert [c.channel_index for c in reloaded.panel.blots[0].channels] == [0, 1]
    assert verify_log_chain(reloaded).status == "ok"

    # Previews rebuilt for both channels, each from its own file and settings.
    for ch in blot.channels:
        p = win.workspace.assets_dir / ch.asset_sha256 / f"preview_crop_{NIR}_ch{ch.channel_index}.tif"
        assert p.is_file()
        on_disk = tifffile.imread(p)
        fresh = tifffile.imread(win.workspace.ensure_blot_crop_preview(
            blot, win.current_project.panel, channel_index=ch.channel_index,
            project=win.current_project))
        assert np.array_equal(on_disk, fresh)

    # The second channel is now selectable and its figure row is cropped.
    ids = sorted(win._nir_ch_btn_group.id(b) for b in win._nir_ch_btn_group.buttons())
    assert ids == [0, 1]
    win._on_nir_channel_changed(1)
    assert win._active_channel(blot) is blot.channels[1]
    assert win._active_display() is blot.channels[1].display
    assert _figure_row_widths(win) == [int(TEMPLATE_W), int(TEMPLATE_W)]


def test_project_without_duplicates_opens_without_a_warning(qapp, tmp_path):
    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    project, path, _ = _write_duplicate_project(ws)
    project.panel.blots[0].channels[1].channel_index = 1
    ws.save_project(project)
    win = MainWindow(ws)
    assert _open(win, path, choice=True) == []


def test_library_open_also_checks(setup):
    win, project, path, _ = setup
    shown = []
    win._ask_renumber_channels = lambda text: shown.append(text) or False
    win.refresh_library()
    row = next(r for r in range(win.library_table.rowCount())
               if win.library_table.item(r, 5) and win.library_table.item(r, 5).text().strip() == str(path))
    with patch("pysternblot.ui.main_window.QMessageBox"):
        win._open_project_from_library(row, 0)
    assert len(shown) == 1 and NIR in shown[0]


def test_archive_import_checks_each_imported_project(setup):
    # The imported project is not opened: on "Renumber" it is renumbered,
    # logged and saved in place, and its previews are rebuilt.
    win, project, path, shas = setup
    shown = []
    win._ask_renumber_channels = lambda text: shown.append(text) or True
    result = ImportArchiveResult(imported_project_ids=[project.project.id])
    with patch.object(win.workspace, "import_archive", return_value=result), \
         patch.object(project_io_module.QFileDialog, "getOpenFileName",
                      return_value=("/fake/archive.zip", "")), \
         patch.object(project_io_module, "QMessageBox", MagicMock()):
        win.import_library()
    assert len(shown) == 1
    reloaded = win.workspace.load_project(str(path))
    assert [c.channel_index for c in reloaded.panel.blots[0].channels] == [0, 1]
    assert [e.operation for e in reloaded.operation_log].count("nir_channels_renumbered") == 1
    assert verify_log_chain(reloaded).status == "ok"
    for ch in reloaded.panel.blots[0].channels:
        assert (win.workspace.assets_dir / ch.asset_sha256 /
                f"preview_crop_{NIR}_ch{ch.channel_index}.tif").is_file()


def test_dialog_offers_the_two_choices(setup):
    win, *_ = setup
    box = MagicMock()
    instance = box.return_value
    renumber, leave = object(), object()
    instance.addButton.side_effect = [renumber, leave]
    with patch.object(project_io_module, "QMessageBox", box):
        instance.clickedButton.return_value = renumber
        assert win._ask_renumber_channels("text") is True
        labels = [c.args[0] for c in instance.addButton.call_args_list]
        assert labels == ["Renumber channels", "Leave as is"]
        instance.setDefaultButton.assert_called_with(leave)       # no change by default
        instance.addButton.side_effect = [renumber, leave]
        instance.clickedButton.return_value = leave
        assert win._ask_renumber_channels("text") is False
