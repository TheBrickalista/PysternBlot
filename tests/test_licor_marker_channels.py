# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
LI-COR channels and per-band marker visibility.

MarkerBand.channels is keyed on the Typhoon excitation wavelengths (685/785).
LI-COR channels carry channel_label "700"/"800" and no wavelength_nm, so
_marker_channel_key maps them onto those keys. These tests cover the mapping,
the Figure render, ladder-row selection and the legend-zone export.

The LI-COR test blot deliberately puts the 800 channel at channel_index 0 and
the 700 channel at channel_index 1, so "the 700 row" is never the same as the
first-row fallback.
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
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsTextItem,
)

from pysternblot.models import (
    Blot,
    BlotChannel,
    CalibrationPoint,
    ConditionRow,
    Crop,
    CropTemplate,
    Group,
    HeaderBlock,
    Ladder,
    LadderBandAssignment,
    LaneLayout,
    Layout,
    LegendSettings,
    LegendZone,
    MarkerBand,
    MarkerSet,
    OverlayLadder,
    Panel,
    Project,
    ProjectMeta,
    ProteinLabel,
    Style,
)
from pysternblot.render import (
    _band_visible_on_channel,
    _ladder_row_for_blot,
    _marker_channel_key,
    build_panel_scene,
    build_provenance_scene,
)
from pysternblot.ui.export_mixin import _ExportMixin

IMG_W, IMG_H = 300, 200

# 100 kDa is restricted to the 685 (LI-COR 700) channel; 50 kDa shows on all.
RESTRICTED, UNRESTRICTED = "100 kDa", "50 kDa"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _ch(index: int, *, wavelength_nm=None, channel_label=None) -> BlotChannel:
    return BlotChannel(
        asset_sha256=f"sha{index}",
        channel_index=index,
        wavelength_nm=wavelength_nm,
        channel_label=channel_label,
    )


def _marker_set() -> MarkerSet:
    return MarkerSet(id="ms1", name="Test", bands=[
        MarkerBand(kda=100.0, label="100", channels=[685]),
        MarkerBand(kda=50.0, label="50", channels=[]),
    ])


def _overlay() -> OverlayLadder:
    return OverlayLadder(
        marker_set_id="ms1",
        side="left",
        show_labels=True,
        bands=[
            LadderBandAssignment(y_px=60.0, kda=100.0),
            LadderBandAssignment(y_px=140.0, kda=50.0),
        ],
    )


def _licor_blot(sha_800: str = "sha0", sha_700: str = "sha1", labels=("800", "700")) -> Blot:
    """Two-channel LI-COR blot: index 0 = labels[0], index 1 = labels[1]."""
    return Blot(
        id="b1",
        asset_sha256=sha_800,
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
        modality="nir_fluorescence",
        channels=[
            BlotChannel(asset_sha256=sha_800, channel_index=0, channel_label=labels[0]),
            BlotChannel(asset_sha256=sha_700, channel_index=1, channel_label=labels[1]),
        ],
        overlay_ladder=_overlay(),
    )


def _project(blot: Blot) -> Project:
    header = HeaderBlock(
        left_title="kDa",
        groups=[Group(label="All", n_lanes=1)],
        condition_rows=[ConditionRow(values=[""])],
    )
    panel = Panel(
        style=Style(),
        lane_layout=LaneLayout(header_block=header),
        blots=[blot],
        layout=Layout(order=[blot.id]),
        legend=LegendSettings(),
        crop_template=CropTemplate(w=float(IMG_W), h=float(IMG_H)),
    )
    return Project(
        project=ProjectMeta(
            id="p1", name="Test", created_utc="2026-01-01T00:00:00Z",
            app_version="0.0", license="GPL-3.0-only",
        ),
        marker_sets=[_marker_set()],
        panel=panel,
    )


