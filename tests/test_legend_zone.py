# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for the optional "Legend export zone" feature:
  - LegendZone model defaults + Blot round-trip (set / unset / legacy JSON)
  - build_provenance_scene(show_legend_zone=True) adds a second CropRectItem
  - the legend-rendering refactor (draw_legend_into_scene / _draw_legend_row_core)
    does not change build_panel_scene's Figure-tab output
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
)

from pysternblot.models import (
    Blot,
    Crop,
    CropTemplate,
    ConditionRow,
    Group,
    HeaderBlock,
    LaneLayout,
    Layout,
    LegendRow,
    LegendSettings,
    LegendZone,
    Ladder,
    CalibrationPoint,
    Panel,
    Project,
    ProjectMeta,
    ProteinLabel,
    Style,
)
from pysternblot.render import build_panel_scene, build_provenance_scene
from pysternblot.ui.crop_rect_item import CropRectItem


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
# Minimal workspace + project helpers (self-contained; mirrors
# tests/test_phase_a_sanity.py's synthetic-PNG approach so build_provenance_scene
# / build_panel_scene can load a real pixmap without external image libs).
# ---------------------------------------------------------------------------

IMG_W, IMG_H = 300, 200


def _encode_png_uint16(arr: np.ndarray) -> bytes:
    """Encode a 2-D uint16 array as a 16-bit grayscale PNG (no external libs)."""
    h, w = arr.shape
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)
    scanlines = bytearray()
    for row in arr:
        scanlines.append(0)
        scanlines.extend(row.astype(">u2").tobytes())
    idat = chunk(b"IDAT", zlib.compress(bytes(scanlines), 6))
    iend = chunk(b"IEND", b"")
    return sig + chunk(b"IHDR", ihdr) + idat + iend


