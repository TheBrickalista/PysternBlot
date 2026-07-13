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
    QGraphicsScene,
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
    LadderBandAssignment,
    Layout,
    LegendRow,
    LegendSettings,
    LegendZone,
    Ladder,
    CalibrationPoint,
    MarkerBand,
    MarkerSet,
    OverlayLadder,
    Panel,
    Project,
    ProjectMeta,
    ProteinLabel,
    Style,
)
from pysternblot.render import build_panel_scene, build_provenance_scene
from pysternblot.ui.export_mixin import _ExportMixin
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
        assert lz.show_markers is True
        assert lz.marker_side == "left"

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
            legend_zone=LegendZone(x=10, y=20, w=150, h=80, enabled=True, show_markers=False, marker_side="right"),
        )
        data = blot.model_dump()
        assert data["legend_zone"] == {
            "x": 10.0, "y": 20.0, "w": 150.0, "h": 80.0, "enabled": True,
            "show_markers": False, "marker_side": "right",
        }

        blot2 = Blot.model_validate(data)
        assert blot2.legend_zone is not None
        assert blot2.legend_zone.x == 10.0
        assert blot2.legend_zone.y == 20.0
        assert blot2.legend_zone.w == 150.0
        assert blot2.legend_zone.h == 80.0
        assert blot2.legend_zone.enabled is True
        assert blot2.legend_zone.show_markers is False
        assert blot2.legend_zone.marker_side == "right"

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

    def test_legacy_legend_zone_without_marker_fields_loads_with_defaults(self):
        """Simulates a project.json saved by the prior version of this feature,
        where legend_zone existed but show_markers/marker_side did not yet."""
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
            "legend_zone": {"x": 5.0, "y": 6.0, "w": 100.0, "h": 80.0, "enabled": True},
        }
        assert "show_markers" not in data["legend_zone"]
        assert "marker_side" not in data["legend_zone"]

        blot = Blot.model_validate(data)
        assert blot.legend_zone is not None
        assert blot.legend_zone.x == 5.0
        assert blot.legend_zone.enabled is True
        assert blot.legend_zone.show_markers is True
        assert blot.legend_zone.marker_side == "left"


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


# ===========================================================================
# _compute_export_geometry: pure arithmetic, no Qt/QApplication required.
# ===========================================================================

from pysternblot.ui.export_mixin import _compute_export_geometry


class TestComputeExportGeometry:

    def test_zone_larger_than_crop_box_uses_zone_as_union(self):
        """Zone already fully contains the crop box -> union == zone, and the crop
        box's offset within the union matches its offset within the zone."""
        lz = LegendZone(x=0.0, y=0.0, w=500.0, h=400.0)
        crop = Crop(x=50.0, y=60.0, w=300.0, h=200.0)
        ct = CropTemplate(w=300.0, h=200.0)

        ex, ey, ew, eh, off_x, off_y = _compute_export_geometry(lz, crop, ct, pm_w=1000.0, pm_h=1000.0)

        assert (ex, ey, ew, eh) == (0.0, 0.0, 500.0, 400.0)
        assert off_x == pytest.approx(50.0)
        assert off_y == pytest.approx(60.0)

    def test_crop_box_extends_beyond_zone_expands_union(self):
        """Zone is smaller than / offset from the crop box -> the expanded rect
        must fully contain the crop box (CHANGE 1)."""
        lz = LegendZone(x=100.0, y=100.0, w=50.0, h=50.0)  # small zone, disjoint-ish
        crop = Crop(x=50.0, y=60.0, w=300.0, h=200.0)
        ct = CropTemplate(w=300.0, h=200.0)

        ex, ey, ew, eh, off_x, off_y = _compute_export_geometry(lz, crop, ct, pm_w=1000.0, pm_h=1000.0)

        # Union must contain both rects.
        assert ex <= min(lz.x, crop.x)
        assert ey <= min(lz.y, crop.y)
        assert ex + ew >= max(lz.x + lz.w, crop.x + ct.w)
        assert ey + eh >= max(lz.y + lz.h, crop.y + ct.h)

        # The crop box's sub-rect within the expanded region must land at the
        # correct offset.
        assert off_x == pytest.approx(crop.x - ex)
        assert off_y == pytest.approx(crop.y - ey)
        assert 0.0 <= off_x <= ew - ct.w + 1e-6
        assert 0.0 <= off_y <= eh - ct.h + 1e-6

    def test_union_clamped_to_pixmap_bounds(self):
        """Crop box (or zone) extending past the pixmap edges must be clamped."""
        lz = LegendZone(x=-50.0, y=-50.0, w=100.0, h=100.0)
        crop = Crop(x=900.0, y=900.0, w=300.0, h=300.0)
        ct = CropTemplate(w=300.0, h=300.0)

        ex, ey, ew, eh, off_x, off_y = _compute_export_geometry(lz, crop, ct, pm_w=1000.0, pm_h=1000.0)

        assert ex >= 0.0
        assert ey >= 0.0
        assert ex + ew <= 1000.0 + 1e-6
        assert ey + eh <= 1000.0 + 1e-6

    def test_offset_math_places_crop_box_correctly_within_export(self):
        """End-to-end offset check matching CHANGE 2's img_col_x/img_col_w formula."""
        lz = LegendZone(x=0.0, y=0.0, w=1754.0, h=1266.0)  # oversized user-drawn zone
        crop = Crop(x=50.0, y=50.0, w=300.0, h=200.0)
        ct = CropTemplate(w=300.0, h=200.0)

        ex, ey, ew, eh, off_x, off_y = _compute_export_geometry(lz, crop, ct, pm_w=2000.0, pm_h=2000.0)

        x0 = 20.0
        ladder_w = 60.0
        image_x = x0 + ladder_w
        img_col_x = image_x + off_x
        img_col_w = ct.w

        # The crop-box sub-rect within the exported image spans exactly
        # [img_col_x, img_col_x + img_col_w] measured from image_x.
        assert img_col_x == pytest.approx(image_x + (crop.x - ex))
        assert img_col_w == pytest.approx(300.0)