def _encode_png_uint16(arr: np.ndarray) -> bytes:
    """Encode a 2-D uint16 array as a 16-bit grayscale PNG (no external libs)."""
    h, w = arr.shape

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)
    scanlines = bytearray()
    for row in arr:
        scanlines.append(0)
        scanlines.extend(row.astype(">u2").tobytes())
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(scanlines), 6)) + chunk(b"IEND", b"")
    )


def _write_asset(root: Path, value: int) -> str:
    png = _encode_png_uint16(np.full((IMG_H, IMG_W), value, dtype=np.uint16))
    sha = hashlib.sha256(png).hexdigest()
    d = root / "assets" / sha
    d.mkdir(parents=True)
    (d / "original.png").write_bytes(png)
    return sha


# ===========================================================================
# _marker_channel_key
# ===========================================================================

class TestMarkerChannelKey:

    def test_typhoon_uses_wavelength(self):
        assert _marker_channel_key(_ch(0, wavelength_nm=685)) == 685
        assert _marker_channel_key(_ch(1, wavelength_nm=785)) == 785

    def test_wavelength_takes_precedence_over_label(self):
        assert _marker_channel_key(_ch(0, wavelength_nm=785, channel_label="700")) == 785

    def test_licor_700_maps_to_685(self):
        assert _marker_channel_key(_ch(0, channel_label="700")) == 685

    def test_licor_800_maps_to_785(self):
        assert _marker_channel_key(_ch(0, channel_label="800")) == 785

    def test_unknown_licor_channel_is_none(self):
        assert _marker_channel_key(_ch(0, channel_label="600")) is None

    def test_empty_and_missing_label_is_none(self):
        assert _marker_channel_key(_ch(0, channel_label="")) is None
        assert _marker_channel_key(_ch(0)) is None

    def test_unknown_channel_still_shows_restricted_band(self):
        """None keeps the existing behaviour: the band is shown on that row."""
        band = MarkerBand(kda=100, channels=[685])
        assert _band_visible_on_channel(band, _marker_channel_key(_ch(0, channel_label="600")))

    def test_does_not_set_wavelength(self):
        ch = _ch(0, channel_label="700")
        _marker_channel_key(ch)
        assert ch.wavelength_nm is None


# ===========================================================================
# Ladder row selection
# ===========================================================================

class TestLicorLadderRow:

    def test_685_band_selects_700_row(self):
        """700 is channel_index 1 here, so the result is not the fallback 0."""
        assert _ladder_row_for_blot(_licor_blot(), [_marker_set()]) == 1

    def test_unknown_channels_fall_back_to_first_row(self):
        blot = _licor_blot(labels=("600", "500"))
        assert _ladder_row_for_blot(blot, [_marker_set()]) == 0


# ===========================================================================
# Figure render (build_panel_scene)
# ===========================================================================

