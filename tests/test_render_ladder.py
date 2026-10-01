# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Overlay-ladder rendering in render.py.

  - _band_visible_on_channel: pure logic.
  - Tick and label placement, label text and the show_in_final split between
    the Figure (build_panel_scene) and the Original Image view
    (build_provenance_scene): asserted on the items of real scenes built from
    a real asset in a tmp workspace (issue #196).
  - OverlayLadder.side model behaviour and derive_lane_groups.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsTextItem,
)

from pysternblot.models import (
    Blot,
    CalibrationPoint,
    Crop,
    Ladder,
    LadderBandAssignment,
    MarkerBand,
    OverlayLadder,
    ProteinLabel,
)
from pysternblot.render import (
    _band_visible_on_channel,
    build_panel_scene,
    build_provenance_scene,
    derive_lane_groups,
)

# Shared scene helpers: a real uint16 PNG asset writer and a one-blot Project
# whose marker set labels 100 kDa "100" and 50 kDa "50".
from test_licor_marker_channels import IMG_H, IMG_W, _project, _write_asset


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestBandVisibleOnChannel:

    def test_band_visible_ecl(self):
        """Band with channels=[685] must be visible on ECL rows (wavelength_nm=None)."""
        band = MarkerBand(kda=100, channels=[685])
        assert _band_visible_on_channel(band, None) is True

    def test_band_visible_matching_channel(self):
        """Band restricted to 685 nm is visible when the channel wavelength is 685."""
        band = MarkerBand(kda=100, channels=[685])
        assert _band_visible_on_channel(band, 685) is True

    def test_band_not_visible_wrong_channel(self):
        """Band restricted to 685 nm must not be visible on a 785 nm channel."""
        band = MarkerBand(kda=100, channels=[685])
        assert _band_visible_on_channel(band, 785) is False

    def test_band_visible_empty_channels(self):
        """Band with empty channels list is visible on every channel."""
        band = MarkerBand(kda=100, channels=[])
        assert _band_visible_on_channel(band, 785) is True

    def test_band_visible_multichannel(self):
        """Band with channels=[685, 785] is visible on both wavelengths."""
        band = MarkerBand(kda=100, channels=[685, 785])
        assert _band_visible_on_channel(band, 785) is True




# ===========================================================================
# Overlay ladder in real scenes
# ===========================================================================

# Geometry constants of build_provenance_scene's overlay ladder.
TICK_LENGTH, TICK_GAP, LABEL_GAP = 50.0, 15.0, 4.0

# y_px -> (kDa, expected label). 12.5 kDa has no preset band, so its label
# falls back to the numeric value.
BANDS = {
    40.0: (100.0, "100 kDa"),
    90.0: (50.0, "50 kDa"),
    150.0: (12.5, "12.5 kDa"),
}


def _ecl_blot(sha: str, side: str = "left", hidden_kda: float | None = None) -> Blot:
    return Blot(
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
        overlay_ladder=OverlayLadder(
            marker_set_id="ms1",
            side=side,
            show_labels=True,
            bands=[
                LadderBandAssignment(y_px=y, kda=kda, show_in_final=(kda != hidden_kda))
                for y, (kda, _label) in BANDS.items()
            ],
        ),
    )


def _image_rect(scene):
    images = [i for i in scene.items() if isinstance(i, QGraphicsPixmapItem)]
    assert len(images) == 1, f"expected one image item, got {len(images)}"
    return images[0].sceneBoundingRect()


def _ticks(scene):
    """Horizontal line items as (x_left, x_right, y) in scene coordinates."""
    ticks = []
    for item in scene.items():
        if isinstance(item, QGraphicsLineItem):
            line, pos = item.line(), item.pos()
            if line.y1() == line.y2():
                ticks.append((
                    pos.x() + min(line.x1(), line.x2()),
                    pos.x() + max(line.x1(), line.x2()),
                    pos.y() + line.y1(),
                ))
    return sorted(ticks, key=lambda t: t[2])


def _kda_labels(scene):
    """kDa label items by text -> (left, right, vertical centre) in scene coords."""
    labels = {}
    for item in scene.items():
        if isinstance(item, QGraphicsTextItem) and item.toPlainText().endswith(" kDa"):
            br = item.boundingRect()
            left = item.pos().x()
            labels[item.toPlainText()] = (left, left + br.width(), item.pos().y() + br.height() / 2.0)
    return labels


def _provenance(tmp_path, side="left", hidden_kda=None):
    sha = _write_asset(tmp_path, 30000)
    project = _project(_ecl_blot(sha, side=side, hidden_kda=hidden_kda))
    return build_provenance_scene(project, tmp_path, blot_id="b1")


