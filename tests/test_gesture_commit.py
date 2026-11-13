# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Continuous controls: one operation-log entry per gesture, scoped refreshes.

  - Part B (gesture_commit.py): ticks of a slider / dial / spinbox update the
    model and the screen only; the gesture is committed once (start -> final
    value, one save) on release, editing finished, the idle timer, or any
    forced flush (another log entry, any UI save, blot switch, export,
    integrity report, quit). project.json and the log never disagree.
  - Part A: refresh_previews(regenerate="all" | "active" | "none") and
    _refresh_provenance_only(); crop previews are rebuilt only where a
    change can affect them.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pysternblot.logchain import verify_log_chain
from pysternblot.models import AssetEntry, Blot, Crop, CropTemplate, ProteinLabel
from pysternblot.storage import Workspace
from pysternblot.ui import export_mixin as export_mixin_module
from pysternblot.ui.gesture_commit import IDLE_COMMIT_MS
from pysternblot.ui.main_window import MainWindow

from test_source_export import _encode_png_uint16, _minimal_ladder, _minimal_project, _write_asset


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _window(tmp_path, n_blots: int = 2) -> MainWindow:
    ws_dir = tmp_path / "ws"
    blots, assets = [], {}
    for i in range(n_blots):
        sha = _write_asset(ws_dir, _encode_png_uint16(np.full((64, 64), 10000 * (i + 1), np.uint16)), ".png")
        assets[sha] = AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.png"))
        blots.append(Blot(
            id=f"blot_{i + 1:02d}", asset_sha256=sha, crop=Crop(x=0, y=0, w=48.0, h=48.0),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=f"P{i + 1}"),
        ))
    project = _minimal_project(blots, assets=assets)
    project.panel.crop_template = CropTemplate(w=48.0, h=48.0)
    ws = Workspace(root=ws_dir)
    ws.ensure()
    win = MainWindow(ws)
    win.current_project = project
    win.active_blot_id = blots[0].id
    ws.save_project(project)
    win.refresh_previews()          # widgets now mirror the model
    return win


def _ops(win, operation=None):
    log = win.current_project.operation_log
    return [e for e in log if operation is None or e.operation == operation]


def _on_disk(win) -> dict:
    path = win.workspace.projects_dir / win.current_project.project.id / "project.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ===========================================================================
# One entry per gesture
# ===========================================================================

