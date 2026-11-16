# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
crop_committed, crop_template_resized and legend_zone_changed record the
value from before the interaction (captured on mouse press), in the same
shape as new_value. A click that moves nothing writes no entry
(log_operation skips old == new).

The interactions are real mouse press/move/release events on the Original
Image viewport (transform reset to identity, so scene deltas are exact).
Projects written by 1.2.x, whose entries have old_value = None, still load
and verify.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from pysternblot.integrity import build_integrity_report
from pysternblot.logchain import verify_log_chain
from pysternblot.models import Project
from pysternblot.storage import Workspace
from pysternblot.ui.crop_rect_item import CropRectItem

from test_refresh_scope_staleness import ECL_B, NIR, _activate
from test_source_export import _encode_png_uint16
from test_view_zoom_preserved import _show_tab_of, _shown

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_124 = ROOT / "tests" / "fixtures" / "crop_log_project_1.2.4.json"
LEGEND_BLUE = QColor("#1e88e5")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# --------------------------------------------------------------------------
# Real mouse interaction on the Original Image view
# --------------------------------------------------------------------------
def _send(view, kind, scene_pt, button, buttons):
    vp = view.viewport()
    local = QPointF(view.mapFromScene(scene_pt))
    ev = QMouseEvent(kind, local, QPointF(vp.mapToGlobal(local.toPoint())),
                     button, buttons, Qt.NoModifier)
    QApplication.sendEvent(vp, ev)


def _drag(view, start: QPointF, delta: QPointF, steps: int = 4):
    view.resetTransform()                          # 1 viewport px == 1 scene unit
    view.centerOn(start)
    _send(view, QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    for k in range(1, steps + 1):
        p = start + delta * (k / steps)
        _send(view, QEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton)
    _send(view, QEvent.MouseButtonRelease, start + delta, Qt.LeftButton, Qt.NoButton)


def _rect_items(win):
    items = [i for i in win.prov_view.scene().items() if isinstance(i, CropRectItem)]
    crop = [i for i in items if i.pen().color() != LEGEND_BLUE]
    legend = [i for i in items if i.pen().color() == LEGEND_BLUE]
    return crop, legend


def _crop_item(win):
    (item,) = _rect_items(win)[0]
    return item


def _legend_item(win):
    (item,) = _rect_items(win)[1]
    return item


def _entries(win, n, operation):
    return [e for e in win.current_project.operation_log[n:] if e.operation == operation]


def _prepared(tmp_path, blot_id=ECL_B, channel=None):
    win = _shown(tmp_path)
    _show_tab_of(win, win.prov_view)
    _activate(win, blot_id, channel=channel)
    assert win.pending_overlay_ladder_kda is None
    return win


# --------------------------------------------------------------------------
# Previous value recorded
# --------------------------------------------------------------------------
def test_crop_drag_move_logs_the_previous_crop(qapp, tmp_path):
    win = _prepared(tmp_path)
    blot = win._get_active_blot()
    before = blot.crop.model_dump()
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, _crop_item(win).crop_scene_rect().center(), QPointF(30, 20))

    (entry,) = _entries(win, n, "crop_committed")
    assert entry.old_value == before
    assert entry.new_value == blot.crop.model_dump()
    assert (entry.new_value["x"], entry.new_value["y"]) == (before["x"] + 30, before["y"] + 20)
    assert verify_log_chain(win.current_project).status == "ok"


def test_nir_channel_crop_drag_logs_that_channels_previous_crop(qapp, tmp_path):
    win = _prepared(tmp_path, NIR, channel=1)
    blot = win._get_active_blot()
    before = blot.get_channel_crop(1).model_dump()
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, _crop_item(win).crop_scene_rect().center(), QPointF(-25, 15))

    (entry,) = _entries(win, n, "crop_committed")
    assert entry.old_value == before
    assert entry.new_value == blot.get_channel_crop(1).model_dump()
    assert "NIR channel 1 (Ch2)" in entry.note


