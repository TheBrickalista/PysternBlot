# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
The legend export zone: rendering never changes the model.

With no stored zone, the Original Image view shows render.default_legend_zone
(300 x 200, centred). It is stored, and logged as legend_zone_changed
None -> value, only when the user first moves or resizes it, or changes one
of its options. The legend-zone PNG export uses the same default, so what is
shown is what is exported.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from pysternblot import render
from pysternblot.models import LegendZone
from pysternblot.render import default_legend_zone
from pysternblot.ui import export_mixin as export_mixin_module

from test_commit_old_values import _drag, _legend_item, _prepared
from test_refresh_scope_staleness import ECL_B


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _disk(win) -> dict:
    path = win.workspace.projects_dir / win.current_project.project.id / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["project"].pop("modified_utc", None)          # save time only
    return data


def _disk_blot(win, blot_id):
    return next(b for b in _disk(win)["panel"]["blots"] if b["id"] == blot_id)


def _image_size(win):
    return win._active_image_size(win._get_active_blot())


def _export_zone_png(win, path):
    with ExitStack() as stack:
        stack.enter_context(patch.object(
            export_mixin_module.QFileDialog, "getSaveFileName", return_value=(str(path), "")))
        stack.enter_context(patch.object(export_mixin_module.QMessageBox, "information"))
        critical = stack.enter_context(patch.object(export_mixin_module.QMessageBox, "critical"))
        win.export_legend_zone_png()
    assert not critical.called, critical.call_args
    assert path.is_file()
    return path.read_bytes()


def test_default_matches_the_previous_formula():
    # The numbers the old render code computed when it created the zone.
    for w, h in [(1200, 1648), (300, 200), (100, 80), (1500.0, 2000.0)]:
        z = default_legend_zone(w, h)
        assert (z.x, z.y, z.w, z.h) == (max(0.0, (w - 300.0) / 2.0), max(0.0, (h - 200.0) / 2.0),
                                        300.0, 200.0)
        assert (z.show_markers, z.marker_side) == (LegendZone().show_markers,
                                                   LegendZone().marker_side)


def test_showing_the_zone_and_saving_change_neither_project_json_nor_log(qapp, tmp_path):
    win = _prepared(tmp_path)
    win._save_project()
    disk_before, log_before = _disk(win), len(win.current_project.operation_log)

    win.legend_zone_cb.setChecked(True)            # shows the default zone
    win._refresh_provenance_only()
    win._sync_controls_from_project()
    win._save_project()

    assert win._get_active_blot().legend_zone is None
    assert len(win.current_project.operation_log) == log_before
    assert _disk(win) == disk_before
    assert _disk_blot(win, ECL_B)["legend_zone"] is None

    # And the shown zone is the centred default.
    r = _legend_item(win).crop_scene_rect()
    ox, oy = render.PROVENANCE_IMAGE_ORIGIN
    d = default_legend_zone(*_image_size(win))
    assert (r.x() - ox, r.y() - oy, r.width(), r.height()) == (d.x, d.y, d.w, d.h)


def test_first_move_logs_none_to_value_and_persists_it(qapp, tmp_path):
    win = _prepared(tmp_path)
    win.legend_zone_cb.setChecked(True)
    n = len(win.current_project.operation_log)
    _drag(win.prov_view, _legend_item(win).crop_scene_rect().center(), QPointF(25, -30))

    lz = win._get_active_blot().legend_zone
    d = default_legend_zone(*_image_size(win))
    assert (lz.x, lz.y, lz.w, lz.h) == (d.x + 25, d.y - 30, d.w, d.h)
    entries = [e for e in win.current_project.operation_log[n:]]
    assert [e.operation for e in entries] == ["legend_zone_changed"]
    assert entries[0].old_value is None
    assert entries[0].new_value == {"x": lz.x, "y": lz.y, "w": lz.w, "h": lz.h}
    on_disk = _disk_blot(win, ECL_B)["legend_zone"]
    assert (on_disk["x"], on_disk["y"], on_disk["w"], on_disk["h"]) == (lz.x, lz.y, lz.w, lz.h)