# ===========================================================================
# _draw_legend_zone_markers: the zone export shows the COMPLETE assigned
# ladder, bypassing the Figure's show_in_final / show_only_highlighted filters.
# ===========================================================================

class _FakeExportHost(_ExportMixin):
    """Minimal host exposing just what _draw_legend_zone_markers reads via self."""

    def __init__(self, project, active_nir_channel: int = 0):
        self.current_project = project
        self._active_nir_channel = active_nir_channel


def _project_with_marker_set(marker_set: MarkerSet) -> Project:
    header = HeaderBlock(
        left_title="kDa",
        groups=[Group(label="All", n_lanes=1)],
        condition_rows=[ConditionRow(values=[""])],
    )
    dummy_blot = Blot(
        id="dummy", asset_sha256="a" * 64,
        crop=Crop(x=0, y=0, w=300, h=200),
        ladder=_minimal_ladder(),
        protein_label=ProteinLabel(text=""),
    )
    panel = Panel(
        style=Style(),
        lane_layout=LaneLayout(header_block=header),
        blots=[dummy_blot],
        layout=Layout(order=["dummy"]),
        legend=LegendSettings(),
        crop_template=CropTemplate(w=300.0, h=200.0),
    )
    return Project(
        project=ProjectMeta(
            id="p1", name="Test", created_utc="2026-01-01T00:00:00Z",
            app_version="0.0", license="GPL-3.0-only",
        ),
        marker_sets=[marker_set],
        panel=panel,
    )


class TestLegendZoneMarkersFullLadder:

    def _blot_with_ladder(self, show_only_highlighted: bool) -> Blot:
        return Blot(
            id="b1", asset_sha256="a" * 64,
            crop=Crop(x=0, y=0, w=300, h=200),
            ladder=_minimal_ladder(),
            protein_label=ProteinLabel(text=""),
            overlay_ladder=OverlayLadder(
                marker_set_id="ms1",
                side="left",
                show_labels=True,
                show_only_highlighted=show_only_highlighted,
                bands=[
                    LadderBandAssignment(y_px=10.0, kda=100.0, show_in_final=True),
                    LadderBandAssignment(y_px=20.0, kda=70.0, show_in_final=False),
                    LadderBandAssignment(y_px=30.0, kda=50.0, show_in_final=False),
                    LadderBandAssignment(y_px=40.0, kda=25.0, show_in_final=True),
                ],
            ),
        )

    def _marker_set(self) -> MarkerSet:
        return MarkerSet(id="ms1", name="Test", bands=[
            MarkerBand(kda=100.0, label="100", highlight=False),
            MarkerBand(kda=70.0, label="70", highlight=True),  # only highlighted band
            MarkerBand(kda=50.0, label="50", highlight=False),
            MarkerBand(kda=25.0, label="25", highlight=False),
        ])

    def test_all_bands_drawn_regardless_of_show_in_final_and_highlight_filter(self, qapp):
        """2 of 4 bands would be hidden in the Figure by show_in_final=False, and
        show_only_highlighted=True would additionally hide all but the 70 kDa band
        (which is itself show_in_final=False) — the zone export must still draw
        all 4."""
        blot = self._blot_with_ladder(show_only_highlighted=True)
        project = _project_with_marker_set(self._marker_set())
        host = _FakeExportHost(project)

        scene = QGraphicsScene()
        drawn = host._draw_legend_zone_markers(
            scene, blot, LegendZone(show_markers=True, marker_side="left"),
            image_x=100.0, image_w=300.0, y_img=50.0, ey=0.0,
        )

        assert drawn == 4
        lines = [i for i in scene.items() if isinstance(i, QGraphicsLineItem)]
        assert len(lines) == 4

    def test_unmatched_band_falls_back_to_numeric_kda_label(self, qapp):
        """A band with no matching preset in marker_sets must still render, labeled
        with its raw kda value rather than being silently dropped."""
        blot = self._blot_with_ladder(show_only_highlighted=False)
        blot.overlay_ladder.bands.append(
            LadderBandAssignment(y_px=50.0, kda=12.5, show_in_final=True)
        )
        project = _project_with_marker_set(self._marker_set())
        host = _FakeExportHost(project)

        scene = QGraphicsScene()
        drawn = host._draw_legend_zone_markers(
            scene, blot, LegendZone(show_markers=True, marker_side="left"),
            image_x=100.0, image_w=300.0, y_img=50.0, ey=0.0,
        )

        assert drawn == 5
        texts = [i.toPlainText() for i in scene.items() if isinstance(i, QGraphicsTextItem)]
        assert "12.5 kDa" in texts

    def test_show_markers_false_draws_nothing(self, qapp):
        blot = self._blot_with_ladder(show_only_highlighted=False)
        project = _project_with_marker_set(self._marker_set())
        host = _FakeExportHost(project)

        scene = QGraphicsScene()
        drawn = host._draw_legend_zone_markers(
            scene, blot, LegendZone(show_markers=False, marker_side="left"),
            image_x=100.0, image_w=300.0, y_img=50.0, ey=0.0,
        )
        assert drawn == 0
        assert len(scene.items()) == 0