def test_crop_resize_logs_the_previous_template(qapp, tmp_path):
    win = _prepared(tmp_path)
    ct = win.current_project.panel.crop_template
    before = {"w": ct.w, "h": ct.h}
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, _crop_item(win).crop_scene_rect().bottomRight(), QPointF(40, 16))

    (entry,) = _entries(win, n, "crop_template_resized")
    assert entry.old_value == before
    assert entry.new_value == {"w": ct.w, "h": ct.h} == {"w": before["w"] + 40, "h": before["h"] + 16}
    assert _entries(win, n, "crop_committed") == []


def test_legend_zone_drag_logs_the_previous_zone(qapp, tmp_path):
    win = _prepared(tmp_path)
    win.legend_zone_cb.setChecked(True)            # creates and shows the zone
    blot = win._get_active_blot()
    lz = blot.legend_zone
    before = {"x": lz.x, "y": lz.y, "w": lz.w, "h": lz.h}
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, _legend_item(win).crop_scene_rect().center(), QPointF(-20, 35))

    (entry,) = _entries(win, n, "legend_zone_changed")
    assert entry.old_value == before
    assert entry.new_value == {"x": lz.x, "y": lz.y, "w": lz.w, "h": lz.h}
    assert (entry.new_value["x"], entry.new_value["y"]) == (before["x"] - 20, before["y"] + 35)


# --------------------------------------------------------------------------
# A click that moves nothing writes no entry
# --------------------------------------------------------------------------
@pytest.mark.parametrize("where", ["crop_body", "crop_resize_handle", "legend_zone"])
def test_click_without_movement_writes_no_entry(qapp, tmp_path, where):
    win = _prepared(tmp_path)
    if where == "legend_zone":
        win.legend_zone_cb.setChecked(True)
        point = _legend_item(win).crop_scene_rect().center()
    elif where == "crop_body":
        point = _crop_item(win).crop_scene_rect().center()
    else:
        point = _crop_item(win).crop_scene_rect().bottomRight()
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, point, QPointF(0, 0), steps=0)

    ops = [e.operation for e in win.current_project.operation_log[n:]]
    assert not set(ops) & {"crop_committed", "crop_template_resized", "legend_zone_changed"}, ops


def test_commit_without_a_press_still_logs_none(qapp, tmp_path):
    # A programmatic commit (no mouse press recorded) keeps the old behaviour.
    win = _prepared(tmp_path)
    blot = win._get_active_blot()
    blot.crop.x += 5
    n = len(win.current_project.operation_log)
    win._on_crop_commit(blot)
    (entry,) = _entries(win, n, "crop_committed")
    assert entry.old_value is None


def test_press_snapshot_is_used_once(qapp, tmp_path):
    win = _prepared(tmp_path)
    blot = win._get_active_blot()
    _drag(win.prov_view, _crop_item(win).crop_scene_rect().center(), QPointF(10, 10))
    assert win._crop_press_snapshot is None        # consumed by the commit
    blot.crop.x += 3
    n = len(win.current_project.operation_log)
    win._on_crop_commit(blot)                      # no new press
    (entry,) = _entries(win, n, "crop_committed")
    assert entry.old_value is None


# --------------------------------------------------------------------------
# 1.2.x projects (old_value = None) still load and verify
# --------------------------------------------------------------------------
def test_v124_project_with_none_old_values_still_verifies(qapp, tmp_path):
    data = json.loads(FIXTURE_124.read_text(encoding="utf-8"))
    old = [(e["operation"], e["old_value"]) for e in data["operation_log"]]
    assert old == [("crop_committed", None), ("crop_template_resized", None),
                   ("legend_zone_changed", None)]

    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    (sha,) = data["assets"]
    asset_dir = ws.assets_dir / sha
    asset_dir.mkdir(parents=True)
    (asset_dir / "original.png").write_bytes(
        _encode_png_uint16(np.full((64, 64), 12000, np.uint16)))
    proj_dir = ws.projects_dir / data["project"]["id"]
    proj_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_124, proj_dir / "project.json")

    project = ws.load_project(str(proj_dir / "project.json"))
    assert isinstance(project, Project)
    assert verify_log_chain(project).status == "ok"
    report = build_integrity_report(project, ws, project_json_path=proj_dir / "project.json")
    assert report["operation_log_chain"]["status"] == "ok"
