# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the update-check UI wiring: QSettings prefs, the first-run
prompt/worker orchestration, and the dismissible Home-tab banner."""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

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


class TestReleaseNotesButton:
    def test_banner_has_view_and_dismiss_buttons(self, main_window):
        main_window._show_update_banner(SAMPLE_RESULT)

        buttons = main_window._update_banner.findChildren(QPushButton)
        texts = {b.text() for b in buttons}

        assert "View release notes" in texts
        assert "Dismiss" in texts

    def test_clicking_view_release_notes_opens_result_url(self, main_window):
        main_window._show_update_banner(SAMPLE_RESULT)
        buttons = main_window._update_banner.findChildren(QPushButton)
        view_btn = next(b for b in buttons if b.text() == "View release notes")

        with patch("pysternblot.ui.main_window.QDesktopServices.openUrl") as mock_open:
            view_btn.click()

        mock_open.assert_called_once()
        (called_url,), _kwargs = mock_open.call_args
        assert called_url.toString() == SAMPLE_RESULT["url"]

    def test_open_release_page_none_does_not_open(self, main_window):
        with patch("pysternblot.ui.main_window.QDesktopServices.openUrl") as mock_open:
            main_window._open_release_page(None)
        mock_open.assert_not_called()

    def test_open_release_page_empty_string_does_not_open(self, main_window):
        with patch("pysternblot.ui.main_window.QDesktopServices.openUrl") as mock_open:
            main_window._open_release_page("")
        mock_open.assert_not_called()


from pysternblot import update_check as uc


def _update_result():
    return uc.CheckResult(outcome=uc.OUTCOME_UPDATE_AVAILABLE, **{
        k: SAMPLE_RESULT[k] for k in ("current", "latest", "install_type", "instruction", "url")
    })


def _failed(category, **kw):
    return uc.CheckResult(outcome=uc.OUTCOME_CHECK_FAILED, category=category, detail="boom", **kw)


class TestAutoUpdateResult:
    def test_none_result_leaves_no_banner(self, main_window):
        main_window._on_auto_update_result(None)
        assert main_window._update_banner is None

    def test_update_available_shows_banner(self, main_window):
        main_window._on_auto_update_result(_update_result())
        assert main_window._update_banner is not None

    def test_up_to_date_is_silent(self, main_window):
        main_window._on_auto_update_result(uc.CheckResult(outcome=uc.OUTCOME_UP_TO_DATE))
        assert main_window._update_banner is None

    @pytest.mark.parametrize("result", [
        _failed(uc.CATEGORY_TLS),
        _failed(uc.CATEGORY_BAD_RESPONSE),
        _failed(uc.CATEGORY_HTTP, status_code=500),
    ])
    def test_serious_failures_show_non_modal_line(self, main_window, result):
        with patch("pysternblot.ui.main_window.QMessageBox") as mock_box:
            main_window._on_auto_update_result(result)
        assert main_window._update_banner is not None
        mock_box.assert_not_called()  # non-modal

    @pytest.mark.parametrize("result", [
        _failed(uc.CATEGORY_NETWORK),
        _failed(uc.CATEGORY_HTTP, status_code=403, rate_limited=True),
        _failed(uc.CATEGORY_HTTP, status_code=429, rate_limited=True),
    ])
    def test_network_and_rate_limit_stay_silent(self, main_window, result):
        main_window._on_auto_update_result(result)
        assert main_window._update_banner is None

    def test_failure_line_can_be_dismissed(self, main_window):
        main_window._on_auto_update_result(_failed(uc.CATEGORY_TLS))
        main_window._dismiss_update_banner()
        assert main_window._update_banner is None


class TestManualUpdateResult:
    def test_up_to_date_message(self, main_window):
        with patch("pysternblot.ui.main_window.QMessageBox") as mock_box:
            main_window._on_manual_update_result(
                uc.CheckResult(outcome=uc.OUTCOME_UP_TO_DATE, current="1.2.0"))
        mock_box.information.assert_called_once()
        assert "latest published release" in mock_box.information.call_args.args[2]

    def test_update_available_shows_banner_no_dialog(self, main_window):
        with patch("pysternblot.ui.main_window.QMessageBox") as mock_box:
            main_window._on_manual_update_result(_update_result())
        assert main_window._update_banner is not None
        mock_box.information.assert_not_called()

    @pytest.mark.parametrize("result, expected", [
        (_failed(uc.CATEGORY_TLS), "security certificate"),
        (_failed(uc.CATEGORY_NETWORK), "could not reach GitHub"),
        (_failed(uc.CATEGORY_HTTP, status_code=429, rate_limited=True), "limiting"),
        (_failed(uc.CATEGORY_HTTP, status_code=500), "HTTP 500"),
        (_failed(uc.CATEGORY_BAD_RESPONSE), "could not be understood"),
    ])
    def test_failure_is_never_shown_as_up_to_date(self, main_window, result, expected):
        with patch("pysternblot.ui.main_window.QMessageBox") as mock_box:
            main_window._on_manual_update_result(result)
        mock_box.information.assert_not_called()
        text = mock_box.call_args.args[2]
        assert expected in text
        assert "latest published release" not in text
        # exception text lives in the details section
        details = mock_box.return_value.setDetailedText.call_args.args[0]
        assert "boom" in details and f"Category: {result.category}" in details
        mock_box.return_value.exec.assert_called_once()


class TestWorker:
    def test_worker_converts_a_crash_into_check_failed(self, qapp):
        from pysternblot.ui.update_worker import UpdateCheckWorker
        got = []
        w = UpdateCheckWorker(enabled=True)
        w.signals.finished.connect(got.append)
        with patch("pysternblot.ui.update_worker.check_for_update", side_effect=RuntimeError("bug")):
            w.run()
        assert got[0].failed and got[0].category == uc.CATEGORY_UNEXPECTED
        assert "bug" in got[0].detail


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


# ---------------------------------------------------------------------------
# First-run consent branch of maybe_prompt_and_check_updates. The real
# QMessageBox.exec() blocks under offscreen Qt, so it is patched at the class
# level (pysternblot.ui.main_window.QMessageBox.exec) to return a canned
# answer instantly — no window is ever shown.
# ---------------------------------------------------------------------------

class TestFirstRunConsentPrompt:
    def test_first_run_yes_opts_in_and_records_prompted(self, main_window):
        assert update_prefs.has_been_prompted() is False  # precondition

        main_window._start_update_check = Mock()
        with patch("pysternblot.ui.main_window.QMessageBox.exec", return_value=QMessageBox.Yes):
            main_window.maybe_prompt_and_check_updates()

        assert update_prefs.has_been_prompted() is True
        assert update_prefs.update_check_enabled() is True
        main_window._start_update_check.assert_called_once_with(manual=False)

    def test_first_run_no_opts_out_and_records_prompted(self, main_window):
        assert update_prefs.has_been_prompted() is False  # precondition

        main_window._start_update_check = Mock()
        with patch("pysternblot.ui.main_window.QMessageBox.exec", return_value=QMessageBox.No):
            main_window.maybe_prompt_and_check_updates()

        assert update_prefs.has_been_prompted() is True
        assert update_prefs.update_check_enabled() is False
        main_window._start_update_check.assert_not_called()

    def test_first_run_dismissed_leaves_prompted_false(self, main_window):
        assert update_prefs.has_been_prompted() is False  # precondition

        main_window._start_update_check = Mock()
        with patch("pysternblot.ui.main_window.QMessageBox.exec", return_value=0):
            main_window.maybe_prompt_and_check_updates()

        assert update_prefs.has_been_prompted() is False  # will be asked again next launch
        assert update_prefs.update_check_enabled() is False  # unchanged default
        main_window._start_update_check.assert_not_called()

    def test_second_launch_after_answer_does_not_prompt_again(self, main_window):
        # Simulate a prior launch where the user answered No.
        update_prefs.set_prompted(True)
        update_prefs.set_update_check_enabled(False)

        main_window._start_update_check = Mock()
        with patch("pysternblot.ui.main_window.QMessageBox.exec") as mock_exec:
            main_window.maybe_prompt_and_check_updates()

        mock_exec.assert_not_called()  # no re-prompt
        assert update_prefs.update_check_enabled() is False  # unchanged
        main_window._start_update_check.assert_not_called()

    def test_second_launch_enabled_checks_without_prompting(self, main_window):
        # Simulate a prior launch where the user answered Yes.
        update_prefs.set_prompted(True)
        update_prefs.set_update_check_enabled(True)

        main_window._start_update_check = Mock()
        with patch("pysternblot.ui.main_window.QMessageBox.exec") as mock_exec:
            main_window.maybe_prompt_and_check_updates()

        mock_exec.assert_not_called()
        main_window._start_update_check.assert_called_once_with(manual=False)
