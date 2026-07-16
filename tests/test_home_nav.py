# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for Home tab navigation shortcuts."""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pysternblot.storage import Workspace
from pysternblot.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def main_window(qapp, tmp_path):
    ws = Workspace(tmp_path / "workspace")
    ws.ensure()
    win = MainWindow(ws)
    win.show()
    yield win
    win.close()


class TestGotoLibraryTab:
    def test_library_tab_stored(self, main_window):
        assert hasattr(main_window, "_library_tab")

    def test_goto_library_tab_switches_current_widget(self, main_window):
        main_window._goto_library_tab()
        assert main_window.tabs.currentWidget() is main_window._library_tab
