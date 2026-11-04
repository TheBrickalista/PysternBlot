# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Issue #202: 3-level (and deeper) legend headers.

A middle row's parent_groups groups its cells under the cell carrying that id
(in cell_groups) in the row above; the upper cell is centred on the union of
their lane extents and the group gets an underline at that level. Legacy
legends are covered by tests/test_legend_layout_compat.py.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSpinBox

from pysternblot.models import LegendRow, LegendSettings, Project
from pysternblot.render import compute_upper_legend_layout
from pysternblot.ui.legend_tab import LegendRowEditor, LegendTab

from test_legend_layout_compat import (
    IMG_COL_W,
    IMG_COL_X,
    ISSUE_LANES,
    ISSUE_ROW_2,
    _figure_snapshot,
    _zone_snapshot,
)

LANE_W = IMG_COL_W / 9.0
PAD = 20.0


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _row(cells, groups, parents=None):
    return LegendRow(cells=list(cells), cell_groups=list(groups), parent_groups=list(parents or []))


def _issue_rows(top_ids=(1, 2), middle_parents=(1, 1, 2, 2)):
    return [
        _row(["Serum starved", "Growing"], top_ids),
        _row(ISSUE_ROW_2, [2, 3, 4, 5], middle_parents),
        _row(ISSUE_LANES, [2, 2, 3, 3, 4, 4, 5, 5, 0]),
    ]


def _lane_x(lane: float) -> float:
    """Scene x of a lane coordinate (0 = left edge of the image column)."""
    return IMG_COL_X + lane * LANE_W


LANE_UNDERLINES = [  # the four lane-level groups of the issue example, unchanged
    (_lane_x(a) + PAD, _lane_x(a + 2) - PAD) for a in (0, 2, 4, 6)
]


# ===========================================================================
# Pure layout
# ===========================================================================