class TestLicorPanelRender:

    def _rows_and_labels(self, scene):
        rows = sorted(
            (i.sceneBoundingRect() for i in scene.items() if isinstance(i, QGraphicsPixmapItem)),
            key=lambda r: r.top(),
        )
        labels = [
            (i.toPlainText(), i.sceneBoundingRect().center().y())
            for i in scene.items() if isinstance(i, QGraphicsTextItem)
        ]
        return rows, labels

    @staticmethod
    def _row_of(rows, y):
        hits = [n for n, r in enumerate(rows) if r.top() <= y <= r.bottom()]
        assert len(hits) == 1, f"label at y={y} is not inside exactly one row"
        return hits[0]

    def test_685_band_drawn_on_700_row_only(self, qapp, tmp_path):
        sha_800 = _write_asset(tmp_path, 20000)
        sha_700 = _write_asset(tmp_path, 40000)
        blot = _licor_blot(sha_800=sha_800, sha_700=sha_700)

        scene = build_panel_scene(_project(blot), tmp_path)
        rows, labels = self._rows_and_labels(scene)

        assert len(rows) == 2  # row 0 = 800 channel, row 1 = 700 channel
        restricted = [self._row_of(rows, y) for text, y in labels if text == RESTRICTED]
        unrestricted = [self._row_of(rows, y) for text, y in labels if text == UNRESTRICTED]
        assert restricted == [1], "685-only band must be on the 700 row and not the 800 row"
        assert sorted(unrestricted) == [0, 1], "unrestricted band must be on both rows"

    def test_unknown_licor_channels_show_band_on_all_rows(self, qapp, tmp_path):
        sha_a = _write_asset(tmp_path, 20000)
        sha_b = _write_asset(tmp_path, 40000)
        blot = _licor_blot(sha_800=sha_a, sha_700=sha_b, labels=("600", "500"))

        scene = build_panel_scene(_project(blot), tmp_path)
        rows, labels = self._rows_and_labels(scene)

        restricted = [self._row_of(rows, y) for text, y in labels if text == RESTRICTED]
        assert sorted(restricted) == [0, 1]

    def test_render_leaves_model_unchanged(self, qapp, tmp_path):
        sha_800 = _write_asset(tmp_path, 20000)
        sha_700 = _write_asset(tmp_path, 40000)
        blot = _licor_blot(sha_800=sha_800, sha_700=sha_700)
        before = blot.model_dump()

        build_panel_scene(_project(blot), tmp_path)

        assert blot.model_dump() == before
        assert all(c.wavelength_nm is None for c in blot.channels)


# ===========================================================================
# Original Image view (build_provenance_scene, one active channel)
# ===========================================================================

class TestLicorProvenanceScene:

    def _texts(self, tmp_path, nir_channel_index: int):
        sha_800 = _write_asset(tmp_path, 20000)
        sha_700 = _write_asset(tmp_path, 40000)
        blot = _licor_blot(sha_800=sha_800, sha_700=sha_700)
        scene = build_provenance_scene(
            _project(blot), tmp_path, blot_id=blot.id, nir_channel_index=nir_channel_index,
        )
        return [i.toPlainText() for i in scene.items() if isinstance(i, QGraphicsTextItem)]

    def test_800_channel_hides_685_band(self, qapp, tmp_path):
        texts = self._texts(tmp_path, nir_channel_index=0)
        assert RESTRICTED not in texts
        assert UNRESTRICTED in texts

    def test_700_channel_shows_685_band(self, qapp, tmp_path):
        texts = self._texts(tmp_path, nir_channel_index=1)
        assert RESTRICTED in texts and UNRESTRICTED in texts


# ===========================================================================
# Legend-zone export (_draw_legend_zone_markers)
# ===========================================================================

class _FakeExportHost(_ExportMixin):
    """Minimal host exposing just what _draw_legend_zone_markers reads via self."""

    def __init__(self, project, active_nir_channel: int):
        self.current_project = project
        self._active_nir_channel = active_nir_channel


class TestLicorLegendZoneMarkers:

    def _draw(self, active_nir_channel: int):
        blot = _licor_blot()
        host = _FakeExportHost(_project(blot), active_nir_channel)
        scene = QGraphicsScene()
        drawn = host._draw_legend_zone_markers(
            scene, blot, LegendZone(show_markers=True, marker_side="left"),
            image_x=100.0, image_w=300.0, y_img=50.0, ey=0.0,
        )
        texts = [i.toPlainText() for i in scene.items() if isinstance(i, QGraphicsTextItem)]
        return drawn, texts

    def test_800_channel_omits_685_band(self, qapp):
        drawn, texts = self._draw(active_nir_channel=0)  # 800
        assert drawn == 1
        assert RESTRICTED not in texts
        assert UNRESTRICTED in texts

    def test_700_channel_keeps_685_band(self, qapp):
        drawn, texts = self._draw(active_nir_channel=1)  # 700
        assert drawn == 2
        assert RESTRICTED in texts and UNRESTRICTED in texts
