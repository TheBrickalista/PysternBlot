# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the update-check UI wiring: QSettings prefs, the first-run
prompt/worker orchestration, and the dismissible Home-tab banner."""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from pysternblot.storage import Workspace
from pysternblot.ui import update_prefs
from pysternblot.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def isolated_settings(qapp, tmp_path):
    """Point QSettings at a throwaway ini file so tests never touch real
    user settings, and start from a clean slate every test."""
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QCoreApplication.setOrganizationName("IRCAN")
    QCoreApplication.setApplicationName("PysternBlot")
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings().clear()
    yield
    QSettings().clear()


@pytest.fixture
def main_window(qapp, isolated_settings, tmp_path):
    ws = Workspace(tmp_path / "workspace")
    ws.ensure()
    win = MainWindow(ws)
    win.show()
    yield win
    win.close()


SAMPLE_RESULT = {
    "current": "1.0.0",
    "latest": "1.2.0",
    "install_type": "pip",
    "instruction": "Run: pip install -U pysternblot",
    "url": "https://github.com/TheBrickalista/PysternBlot/releases/latest",
}


# ---------------------------------------------------------------------------
# update_prefs round-trips
# ---------------------------------------------------------------------------

class TestUpdatePrefs:
    def test_enabled_defaults_false(self, isolated_settings):
        assert update_prefs.update_check_enabled() is False

    def test_set_enabled_true_reads_true(self, isolated_settings):
        update_prefs.set_update_check_enabled(True)
        assert update_prefs.update_check_enabled() is True

    def test_prompted_defaults_false(self, isolated_settings):
        assert update_prefs.has_been_prompted() is False

    def test_set_prompted_true_reads_true(self, isolated_settings):
        update_prefs.set_prompted(True)
        assert update_prefs.has_been_prompted() is True


# ---------------------------------------------------------------------------
# Banner show / dismiss
# ---------------------------------------------------------------------------

class TestUpdateBanner:
    def test_show_update_banner_inserts_into_home_layout(self, main_window):
        assert main_window._update_banner is None
        count_before = main_window._home_root_layout.count()

        main_window._show_update_banner(SAMPLE_RESULT)

        assert main_window._update_banner is not None
        assert main_window._home_root_layout.count() == count_before + 1
        assert main_window._home_root_layout.itemAt(0).widget() is main_window._update_banner

    def test_dismiss_update_banner_removes_it(self, main_window):
        main_window._show_update_banner(SAMPLE_RESULT)
        assert main_window._update_banner is not None

        main_window._dismiss_update_banner()

        assert main_window._update_banner is None

    def test_dismiss_when_no_banner_is_a_noop(self, main_window):
        assert main_window._update_banner is None
        main_window._dismiss_update_banner()
        assert main_window._update_banner is None

    def test_show_update_banner_twice_is_idempotent(self, main_window):
        main_window._show_update_banner(SAMPLE_RESULT)
        first_banner = main_window._update_banner

        main_window._show_update_banner(SAMPLE_RESULT)

        assert main_window._update_banner is not None
        assert main_window._update_banner is not first_banner


class TestAutoUpdateResult:
    def test_none_result_leaves_no_banner(self, main_window):
        main_window._on_auto_update_result(None)
        assert main_window._update_banner is None

    def test_dict_result_shows_banner(self, main_window):
        main_window._on_auto_update_result(SAMPLE_RESULT)
        assert main_window._update_banner is not None


# ---------------------------------------------------------------------------
# maybe_prompt_and_check_updates orchestration (no network: _start_update_check
# is patched out everywhere below).
# ---------------------------------------------------------------------------

class TestMaybePromptAndCheckUpdates:
    def test_already_prompted_and_disabled_does_not_start_worker(self, main_window):
        update_prefs.set_prompted(True)
        update_prefs.set_update_check_enabled(False)

        main_window._start_update_check = Mock()
        main_window.maybe_prompt_and_check_updates()

        main_window._start_update_check.assert_not_called()

    def test_already_prompted_and_enabled_starts_worker(self, main_window):
        update_prefs.set_prompted(True)
        update_prefs.set_update_check_enabled(True)

        main_window._start_update_check = Mock()
        main_window.maybe_prompt_and_check_updates()

        main_window._start_update_check.assert_called_once_with(manual=False)

    def test_syncs_preferences_checkbox_to_stored_state(self, main_window):
        update_prefs.set_prompted(True)
        update_prefs.set_update_check_enabled(True)

        main_window._start_update_check = Mock()
        main_window.maybe_prompt_and_check_updates()

        assert main_window.update_check_cb.isChecked() is True


# ---------------------------------------------------------------------------
# Preferences checkbox <-> update_prefs
# ---------------------------------------------------------------------------

class TestPreferencesCheckbox:
    def test_toggle_updates_prefs(self, main_window):
        assert update_prefs.update_check_enabled() is False

        main_window.update_check_cb.setChecked(True)

        assert update_prefs.update_check_enabled() is True
        assert update_prefs.has_been_prompted() is True

    def test_toggle_off_updates_prefs(self, main_window):
        main_window.update_check_cb.setChecked(True)
        update_prefs.set_prompted(False)  # reset so the second toggle is meaningful

        main_window.update_check_cb.setChecked(False)

        assert update_prefs.update_check_enabled() is False
        assert update_prefs.has_been_prompted() is True

    def test_manual_check_button_calls_start_update_check_manual(self, main_window):
        main_window._start_update_check = Mock()
        main_window.update_check_now_btn.click()
        main_window._start_update_check.assert_called_once_with(manual=True)