class TestComputeUpperLegendLayout:

    def test_issue_example_centres_on_combined_lanes(self):
        rows = _issue_rows()
        layout = compute_upper_legend_layout(rows, rows[-1], IMG_COL_X, IMG_COL_W)
        serum, growing = layout.rows[0].centers
        assert serum == pytest.approx(_lane_x(2.0), abs=1e-6)      # lanes 0-3
        assert growing == pytest.approx(_lane_x(6.0), abs=1e-6)    # lanes 4-7
        assert serum == pytest.approx(IMG_COL_X + 2 / 9 * IMG_COL_W, abs=1e-6)
        assert growing == pytest.approx(IMG_COL_X + 6 / 9 * IMG_COL_W, abs=1e-6)

    def test_parent_underlines_and_unchanged_lane_underlines(self):
        rows = _issue_rows()
        layout = compute_upper_legend_layout(rows, rows[-1], IMG_COL_X, IMG_COL_W)
        assert layout.rows[1].parent_underlines == pytest.approx([
            (_lane_x(0) + PAD, _lane_x(4) - PAD),
            (_lane_x(4) + PAD, _lane_x(8) - PAD),
        ])
        assert layout.rows[2].lane_underlines == pytest.approx(LANE_UNDERLINES)
        assert layout.rows[0].parent_underlines == []
        assert layout.rows[2].parent_underlines == []

    def test_single_member_parent_centres_on_that_cell_without_underline(self):
        rows = _issue_rows(middle_parents=(1, 0, 2, 2))
        layout = compute_upper_legend_layout(rows, rows[-1], IMG_COL_X, IMG_COL_W)
        assert layout.rows[0].centers[0] == pytest.approx(_lane_x(1.0))   # "Control" = lanes 0-1
        assert layout.rows[0].centers[1] == pytest.approx(_lane_x(6.0))
        assert layout.rows[1].parent_underlines == pytest.approx([(_lane_x(4) + PAD, _lane_x(8) - PAD)])

    def test_non_contiguous_parent_is_reported_and_falls_back(self):
        rows = _issue_rows(middle_parents=(1, 2, 1, 0))
        layout = compute_upper_legend_layout(rows, rows[-1], IMG_COL_X, IMG_COL_W)
        assert layout.rows[1].parent_errors == {1}
        # id 1 is not a lane group either -> even slot of 2 cells (lane 2.25)
        assert layout.rows[0].centers[0] == pytest.approx(_lane_x(2.25))
        # id 2 is a single contiguous member (cell 1) -> centred on it
        assert layout.rows[0].centers[1] == pytest.approx(_lane_x(3.0))
        assert layout.rows[1].parent_underlines == []

    def test_parent_with_no_labelling_cell_above_draws_no_underline(self):
        rows = _issue_rows(middle_parents=(3, 3, 0, 0))   # row 1 uses 1 and 2, not 3
        layout = compute_upper_legend_layout(rows, rows[-1], IMG_COL_X, IMG_COL_W)
        assert layout.rows[1].parent_underlines == []
        # no parent run for 1 or 2: id 1 -> even slot (lane 2.25); id 2 is a lane
        # group (lanes 0-1) -> step 2, exactly as before
        assert layout.rows[0].centers == pytest.approx([_lane_x(2.25), _lane_x(1.0)])

    def test_four_level_chain_resolves_recursively(self):
        rows = [
            _row(["All"], [9]),
            _row(["Serum starved", "Growing"], [1, 2], [9, 9]),
            _row(ISSUE_ROW_2, [2, 3, 4, 5], [1, 1, 2, 2]),
            _row(ISSUE_LANES, [2, 2, 3, 3, 4, 4, 5, 5, 0]),
        ]
        layout = compute_upper_legend_layout(rows, rows[-1], IMG_COL_X, IMG_COL_W)
        assert layout.rows[0].centers == pytest.approx([_lane_x(4.0)])                # lanes 0-7
        assert layout.rows[1].centers == pytest.approx([_lane_x(2.0), _lane_x(6.0)])
        assert layout.rows[1].parent_underlines == pytest.approx([(_lane_x(0) + PAD, _lane_x(8) - PAD)])
        assert len(layout.rows[2].parent_underlines) == 2

    def test_mixed_mode_resolves_the_same_way(self):
        lane_ref = _row(ISSUE_LANES, [2, 2, 3, 3, 4, 4, 5, 5, 0])
        upper = [
            _row(["Serum starved", "Growing"], [1, 2]),
            _row(ISSUE_ROW_2, [2, 3, 4, 5], [1, 1, 2, 2]),
            _row(["d1", "d2", "d3", "d4"], [2, 3, 4, 5]),
        ]
        layout = compute_upper_legend_layout(upper, lane_ref, IMG_COL_X, IMG_COL_W)
        assert layout.rows[0].centers == pytest.approx([_lane_x(2.0), _lane_x(6.0)])
        assert len(layout.rows[1].parent_underlines) == 2
        assert all(r.lane_underlines == [] for r in layout.rows)   # lower row draws its own

    def test_empty_parent_groups_is_the_legacy_layout(self):
        rows = _issue_rows(top_ids=(1, 1), middle_parents=())
        layout = compute_upper_legend_layout(rows, rows[-1], IMG_COL_X, IMG_COL_W)
        assert layout.rows[0].centers == pytest.approx([_lane_x(2.25), _lane_x(6.75)])
        assert all(r.parent_underlines == [] for r in layout.rows)


# ===========================================================================
# Drawn scenes
# ===========================================================================

def _issue_legend(**kw) -> LegendSettings:
    return LegendSettings(upper_rows=_issue_rows(**kw))