class TestOneEntryPerGesture:

    def test_twenty_alpha_ticks_make_one_entry(self, qapp, tmp_path):
        win = _window(tmp_path)
        start = win.current_project.panel.blots[0].display.overlay_alpha
        for v in range(36, 56):                       # 20 ticks
            win.alpha_slider.setValue(v)
        assert _ops(win, "overlay_alpha_changed") == []   # nothing committed mid-gesture
        win._gesture_committer.flush()

        (entry,) = _ops(win, "overlay_alpha_changed")
        assert entry.old_value == pytest.approx(start) and entry.new_value == pytest.approx(0.55)
        assert entry.target_id == "blot_01"
        assert verify_log_chain(win.current_project).status == "ok"
        assert _on_disk(win)["panel"]["blots"][0]["display"]["overlay_alpha"] == pytest.approx(0.55)

    def test_returning_to_start_value_makes_no_entry(self, qapp, tmp_path):
        win = _window(tmp_path)
        n = len(_ops(win))
        for v in (36, 40, 45, 40, 35):
            win.alpha_slider.setValue(v)
        win._gesture_committer.flush()
        assert len(_ops(win)) == n

    def test_key_change_flushes_previous_gesture_in_order(self, qapp, tmp_path):
        win = _window(tmp_path)
        for v in (10, 11, 12):
            win.protein_font_size_spin.setValue(v)
        for v in (40, 50):
            win.alpha_slider.setValue(v)
        win._gesture_committer.flush()
        ops = [e.operation for e in _ops(win) if e.operation in ("protein_font_size_changed", "overlay_alpha_changed")]
        assert ops == ["protein_font_size_changed", "overlay_alpha_changed"]
        font = _ops(win, "protein_font_size_changed")[0]
        assert font.new_value == 12.0
        assert verify_log_chain(win.current_project).status == "ok"

    def test_idle_timer_commits_without_explicit_flush(self, qapp, tmp_path):
        win = _window(tmp_path)
        for v in (3, 4, 5):
            win.border_width_spin.setValue(v)
        assert _ops(win, "border_width_changed") == []
        QTest.qWait(IDLE_COMMIT_MS + 300)
        (entry,) = _ops(win, "border_width_changed")
        assert (entry.old_value, entry.new_value) == (1, 5)
        assert _on_disk(win)["panel"]["style"]["border_width_px"] == 5

    def test_slider_release_commits(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.alpha_slider.setValue(60)
        win.alpha_slider.sliderReleased.emit()
        assert len(_ops(win, "overlay_alpha_changed")) == 1

    def test_held_slider_is_not_committed_by_idle_timer(self, qapp, tmp_path):
        # A mouse drag that pauses past IDLE_COMMIT_MS is still one gesture:
        # the idle timer re-arms while the slider is down; release commits.
        win = _window(tmp_path)
        start = win.current_project.panel.blots[0].display.overlay_alpha
        win.alpha_slider.setSliderDown(True)
        win.alpha_slider.setValue(50)
        QTest.qWait(IDLE_COMMIT_MS + 300)
        win.alpha_slider.setValue(60)
        QTest.qWait(IDLE_COMMIT_MS + 300)
        assert _ops(win, "overlay_alpha_changed") == []
        assert win._gesture_committer.has_pending

        win.alpha_slider.setSliderDown(False)          # emits sliderReleased
        (entry,) = _ops(win, "overlay_alpha_changed")
        assert entry.old_value == pytest.approx(start) and entry.new_value == pytest.approx(0.60)
        assert _on_disk(win)["panel"]["blots"][0]["display"]["overlay_alpha"] == pytest.approx(0.60)

    def test_held_rotation_dial_is_not_committed_by_idle_timer(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.prov_rotate_dial.setSliderDown(True)
        win.prov_rotate_dial.setValue(25)
        QTest.qWait(IDLE_COMMIT_MS + 300)
        assert _ops(win, "rotation_changed") == []
        win.prov_rotate_dial.setSliderDown(False)
        assert len(_ops(win, "rotation_changed")) == 1

    def test_slider_not_held_still_commits_on_idle(self, qapp, tmp_path):
        # Keyboard and wheel changes move the slider without holding it down.
        win = _window(tmp_path)
        assert not win.alpha_slider.isSliderDown()
        win.alpha_slider.setValue(60)
        QTest.qWait(IDLE_COMMIT_MS + 300)
        assert len(_ops(win, "overlay_alpha_changed")) == 1

    def test_rotation_dial_gesture_is_one_entry_keyed_per_blot(self, qapp, tmp_path):
        win = _window(tmp_path)
        for v in (5, 10, 15, 20):
            win.prov_rotate_dial.setValue(v)
        win._gesture_committer.flush()
        (entry,) = _ops(win, "rotation_changed")
        assert (entry.old_value, entry.new_value) == (0.0, 2.0)

    def test_typed_rotation_is_still_logged_at_once(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.prov_rotate_label.setText("3.5")
        win._on_rotate_label_edited()
        (entry,) = _ops(win, "rotation_changed")       # no flush needed
        assert entry.new_value == 3.5
        assert not win._gesture_committer.has_pending

    def test_typed_black_value_is_still_logged_at_once(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.black_value_edit.setText("1200")
        win._on_black_value_edited()
        (entry,) = _ops(win, "levels_changed")
        assert entry.new_value["black"] == 1200
        assert not win._gesture_committer.has_pending

    def test_histogram_drag_is_one_entry_from_drag_start_to_end(self, qapp, tmp_path):
        win = _window(tmp_path)
        for v in (500, 1000, 1500, 2000):
            win._on_histogram_gate_changed("black", v)
        assert _ops(win, "levels_changed") == []           # drag: no log, no save
        win._on_histogram_gate_commit()
        (entry,) = _ops(win, "levels_changed")
        assert entry.old_value["black"] == 0 and entry.new_value["black"] == 2000
        assert not win._gesture_committer.has_pending
        assert _on_disk(win)["panel"]["blots"][0]["display"]["levels_black"] == 2000


# ===========================================================================
# Forced flushes keep disk and log consistent
# ===========================================================================

def _patched_save(path):
    return (
        patch.object(export_mixin_module.QFileDialog, "getSaveFileName", return_value=(str(path), "")),
        patch.object(export_mixin_module.QFileDialog, "getExistingDirectory", return_value=str(path)),
        patch.object(export_mixin_module.QMessageBox, "information"),
        patch.object(export_mixin_module.QMessageBox, "critical"),
    )


class TestForcedFlush:

    def test_ui_save_mid_gesture_commits_first(self, qapp, tmp_path):
        win = _window(tmp_path)
        for v in (41, 42, 43):
            win.alpha_slider.setValue(v)
        win._on_legend_changed()        # a UI save that does not log anything itself

        disk_alpha = _on_disk(win)["panel"]["blots"][0]["display"]["overlay_alpha"]
        last = [e for e in _ops(win) if e.field == "display.overlay_alpha"][-1]
        assert disk_alpha == pytest.approx(last.new_value) == pytest.approx(0.43)
        assert not win._gesture_committer.has_pending
        reloaded = win.workspace.load_project(
            str(win.workspace.projects_dir / win.current_project.project.id / "project.json"))
        assert verify_log_chain(reloaded).status == "ok"

    def test_other_log_entry_flushes_first(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.alpha_slider.setValue(70)
        win._on_flip_horizontal()
        ops = [e.operation for e in _ops(win)][-2:]
        assert ops == ["overlay_alpha_changed", "flip_horizontal_changed"]

    def test_export_entry_point_flushes_before_export_entry(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.alpha_slider.setValue(80)
        p1, p2, p3, p4 = _patched_save(tmp_path / "fig.png")
        with p1, p2, p3, p4 as critical:
            win.export_final_png()
        assert not critical.called, critical.call_args
        ops = [e.operation for e in _ops(win)]
        assert ops.index("overlay_alpha_changed") < ops.index("export_generated")

    def test_integrity_report_flushes_before_its_entry(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.protein_font_size_spin.setValue(14)
        out = tmp_path / "reports"
        out.mkdir()
        p1, p2, p3, p4 = _patched_save(out)
        with p1, p2, p3, p4 as critical:
            win.export_integrity_report()
        assert not critical.called, critical.call_args
        ops = [e.operation for e in _ops(win)]
        assert ops.index("protein_font_size_changed") < ops.index("integrity_report_generated")

    def test_switching_blot_commits_change_to_previous_blot(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.alpha_slider.setValue(20)
        win.prov_blot_combo.setCurrentIndex(1)          # -> blot_02
        (entry,) = _ops(win, "overlay_alpha_changed")
        assert entry.target_id == "blot_01" and entry.new_value == pytest.approx(0.20)
        assert win.active_blot_id == "blot_02"

    def test_close_commits_pending_change(self, qapp, tmp_path):
        win = _window(tmp_path)
        win.mw_label_size_spin.setValue(30)
        win.close()
        (entry,) = _ops(win, "kda_label_font_size_changed")
        assert entry.new_value == 30.0
        assert _on_disk(win)["panel"]["style"]["kda_label_font_size_pt"] == 30.0


# ===========================================================================
# Part A: crop previews rebuilt only where a change can affect them
# ===========================================================================

class TestScopedRefresh:

    @pytest.fixture
    def spy(self):
        calls = []
        real = Workspace.ensure_blot_crop_preview

        def wrapper(self_ws, blot, panel, channel_index=-1, **kw):
            calls.append(blot.id)
            return real(self_ws, blot, panel, channel_index=channel_index, **kw)

        with patch.object(Workspace, "ensure_blot_crop_preview", wrapper):
            yield calls

    def test_protein_font_size_regenerates_nothing(self, qapp, tmp_path, spy):
        win = _window(tmp_path)
        spy.clear()
        win.protein_font_size_spin.setValue(15)
        win._gesture_committer.flush()                 # also runs the pending redraw
        assert spy == []

    def test_overlay_alpha_regenerates_nothing(self, qapp, tmp_path, spy):
        win = _window(tmp_path)
        spy.clear()
        win.alpha_slider.setValue(90)
        win._gesture_committer.flush()
        assert spy == []

    def test_levels_slider_regenerates_active_blot_only(self, qapp, tmp_path, spy):
        win = _window(tmp_path)
        spy.clear()
        win.levels_black_slider.setValue(3000)
        win._gesture_committer.flush()
        assert spy and set(spy) == {"blot_01"}

    def test_rotation_dial_regenerates_active_blot_only(self, qapp, tmp_path, spy):
        win = _window(tmp_path)
        spy.clear()
        win.prov_rotate_dial.setValue(25)
        win._gesture_committer.flush()
        assert spy and set(spy) == {"blot_01"}

    def test_crop_template_resize_regenerates_all_blots(self, qapp, tmp_path, spy):
        win = _window(tmp_path)
        spy.clear()
        win._on_crop_resize_commit()
        assert set(spy) == {"blot_01", "blot_02"}

    def test_refresh_button_regenerates_all(self, qapp, tmp_path, spy):
        """clicked(bool) must not be passed on as the regenerate scope."""
        win = _window(tmp_path)
        spy.clear()
        with patch("pysternblot.ui.main_window.QMessageBox.critical") as critical:
            win.final_refresh_btn.click()
        assert not critical.called
        assert set(spy) == {"blot_01", "blot_02"}

    def test_refresh_previews_scopes(self, qapp, tmp_path, spy):
        win = _window(tmp_path)
        for scope, expected in (("all", {"blot_01", "blot_02"}), ("active", {"blot_01"}), ("none", set())):
            spy.clear()
            win.refresh_previews(regenerate=scope)
            assert set(spy) == expected, scope
        with pytest.raises(ValueError):
            win.refresh_previews(regenerate="some")