class TestProvenanceLadderPlacement:

    def test_left_ticks_span_left_of_image(self, qapp, tmp_path):
        scene = _provenance(tmp_path, side="left")
        img = _image_rect(scene)
        ticks = _ticks(scene)

        assert len(ticks) == len(BANDS)
        for (x_left, x_right, y), y_px in zip(ticks, sorted(BANDS)):
            assert x_left == pytest.approx(img.left() - TICK_GAP - TICK_LENGTH)  # x0 - 65
            assert x_right == pytest.approx(img.left() - TICK_GAP)               # x0 - 15
            assert y == pytest.approx(img.top() + y_px)

    def test_left_label_right_edge_is_gap_before_tick(self, qapp, tmp_path):
        scene = _provenance(tmp_path, side="left")
        tick_x0 = _image_rect(scene).left() - TICK_GAP - TICK_LENGTH
        labels = _kda_labels(scene)

        assert len(labels) == len(BANDS)
        for _left, right, _cy in labels.values():
            assert right == pytest.approx(tick_x0 - LABEL_GAP)

    def test_right_ticks_span_right_of_image(self, qapp, tmp_path):
        scene = _provenance(tmp_path, side="right")
        img = _image_rect(scene)
        ticks = _ticks(scene)

        assert len(ticks) == len(BANDS)
        for (x_left, x_right, y), y_px in zip(ticks, sorted(BANDS)):
            assert x_left == pytest.approx(img.right() + TICK_GAP)                # img_right + 15
            assert x_right == pytest.approx(img.right() + TICK_GAP + TICK_LENGTH) # img_right + 65
            assert y == pytest.approx(img.top() + y_px)

    def test_right_label_left_edge_is_gap_after_tick(self, qapp, tmp_path):
        scene = _provenance(tmp_path, side="right")
        tick_x1 = _image_rect(scene).right() + TICK_GAP + TICK_LENGTH
        labels = _kda_labels(scene)

        assert len(labels) == len(BANDS)
        for left, _right, _cy in labels.values():
            assert left == pytest.approx(tick_x1 + LABEL_GAP)

    @pytest.mark.parametrize("side", ["left", "right"])
    def test_label_text_and_vertical_centre(self, qapp, tmp_path, side):
        scene = _provenance(tmp_path, side=side)
        img_top = _image_rect(scene).top()
        labels = _kda_labels(scene)

        assert set(labels) == {label for _kda, label in BANDS.values()}
        for y_px, (_kda, label) in BANDS.items():
            assert labels[label][2] == pytest.approx(img_top + y_px)


class TestShowInFinal:

    def test_hidden_in_panel_scene(self, qapp, tmp_path):
        sha = _write_asset(tmp_path, 30000)
        project = _project(_ecl_blot(sha, hidden_kda=50.0))

        scene = build_panel_scene(project, tmp_path)
        labels = _kda_labels(scene)

        assert "50 kDa" not in labels
        assert {"100 kDa", "12.5 kDa"} <= set(labels)
        assert len(_ticks(scene)) == len(BANDS) - 1

    def test_still_shown_in_provenance_scene(self, qapp, tmp_path):
        scene = _provenance(tmp_path, hidden_kda=50.0)
        img_top = _image_rect(scene).top()

        assert "50 kDa" in _kda_labels(scene)
        assert img_top + 90.0 in [pytest.approx(y) for _l, _r, y in _ticks(scene)]
        assert len(_ticks(scene)) == len(BANDS)


class TestLadderSide:

    def test_side_defaults_to_left(self):
        """A freshly constructed OverlayLadder must have side == 'left'."""
        ladder = OverlayLadder(marker_set_id="ms1")
        assert ladder.side == "left"

    def test_side_right_persists_after_round_trip(self):
        """side='right' must survive model_dump / model_validate serialisation."""
        ladder = OverlayLadder(marker_set_id="ms1", side="right")
        data = ladder.model_dump()
        assert data["side"] == "right"
        ladder2 = OverlayLadder.model_validate(data)
        assert ladder2.side == "right"



# ===========================================================================
# derive_lane_groups
# ===========================================================================

class TestDeriveLaneGroups:

    def test_two_groups_no_errors(self):
        spans, errors = derive_lane_groups([0, 1, 1, 0, 2, 2, 0])
        assert spans == {1: (1, 2), 2: (4, 5)}
        assert errors == set()

    def test_full_row_single_id(self):
        spans, errors = derive_lane_groups([1, 1, 1])
        assert spans == {1: (0, 2)}
        assert errors == set()

    def test_non_contiguous_is_error(self):
        spans, errors = derive_lane_groups([1, 0, 1])
        assert spans == {}
        assert errors == {1}

    def test_single_lane_group_no_span_no_error(self):
        spans, errors = derive_lane_groups([0, 1, 0])
        assert spans == {}
        assert errors == set()

    def test_empty_input(self):
        spans, errors = derive_lane_groups([])
        assert spans == {}
        assert errors == set()

    def test_all_zero(self):
        spans, errors = derive_lane_groups([0, 0, 0])
        assert spans == {}
        assert errors == set()

    def test_mixed_valid_and_error(self):
        """id=1 is contiguous (span), id=2 is non-contiguous (error)."""
        spans, errors = derive_lane_groups([1, 1, 0, 2, 0, 2])
        assert spans == {1: (0, 1)}
        assert errors == {2}

    def test_three_contiguous_groups(self):
        spans, errors = derive_lane_groups([1, 1, 2, 2, 3, 3])
        assert spans == {1: (0, 1), 2: (2, 3), 3: (4, 5)}
        assert errors == set()

    def test_zero_id_always_ignored(self):
        spans, errors = derive_lane_groups([0, 0, 0, 0])
        assert 0 not in spans
        assert 0 not in errors