def test_click_on_the_default_zone_without_moving_stores_nothing(qapp, tmp_path):
    win = _prepared(tmp_path)
    win.legend_zone_cb.setChecked(True)
    n = len(win.current_project.operation_log)
    _drag(win.prov_view, _legend_item(win).crop_scene_rect().center(), QPointF(0, 0), steps=0)
    assert win._get_active_blot().legend_zone is None
    assert len(win.current_project.operation_log) == n


def test_export_without_a_stored_zone_stores_and_logs_it_first(qapp, tmp_path):
    win = _prepared(tmp_path / "a")
    win.legend_zone_cb.setChecked(True)
    blot = win._get_active_blot()
    assert blot.legend_zone is None
    n = len(win.current_project.operation_log)

    implicit = _export_zone_png(win, tmp_path / "implicit.png")

    d = default_legend_zone(*_image_size(win))
    lz = blot.legend_zone
    assert (lz.x, lz.y, lz.w, lz.h) == (d.x, d.y, d.w, d.h)        # the zone exported
    entries = win.current_project.operation_log[n:]
    assert [e.operation for e in entries] == ["legend_zone_changed", "export_generated"]
    assert entries[0].old_value is None
    assert entries[0].new_value == {"x": d.x, "y": d.y, "w": d.w, "h": d.h}
    assert entries[1].field == "legend_zone_png"
    on_disk = _disk_blot(win, ECL_B)["legend_zone"]
    assert (on_disk["x"], on_disk["y"]) == (d.x, d.y)

    # Byte-identical to the old code path, where the default had already been
    # stored (by rendering) before the export: reproduce that in a fresh window.
    win2 = _prepared(tmp_path / "b")
    win2.legend_zone_cb.setChecked(True)
    win2._get_active_blot().legend_zone = default_legend_zone(*_image_size(win2))
    explicit = _export_zone_png(win2, tmp_path / "explicit.png")
    assert implicit == explicit


def test_export_with_no_stored_zone_and_checkbox_unticked_is_refused(qapp, tmp_path):
    win = _prepared(tmp_path)
    assert not win.legend_zone_cb.isChecked()
    blot = win._get_active_blot()
    n = len(win.current_project.operation_log)
    out = tmp_path / "zone.png"
    with ExitStack() as stack:
        stack.enter_context(patch.object(
            export_mixin_module.QFileDialog, "getSaveFileName", return_value=(str(out), "")))
        info = stack.enter_context(patch.object(export_mixin_module.QMessageBox, "information"))
        stack.enter_context(patch.object(export_mixin_module.QMessageBox, "critical"))
        win.export_legend_zone_png()
    assert info.call_args.args[1:] == (
        "Legend export zone not set",
        "Enable and position the Legend export zone on the Original Image "
        "tab first (checkbox above the canvas).",
    )
    assert not out.exists()
    assert blot.legend_zone is None
    assert len(win.current_project.operation_log) == n


def test_cancelled_export_stores_nothing(qapp, tmp_path):
    win = _prepared(tmp_path)
    win.legend_zone_cb.setChecked(True)
    n = len(win.current_project.operation_log)
    with ExitStack() as stack:
        stack.enter_context(patch.object(
            export_mixin_module.QFileDialog, "getSaveFileName", return_value=("", "")))
        stack.enter_context(patch.object(export_mixin_module.QMessageBox, "information"))
        stack.enter_context(patch.object(export_mixin_module.QMessageBox, "critical"))
        win.export_legend_zone_png()
    assert win._get_active_blot().legend_zone is None
    assert len(win.current_project.operation_log) == n


