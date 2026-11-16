# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
A NIR import whose files would become the same channel is refused.

channel_index comes from the Typhoon Tag 270 "Scan number" (numerator - 1),
or the file's position when a file has none. Two files with the same
resulting index (same scan number, or a file without one taking the other's
position) are refused before anything is copied, stored or logged.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from pysternblot.models import Project
from pysternblot.storage import DuplicateNirChannelError, Workspace, nir_channel_assignment
from pysternblot.ui import nir_import_dialog as nir_import_dialog_module
from pysternblot.ui import project_io_mixin as project_io_module
from pysternblot.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
IRLONG = ROOT / "tests" / "20260507-142651-[IRlong].tif"      # Scan number 1/2
IRSHORT = ROOT / "tests" / "20260507-142651-[IRshort].tif"    # Scan number 2/2
CHEMI = ROOT / "tests" / "rhoa 20260220_131003_Ch_Chemi.tif"  # no Scan number


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def win(qapp, tmp_path):
    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    w = MainWindow(ws)
    w.current_project = ws.load_project(str(ws.create_new_project("nir import")))
    w._save_project()
    w.refresh_previews()
    return w


def _copy_as(src: Path, tmp_path: Path, name: str) -> Path:
    d = tmp_path / "src"
    d.mkdir(exist_ok=True)
    return Path(shutil.copy(src, d / name))


def _import(win, ch1, ch2=None) -> MagicMock:
    class FakeDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

        channel1_path = Path(ch1)
        channel2_path = Path(ch2) if ch2 is not None else None

    box = MagicMock()
    with patch.object(nir_import_dialog_module, "NirImportDialog", FakeDialog), \
         patch.object(project_io_module, "QMessageBox", box):
        win._on_import_nir_blot()
    return box


def _state(win):
    ws = win.workspace
    path = ws.projects_dir / win.current_project.project.id / "project.json"
    return (
        sorted(str(p.relative_to(ws.root)) for p in ws.assets_dir.rglob("*") if p.is_file()),
        path.read_bytes(),
        [e.model_dump() for e in win.current_project.operation_log],
        [b.id for b in win.current_project.panel.blots],
        sorted(win.current_project.assets),
    )


# --------------------------------------------------------------------------
# Refused
# --------------------------------------------------------------------------
def _duplicate_cases(tmp_path):
    return {
        "same_file_twice": (IRLONG, IRLONG, "1/2", "1/2", 1),
        "two_files_scan_1_of_2": (IRLONG, _copy_as(IRLONG, tmp_path, "other[IRlong].tif"),
                                  "1/2", "1/2", 1),
        "two_files_scan_2_of_2": (IRSHORT, _copy_as(IRSHORT, tmp_path, "other[IRshort].tif"),
                                  "2/2", "2/2", 2),
        "no_scan_number_takes_position_0": (CHEMI, IRLONG, None, "1/2", 1),
    }


@pytest.mark.parametrize("case", ["same_file_twice", "two_files_scan_1_of_2",
                                  "two_files_scan_2_of_2", "no_scan_number_takes_position_0"])
def test_duplicate_channel_is_refused_and_nothing_changes(win, tmp_path, case):
    ch1, ch2, scan1, scan2, ch_number = _duplicate_cases(tmp_path)[case]
    before = _state(win)

    box = _import(win, ch1, ch2)

    assert _state(win) == before                     # assets, project.json, log, blots
    box.warning.assert_called_once()
    title, text = box.warning.call_args.args[1:3]
    assert title == "Same NIR channel twice"
    assert f"would both be channel Ch{ch_number}" in text
    assert Path(ch1).name in text and Path(ch2).name in text
    for scan in (scan1, scan2):
        assert (f"Scan number {scan}" if scan else "no Scan number") in text
    assert "Nothing was imported." in text
    assert not box.critical.called and not box.information.called


def test_storage_import_refuses_before_storing(win, tmp_path):
    other = _copy_as(IRLONG, tmp_path, "other[IRlong].tif")
    before = _state(win)
    with pytest.raises(DuplicateNirChannelError) as exc:
        win.workspace.import_nir_blot_typhoon([IRLONG, other], win.current_project)
    assert exc.value.channel_index == 0
    assert (exc.value.first_path, exc.value.second_path) == (IRLONG, other)
    assert _state(win) == before


def test_assignment_matches_the_import():
    # The check uses the same assignment as import_nir_blot_typhoon.
    assert [(i, s) for _p, i, s in nir_channel_assignment([IRLONG, IRSHORT])] == [(0, "1/2"), (1, "2/2")]
    assert [(i, s) for _p, i, s in nir_channel_assignment([CHEMI, IRSHORT])] == [(0, None), (1, "2/2")]


# --------------------------------------------------------------------------
# Still imported
# --------------------------------------------------------------------------
@pytest.mark.parametrize("order", [(IRLONG, IRSHORT), (IRSHORT, IRLONG)], ids=["1_2", "2_1"])
def test_normal_pair_imports(win, order):
    box = _import(win, *order)
    assert not box.warning.called and not box.critical.called
    (blot,) = win.current_project.panel.blots
    assert [c.channel_index for c in blot.channels] == [0, 1]
    assert win.active_blot_id == blot.id
    assert win._active_nir_channel == 0                 # selector: the lowest channel_index
    ops = [e.operation for e in win.current_project.operation_log]
    assert ops.count("nir_channel_imported") == 2 and "nir_blot_imported" in ops
    loaded = Project.model_validate_json(
        (win.workspace.projects_dir / win.current_project.project.id / "project.json").read_text())
    assert [c.channel_index for c in loaded.panel.blots[0].channels] == [0, 1]


def test_single_second_scan_imports_as_channel_1(win):
    box = _import(win, IRSHORT)
    assert not box.warning.called and not box.critical.called
    (blot,) = win.current_project.panel.blots
    assert [c.channel_index for c in blot.channels] == [1]
    assert win._active_nir_channel == 1                 # normalised by the selector


def test_file_without_scan_number_next_to_a_2_of_2_imports(win):
    # Position 0 (no scan number) + Scan number 2/2 -> channels 0 and 1: no clash.
    box = _import(win, CHEMI, IRSHORT)
    assert not box.warning.called
    (blot,) = win.current_project.panel.blots
    assert [c.channel_index for c in blot.channels] == [0, 1]
