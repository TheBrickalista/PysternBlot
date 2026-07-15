# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the collapsible Display section header in the Original Image tab."""

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
    for i in range(win.tabs.count()):
        if win.tabs.tabText(i) == "Original Image":
            win.tabs.setCurrentIndex(i)
            break
    yield win
    win.close()


class TestDisplaySectionCollapse:
    def test_toggle_button_exists_and_expanded_by_default(self, main_window):
        assert hasattr(main_window, "display_toggle_btn")
        assert main_window.display_toggle_btn.isChecked() is True

    def test_body_visible_by_default(self, main_window):
        assert main_window._display_body.isVisible() is True

    def test_collapsing_hides_body_and_updates_text(self, main_window):
        main_window.display_toggle_btn.setChecked(False)
        assert main_window._display_body.isVisible() is False
        assert main_window.display_toggle_btn.text().startswith("›")

    def test_expanding_again_shows_body(self, main_window):
        main_window.display_toggle_btn.setChecked(False)
        main_window.display_toggle_btn.setChecked(True)
        assert main_window._display_body.isVisible() is True
        assert main_window.display_toggle_btn.text().startswith("⌄")
