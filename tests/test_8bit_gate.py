# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
The two 8-bit acknowledgement gates must fail closed (issue #195):

  - _ProjectIOMixin._check_jpeg_and_8bit  (import an 8-bit TIFF)
  - _ExportMixin._warn_8bit_export        (export with an 8-bit blot)

Only an explicit click on the proceed button may return True. Cancel, Esc,
closing the window, a dialog that ends with no button clicked, and any other
button must all return False.

The dialog is driven for real: a zero-delay timer fires inside
QMessageBox.exec(), finds the open dialog and acts on it (click, key press,
close(), done()). Nothing patches the dialog's result.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from pysternblot.ui import project_io_mixin as project_io_mixin_module
from pysternblot.ui.export_mixin import _ExportMixin
from pysternblot.ui.project_io_mixin import _ProjectIOMixin


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# Hosts: the gates pass `self` as the dialog parent, so they need a QWidget.
# ---------------------------------------------------------------------------

class _ImportHost(QWidget, _ProjectIOMixin):
    pass


class _ExportHost(QWidget, _ExportMixin):
    def __init__(self, original_path):
        super().__init__()
        self.current_project = SimpleNamespace(
            panel=SimpleNamespace(blots=[SimpleNamespace(asset_sha256="a" * 64)])
        )
        self.workspace = SimpleNamespace(asset_original_file=lambda _sha: original_path)


def _write_tiff(path, dtype):
    tifffile.imwrite(str(path), np.full((16, 16), 100, dtype=dtype))
    return str(path)


def _import_gate(tmp_path):
    path = _write_tiff(tmp_path / "blot_8bit.tif", np.uint8)
    host = _ImportHost()
    return host, lambda: host._check_jpeg_and_8bit(path), "I understand, proceed"


def _export_gate(tmp_path):
    path = _write_tiff(tmp_path / "blot_8bit.tif", np.uint8)
    host = _ExportHost(path)
    return host, host._warn_8bit_export, "Proceed with export"


GATES = {"import": _import_gate, "export": _export_gate}


# ---------------------------------------------------------------------------
# Driving the open dialog
# ---------------------------------------------------------------------------

def _button(dlg, text):
    matches = [b for b in dlg.findChildren(QPushButton) if b.text() == text]
    assert len(matches) == 1, f"expected one {text!r} button, got {len(matches)}"
    return matches[0]


def _run_gate(gate, action):
    """Call gate(); while its dialog is open, apply action(dlg).

    Returns (gate result, the dialog). A 10 s watchdog ends a dialog the
    action failed to close, so a broken test fails instead of hanging.
    """
    seen = {}

    def fire():
        dlg = QApplication.activeModalWidget()
        if not isinstance(dlg, QMessageBox):
            QTimer.singleShot(10, fire)  # dialog not up yet
            return
        seen["dlg"] = dlg
        QTimer.singleShot(10_000, lambda: dlg.isVisible() and dlg.done(-1))
        action(dlg)

    QTimer.singleShot(0, fire)
    result = gate()
    assert "dlg" in seen, "the gate did not show a dialog"
    return result, seen["dlg"]


def _click(text):
    return lambda dlg: _button(dlg, text).click()


def _escape(dlg):
    QTest.keyClick(dlg, Qt.Key_Escape)


def _close_window(dlg):
    dlg.close()


def _end_without_button(dlg):
    dlg.done(0)


def _click_unrelated_button(dlg):
    dlg.addButton("Something else", QMessageBox.ActionRole).click()


# ===========================================================================
# Both gates: only an explicit proceed continues
# ===========================================================================

@pytest.fixture(params=list(GATES))
def gate(request, qapp, tmp_path):
    host, call, proceed_text = GATES[request.param](tmp_path)
    yield call, proceed_text
    host.deleteLater()


def test_proceed_returns_true(gate):
    call, proceed_text = gate
    result, dlg = _run_gate(call, _click(proceed_text))
    assert dlg.clickedButton().text() == proceed_text
    assert result is True


def test_cancel_returns_false(gate):
    call, _ = gate
    result, dlg = _run_gate(call, _click("Cancel"))
    assert dlg.clickedButton().text() == "Cancel"
    assert result is False


def test_escape_returns_false(gate):
    call, _ = gate
    result, _ = _run_gate(call, _escape)
    assert result is False


def test_window_close_returns_false(gate):
    call, _ = gate
    result, _ = _run_gate(call, _close_window)
    assert result is False


def test_no_button_clicked_returns_false(gate):
    call, _ = gate
    result, dlg = _run_gate(call, _end_without_button)
    assert dlg.clickedButton() is None  # the scenario under test
    assert result is False


def test_unrelated_button_returns_false(gate):
    call, proceed_text = gate
    result, dlg = _run_gate(call, _click_unrelated_button)
    assert dlg.clickedButton().text() == "Something else"
    assert result is False


# ===========================================================================
# Cases where no 8-bit dialog may appear
# ===========================================================================

@pytest.fixture
def no_dialog(monkeypatch):
    """Fail at once if any QMessageBox is exec()'d (instead of blocking)."""
    def _fail(self, *a, **k):
        raise AssertionError(f"unexpected dialog: {self.windowTitle()!r}")
    monkeypatch.setattr(QMessageBox, "exec", _fail)


def test_16bit_tiff_import_shows_no_dialog(qapp, tmp_path, no_dialog):
    path = _write_tiff(tmp_path / "blot_16bit.tif", np.uint16)
    assert _ImportHost()._check_jpeg_and_8bit(path) is True


def test_16bit_blot_export_shows_no_dialog(qapp, tmp_path, no_dialog):
    path = _write_tiff(tmp_path / "blot_16bit.tif", np.uint16)
    assert _ExportHost(path)._warn_8bit_export() is True


def test_jpeg_rejected_before_any_8bit_check(qapp, tmp_path, monkeypatch):
    path = tmp_path / "blot.jpg"
    Image.new("L", (16, 16)).save(str(path), format="JPEG")

    calls = []
    monkeypatch.setattr(
        project_io_mixin_module, "get_bit_depth",
        lambda p: calls.append(p) or pytest.fail("8-bit check ran for a JPEG"),
    )

    # The JPEG rejection is itself a modal critical box; dismiss it with OK.
    # QMessageBox.critical() deletes its box on return, so read it while open.
    shown = []

    def dismiss(d):
        shown.append(d.text())
        d.accept()

    result, _ = _run_gate(lambda: _ImportHost()._check_jpeg_and_8bit(str(path)), dismiss)
    assert len(shown) == 1 and "JPEG files are not accepted" in shown[0]
    assert result is False
    assert calls == []
