# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Tests for NIR multichannel TIFF loading (image_utils.py — Phase 6).

Instrument test files are not yet committed. Tests that require them
are marked skip with the expected filename. Drop the file into tests/
and remove the skip to activate.

Run from repo root:
    pytest tests/test_multichannel_tiff.py -v
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pysternblot.image_utils import (
    detect_tiff_channel_encoding,
    load_image_uint16,
    load_multichannel_tiff,
    parse_typhoon_channel_id,
)

TESTS_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uint16_page(value: int, size: tuple[int, int] = (10, 10)) -> Image.Image:
    """Return a single I;16 PIL image filled with *value*."""
    w, h = size
    arr = np.full((h, w), value, dtype=np.uint16)
    return Image.frombuffer("I;16", (w, h), arr.tobytes(), "raw", "I;16", 0, 1)


def _save_multipage_uint16(path: Path, values: list[int]) -> None:
    """Save a multi-page I;16 TIFF with one page per value in *values*."""
    pages = [_make_uint16_page(v) for v in values]
    pages[0].save(path, format="TIFF", save_all=True, append_images=pages[1:])


# ---------------------------------------------------------------------------
# detect_tiff_channel_encoding
# ---------------------------------------------------------------------------

class TestDetectTiffChannelEncoding:

    def test_detect_single_page_tiff_encoding(self, tmp_path):
        """
        A single-frame I;16 TIFF must be detected as "single".

        This covers the standard ECL blot case and any single-channel NIR
        acquisition saved as an independent file.
        """
        path = tmp_path / "single.tif"
        _make_uint16_page(1000).save(path, format="TIFF")

        assert detect_tiff_channel_encoding(path) == "single"

    def test_detect_multipage_tiff_encoding(self, tmp_path):
        """
        A TIFF with two I;16 frames must be detected as "multipage".

        This is the primary LI-COR Odyssey export format: one page per
        fluorescence channel (e.g. 700 nm on page 0, 800 nm on page 1).
        """
        path = tmp_path / "multipage.tif"
        _save_multipage_uint16(path, [1000, 2000])

        assert detect_tiff_channel_encoding(path) == "multipage"

    def test_detect_rgb_interleaved_encoding(self, tmp_path):
        """
        A single-frame RGB TIFF must be detected as "rgb_interleaved".

        Some composite exports from NIR platforms (or false-colour previews)
        pack two channels into the R and G bands of a standard RGB image.
        """
        path = tmp_path / "rgb.tif"
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        Image.fromarray(arr, mode="RGB").save(path, format="TIFF")

        assert detect_tiff_channel_encoding(path) == "rgb_interleaved"


# ---------------------------------------------------------------------------
# load_multichannel_tiff — synthetic data
# ---------------------------------------------------------------------------

class TestLoadMultichannelTiff:

    def test_load_multipage_tiff_returns_two_uint16_arrays(self, tmp_path):
        """
        load_multichannel_tiff on a 2-page I;16 TIFF must return a list of
        exactly 2 arrays, each with dtype == np.uint16.
        """
        path = tmp_path / "multipage.tif"
        _save_multipage_uint16(path, [1000, 2000])

        channels = load_multichannel_tiff(path)

        assert len(channels) == 2
        assert all(ch.dtype == np.uint16 for ch in channels)

    def test_each_channel_preserves_pixel_values(self, tmp_path):
        """
        When page 0 is all-1000 and page 1 is all-2000, load_multichannel_tiff
        must return channel 0 with max 1000 and channel 1 with max 2000.

        This verifies that channel ordering is preserved and that no cross-
        channel blending occurs during loading.
        """
        path = tmp_path / "multipage.tif"
        _save_multipage_uint16(path, [1000, 2000])

        channels = load_multichannel_tiff(path)

        assert int(channels[0].max()) == 1000
        assert int(channels[1].max()) == 2000

    def test_load_multichannel_rgb_interleaved(self, tmp_path):
        """
        For an RGB TIFF whose R and G bands contain distinct values,
        load_multichannel_tiff must return exactly 2 channels with
        correctly separated (non-equal) values.

        The R band maps to channel 0 and the G band to channel 1, matching
        the dual-channel NIR convention where shorter-wavelength signal is
        stored in R and longer in G (or vice-versa, platform-dependent).
        """
        path = tmp_path / "rgb.tif"
        w, h = 10, 10
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[:, :, 0] = 100  # R channel — channel 0
        arr[:, :, 1] = 200  # G channel — channel 1
        Image.fromarray(arr, mode="RGB").save(path, format="TIFF")

        channels = load_multichannel_tiff(path)

        assert len(channels) == 2
        assert all(ch.dtype == np.uint16 for ch in channels)
        assert int(channels[0].max()) != int(channels[1].max()), (
            "R and G channels should be distinct after extraction"
        )
        assert int(channels[0].max()) == 100
        assert int(channels[1].max()) == 200


