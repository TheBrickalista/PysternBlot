# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Characterisation test for the legend layout (issue #202).

Written and frozen against the renderer as it was before 3-level headers
were added: every legacy legend below must keep rendering exactly as it did.
Any change to the EXPECTED literals is a regression.

The snapshot is font-independent so it holds on every platform's fonts:
  - centred text: its centre x (x + width / 2), which does not depend on the
    font; right-column text (left-aligned): its left x;
  - rows: an ordinal (0 = top) instead of an absolute y;
  - underlines: x1, x2 and their vertical relation to a text row: "above"
    (exactly 6 px above that row's text) or "below" (below that row).
Both the Figure tab (build_panel_scene) and the Legend export zone
(draw_legend_into_scene) are checked.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsScene, QGraphicsTextItem

from pysternblot.models import Blot, LegendRow, LegendSettings, Style
from pysternblot.render import build_panel_scene, draw_legend_into_scene

from test_licor_marker_channels import IMG_H, IMG_W, _project, _write_asset

X0 = 20.0
LADDER_W = float(Style().ladder_col_width_px)
IMG_COL_X = X0 + LADDER_W            # 80.0
IMG_COL_W = float(IMG_W)             # 300.0 (one 300 px blot, drawn 1:1)
RIGHT_COL_X = IMG_COL_X + IMG_COL_W + 10.0


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _row(cells, groups, left="", right=""):
    return LegendRow(left=left, cells=list(cells), right=right, cell_groups=list(groups))


ISSUE_ROW_2 = ["Control", "JPH203 1uM", "Control", "JPH203 1uM"]
ISSUE_LANES = ["0", "10", "0", "10", "0", "10", "0", "10", "Pos. control"]

LEGENDS = {
    # (a) 2 upper rows, grouped (ids on both rows)
    "a_two_upper_grouped": LegendSettings(upper_rows=[
        _row(["Treated", "Untreated"], [1, 2], left="Cond."),
        _row(["a", "b", "c", "d"], [1, 1, 2, 2], right="Time"),
    ]),
    # (b) 2 upper rows, ungrouped top cells (own_step path)
    "b_two_upper_ungrouped": LegendSettings(upper_rows=[
        _row(["X", "Y", "Z"], [0, 0, 0], left="L1", right="R1"),
        _row(["p", "q", "r", "s"], [0, 0, 0, 0]),
    ]),
    # (c) issue #202 exactly: row 1 ids 1,1 -> own_step 2.25 / 6.75 lanes
    "c_issue_202_ids_1_1": LegendSettings(upper_rows=[
        _row(["Serum starved", "Growing"], [1, 1]),
        _row(ISSUE_ROW_2, [2, 3, 4, 5]),
        _row(ISSUE_LANES, [2, 2, 3, 3, 4, 4, 5, 5, 0]),
    ]),
    # (d) same, row 1 ids 2,4 -> centred on single middle groups (collapse)
    "d_issue_202_ids_2_4": LegendSettings(upper_rows=[
        _row(["Serum starved", "Growing"], [2, 4]),
        _row(ISSUE_ROW_2, [2, 3, 4, 5]),
        _row(ISSUE_LANES, [2, 2, 3, 3, 4, 4, 5, 5, 0]),
    ]),
    # (e) mixed: 2 upper + 1 lower (lane ref = lower_rows[0])
    "e_mixed": LegendSettings(
        upper_rows=[
            _row(["A", "B"], [1, 2], left="Top"),
            _row(["x", "y", "z"], [0, 0, 0]),
        ],
        lower_rows=[_row(["l1", "l2", "l3", "l4"], [1, 1, 2, 2], right="Lanes")],
    ),
    # (f) single-lane id (3) and non-contiguous id (4) on the lane row
    "f_single_and_noncontiguous": LegendSettings(upper_rows=[
        _row(["P", "Q", "R"], [3, 4, 0]),
        _row(["1", "2", "3", "4", "5"], [3, 4, 0, 4, 0]),
    ]),
    # (g) lower rows only
    "g_lower_only": LegendSettings(lower_rows=[
        _row(["a", "b", "c"], [1, 1, 0], left="Low"),
        _row(["d", "e"], [0, 0]),
    ]),
}


def _plain_blot(sha: str) -> Blot:
    """One ECL blot, no overlay ladder and no protein label: the figure then
    contains only the image, its border and the legend."""
    return Blot.model_validate({
        "id": "b1", "asset_sha256": sha,
        "crop": {"x": 0, "y": 0, "w": IMG_W, "h": IMG_H},
        "ladder": {"lane_index": 0, "marker_set_id": "ms1",
                   "calibration_points": [{"y_px": 1, "kda": 55}, {"y_px": 2, "kda": 36}]},
        "protein_label": {"text": ""},
    })


def _snapshot(scene, right_col_x: float):
    texts = [i for i in scene.items() if isinstance(i, QGraphicsTextItem) and i.toPlainText()]
    row_ys = sorted({round(t.pos().y(), 6) for t in texts})
    ordinal = {y: n for n, y in enumerate(row_ys)}

    text_snap = []
    for t in texts:
        x, y = t.pos().x(), round(t.pos().y(), 6)
        if abs(x - right_col_x) < 1e-9:
            key = ("L", round(x, 2))
        else:
            key = ("C", round(x + t.boundingRect().width() / 2.0, 2))
        text_snap.append((t.toPlainText(), key[0], key[1], ordinal[y]))

    line_snap = []
    for item in scene.items():
        if not isinstance(item, QGraphicsLineItem):
            continue
        line = item.line()
        ly = round(line.y1(), 6)
        above = [n for y, n in ordinal.items() if abs((y - 6.0) - ly) < 1e-6]
        if above:
            rel = ("above", above[0])
        else:
            rel = ("below", max(n for y, n in ordinal.items() if y < ly))
        line_snap.append((round(line.x1(), 2), round(line.x2(), 2)) + rel)

    return sorted(text_snap), sorted(line_snap)


def _figure_snapshot(tmp_path, legend):
    project = _project(_plain_blot(_write_asset(tmp_path, 30000)))
    project.panel.legend = legend
    return _snapshot(build_panel_scene(project, tmp_path), RIGHT_COL_X)


def _zone_snapshot(legend):
    project = _project(_plain_blot("unused"))
    project.panel.legend = legend
    scene = QGraphicsScene()
    draw_legend_into_scene(scene, project, X0, 20.0, IMG_COL_X, IMG_COL_W)
    return _snapshot(scene, RIGHT_COL_X)


# Frozen from the renderer before 3-level headers (do not edit).
EXPECTED = {'a_two_upper_grouped': ([('Cond.', 'C', 50.0, 0),
                          ('Time', 'L', 390.0, 1),
                          ('Treated', 'C', 155.0, 0),
                          ('Untreated', 'C', 305.0, 0),
                          ('a', 'C', 117.5, 1),
                          ('b', 'C', 192.5, 1),
                          ('c', 'C', 267.5, 1),
                          ('d', 'C', 342.5, 1)],
                         [(100.0, 210.0, 'above', 1), (250.0, 360.0, 'above', 1)]),
 'b_two_upper_ungrouped': ([('L1', 'C', 50.0, 0),
                            ('R1', 'L', 390.0, 0),
                            ('X', 'C', 130.0, 0),
                            ('Y', 'C', 230.0, 0),
                            ('Z', 'C', 330.0, 0),
                            ('p', 'C', 117.5, 1),
                            ('q', 'C', 192.5, 1),
                            ('r', 'C', 267.5, 1),
                            ('s', 'C', 342.5, 1)],
                           []),
 'c_issue_202_ids_1_1': ([('0', 'C', 96.67, 2),
                          ('0', 'C', 163.33, 2),
                          ('0', 'C', 230.0, 2),
                          ('0', 'C', 296.67, 2),
                          ('10', 'C', 130.0, 2),
                          ('10', 'C', 196.67, 2),
                          ('10', 'C', 263.33, 2),
                          ('10', 'C', 330.0, 2),
                          ('Control', 'C', 113.33, 1),
                          ('Control', 'C', 246.67, 1),
                          ('Growing', 'C', 305.0, 0),
                          ('JPH203 1uM', 'C', 180.0, 1),
                          ('JPH203 1uM', 'C', 313.33, 1),
                          ('Pos. control', 'C', 363.33, 2),
                          ('Serum starved', 'C', 155.0, 0)],
                         [(100.0, 126.67, 'above', 2),
                          (166.67, 193.33, 'above', 2),
                          (233.33, 260.0, 'above', 2),
                          (300.0, 326.67, 'above', 2)]),
 'd_issue_202_ids_2_4': ([('0', 'C', 96.67, 2),
                          ('0', 'C', 163.33, 2),
                          ('0', 'C', 230.0, 2),
                          ('0', 'C', 296.67, 2),
                          ('10', 'C', 130.0, 2),
                          ('10', 'C', 196.67, 2),
                          ('10', 'C', 263.33, 2),
                          ('10', 'C', 330.0, 2),
                          ('Control', 'C', 113.33, 1),
                          ('Control', 'C', 246.67, 1),
                          ('Growing', 'C', 246.67, 0),
                          ('JPH203 1uM', 'C', 180.0, 1),
                          ('JPH203 1uM', 'C', 313.33, 1),
                          ('Pos. control', 'C', 363.33, 2),
                          ('Serum starved', 'C', 113.33, 0)],
                         [(100.0, 126.67, 'above', 2),
                          (166.67, 193.33, 'above', 2),
                          (233.33, 260.0, 'above', 2),
                          (300.0, 326.67, 'above', 2)]),
 'e_mixed': ([('A', 'C', 155.0, 0),
              ('B', 'C', 305.0, 0),
              ('Lanes', 'L', 390.0, 2),
              ('Top', 'C', 50.0, 0),
              ('l1', 'C', 117.5, 2),
              ('l2', 'C', 192.5, 2),
              ('l3', 'C', 267.5, 2),
              ('l4', 'C', 342.5, 2),
              ('x', 'C', 130.0, 1),
              ('y', 'C', 230.0, 1),
              ('z', 'C', 330.0, 1)],
             [(100.0, 210.0, 'below', 2), (250.0, 360.0, 'below', 2)]),
 'f_single_and_noncontiguous': ([('1', 'C', 110.0, 1),
                                 ('2', 'C', 170.0, 1),
                                 ('3', 'C', 230.0, 1),
                                 ('4', 'C', 290.0, 1),
                                 ('5', 'C', 350.0, 1),
                                 ('P', 'C', 130.0, 0),
                                 ('Q', 'C', 230.0, 0),
                                 ('R', 'C', 330.0, 0)],
                                []),
 'g_lower_only': ([('Low', 'C', 50.0, 0),
                   ('a', 'C', 130.0, 0),
                   ('b', 'C', 230.0, 0),
                   ('c', 'C', 330.0, 0),
                   ('d', 'C', 155.0, 1),
                   ('e', 'C', 305.0, 1)],
                  [(100.0, 260.0, 'below', 0)])}


@pytest.mark.parametrize("name", sorted(LEGENDS))
def test_figure_tab_layout_unchanged(qapp, tmp_path, name):
    assert _figure_snapshot(tmp_path, LEGENDS[name]) == EXPECTED[name]


@pytest.mark.parametrize("name", sorted(LEGENDS))
def test_export_zone_layout_unchanged(qapp, name):
    assert _zone_snapshot(LEGENDS[name]) == EXPECTED[name]
