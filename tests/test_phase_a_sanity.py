# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Step-0 sanity tests for Phase A legend grouping.

These tests verify derive_lane_groups math and the scene geometry produced by
build_panel_scene for four specific configurations, without requiring a real
blot image on disk. They create a synthetic 300x200 PNG in a temp workspace
so the renderer can get past its early-return guard.
"""

from __future__ import annotations

import os
import sys
import hashlib
import tempfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsTextItem

from pysternblot.render import derive_lane_groups, build_panel_scene
from pysternblot.models import (
    Blot, Crop, CropTemplate, HeaderBlock, Group, ConditionRow, LaneLayout,
    Layout, LegendRow, LegendSettings, Ladder, CalibrationPoint, Panel,
    Project, ProjectMeta, ProteinLabel, Style,
)


# ---------------------------------------------------------------------------
# Qt application singleton
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# Minimal workspace + project helpers
# ---------------------------------------------------------------------------

IMG_W, IMG_H = 300, 200


def _make_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Write a 300x200 white uint16 PNG; return (workspace_root, sha256)."""
    arr = np.full((IMG_H, IMG_W), 32768, dtype=np.uint16)
    png_bytes = _encode_png_uint16(arr)
    sha = hashlib.sha256(png_bytes).hexdigest()
    asset_dir = tmp_path / "assets" / sha
    asset_dir.mkdir(parents=True)
    (asset_dir / "original.png").write_bytes(png_bytes)
    return tmp_path, sha


def _encode_png_uint16(arr: np.ndarray) -> bytes:
    """Encode a 2-D uint16 array as a 16-bit grayscale PNG (no external libs)."""
    import struct, zlib

    h, w = arr.shape
    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    # IHDR: width, height, bit depth 16, color type 0 (grayscale), compression 0, filter 0, interlace 0
    ihdr = struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)
    # Raw scanlines: filter byte 0 + big-endian uint16 pixels
    scanlines = bytearray()
    for row in arr:
        scanlines.append(0)
        scanlines.extend(row.astype(">u2").tobytes())
    idat = chunk(b"IDAT", zlib.compress(bytes(scanlines), 6))
    iend = chunk(b"IEND", b"")
    return sig + chunk(b"IHDR", ihdr) + idat + iend


def _minimal_project(sha: str, legend: LegendSettings, n_lanes: int = 6) -> Project:
    header = HeaderBlock(
        left_title="kDa",
        groups=[Group(label="All", n_lanes=n_lanes)],
        condition_rows=[ConditionRow(values=[""] * n_lanes)],
    )
    blot = Blot(
        id="b1",
        asset_sha256=sha,
        crop=Crop(x=0, y=0, w=float(IMG_W), h=float(IMG_H)),
        ladder=Ladder(
            lane_index=0,
            marker_set_id="ms1",
            calibration_points=[
                CalibrationPoint(y_px=50, kda=55),
                CalibrationPoint(y_px=120, kda=36),
            ],
        ),
        protein_label=ProteinLabel(text=""),
    )
    panel = Panel(
        style=Style(),
        lane_layout=LaneLayout(header_block=header),
        blots=[blot],
        layout=Layout(order=["b1"]),
        legend=legend,
        crop_template=CropTemplate(w=float(IMG_W), h=float(IMG_H)),
    )
    return Project(
        project=ProjectMeta(
            id="p1", name="Test", created_utc="2026-01-01T00:00:00Z",
            app_version="0.0", license="GPL-3.0-only",
        ),
        panel=panel,
    )


def _lines(scene) -> list:
    return [item for item in scene.items() if isinstance(item, QGraphicsLineItem)]


def _texts(scene) -> list:
    return [item for item in scene.items() if isinstance(item, QGraphicsTextItem)]


# ---------------------------------------------------------------------------
# Case 1: Six lower cells [1,1,2,2,3,3] + three upper ["Total","Elution","Beads"]
# with cell_groups [1,2,3].  Expect 3 underlines and upper labels centered over
# their respective pairs.
# ---------------------------------------------------------------------------

