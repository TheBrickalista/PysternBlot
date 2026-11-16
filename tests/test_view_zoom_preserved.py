# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Zoom and pan survive redraws of the Original Image view and the figure.

A view is in fit mode until the user zooms or pans; redraws then keep the
user's transform and scroll position. The Fit button, a double-click and
content changes (other blot or channel, new project, imports) refit.

The "preserved" checks use only plain QGraphicsView API (transform and
scrollbars), so they also run against the code before this change.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSlider, QApplication

from test_refresh_scope_staleness import ECL_A, ECL_B, NIR, _window as _real_tiff_window


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _shown(tmp_path):
    win = _real_tiff_window(tmp_path)
    win.resize(1200, 900)
    win.show()
    QTest.qWaitForWindowExposed(win)
    return win


def _show_tab_of(win, view):
    for i in range(win.tabs.count()):
        if win.tabs.widget(i).isAncestorOf(view):
            win.tabs.setCurrentIndex(i)
            QApplication.processEvents()
            return
    raise AssertionError("view not found in any tab")


def _user_zoom_in(view, steps=6):
    centre = QPointF(view.viewport().rect().center())
    for _ in range(steps):
        ev = QWheelEvent(centre, view.viewport().mapToGlobal(centre), QPoint(0, 0), QPoint(0, 120),
                         Qt.NoButton, Qt.ShiftModifier, Qt.NoScrollPhase, False)
        view.wheelEvent(ev)


def _user_pan(view):
    for bar in (view.horizontalScrollBar(), view.verticalScrollBar()):
        for _ in range(3):
            bar.triggerAction(QAbstractSlider.SliderPageStepAdd)


def _state(view):
    t = view.transform()
    return (round(t.m11(), 9), round(t.m22(), 9),
            view.horizontalScrollBar().value(), view.verticalScrollBar().value())


def _zoomed_and_panned(win, view):
    _show_tab_of(win, view)
    fitted = _state(view)
    _user_zoom_in(view)
    _user_pan(view)
    state = _state(view)
    assert state[0] > fitted[0] * 1.5, "precondition: the user zoom must take effect"
    assert state[2] > 0 or state[3] > 0, "precondition: the user pan must take effect"
    return state


# --------------------------------------------------------------------------
# Preserved
# --------------------------------------------------------------------------
def test_original_image_keeps_zoom_on_opacity_change(qapp, tmp_path):
    win = _shown(tmp_path)
    before = _zoomed_and_panned(win, win.prov_view)
    old_scene = win.prov_view.scene()
    win.alpha_slider.setValue(win.alpha_slider.value() + 20)
    win._gesture_committer.flush()                 # runs the provenance-only redraw
    assert win.prov_view.scene() is not old_scene  # really redrawn
    assert _state(win.prov_view) == before


def test_original_image_keeps_zoom_on_grid_toggle(qapp, tmp_path):
    win = _shown(tmp_path)
    before = _zoomed_and_panned(win, win.prov_view)
    old_scene = win.prov_view.scene()
    win.prov_grid_cb.setChecked(not win.prov_grid_cb.isChecked())
    assert win.prov_view.scene() is not old_scene
    assert _state(win.prov_view) == before


def test_figure_keeps_zoom_on_levels_change(qapp, tmp_path):
    win = _shown(tmp_path)
    before = _zoomed_and_panned(win, win.view)
    old_scene = win.view.scene()
    win.black_value_edit.setText("2500")
    win._on_black_value_edited()                   # typed levels -> refresh_previews("active")
    assert win.view.scene() is not old_scene
    assert _state(win.view) == before


def test_zoom_is_kept_across_many_redraws_without_drift(qapp, tmp_path):
    win = _shown(tmp_path)
    before = _zoomed_and_panned(win, win.prov_view)
    for _ in range(10):
        win.prov_grid_cb.setChecked(not win.prov_grid_cb.isChecked())
    assert _state(win.prov_view) == before


# --------------------------------------------------------------------------
# Refit
# --------------------------------------------------------------------------
def _fitted_state(view):
    view.fit_scene()
    return _state(view)


def test_switching_blot_refits_original_image(qapp, tmp_path):
    win = _shown(tmp_path)
    _zoomed_and_panned(win, win.prov_view)
    win.prov_blot_combo.setCurrentIndex(win.prov_blot_combo.findData(NIR))
    assert win.prov_view.in_fit_mode
    after = _state(win.prov_view)
    assert after == _fitted_state(win.prov_view)


def test_switching_nir_channel_refits_original_image(qapp, tmp_path):
    win = _shown(tmp_path)
    win.prov_blot_combo.setCurrentIndex(win.prov_blot_combo.findData(NIR))
    _zoomed_and_panned(win, win.prov_view)
    win._on_nir_channel_changed(1)
    assert win.prov_view.in_fit_mode
    assert _state(win.prov_view) == _fitted_state(win.prov_view)


def test_fit_button_and_double_click_return_to_fit_mode(qapp, tmp_path):
    win = _shown(tmp_path)
    _zoomed_and_panned(win, win.prov_view)
    assert not win.prov_view.in_fit_mode
    win.prov_fit_btn.click()
    assert win.prov_view.in_fit_mode

    _zoomed_and_panned(win, win.view)
    assert not win.view.in_fit_mode
    QTest.mouseDClick(win.view.viewport(), Qt.LeftButton, Qt.NoModifier,
                      win.view.viewport().rect().center())
    assert win.view.in_fit_mode


def test_in_fit_mode_the_next_refresh_follows_the_scene_size(qapp, tmp_path):
    win = _shown(tmp_path)
    _show_tab_of(win, win.view)
    _zoomed_and_panned(win, win.view)
    QTest.mouseDClick(win.view.viewport(), Qt.LeftButton, Qt.NoModifier,
                      win.view.viewport().rect().center())
    fitted_before = _state(win.view)

    # A crop resize changes the figure's size; the view is in fit mode, so
    # the (non-forced) redraw fits the new scene.
    ct = win.current_project.panel.crop_template
    ct.w, ct.h = ct.w * 0.5, ct.h * 2.0
    win._on_crop_resize_commit()
    after = _state(win.view)
    assert after != fitted_before                  # a different size, refitted
    assert after == _fitted_state(win.view)


def test_zoomed_figure_is_not_refit_by_a_crop_resize(qapp, tmp_path):
    win = _shown(tmp_path)
    before = _zoomed_and_panned(win, win.view)
    ct = win.current_project.panel.crop_template
    ct.w = ct.w * 0.8
    win._on_crop_resize_commit()
    assert not win.view.in_fit_mode
    assert _state(win.view)[:2] == before[:2]      # zoom kept (scene size changed)


def test_forced_fit_paths_refit(qapp, tmp_path):
    win = _shown(tmp_path)
    _zoomed_and_panned(win, win.view)
    win._on_border_width_changed(3)                # _refresh_final_only(fit=True)
    win._gesture_committer.flush()
    assert win.view.in_fit_mode
    _zoomed_and_panned(win, win.prov_view)
    win.prov_blot_combo.setCurrentIndex(win.prov_blot_combo.findData(ECL_B))
    assert win.prov_view.in_fit_mode


def test_zoom_and_fit_mode_are_pure_view_state(qapp, tmp_path):
    win = _shown(tmp_path)
    n_log = len(win.current_project.operation_log)
    _zoomed_and_panned(win, win.prov_view)
    _zoomed_and_panned(win, win.view)
    win.prov_fit_btn.click()
    assert len(win.current_project.operation_log) == n_log
    assert win.active_blot_id == ECL_A