def test_export_uses_the_displayed_default(qapp, tmp_path):
    # The exported region is the default zone of the same image the view shows.
    win = _prepared(tmp_path)
    win.legend_zone_cb.setChecked(True)
    seen = {}
    real = export_mixin_module._compute_export_geometry

    def spy(lz, *args, **kwargs):
        seen["zone"] = (lz.x, lz.y, lz.w, lz.h)
        return real(lz, *args, **kwargs)

    with patch.object(export_mixin_module, "_compute_export_geometry", spy):
        _export_zone_png(win, tmp_path / "zone.png")
    r = _legend_item(win).crop_scene_rect()
    ox, oy = render.PROVENANCE_IMAGE_ORIGIN
    assert seen["zone"] == (r.x() - ox, r.y() - oy, r.width(), r.height())


def test_stored_zone_behaves_as_before(qapp, tmp_path):
    win = _prepared(tmp_path)
    blot = win._get_active_blot()
    blot.legend_zone = LegendZone(x=40, y=50, w=220, h=150, show_markers=False, marker_side="right")
    win._save_project()
    win.legend_zone_cb.setChecked(True)

    r = _legend_item(win).crop_scene_rect()
    ox, oy = render.PROVENANCE_IMAGE_ORIGIN
    assert (r.x() - ox, r.y() - oy, r.width(), r.height()) == (40, 50, 220, 150)

    seen = {}
    real = export_mixin_module._compute_export_geometry

    def spy(lz, *args, **kwargs):
        seen["zone"] = lz
        return real(lz, *args, **kwargs)

    with patch.object(export_mixin_module, "_compute_export_geometry", spy):
        _export_zone_png(win, tmp_path / "zone.png")
    assert seen["zone"] is blot.legend_zone

    n = len(win.current_project.operation_log)
    _drag(win.prov_view, _legend_item(win).crop_scene_rect().center(), QPointF(10, 5))
    (entry,) = [e for e in win.current_project.operation_log[n:]
                if e.operation == "legend_zone_changed"]
    assert entry.old_value == {"x": 40, "y": 50, "w": 220, "h": 150}
    assert (blot.legend_zone.show_markers, blot.legend_zone.marker_side) == (False, "right")


def test_markers_toggle_without_a_stored_zone_stores_the_shown_default_and_logs_it(qapp, tmp_path):
    win = _prepared(tmp_path)
    win.legend_zone_cb.setChecked(True)
    n = len(win.current_project.operation_log)
    win.legend_zone_markers_cb.setChecked(False)   # -> _on_legend_zone_markers_toggled

    blot = win._get_active_blot()
    d = default_legend_zone(*_image_size(win))
    lz = blot.legend_zone
    assert (lz.x, lz.y, lz.w, lz.h) == (d.x, d.y, d.w, d.h)   # centred, not (0, 0)
    assert lz.show_markers is False
    ops = [(e.operation, e.old_value) for e in win.current_project.operation_log[n:]]
    assert ops == [("legend_zone_changed", None), ("legend_zone_markers_changed", True)]
    first = win.current_project.operation_log[n]
    assert first.new_value == {"x": d.x, "y": d.y, "w": d.w, "h": d.h}


def test_side_change_without_a_stored_zone(qapp, tmp_path):
    win = _prepared(tmp_path)
    win.legend_zone_cb.setChecked(True)
    blot = win._get_active_blot()
    combo = win.legend_zone_side_combo
    n = len(win.current_project.operation_log)

    win._on_legend_zone_side_changed(combo.currentIndex())    # same as the default: no-op
    assert blot.legend_zone is None
    assert len(win.current_project.operation_log) == n

    combo.setCurrentIndex(combo.findData("right"))             # a real change
    ops = [e.operation for e in win.current_project.operation_log[n:]]
    assert ops == ["legend_zone_changed", "legend_zone_side_changed"]
    d = default_legend_zone(*_image_size(win))
    assert (blot.legend_zone.x, blot.legend_zone.y) == (d.x, d.y)
    assert blot.legend_zone.marker_side == "right"