class TestCase1ThreeGroups:

    @pytest.fixture(autouse=True)
    def _scene(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        legend = LegendSettings(
            upper_rows=[
                LegendRow(
                    cells=["Total", "Elution", "Beads"],
                    cell_groups=[1, 2, 3],
                )
            ],
            lower_rows=[
                LegendRow(
                    cells=["Ctrl", "PNGase F", "Ctrl", "PNGase F", "Ctrl", "PNGase F"],
                    cell_groups=[1, 1, 2, 2, 3, 3],
                )
            ],
        )
        proj = _minimal_project(sha, legend, n_lanes=6)
        self.scene = build_panel_scene(proj, ws)
        # Layout constants that the renderer uses (must match render.py defaults)
        s = proj.panel.style
        self.x0 = 20.0
        self.ladder_w = float(s.ladder_col_width_px)
        self.img_col_x = self.x0 + self.ladder_w
        self.img_col_w = float(IMG_W)
        self.lane_w = self.img_col_w / 6.0

    def test_three_underlines_drawn(self):
        lines = _lines(self.scene)
        assert len(lines) == 3, f"Expected 3 underlines, got {len(lines)}"

    def test_underline_spans_correct(self):
        """Each underline should span one pair of lanes (with padding)."""
        lines = _lines(self.scene)
        gap_px = 40.0
        pad = gap_px / 2.0
        lane_w = self.lane_w
        x = self.img_col_x

        expected_spans = [
            (x + 0 * lane_w + pad, x + 2 * lane_w - pad),  # group 1: lanes 0-1
            (x + 2 * lane_w + pad, x + 4 * lane_w - pad),  # group 2: lanes 2-3
            (x + 4 * lane_w + pad, x + 6 * lane_w - pad),  # group 3: lanes 4-5
        ]
        actual_spans = sorted(
            [(item.line().x1(), item.line().x2()) for item in lines],
            key=lambda t: t[0],
        )
        for (ex1, ex2), (ax1, ax2) in zip(expected_spans, actual_spans):
            assert abs(ax1 - ex1) < 0.5, f"x1 mismatch: expected {ex1:.1f}, got {ax1:.1f}"
            assert abs(ax2 - ex2) < 0.5, f"x2 mismatch: expected {ex2:.1f}, got {ax2:.1f}"

    def test_upper_labels_centered_over_groups(self):
        """Total/Elution/Beads should be centered over lane-pairs 0-1, 2-3, 4-5."""
        lane_w = self.lane_w
        x = self.img_col_x
        # group 1: (0,1) → center = x + (0+1+1)/2*lane_w = x + 1.0*lane_w
        # group 2: (2,3) → center = x + (2+3+1)/2*lane_w = x + 3.0*lane_w
        # group 3: (4,5) → center = x + (4+5+1)/2*lane_w = x + 5.0*lane_w
        expected_cx = [x + 1.0 * lane_w, x + 3.0 * lane_w, x + 5.0 * lane_w]

        texts = [t for t in _texts(self.scene)
                 if t.toPlainText().strip() in ("Total", "Elution", "Beads")]
        assert len(texts) == 3, f"Expected 3 upper labels, got {len(texts)}: {[t.toPlainText() for t in _texts(self.scene)]}"

        for item, ecx in zip(
            sorted(texts, key=lambda t: t.x()),
            sorted(expected_cx),
        ):
            br = item.boundingRect()
            # item.x() is the left edge; center = x + width/2
            actual_cx = item.x() + br.width() / 2.0
            assert abs(actual_cx - ecx) < 2.0, (
                f"Label '{item.toPlainText()}' center {actual_cx:.1f} ≠ expected {ecx:.1f}"
            )


# ---------------------------------------------------------------------------
# Case 2: Single-lane labeled group — lower [0,1,1,2], upper has cell with
# group #2 (covers exactly 1 lower lane).  The upper label should fall back
# to its own even-distribution position since group 2 has only 1 lane
# (not in spans).
# ---------------------------------------------------------------------------

class TestCase2SingleLaneGroup:

    @pytest.fixture(autouse=True)
    def _scene(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        # Lower: 4 lanes. group 1 spans lanes 1-2, group 2 is single lane 3.
        # Upper: 2 cells. cell 0 has group 1 (valid span), cell 1 has group 2 (single lane).
        legend = LegendSettings(
            upper_rows=[
                LegendRow(
                    cells=["Grouped", "Single"],
                    cell_groups=[1, 2],
                )
            ],
            lower_rows=[
                LegendRow(
                    cells=["A", "B", "C", "D"],
                    cell_groups=[0, 1, 1, 2],
                )
            ],
        )
        proj = _minimal_project(sha, legend, n_lanes=4)
        self.scene = build_panel_scene(proj, ws)
        s = proj.panel.style
        self.img_col_x = 20.0 + float(s.ladder_col_width_px)
        self.img_col_w = float(IMG_W)
        self.n_lanes = 4
        self.lane_w = self.img_col_w / 4.0
        self.n_cells = 2
        self.own_step = self.img_col_w / 2.0

    def test_one_underline_only(self):
        """Only group 1 (lanes 1-2) should draw an underline. Group 2 is single-lane."""
        lines = _lines(self.scene)
        assert len(lines) == 1, f"Expected 1 underline, got {len(lines)}"

    def test_grouped_label_centered_over_span(self):
        """'Grouped' (group 1, lanes 1-2) → center at img_col_x + (1+2+1)/2 * lane_w."""
        expected_cx = self.img_col_x + (1 + 2 + 1) / 2.0 * self.lane_w
        items = [t for t in _texts(self.scene) if t.toPlainText().strip() == "Grouped"]
        assert len(items) == 1
        br = items[0].boundingRect()
        actual_cx = items[0].x() + br.width() / 2.0
        assert abs(actual_cx - expected_cx) < 2.0, (
            f"'Grouped' center {actual_cx:.1f} ≠ expected {expected_cx:.1f}"
        )

    def test_single_lane_group_label_uses_own_distribution(self):
        """'Single' (group 2, single lower lane) → not in spans → fallback to own_step.
        Cell index 1 of 2: center = img_col_x + (1 + 0.5) * own_step."""
        expected_cx = self.img_col_x + 1.5 * self.own_step
        items = [t for t in _texts(self.scene) if t.toPlainText().strip() == "Single"]
        assert len(items) == 1, f"Expected 1 'Single' label, got {len(items)}"
        br = items[0].boundingRect()
        actual_cx = items[0].x() + br.width() / 2.0
        assert abs(actual_cx - expected_cx) < 2.0, (
            f"'Single' center {actual_cx:.1f} ≠ expected (fallback) {expected_cx:.1f}"
        )


# ---------------------------------------------------------------------------
# Case 3: Non-contiguous group — lower [1,0,1] — confirm no underline drawn.
# ---------------------------------------------------------------------------

class TestCase3NonContiguous:

    @pytest.fixture(autouse=True)
    def _scene(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        legend = LegendSettings(
            lower_rows=[
                LegendRow(
                    cells=["A", "B", "C"],
                    cell_groups=[1, 0, 1],
                )
            ],
        )
        proj = _minimal_project(sha, legend, n_lanes=3)
        self.scene = build_panel_scene(proj, ws)

    def test_no_underline_for_non_contiguous(self):
        lines = _lines(self.scene)
        assert len(lines) == 0, (
            f"Non-contiguous group must not draw underline; got {len(lines)} line(s)"
        )


# ---------------------------------------------------------------------------
# Case 4: upper-rows only (the common workflow) — no lower rows.
# 2 upper rows: group-label row above + per-lane row below (the lane_ref).
# Bug regression: underlines must draw and group labels must center correctly.
# ---------------------------------------------------------------------------

class TestCase4UpperOnlyGrouping:

    @pytest.fixture(autouse=True)
    def _scene(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        legend = LegendSettings(
            upper_rows=[
                # Row 0: group-label row — 3 cells, each referencing one group
                LegendRow(
                    cells=["Total", "Elution", "Beads"],
                    cell_groups=[1, 2, 3],
                ),
                # Row 1 (lane_ref): per-lane row — 6 cells, pairs form groups
                LegendRow(
                    cells=["Ctrl", "Ctrl", "Sg1", "Sg1", "Sg2", "Sg2"],
                    cell_groups=[1, 1, 2, 2, 3, 3],
                ),
            ],
            # No lower_rows — the common case that was broken.
        )
        proj = _minimal_project(sha, legend, n_lanes=6)
        self.scene = build_panel_scene(proj, ws)
        s = proj.panel.style
        self.img_col_x = 20.0 + float(s.ladder_col_width_px)
        self.img_col_w = float(IMG_W)
        self.lane_w = self.img_col_w / 6.0

    def test_three_underlines_drawn(self):
        """Bug #1 regression: underlines must draw for upper-only grouping."""
        lines = _lines(self.scene)
        assert len(lines) == 3, (
            f"Expected 3 underlines for upper-only grouping; got {len(lines)}"
        )

    def test_underline_spans_correct(self):
        lines = _lines(self.scene)
        gap_px = 40.0
        pad = gap_px / 2.0
        x = self.img_col_x
        lw = self.lane_w
        expected = sorted([
            (x + 0 * lw + pad, x + 2 * lw - pad),  # group 1: lanes 0-1
            (x + 2 * lw + pad, x + 4 * lw - pad),  # group 2: lanes 2-3
            (x + 4 * lw + pad, x + 6 * lw - pad),  # group 3: lanes 4-5
        ])
        actual = sorted(
            [(item.line().x1(), item.line().x2()) for item in lines],
            key=lambda t: t[0],
        )
        for (ex1, ex2), (ax1, ax2) in zip(expected, actual):
            assert abs(ax1 - ex1) < 0.5, f"x1: expected {ex1:.1f}, got {ax1:.1f}"
            assert abs(ax2 - ex2) < 0.5, f"x2: expected {ex2:.1f}, got {ax2:.1f}"

    def test_group_labels_centered_over_spans(self):
        """Bug #2 regression: group-label row must use lane_ref geometry, not own."""
        x = self.img_col_x
        lw = self.lane_w
        expected_cx = {
            "Total":   x + 1.0 * lw,   # group 1: (0,1) midpoint
            "Elution": x + 3.0 * lw,   # group 2: (2,3) midpoint
            "Beads":   x + 5.0 * lw,   # group 3: (4,5) midpoint
        }
        for label, ecx in expected_cx.items():
            items = [t for t in _texts(self.scene) if t.toPlainText().strip() == label]
            assert len(items) >= 1, f"Label '{label}' not found in scene"
            br = items[0].boundingRect()
            acx = items[0].x() + br.width() / 2.0
            assert abs(acx - ecx) < 2.0, (
                f"'{label}' center {acx:.1f} ≠ expected {ecx:.1f}"
            )

    def test_underlines_above_lane_ref_text(self):
        """Option (a): underline must be above the lane_ref row's text (between rows)."""
        lines = _lines(self.scene)
        lane_texts = [t for t in _texts(self.scene)
                      if t.toPlainText().strip() in ("Ctrl", "Sg1", "Sg2")]
        assert lane_texts, "No lane_ref labels found"
        min_lane_y = min(t.y() for t in lane_texts)
        for line in lines:
            ul_y = line.line().y1()
            assert ul_y < min_lane_y, (
                f"Underline at y={ul_y:.1f} must be above lane labels at y≥{min_lane_y:.1f}"
            )

    def test_lane_ref_cells_at_per_lane_positions(self):
        """Bug fix: lane_ref row cells must not collapse to group center.

        lane_ref: cells=["Ctrl","Ctrl","Sg1","Sg1","Sg2","Sg2"],
                  cell_groups=[1,1,2,2,3,3], 6 lanes.
        After fix each cell is at its own lane center (i+0.5)*lane_w, not the
        group-span center that caused overprinting.
        """
        x = self.img_col_x
        lw = self.lane_w
        expected = [x + (i + 0.5) * lw for i in range(6)]

        def _cx(item):
            return item.x() + item.boundingRect().width() / 2.0

        ctrl_items = sorted(
            [t for t in _texts(self.scene) if t.toPlainText().strip() == "Ctrl"],
            key=_cx,
        )
        sg1_items = sorted(
            [t for t in _texts(self.scene) if t.toPlainText().strip() == "Sg1"],
            key=_cx,
        )
        sg2_items = sorted(
            [t for t in _texts(self.scene) if t.toPlainText().strip() == "Sg2"],
            key=_cx,
        )

        assert len(ctrl_items) == 2, f"Expected 2 'Ctrl' items; got {len(ctrl_items)}"
        assert len(sg1_items) == 2, f"Expected 2 'Sg1' items; got {len(sg1_items)}"
        assert len(sg2_items) == 2, f"Expected 2 'Sg2' items; got {len(sg2_items)}"

        for item, exp in zip(ctrl_items, expected[0:2]):
            assert abs(_cx(item) - exp) < 2.0, f"Ctrl center {_cx(item):.1f} ≠ {exp:.1f}"
        for item, exp in zip(sg1_items, expected[2:4]):
            assert abs(_cx(item) - exp) < 2.0, f"Sg1 center {_cx(item):.1f} ≠ {exp:.1f}"
        for item, exp in zip(sg2_items, expected[4:6]):
            assert abs(_cx(item) - exp) < 2.0, f"Sg2 center {_cx(item):.1f} ≠ {exp:.1f}"


# ---------------------------------------------------------------------------
# Case 5: derive_lane_groups pure logic checks (no Qt required)
# ---------------------------------------------------------------------------

class TestDeriveLaneGroupsStep0:

    def test_case1_three_pairs(self):
        spans, errors = derive_lane_groups([1, 1, 2, 2, 3, 3])
        assert spans == {1: (0, 1), 2: (2, 3), 3: (4, 5)}
        assert errors == set()

    def test_case2_single_lane_not_in_spans(self):
        spans, errors = derive_lane_groups([0, 1, 1, 2])
        assert 1 in spans
        assert 2 not in spans   # single occurrence → not in spans
        assert 2 not in errors  # single occurrence → not in errors

    def test_case3_non_contiguous_in_errors(self):
        spans, errors = derive_lane_groups([1, 0, 1])
        assert 1 not in spans
        assert 1 in errors

    def test_empty(self):
        spans, errors = derive_lane_groups([])
        assert spans == {} and errors == set()
