# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Figure exports rebuild the crop previews from the model first.

build_panel_scene reads the cached preview_crop_*.tif files. The export path
(_final_scene_and_rect) regenerates them for every blot, so an export always
matches a fresh full refresh, even when the on-screen refresh skipped some.
"""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from test_gesture_commit import _patched_save, _window


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _export_png(win, path) -> QImage:
    with ExitStack() as stack:
        for p in _patched_save(path):
            stack.enter_context(p)
        win.export_final_png()
    img = QImage(str(path))
    assert not img.isNull(), "export_final_png wrote no readable PNG"
    return img


def test_export_regenerates_stale_crop_previews(qapp, tmp_path):
    win = _window(tmp_path)
    before = _export_png(win, tmp_path / "before.png")

    # Change levels in the model only: no refresh, so the cached
    # preview_crop_blot_01.tif still holds the old levels.
    win.current_project.panel.blots[0].display.levels_black = 20000
    stale_export = _export_png(win, tmp_path / "stale.png")

    win.refresh_previews()          # full regeneration ("all")
    fresh_export = _export_png(win, tmp_path / "fresh.png")

    assert stale_export != before, "the levels change must be visible in the export"
    assert stale_export == fresh_export
    assert stale_export.size() == fresh_export.size()
