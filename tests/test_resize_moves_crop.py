# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
A crop resize that moves the crop is logged as a crop move too.

Resizing from the top or left handle (or growing past the image edge, where
the position is clamped) changes the resized blot's crop x/y as well as the
shared template. crop_template_resized is logged as before, then
crop_committed with the previous and new crop (the active channel's on NIR
blots, named as in the other NIR entries). A resize that only changes the
size writes no crop entry.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from pysternblot.logchain import verify_log_chain

from test_commit_old_values import _crop_item, _drag, _prepared
from test_refresh_scope_staleness import ECL_A, NIR

RESIZE_NOTE = "Position changed by resizing the crop rectangle."


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _new_entries(win, n):
    return [e for e in win.current_project.operation_log[n:]
            if e.operation in ("crop_template_resized", "crop_committed")]


def _template(win):
    ct = win.current_project.panel.crop_template
    return {"w": ct.w, "h": ct.h}


def test_bottom_right_resize_logs_the_template_only(qapp, tmp_path):
    win = _prepared(tmp_path)
    t0 = _template(win)
    n = len(win.current_project.operation_log)
    _drag(win.prov_view, _crop_item(win).crop_scene_rect().bottomRight(), QPointF(40, 16))
    (entry,) = _new_entries(win, n)
    assert entry.operation == "crop_template_resized"
    assert (entry.old_value, entry.new_value) == (t0, {"w": t0["w"] + 40, "h": t0["h"] + 16})


@pytest.mark.parametrize("handle,delta,moved", [
    ("top_left", QPointF(-30, -20), (-30, -20)),
    ("left", QPointF(-25, 0), (-25, 0)),
    ("top", QPointF(0, -18), (0, -18)),
], ids=["top_left", "left", "top"])
def test_top_or_left_resize_logs_template_then_crop(qapp, tmp_path, handle, delta, moved):
    win = _prepared(tmp_path)
    blot = win._get_active_blot()
    crop0, t0 = blot.crop.model_dump(), _template(win)
    r = _crop_item(win).crop_scene_rect()
    start = {"top_left": r.topLeft(),
             "left": QPointF(r.left(), r.center().y()),
             "top": QPointF(r.center().x(), r.top())}[handle]
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, start, delta)

    template, crop = _new_entries(win, n)                 # this order
    assert template.operation == "crop_template_resized"
    assert template.old_value == t0
    assert template.new_value == {"w": t0["w"] - moved[0], "h": t0["h"] - moved[1]}
    assert crop.operation == "crop_committed"
    assert crop.old_value == crop0
    assert crop.new_value == blot.crop.model_dump()
    assert (crop.new_value["x"], crop.new_value["y"]) == (crop0["x"] + moved[0], crop0["y"] + moved[1])
    assert (crop.new_value["w"], crop.new_value["h"]) == (crop0["w"], crop0["h"])
    assert crop.note.endswith(RESIZE_NOTE)
    assert verify_log_chain(win.current_project).status == "ok"


def test_nir_channel_top_left_resize_names_the_channel(qapp, tmp_path):
    win = _prepared(tmp_path, NIR, channel=1)
    blot = win._get_active_blot()
    ch1_before = blot.get_channel_crop(1).model_dump()
    ch0_before = blot.get_channel_crop(0).model_dump()
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, _crop_item(win).crop_scene_rect().topLeft(), QPointF(-12, -9))

    template, crop = _new_entries(win, n)
    assert template.operation == "crop_template_resized"
    assert crop.operation == "crop_committed"
    assert crop.asset_sha256 == blot.channels[1].asset_sha256
    assert "NIR channel 1 (Ch2)" in crop.note and crop.note.endswith(RESIZE_NOTE)
    assert crop.old_value == ch1_before
    assert crop.new_value == blot.get_channel_crop(1).model_dump()
    assert (crop.new_value["x"], crop.new_value["y"]) == (ch1_before["x"] - 12, ch1_before["y"] - 9)
    assert blot.get_channel_crop(0).model_dump() == ch0_before     # other channel untouched


def _all_other_crops(project, resized_id):
    """Stored crops of every blot and NIR channel except the resized blot."""
    out = {}
    for b in project.panel.blots:
        if b.id == resized_id:
            continue
        out[b.id] = b.crop.model_dump()
        for ch in b.channels:
            out[f"{b.id}/ch{ch.channel_index}"] = ch.crop.model_dump() if ch.crop else None
    return out


def _disk_other_crops(win, resized_id):
    path = win.workspace.projects_dir / win.current_project.project.id / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for b in data["panel"]["blots"]:
        if b["id"] == resized_id:
            continue
        out[b["id"]] = b["crop"]
        for ch in b.get("channels") or []:
            out[f"{b['id']}/ch{ch['channel_index']}"] = ch.get("crop")
    return out


def test_growing_past_the_image_edge_clamps_and_logs_the_move(qapp, tmp_path):
    # Bottom-right handle, but the crop is pushed back inside the image: the
    # position changes, so a crop entry is written too.
    win = _prepared(tmp_path)
    blot = win._get_active_blot()

    # Another blot whose crop sits 10 px from its image's right edge: the
    # larger template must not move it in the model (clamping belongs to the
    # preview only).
    other = next(b for b in win.current_project.panel.blots if b.id == ECL_A)
    other_w, _ = win._active_image_size(other)
    other.crop.x = other_w - win.current_project.panel.crop_template.w - 10
    win._save_project()
    others_before = _all_other_crops(win.current_project, blot.id)
    assert _disk_other_crops(win, blot.id) == others_before

    crop0 = blot.crop.model_dump()
    image_w, _ = win._active_image_size(blot)
    grow = image_w - crop0["x"] - crop0["w"] + 150      # 150 px past the right edge
    n = len(win.current_project.operation_log)

    _drag(win.prov_view, _crop_item(win).crop_scene_rect().bottomRight(), QPointF(grow, 0))

    template, crop = _new_entries(win, n)
    assert template.operation == "crop_template_resized"
    assert crop.operation == "crop_committed" and crop.old_value == crop0
    assert crop.new_value["x"] == crop0["x"] - 150     # clamped back inside
    assert crop.new_value["y"] == crop0["y"]
    assert crop.target_id == blot.id                    # the only crop entry

    # Every other blot's and channel's stored crop is untouched, in the model
    # and on disk, even where the new template now runs past its image.
    assert _all_other_crops(win.current_project, blot.id) == others_before
    assert _disk_other_crops(win, blot.id) == others_before
    new_w = win.current_project.panel.crop_template.w
    assert other.crop.x + new_w > other_w               # the template overhangs it ...
    preview = win.workspace.assets_dir / other.asset_sha256 / f"preview_crop_{other.id}.tif"
    assert tifffile.imread(preview).shape[1] == int(other_w - other.crop.x)   # ... clamped in the preview only
