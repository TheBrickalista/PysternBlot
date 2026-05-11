# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for _band_visible_on_channel in render.py.

No Qt or display required — pure logic tests.
"""

from __future__ import annotations

from pysternblot.models import MarkerBand
from pysternblot.render import _band_visible_on_channel


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