class TestDrawnScenes:

    def test_figure_tab_draws_parent_and_lane_underlines(self, qapp, tmp_path):
        texts, lines = _figure_snapshot(tmp_path, _issue_legend())
        centres = {t[0]: t[2] for t in texts if t[0] in ("Serum starved", "Growing")}
        assert centres == pytest.approx({"Serum starved": round(_lane_x(2.0), 2), "Growing": round(_lane_x(6.0), 2)})
        parent = [(x1, x2) for x1, x2, rel, row in lines if (rel, row) == ("above", 1)]
        lane = [(x1, x2) for x1, x2, rel, row in lines if (rel, row) == ("above", 2)]
        assert parent == pytest.approx([(round(_lane_x(0) + PAD, 2), round(_lane_x(4) - PAD, 2)),
                                        (round(_lane_x(4) + PAD, 2), round(_lane_x(8) - PAD, 2))])
        assert lane == pytest.approx([(round(a, 2), round(b, 2)) for a, b in LANE_UNDERLINES])

    def test_figure_tab_and_export_zone_identical(self, qapp, tmp_path):
        legend = _issue_legend()
        assert _figure_snapshot(tmp_path, legend) == _zone_snapshot(legend)


# ===========================================================================
# project.json
# ===========================================================================

class TestSerialisation:

    def test_round_trip_keeps_parent_groups(self):
        legend = _issue_legend()
        back = LegendSettings.model_validate_json(legend.model_dump_json())
        assert back.upper_rows[1].parent_groups == [1, 1, 2, 2]

    def test_legacy_json_without_key_loads_empty(self):
        legacy = {"left": "", "cells": ["a", "b"], "right": "", "cell_groups": [1, 1]}
        row = LegendRow.model_validate_json(json.dumps(legacy))
        assert row.parent_groups == []
        fixture = Project.model_validate_json(open("tests/fixtures/chained_log_project_1.2.2.json").read())
        assert all(r.parent_groups == [] for r in fixture.panel.legend.upper_rows + fixture.panel.legend.lower_rows)


# ===========================================================================
# Legend tab UI
# ===========================================================================

def _parent_spins(editor) -> list[QSpinBox]:
    return list(getattr(editor, "_parent_group_spins", []))


def _tab_with_upper_rows(n: int, *, lower: int = 0) -> LegendTab:
    from types import SimpleNamespace
    legend = LegendSettings(
        upper_rows=[_row(["a", "b"], [0, 0]) for _ in range(n)],
        lower_rows=[_row(["c", "d"], [0, 0]) for _ in range(lower)],
    )
    project = SimpleNamespace(panel=SimpleNamespace(legend=legend))
    tab = LegendTab()
    tab.bind(project, lambda: [], lambda _txt: None)
    return tab


class TestLegendTabUi:

    def test_row_editor_writes_parent_groups(self, qapp):
        row = _row(["x", "y", "z"], [0, 0, 0])
        editor = LegendRowEditor("Row 2", row, lambda: [], lambda _t: None, lambda: None, show_parent=True)
        spins = _parent_spins(editor)
        assert len(spins) == 3
        spins[0].setValue(1)
        spins[1].setValue(1)
        spins[2].setValue(2)
        assert row.parent_groups == [1, 1, 2]

        editor.n_cells.setValue(4)            # kept the same length as cells
        assert row.parent_groups == [1, 1, 2, 0]

    def test_non_contiguous_parent_spin_is_tinted(self, qapp):
        row = _row(["x", "y", "z"], [0, 0, 0], [1, 2, 1])
        editor = LegendRowEditor("Row 2", row, lambda: [], lambda _t: None, lambda: None, show_parent=True)
        styles = [s.styleSheet() for s in _parent_spins(editor)]
        assert "#fef3c7" in styles[0] and "#fef3c7" in styles[2] and styles[1] == ""

    def test_two_upper_rows_show_no_parent_spinbox(self, qapp):
        tab = _tab_with_upper_rows(2)
        assert [len(_parent_spins(w)) for w in tab._upper_row_widgets] == [0, 0]

    def test_three_upper_rows_show_it_on_row_2_only(self, qapp):
        tab = _tab_with_upper_rows(3)
        assert [len(_parent_spins(w)) for w in tab._upper_row_widgets] == [0, 2, 0]

    def test_mixed_mode_shows_it_on_rows_2_to_n(self, qapp):
        tab = _tab_with_upper_rows(3, lower=1)
        assert [len(_parent_spins(w)) for w in tab._upper_row_widgets] == [0, 2, 2]