# ---------------------------------------------------------------------------
# Backward compatibility — existing ECL single-channel file
# ---------------------------------------------------------------------------

class TestBackwardCompatSingleChannelEcl:

    def test_backward_compat_single_channel_ecl(self):
        """
        The existing ECL test TIFF (rhoa 20260220_131003_Ch_Chemi.tif) must be
        detected as "single" and load as a one-element list, confirming that
        the new multichannel API is a pure superset and does not break any
        existing ECL workflow.
        """
        path = TESTS_DIR / "rhoa 20260220_131003_Ch_Chemi.tif"
        if not path.exists():
            pytest.skip(f"Test image not found: {path.name}")

        assert detect_tiff_channel_encoding(path) == "single"

        channels = load_multichannel_tiff(path)
        assert len(channels) == 1
        assert channels[0].dtype == np.uint16
        assert channels[0].ndim == 2


# ---------------------------------------------------------------------------
# Instrument file tests — skipped until files are committed
# ---------------------------------------------------------------------------

class TestInstrumentFiles:

    def test_load_licor_odyssey_multipage(self):
        """
        Verify that a real LI-COR Odyssey TIFF export (Image Studio format)
        loads as exactly 2 channels, each uint16, with correct shape.

        The file is a multi-page TIFF produced by Image Studio software with
        one 16-bit grayscale page per fluorescence channel.
        """
        pytest.skip("awaiting test image: licor_odyssey_sample.tif")

    def test_load_licor_odyssey_channel_independence(self):
        """
        Verify that channels 0 and 1 from a real LI-COR Odyssey file are not
        identical — i.e. they genuinely represent different fluorescence
        signals (700 nm vs 800 nm) and have not been duplicated or blended.
        """
        pytest.skip("awaiting test image: licor_odyssey_sample.tif")

    def test_load_typhoon_separate_files(self):
        """
        Verify that each Typhoon channel file (IRshort / IRlong) loads as a
        single uint16 array via load_image_uint16, and that both have the same
        shape — confirming co-registered acquisition from the same membrane
        scan (Cytiva Typhoon convention: one 16-bit grayscale TIFF per channel).
        """
        ch_short = TESTS_DIR / "20260507-142651-[IRshort].tif"
        ch_long = TESTS_DIR / "20260507-142651-[IRlong].tif"

        arr_short = load_image_uint16(ch_short)
        arr_long = load_image_uint16(ch_long)

        assert arr_short.dtype == np.uint16
        assert arr_long.dtype == np.uint16
        assert arr_short.shape == arr_long.shape, (
            "Both channels must have identical shape (co-registered acquisition)"
        )

    def test_load_typhoon_wavelength_from_filename(self):
        """
        Verify that parse_typhoon_channel_id correctly extracts the channel
        identifier from Typhoon / ImageQuant bracket-notation filenames.

        The Typhoon convention encodes the channel name as a bracketed token:
          "20260507-142651-[IRshort].tif" → "IRshort"
          "20260507-142651-[IRlong].tif"  → "IRlong"

        Numeric wavelength filenames (e.g. "scan_700nm.tif" → "700nm") are
        also supported by the parser but are not present in this acquisition.
        """
        ch_short = TESTS_DIR / "20260507-142651-[IRshort].tif"
        ch_long = TESTS_DIR / "20260507-142651-[IRlong].tif"

        assert parse_typhoon_channel_id(ch_short.name) == "IRshort"
        assert parse_typhoon_channel_id(ch_long.name) == "IRlong"