# ===========================================================================
# Regression guard: this change only touches export_mixin.py's zone-export
# marker helper. build_panel_scene (the Figure tab) must keep honoring
# show_in_final and show_only_highlighted exactly as before.
# ===========================================================================

class TestFigureMarkerFiltersUnchanged:

    def _project_with_ladder_blot(self, show_only_highlighted: bool, sha: str) -> Project:
        header = HeaderBlock(
            left_title="kDa",
            groups=[Group(label="All", n_lanes=1)],
            condition_rows=[ConditionRow(values=[""])],
        )
        blot = Blot(
            id="b1", asset_sha256=sha,
            crop=Crop(x=0, y=0, w=float(IMG_W), h=float(IMG_H)),
            ladder=_minimal_ladder(),
            protein_label=ProteinLabel(text=""),
            overlay_ladder=OverlayLadder(
                marker_set_id="ms1",
                side="left",
                show_labels=True,
                show_only_highlighted=show_only_highlighted,
                bands=[
                    LadderBandAssignment(y_px=10.0, kda=100.0, show_in_final=True),
                    LadderBandAssignment(y_px=20.0, kda=70.0, show_in_final=True),
                    LadderBandAssignment(y_px=30.0, kda=50.0, show_in_final=False),
                ],
            ),
        )
        panel = Panel(
            style=Style(),
            lane_layout=LaneLayout(header_block=header),
            blots=[blot],
            layout=Layout(order=["b1"]),
            legend=LegendSettings(),
            crop_template=CropTemplate(w=float(IMG_W), h=float(IMG_H)),
        )
        return Project(
            project=ProjectMeta(
                id="p1", name="Test", created_utc="2026-01-01T00:00:00Z",
                app_version="0.0", license="GPL-3.0-only",
            ),
            marker_sets=[MarkerSet(id="ms1", name="Test", bands=[
                MarkerBand(kda=100.0, label="100", highlight=False),
                MarkerBand(kda=70.0, label="70", highlight=True),
                MarkerBand(kda=50.0, label="50", highlight=False),
            ])],
            panel=panel,
        )

    def test_show_in_final_false_still_hidden_in_figure(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        proj = self._project_with_ladder_blot(show_only_highlighted=False, sha=sha)

        scene = build_panel_scene(proj, ws)
        lines = [i for i in scene.items() if isinstance(i, QGraphicsLineItem)]
        # Only the 2 show_in_final=True bands (100, 70) draw a tick; 50 stays hidden.
        assert len(lines) == 2

    def test_show_only_highlighted_still_hides_non_highlighted_in_figure(self, qapp, tmp_path):
        ws, sha = _make_workspace(tmp_path)
        proj = self._project_with_ladder_blot(show_only_highlighted=True, sha=sha)

        scene = build_panel_scene(proj, ws)
        lines = [i for i in scene.items() if isinstance(i, QGraphicsLineItem)]
        # show_only_highlighted=True -> only kda=70 (highlighted, and show_in_final=True).
        assert len(lines) == 1
