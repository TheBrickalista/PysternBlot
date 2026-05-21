# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for 8-bit import detection, JPEG rejection, and integrity report flagging."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from pysternblot.image_utils import get_bit_depth, is_jpeg

TYPHOON_IRSHORT = Path("tests/20260507-142651-[IRshort].tif")


def _minimal_project():
    from pysternblot.models import Project
    return Project.model_validate({
        "project": {
            "id": "test_project_8bit",
            "name": "Test 8-bit",
            "created_utc": "2024-01-01T00:00:00Z",
            "modified_utc": "2024-01-01T00:00:00Z",
            "app_version": "0.1.0",
            "license": "GPL-3.0-only",
        },
        "panel": {
            "blots": [],
            "style": {},
            "layout": {"stack_mode": "vertical_stack", "order": []},
            "legend": {"mode": "protein", "upper_rows": [], "lower_rows": []},
            "crop_template": {"w": 300.0, "h": 200.0},
            "lane_layout": {
                "mode": "manual_n_lanes",
                "n_lanes_manual": 2,
                "header_block": {
                    "left_title": "",
                    "groups": [{"label": "", "n_lanes": 2, "underline": True}],
                    "condition_rows": [{"values": ["", ""], "unit_right": ""}],
                    "span_rows": [],
                },
            },
        },
        "assets": {},
        "marker_sets": [],
        "operation_log": [],
    })


# ---------------------------------------------------------------------------
# 1 & 2. is_jpeg()
# ---------------------------------------------------------------------------

class TestIsJpeg:
    def test_is_jpeg_true(self, tmp_path):
        p = tmp_path / "test.jpg"
        p.write_bytes(b'\xff\xd8\xff' + b'\x00' * 100)
        assert is_jpeg(p) is True

    def test_is_jpeg_false_tiff(self, tmp_path):
        p = tmp_path / "test.tif"
        p.write_bytes(b'\x49\x49\x2a\x00' + b'\x00' * 100)
        assert is_jpeg(p) is False

    def test_is_jpeg_false_png(self, tmp_path):
        p = tmp_path / "test.png"
        p.write_bytes(b'\x89PNG' + b'\x00' * 100)
        assert is_jpeg(p) is False


# ---------------------------------------------------------------------------
# 3 & 4. get_bit_depth()
# ---------------------------------------------------------------------------

class TestGetBitDepth:
    def test_get_bit_depth_16(self):
        assert get_bit_depth(TYPHOON_IRSHORT) == 16

    def test_get_bit_depth_8(self, tmp_path):
        p = tmp_path / "test_8bit.tif"
        Image.new("L", (10, 10)).save(str(p))
        assert get_bit_depth(p) == 8


# ---------------------------------------------------------------------------
# 5 & 6. levels_white logic
# ---------------------------------------------------------------------------

class TestLevelsWhiteLogic:
    def test_levels_white_8bit(self, tmp_path):
        p = tmp_path / "eight.tif"
        Image.new("L", (10, 10)).save(str(p))
        bit_depth = get_bit_depth(p)
        levels_white = 255 if bit_depth == 8 else 65535
        assert levels_white == 255

    def test_levels_white_16bit(self):
        bit_depth = get_bit_depth(TYPHOON_IRSHORT)
        levels_white = 255 if bit_depth == 8 else 65535
        assert levels_white == 65535


# ---------------------------------------------------------------------------
# 7 & 8. _asset_info() bit_depth_warning
# ---------------------------------------------------------------------------

class TestAssetInfo:
    def test_bit_depth_warning_in_asset_info(self, tmp_path):
        from pysternblot.integrity import _asset_info
        from pysternblot.storage import Workspace

        ws = Workspace(tmp_path)
        project = _minimal_project()

        img_path = tmp_path / "original.tif"
        Image.new("L", (10, 10)).save(str(img_path))

        with patch.object(ws, "asset_original_file", return_value=img_path):
            result = _asset_info(ws, project, "testdigest8bit")

        assert result["bit_depth"] == 8
        assert result["bit_depth_warning"] is not None

    def test_bit_depth_warning_absent_for_16bit(self, tmp_path):
        from pysternblot.integrity import _asset_info
        from pysternblot.storage import Workspace

        ws = Workspace(tmp_path)
        project = _minimal_project()

        with patch.object(ws, "asset_original_file", return_value=TYPHOON_IRSHORT):
            result = _asset_info(ws, project, "testdigest16bit")

        assert result["bit_depth"] == 16
        assert result["bit_depth_warning"] is None

    # ---------------------------------------------------------------------------
    # 9. get_bit_depth() must never be called on a preview path
    # ---------------------------------------------------------------------------

    def test_get_bit_depth_never_called_on_preview(self, tmp_path):
        """_asset_info raises if asset_original_file returns a path with 'preview' in the name."""
        from pysternblot.integrity import _asset_info
        from pysternblot.storage import Workspace

        ws = Workspace(tmp_path)
        project = _minimal_project()

        # Simulate a misconfigured workspace that returns a preview path
        preview_path = tmp_path / "preview_crop_blot_01.tif"
        Image.new("L", (10, 10)).save(str(preview_path))

        with patch.object(ws, "asset_original_file", return_value=preview_path):
            with pytest.raises((RuntimeError, AssertionError)):
                _asset_info(ws, project, "testdigest_preview")
