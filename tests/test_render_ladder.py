# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for _band_visible_on_channel and _ladder_row_for_blot in render.py.

No Qt or display required — pure logic tests.
"""

from __future__ import annotations

from pysternblot.models import (
    Blot,
    BlotChannel,
    CalibrationPoint,
    Crop,
    DisplaySettings,
    Ladder,
    LadderBandAssignment,
    MarkerBand,
    MarkerSet,
    OverlayLadder,
    ProteinLabel,
)
import inspect

from pysternblot.render import _band_visible_on_channel, _ladder_row_for_blot, build_panel_scene, build_provenance_scene


def _minimal_ladder() -> Ladder:
    return Ladder(
        lane_index=0,
        marker_set_id="ms1",
        calibration_points=[
            CalibrationPoint(y_px=50, kda=55),
            CalibrationPoint(y_px=120, kda=36),
        ],
    )


def _ecl_blot() -> Blot:
    return Blot(
        id="ecl_blot",
        asset_sha256="aaa",
        crop=Crop(x=0, y=0, w=300, h=200),
        ladder=_minimal_ladder(),
        protein_label=ProteinLabel(text=""),
    )


def _nir_blot(overlay_ladder=None) -> Blot:
    """NIR blot with channel_index 0 = 785 nm, channel_index 1 = 685 nm."""
    return Blot(
        id="nir_blot",
        asset_sha256="bbb",
        crop=Crop(x=0, y=0, w=300, h=200),
        ladder=_minimal_ladder(),
        protein_label=ProteinLabel(text=""),
        modality="nir_fluorescence",
        channels=[
            BlotChannel(
                asset_sha256="ch0",
                channel_index=0,
                wavelength_nm=785,
                antibody_name="Ab-800",
            ),
            BlotChannel(
                asset_sha256="ch1",
                channel_index=1,
                wavelength_nm=685,
                antibody_name="Ab-700",
            ),
        ],
        overlay_ladder=overlay_ladder,
    )


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


class TestLadderRowForBlot:

    def test_ladder_row_ecl(self):
        """ECL blot always returns channel_index 0."""
        blot = _ecl_blot()
        assert _ladder_row_for_blot(blot, []) == 0

    def test_ladder_row_nir_no_bands(self):
        """NIR blot with no overlay ladder returns 0."""
        blot = _nir_blot(overlay_ladder=None)
        assert _ladder_row_for_blot(blot, []) == 0

    def test_ladder_row_nir_all_blank_channels(self):
        """NIR blot where all preset bands have channels==[] falls back to 0."""
        marker_sets = [MarkerSet(id="ms1", name="Test", bands=[
            MarkerBand(kda=100, channels=[]),
            MarkerBand(kda=50, channels=[]),
        ])]
        overlay = OverlayLadder(
            marker_set_id="ms1",
            bands=[
                LadderBandAssignment(y_px=100, kda=100),
                LadderBandAssignment(y_px=200, kda=50),
            ],
        )
        blot = _nir_blot(overlay_ladder=overlay)
        assert _ladder_row_for_blot(blot, marker_sets) == 0

    def test_ladder_row_nir_685_bands(self):
        """Bands tagged [685]: 685 nm is on channel_index 1, so returns 1."""
        marker_sets = [MarkerSet(id="ms1", name="Test", bands=[
            MarkerBand(kda=100, channels=[685]),
            MarkerBand(kda=50, channels=[685]),
        ])]
        overlay = OverlayLadder(
            marker_set_id="ms1",
            bands=[
                LadderBandAssignment(y_px=100, kda=100),
                LadderBandAssignment(y_px=200, kda=50),
            ],
        )
        blot = _nir_blot(overlay_ladder=overlay)
        assert _ladder_row_for_blot(blot, marker_sets) == 1

    def test_ladder_row_nir_785_bands(self):
        """Bands tagged [785]: 785 nm is on channel_index 0, so returns 0."""
        marker_sets = [MarkerSet(id="ms1", name="Test", bands=[
            MarkerBand(kda=100, channels=[785]),
            MarkerBand(kda=50, channels=[785]),
        ])]
        overlay = OverlayLadder(
            marker_set_id="ms1",
            bands=[
                LadderBandAssignment(y_px=100, kda=100),
                LadderBandAssignment(y_px=200, kda=50),
            ],
        )
        blot = _nir_blot(overlay_ladder=overlay)
        assert _ladder_row_for_blot(blot, marker_sets) == 0

    def test_ladder_row_nir_mixed_bands(self):
        """Some bands tagged [685], some blank: first channel matching 685 is index 1."""
        marker_sets = [MarkerSet(id="ms1", name="Test", bands=[
            MarkerBand(kda=100, channels=[685]),
            MarkerBand(kda=50, channels=[]),
        ])]
        overlay = OverlayLadder(
            marker_set_id="ms1",
            bands=[
                LadderBandAssignment(y_px=100, kda=100),
                LadderBandAssignment(y_px=200, kda=50),
            ],
        )
        blot = _nir_blot(overlay_ladder=overlay)
        assert _ladder_row_for_blot(blot, marker_sets) == 1


class TestShowInFinalFlag:

    def test_show_in_final_false_hides_in_panel_scene(self):
        """build_panel_scene must gate band drawing on show_in_final."""
        src = inspect.getsource(build_panel_scene)
        assert "show_in_final" in src, (
            "build_panel_scene must check show_in_final to hide bands in the final figure"
        )

    def test_show_in_final_does_not_gate_provenance(self):
        """build_provenance_scene must not filter bands by show_in_final."""
        src = inspect.getsource(build_provenance_scene)
        assert "show_in_final" not in src, (
            "build_provenance_scene must not filter bands by show_in_final; "
            "all bands must always be visible in the provenance (Original Image) view"
        )


class TestLabelAlignment:

    def test_label_x_tracks_tick_x0(self):
        """Provenance kDa label must use font-adaptive right-edge alignment, not a fixed offset."""
        src = inspect.getsource(build_provenance_scene)
        assert "tick_x0 - br.width() - 4.0" in src, (
            "provenance label x must be tick_x0 - br.width() - 4.0 so it stays "
            "flush with the tick regardless of font size"
        )
        assert "label_x" not in src, (
            "old fixed label_x offset must be removed from build_provenance_scene"
        )
