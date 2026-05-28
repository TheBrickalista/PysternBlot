# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Tests for NIR TIFF export filename logic in export_mixin.py.

No Qt or display required — pure logic tests.
"""

from __future__ import annotations

from pysternblot.ui.export_mixin import _nir_channel_path
from pysternblot.models import (
    Blot,
    CalibrationPoint,
    Crop,
    Ladder,
    ProteinLabel,
)


def test_nir_channel_filename_suffix():
    """Channel with a known wavelength gets _ch{idx}_{wl}nm appended before .tif."""
    result = _nir_channel_path(
        "output/myblot_original_annotated.tif",
        channel_index=0,
        wavelength_nm=785,
    )
    assert result == "output/myblot_original_annotated_ch0_785nm.tif"


def test_nir_channel_filename_no_wavelength():
    """Channel without a wavelength gets only _ch{idx} appended."""
    result = _nir_channel_path(
        "output/myblot_original_annotated.tif",
        channel_index=1,
        wavelength_nm=None,
    )
    assert result == "output/myblot_original_annotated_ch1.tif"


def test_ecl_blot_filename_unchanged():
    """ECL blots have is_nir()==False so the per-channel export path is never applied."""
    blot = Blot(
        id="ecl_blot",
        asset_sha256="aaa",
        crop=Crop(x=0, y=0, w=300, h=200),
        ladder=Ladder(
            lane_index=0,
            marker_set_id="ms1",
            calibration_points=[
                CalibrationPoint(y_px=50, kda=55),
                CalibrationPoint(y_px=120, kda=36),
            ],
        ),
        protein_label=ProteinLabel(text=""),
        modality="ecl",
    )
    assert not blot.is_nir(), "ECL blot must not be treated as NIR"
    # For ECL blots the export code takes the single-file path unchanged.
    # Verify the helper does not mangle a path when called with index 0 / no wl
    # (caller is responsible for not calling this for ECL blots, but the
    # function itself must still produce correct output if called).
    result = _nir_channel_path("myblot.tif", channel_index=0, wavelength_nm=None)
    assert result == "myblot_ch0.tif"