def _make_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Write a 300x200 white uint16 PNG asset; return (workspace_root, sha256)."""
    arr = np.full((IMG_H, IMG_W), 32768, dtype=np.uint16)
    png_bytes = _encode_png_uint16(arr)
    sha = hashlib.sha256(png_bytes).hexdigest()
    asset_dir = tmp_path / "assets" / sha
    asset_dir.mkdir(parents=True)
    (asset_dir / "original.png").write_bytes(png_bytes)
    return tmp_path, sha


def _minimal_ladder() -> Ladder:
    return Ladder(
        lane_index=0,
        marker_set_id="ms1",
        calibration_points=[
            CalibrationPoint(y_px=50, kda=55),
            CalibrationPoint(y_px=120, kda=36),
        ],
    )


def _minimal_project(sha: str, legend: LegendSettings, n_lanes: int = 4) -> Project:
    header = HeaderBlock(
        left_title="kDa",
        groups=[Group(label="All", n_lanes=n_lanes)],
        condition_rows=[ConditionRow(values=[""] * n_lanes)],
    )
    blot = Blot(
        id="b1",
        asset_sha256=sha,
        crop=Crop(x=0, y=0, w=float(IMG_W), h=float(IMG_H)),
        ladder=_minimal_ladder(),
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


# ===========================================================================
# LegendZone model + Blot round-trip
# ===========================================================================

class TestLegendZoneModel:

    def test_defaults(self):
        lz = LegendZone()
        assert lz.x == 0.0
        assert lz.y == 0.0
        assert lz.w == 300.0
        assert lz.h == 200.0
        assert lz.enabled is False

    def test_blot_defaults_legend_zone_to_none(self):
        blot = Blot(
            id="b1", asset_sha256="a" * 64,
            crop=Crop(x=0, y=0, w=300, h=200),
            ladder=_minimal_ladder(),
            protein_label=ProteinLabel(text=""),
        )
        assert blot.legend_zone is None

    def test_blot_round_trip_with_legend_zone_set(self):
        blot = Blot(
            id="b1", asset_sha256="a" * 64,
            crop=Crop(x=0, y=0, w=300, h=200),
            ladder=_minimal_ladder(),
            protein_label=ProteinLabel(text=""),
            legend_zone=LegendZone(x=10, y=20, w=150, h=80, enabled=True),
        )
        data = blot.model_dump()
        assert data["legend_zone"] == {"x": 10.0, "y": 20.0, "w": 150.0, "h": 80.0, "enabled": True}

        blot2 = Blot.model_validate(data)
        assert blot2.legend_zone is not None
        assert blot2.legend_zone.x == 10.0
        assert blot2.legend_zone.y == 20.0
        assert blot2.legend_zone.w == 150.0
        assert blot2.legend_zone.h == 80.0
        assert blot2.legend_zone.enabled is True

    def test_blot_round_trip_with_legend_zone_unset(self):
        blot = Blot(
            id="b1", asset_sha256="a" * 64,
            crop=Crop(x=0, y=0, w=300, h=200),
            ladder=_minimal_ladder(),
            protein_label=ProteinLabel(text=""),
        )
        data = blot.model_dump()
        assert data["legend_zone"] is None

        blot2 = Blot.model_validate(data)
        assert blot2.legend_zone is None

    def test_legacy_json_without_legend_zone_key_loads_unchanged(self):
        """Simulates an existing project.json written before this field existed:
        the key is absent entirely, not just null."""
        data = {
            "id": "b1",
            "asset_sha256": "a" * 64,
            "crop": {"x": 0, "y": 0, "w": 300, "h": 200},
            "ladder": {
                "lane_index": 0,
                "marker_set_id": "ms1",
                "calibration_points": [
                    {"y_px": 50, "kda": 55},
                    {"y_px": 120, "kda": 36},
                ],
            },
            "protein_label": {"text": ""},
        }
        assert "legend_zone" not in data
        blot = Blot.model_validate(data)
        assert blot.legend_zone is None


# ===========================================================================
# build_provenance_scene: second CropRectItem when show_legend_zone=True
# ===========================================================================

class TestProvenanceSceneLegendZone:

    def _crop_rect_items(self, scene):
        return [item for item in scene.items() if isinstance(item, CropRectItem)]

    def test_show_legend_zone_false_has_one_crop_rect_item(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        proj = _minimal_project(sha, LegendSettings())

        scene = build_provenance_scene(
            proj, ws, blot_id="b1", show_legend_zone=False,
        )
        assert len(self._crop_rect_items(scene)) == 1

    def test_show_legend_zone_true_adds_second_crop_rect_item(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        proj = _minimal_project(sha, LegendSettings())

        scene_without = build_provenance_scene(
            proj, ws, blot_id="b1", show_legend_zone=False,
        )
        scene_with = build_provenance_scene(
            proj, ws, blot_id="b1", show_legend_zone=True,
        )

        assert len(self._crop_rect_items(scene_without)) == 1
        assert len(self._crop_rect_items(scene_with)) == 2

    def test_show_legend_zone_true_creates_default_centered_zone(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        proj = _minimal_project(sha, LegendSettings())
        blot = proj.panel.blots[0]
        assert blot.legend_zone is None

        build_provenance_scene(proj, ws, blot_id="b1", show_legend_zone=True)

        assert blot.legend_zone is not None
        assert blot.legend_zone.enabled is True
        # Default 300x200 zone centered on the 300x200 synthetic image -> (0, 0).
        assert blot.legend_zone.x == pytest.approx(0.0)
        assert blot.legend_zone.y == pytest.approx(0.0)
        assert blot.legend_zone.w == pytest.approx(300.0)
        assert blot.legend_zone.h == pytest.approx(200.0)

    def test_legend_zone_pen_distinct_from_crop_pen(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        proj = _minimal_project(sha, LegendSettings())

        scene = build_provenance_scene(proj, ws, blot_id="b1", show_legend_zone=True)
        items = self._crop_rect_items(scene)
        assert len(items) == 2

        colors = {item.pen().color().name() for item in items}
        assert "#1e88e5" in colors, "legend zone rect must use the distinct blue pen"
        assert len(colors) == 2, "crop rect and legend zone rect must have different pen colors"

    def test_legend_zone_commit_callback_fires_on_apply(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        proj = _minimal_project(sha, LegendSettings())

        committed = []
        scene = build_provenance_scene(
            proj, ws, blot_id="b1", show_legend_zone=True,
            on_legend_zone_commit=lambda blot: committed.append(blot.id),
        )
        items = self._crop_rect_items(scene)
        legend_item = next(i for i in items if i.pen().color().name() == "#1e88e5")

        from PySide6.QtCore import QRectF
        assert callable(legend_item._on_move_commit)
        legend_item._on_move_commit(QRectF(15.0, 15.0, 100.0, 80.0))
        assert committed == ["b1"]


# ===========================================================================
# Legend-rendering refactor regression guard:
# build_panel_scene's Figure-tab legend output must be unchanged.
# ===========================================================================

class TestLegendRefactorRegression:

    @pytest.fixture(autouse=True)
    def _scene(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        legend = LegendSettings(
            upper_rows=[LegendRow(cells=["G1", "G2"], cell_groups=[1, 2])],
            lower_rows=[LegendRow(cells=["a", "b", "c", "d"], cell_groups=[1, 1, 2, 2])],
        )
        self.ws = ws
        self.proj = _minimal_project(sha, legend, n_lanes=4)
        self.scene = build_panel_scene(self.proj, ws)

    def test_expected_text_item_count(self):
        texts = [i for i in self.scene.items() if isinstance(i, QGraphicsTextItem)]
        # 2 upper cells + 4 lower cells; no left/right labels, empty protein label.
        assert len(texts) == 6

    def test_expected_underline_count(self):
        lines = [i for i in self.scene.items() if isinstance(i, QGraphicsLineItem)]
        # Two contiguous groups of 2 lanes each -> 2 underlines.
        assert len(lines) == 2

    def test_expected_pixmap_and_border_item_counts(self):
        pixmaps = [i for i in self.scene.items() if isinstance(i, QGraphicsPixmapItem)]
        rects = [
            i for i in self.scene.items()
            if type(i) is QGraphicsRectItem  # exact type: excludes CropRectItem subclass
        ]
        assert len(pixmaps) == 1
        assert len(rects) == 1  # border around the single blot image

    def test_total_scene_item_count_unchanged(self):
        # Regression guard for the _draw_legend_row_core / draw_legend_into_scene
        # extraction: 1 pixmap + 1 border rect + 6 texts + 2 underlines == 10.
        assert len(self.scene.items()) == 10

    def test_build_panel_scene_deterministic_across_calls(self):
        scene_a = build_panel_scene(self.proj, self.ws)
        scene_b = build_panel_scene(self.proj, self.ws)
        assert len(scene_a.items()) == len(scene_b.items())
