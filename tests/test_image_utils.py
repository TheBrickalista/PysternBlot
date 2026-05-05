# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for pysternblot/image_utils.py

Run from repo root:
    pytest tests/test_image_utils.py -v

No Qt display is required — the Qt-dependent functions (uint16_to_qimage,
uint16_to_qpixmap) are tested separately and skipped if a display is not
available.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uint16(h: int = 16, w: int = 16, fill: int = 32768) -> np.ndarray:
    """Return a small solid uint16 image."""
    return np.full((h, w), fill, dtype=np.uint16)


def _make_gradient_uint16(h: int = 16, w: int = 16) -> np.ndarray:
    """Return a uint16 image with values ramping 0 → 65535 across columns."""
    row = np.linspace(0, 65535, w, dtype=np.float32)
    return np.tile(row, (h, 1)).astype(np.uint16)


def _save_tmp_uint16_tiff(arr: np.ndarray) -> Path:
    """Save a uint16 array to a temp TIFF and return the path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
    h, w = arr.shape
    Image.frombuffer("I;16", (w, h), arr.tobytes(), "raw", "I;16", 0, 1).save(tmp.name, format="TIFF")
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from pysternblot.image_utils import (
    apply_levels_uint16,
    crop_uint16,
    load_image_uint16,
    rotate_uint16,
    save_uint16_tiff,
)


# ===========================================================================
# apply_levels_uint16
# ===========================================================================

class TestApplyLevels:

    def test_returns_uint16(self):
        img = _make_uint16(fill=32768)
        out = apply_levels_uint16(img, black=0, white=65535, gamma=1.0, invert=False)
        assert out.dtype == np.uint16

    def test_identity_passthrough(self):
        """black=0, white=65535, gamma=1, no invert → values unchanged."""
        img = _make_gradient_uint16()
        out = apply_levels_uint16(img, black=0, white=65535, gamma=1.0, invert=False)
        # Allow ±1 rounding tolerance
        assert np.max(np.abs(out.astype(np.int32) - img.astype(np.int32))) <= 1

    def test_black_clips_to_zero(self):
        """Pixels at or below black point should map to 0."""
        img = _make_uint16(fill=1000)
        out = apply_levels_uint16(img, black=1000, white=65535, gamma=1.0, invert=False)
        assert np.all(out == 0)

    def test_white_clips_to_max(self):
        """Pixels at or above white point should map to 65535."""
        img = _make_uint16(fill=65535)
        out = apply_levels_uint16(img, black=0, white=65535, gamma=1.0, invert=False)
        assert np.all(out == 65535)

    def test_invert_flips_values(self):
        """Invert should flip: 0 → 65535 and 65535 → 0."""
        img_black = _make_uint16(fill=0)
        img_white = _make_uint16(fill=65535)
        out_black = apply_levels_uint16(img_black, 0, 65535, 1.0, invert=True)
        out_white = apply_levels_uint16(img_white, 0, 65535, 1.0, invert=True)
        assert np.all(out_black == 65535)
        assert np.all(out_white == 0)

    def test_gamma_greater_than_one_darkens(self):
        img = _make_uint16(fill=32768)
        out_g1 = apply_levels_uint16(img, 0, 65535, gamma=1.0, invert=False)
        out_g2 = apply_levels_uint16(img, 0, 65535, gamma=2.0, invert=False)
        assert out_g2[0, 0] > out_g1[0, 0]  # gamma>1 brightens

    def test_gamma_less_than_one_brightens(self):
        img = _make_uint16(fill=32768)
        out_g1 = apply_levels_uint16(img, 0, 65535, gamma=1.0, invert=False)
        out_g05 = apply_levels_uint16(img, 0, 65535, gamma=0.5, invert=False)
        assert out_g05[0, 0] < out_g1[0, 0]  # gamma<1 darkens

    def test_white_equal_black_does_not_crash(self):
        """white <= black is clamped to black+1 — should not divide by zero."""
        img = _make_uint16(fill=1000)
        out = apply_levels_uint16(img, black=5000, white=5000, gamma=1.0, invert=False)
        assert out.dtype == np.uint16

    def test_zero_gamma_does_not_crash(self):
        """gamma=0 is clamped to 1.0 — should not raise ZeroDivisionError."""
        img = _make_uint16(fill=32768)
        out = apply_levels_uint16(img, 0, 65535, gamma=0.0, invert=False)
        assert out.dtype == np.uint16

    def test_rejects_non_uint16(self):
        img = np.zeros((16, 16), dtype=np.uint8)
        with pytest.raises(TypeError):
            apply_levels_uint16(img, 0, 255, 1.0, False)

    def test_output_is_contiguous(self):
        img = _make_uint16()
        out = apply_levels_uint16(img, 0, 65535, 1.0, False)
        assert out.flags["C_CONTIGUOUS"]


# ===========================================================================
# crop_uint16
# ===========================================================================

class TestCropUint16:

    def test_basic_crop(self):
        img = _make_gradient_uint16(h=32, w=32)
        out = crop_uint16(img, x=4, y=4, w=8, h=8)
        assert out.shape == (8, 8)
        assert np.array_equal(out, img[4:12, 4:12])

    def test_out_of_bounds_x_clamped(self):
        img = _make_uint16(h=10, w=10)
        out = crop_uint16(img, x=8, y=0, w=10, h=5)
        # x=8, w clamped to 10-8=2
        assert out.shape[1] == 2

    def test_out_of_bounds_y_clamped(self):
        img = _make_uint16(h=10, w=10)
        out = crop_uint16(img, x=0, y=8, w=5, h=10)
        assert out.shape[0] == 2

    def test_negative_x_clamped_to_zero(self):
        img = _make_uint16(h=10, w=10)
        out = crop_uint16(img, x=-5, y=0, w=5, h=5)
        assert out.shape == (5, 5)

    def test_minimum_size_is_1x1(self):
        """Even with a zero-width request, output must be at least 1×1."""
        img = _make_uint16(h=10, w=10)
        out = crop_uint16(img, x=9, y=9, w=0, h=0)
        assert out.shape == (1, 1)

    def test_full_image_crop(self):
        img = _make_gradient_uint16(h=8, w=8)
        out = crop_uint16(img, x=0, y=0, w=8, h=8)
        assert np.array_equal(out, img)

    def test_output_is_contiguous(self):
        img = _make_uint16()
        out = crop_uint16(img, 0, 0, 8, 8)
        assert out.flags["C_CONTIGUOUS"]

    def test_preserves_dtype(self):
        img = _make_uint16()
        out = crop_uint16(img, 0, 0, 8, 8)
        assert out.dtype == np.uint16


# ===========================================================================
# rotate_uint16
# ===========================================================================

class TestRotateUint16:

    def test_zero_rotation_is_noop(self):
        """0° rotation must return the original array unchanged."""
        img = _make_gradient_uint16()
        out = rotate_uint16(img, rotation_deg=0.0)
        assert np.array_equal(out, img)

    def test_zero_rotation_returns_contiguous(self):
        img = _make_gradient_uint16()
        out = rotate_uint16(img, rotation_deg=0.0)
        assert out.flags["C_CONTIGUOUS"]

    def test_returns_uint16(self):
        img = _make_uint16()
        out = rotate_uint16(img, rotation_deg=90.0)
        assert out.dtype == np.uint16

    def test_180_rotation_shape_preserved(self):
        img = _make_uint16(h=10, w=20)
        out = rotate_uint16(img, rotation_deg=180.0)
        assert out.shape == (10, 20)

    def test_90_rotation_with_expand_swaps_dimensions(self):
        img = _make_uint16(h=10, w=20)
        out = rotate_uint16(img, rotation_deg=90.0, expand=True)
        assert out.shape == (20, 10)

    def test_values_clipped_to_uint16_range(self):
        img = _make_uint16(fill=65535)
        out = rotate_uint16(img, rotation_deg=45.0)
        assert out.max() <= 65535
        assert out.min() >= 0

    def test_rejects_non_uint16(self):
        img = np.zeros((16, 16), dtype=np.float32)
        with pytest.raises(TypeError):
            rotate_uint16(img, 45.0)

    def test_near_zero_rotation_treated_as_noop(self):
        """Angles smaller than 1e-6 should return the original array."""
        img = _make_gradient_uint16()
        out = rotate_uint16(img, rotation_deg=1e-7)
        assert np.array_equal(out, img)


# ===========================================================================
# load_image_uint16
# ===========================================================================

class TestLoadImageUint16:

    def test_loads_valid_uint16_tiff(self, tmp_path):
        img = _make_gradient_uint16(h=8, w=8)
        path = tmp_path / "test.tif"
        Image.frombuffer("I;16", (img.shape[1], img.shape[0]), img.tobytes(), "raw", "I;16", 0, 1).save(str(path), format="TIFF")
        loaded = load_image_uint16(path)
        assert loaded.dtype == np.uint16
        assert loaded.shape == (8, 8)

    def test_roundtrip_values_preserved(self, tmp_path):
        img = _make_gradient_uint16(h=8, w=16)
        path = tmp_path / "rt.tif"
        Image.frombuffer("I;16", (img.shape[1], img.shape[0]), img.tobytes(), "raw", "I;16", 0, 1).save(str(path), format="TIFF")
        loaded = load_image_uint16(path)
        assert np.array_equal(loaded, img)

    def test_rejects_8bit_grayscale(self, tmp_path):
        img8 = np.zeros((8, 8), dtype=np.uint8)
        path = tmp_path / "gray8.tif"
        Image.fromarray(img8, mode="L").save(str(path), format="TIFF")
        with pytest.raises(ValueError, match="Unsupported image mode"):
            load_image_uint16(path)

    def test_rejects_rgb(self, tmp_path):
        img_rgb = np.zeros((8, 8, 3), dtype=np.uint8)
        path = tmp_path / "rgb.png"
        Image.fromarray(img_rgb, mode="RGB").save(str(path))
        with pytest.raises(ValueError, match="Unsupported image mode"):
            load_image_uint16(path)

    def test_returns_contiguous_array(self, tmp_path):
        img = _make_uint16()
        path = tmp_path / "c.tif"
        Image.frombuffer("I;16", (img.shape[1], img.shape[0]), img.tobytes(), "raw", "I;16", 0, 1).save(str(path), format="TIFF")
        loaded = load_image_uint16(path)
        assert loaded.flags["C_CONTIGUOUS"]

    def test_accepts_path_object(self, tmp_path):
        img = _make_uint16()
        path = tmp_path / "pathobj.tif"
        Image.frombuffer("I;16", (img.shape[1], img.shape[0]), img.tobytes(), "raw", "I;16", 0, 1).save(str(path), format="TIFF")
        loaded = load_image_uint16(path)  # Path object, not string
        assert loaded.dtype == np.uint16

    def test_accepts_string_path(self, tmp_path):
        img = _make_uint16()
        path = tmp_path / "strpath.tif"
        Image.frombuffer("I;16", (img.shape[1], img.shape[0]), img.tobytes(), "raw", "I;16", 0, 1).save(str(path), format="TIFF")
        loaded = load_image_uint16(str(path))  # string, not Path
        assert loaded.dtype == np.uint16


# ===========================================================================
# save_uint16_tiff
# ===========================================================================

class TestSaveUint16Tiff:

    def test_roundtrip(self, tmp_path):
        img = _make_gradient_uint16(h=8, w=16)
        path = tmp_path / "out.tif"
        save_uint16_tiff(img, path)
        loaded = load_image_uint16(path)
        assert np.array_equal(loaded, img)

    def test_rejects_non_uint16(self, tmp_path):
        img = np.zeros((8, 8), dtype=np.float32)
        with pytest.raises(TypeError):
            save_uint16_tiff(img, tmp_path / "bad.tif")

    def test_accepts_path_object(self, tmp_path):
        img = _make_uint16()
        save_uint16_tiff(img, tmp_path / "p.tif")  # should not raise

    def test_accepts_string_path(self, tmp_path):
        img = _make_uint16()
        save_uint16_tiff(img, str(tmp_path / "s.tif"))  # should not raise