# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt

from .models import SaturationStats


def load_image_uint16(path: str | Path) -> np.ndarray:
    """
    Load an image as native grayscale uint16.

    Strict rules:
    - accepts only native 16-bit grayscale images
    - rejects 8-bit, RGB, RGBA, palette, and other modes
    - performs no bit-depth promotion and no color conversion
    """
    path = str(path)

    with Image.open(path) as im:
        if im.mode not in ("I;16", "I;16L", "I;16B"):
            raise ValueError(
                f"Unsupported image mode {im.mode!r} for {path}. "
                "Only native 16-bit grayscale images are accepted."
            )

        arr = np.array(im, dtype=np.uint16)

    if arr.ndim != 2:
        raise ValueError(
            f"Expected a 2D grayscale image for {path}, got shape {arr.shape}."
        )

    return np.ascontiguousarray(arr)


def apply_levels_uint16(
    img: np.ndarray,
    black: int,
    white: int,
    gamma: float,
    invert: bool,
) -> np.ndarray:
    """
    Apply black/white/gamma/invert in 16-bit space.
    Returns uint16.
    """
    if img.dtype != np.uint16:
        raise TypeError(f"Expected uint16 image, got {img.dtype}")

    black = int(black)
    white = int(white)
    gamma = float(gamma)

    if white <= black:
        white = black + 1
    if gamma <= 0:
        gamma = 1.0

    arr = img.astype(np.float32)
    arr = (arr - black) / float(white - black)
    arr = np.clip(arr, 0.0, 1.0)

    inv_gamma = 1.0 / gamma
    arr = np.power(arr, inv_gamma)

    if invert:
        arr = 1.0 - arr

    out = np.round(arr * 65535.0).astype(np.uint16)
    return np.ascontiguousarray(out)


def rotate_uint16(
    img: np.ndarray,
    rotation_deg: float,
    expand: bool = False,
) -> np.ndarray:
    """
    Rotate a uint16 grayscale image while preserving high bit depth.

    Uses Pillow in 32-bit integer mode ("I") for the transform, then clips
    back to uint16. No 8-bit conversion is involved.

    Parameters
    ----------
    img : np.ndarray
        2D uint16 grayscale image.
    rotation_deg : float
        Rotation angle in degrees.
    expand : bool
        If True, Pillow expands the output canvas to contain the whole rotated
        image. If False, the output canvas keeps the original width/height and
        overflowing corners are clipped.
    """
    if img.dtype != np.uint16:
        raise TypeError(f"Expected uint16 image, got {img.dtype}")

    if abs(float(rotation_deg)) < 1e-6:
        return np.ascontiguousarray(img)

    pil = Image.fromarray(img.astype(np.int32), mode="I")

    rotated = pil.rotate(
        float(rotation_deg),
        resample=Image.Resampling.BICUBIC,
        expand=bool(expand),
        fillcolor=0,
    )

    arr = np.array(rotated, dtype=np.int32)
    arr = np.clip(arr, 0, 65535).astype(np.uint16)

    return np.ascontiguousarray(arr)


def crop_uint16(img: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """
    Crop a uint16 image with clamping.
    """
    ih, iw = img.shape[:2]

    x = max(0, min(int(x), max(0, iw - 1)))
    y = max(0, min(int(y), max(0, ih - 1)))
    w = max(1, min(int(w), iw - x))
    h = max(1, min(int(h), ih - y))

    return np.ascontiguousarray(img[y:y + h, x:x + w])


def save_uint16_tiff(img: np.ndarray, path: str | Path) -> None:
    """
    Save uint16 grayscale TIFF.
    """
    if img.dtype != np.uint16:
        raise TypeError(f"Expected uint16 image, got {img.dtype}")

    h, w = img.shape
    pil = Image.frombuffer("I;16", (w, h), img.tobytes(), "raw", "I;16", 0, 1)
    pil.save(str(path), format="TIFF")


def uint16_to_qimage(img: np.ndarray) -> QImage:
    """
    Wrap a uint16 grayscale NumPy array as QImage.Format_Grayscale16.
    Caller must keep the NumPy array alive while the QImage is in use.
    """
    if img.dtype != np.uint16:
        raise TypeError(f"Expected uint16 image, got {img.dtype}")
    if img.ndim != 2:
        raise ValueError(f"Expected 2D grayscale image, got shape {img.shape}")

    h, w = img.shape
    bytes_per_line = w * 2

    qimg = QImage(
        img.data,
        w,
        h,
        bytes_per_line,
        QImage.Format_Grayscale16,
    )
    return qimg


def detect_tiff_channel_encoding(
    path: str | Path,
) -> Literal["multipage", "rgb_interleaved", "single"]:
    """
    Inspect a TIFF and return how its channels are encoded.

    - "multipage"       — multiple frames, one channel per frame (LI-COR Odyssey style)
    - "rgb_interleaved" — single-frame RGB/RGBA (some composite exports)
    - "single"          — single-frame grayscale (ECL, single-channel NIR)
    """
    with Image.open(str(path)) as im:
        n_frames = getattr(im, "n_frames", 1)
        if n_frames > 1:
            return "multipage"
        if im.mode in ("RGB", "RGBA"):
            return "rgb_interleaved"
        return "single"


def load_multichannel_tiff(path: str | Path) -> list[np.ndarray]:
    """
    Load a TIFF and return one uint16 ndarray per channel.

    Dispatch is based on detect_tiff_channel_encoding:
    - "multipage"       — one array per frame
    - "rgb_interleaved" — R and G bands returned as two arrays (NIR dual-channel)
    - "single"          — delegates to load_image_uint16; returns a one-element list
    """
    encoding = detect_tiff_channel_encoding(path)
    path_str = str(path)

    if encoding == "multipage":
        channels: list[np.ndarray] = []
        with Image.open(path_str) as im:
            for i in range(im.n_frames):
                im.seek(i)
                arr = np.array(im, dtype=np.uint16)
                channels.append(np.ascontiguousarray(arr))
        return channels

    if encoding == "rgb_interleaved":
        with Image.open(path_str) as im:
            bands = im.split()
        return [
            np.ascontiguousarray(np.array(b, dtype=np.uint16))
            for b in bands[:2]
        ]

    # "single"
    return [load_image_uint16(path_str)]


def parse_typhoon_channel_id(filename: str) -> str | None:
    """
    Extract a channel identifier from a Typhoon / ImageQuant TIFF filename.

    Two conventions are recognised:
    - Bracket notation: "20260507-142651-[IRlong].tif"  → "IRlong"
    - Wavelength suffix: "scan_700nm_ch1.tif"           → "700nm"

    Returns None if neither pattern is found.
    """
    m = re.search(r'\[([^\]]+)\]', filename)
    if m:
        return m.group(1)
    m = re.search(r'(\d+nm)', filename, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def uint16_to_qpixmap(img: np.ndarray) -> QPixmap:
    """
    Convert uint16 grayscale NumPy array to QPixmap through Grayscale16 QImage.
    """
    qimg = uint16_to_qimage(img)
    return QPixmap.fromImage(qimg, Qt.NoFormatConversion)


def load_image_as_uint16(path: str | Path) -> np.ndarray:
    """
    Load a grayscale image as uint16, accepting both 16-bit and 8-bit sources.

    - Native 16-bit modes (I;16, I;16L, I;16B): loaded directly, unchanged.
    - 8-bit greyscale mode "L": loaded directly, values kept in 0–255 range.
    - 8-bit palette mode "P", and colour modes "RGB"/"RGBA"/"LA" (common
      scanner output for greyscale content): converted to "L" via PIL first.
    - All other modes: raise ValueError.

    Always call on the original asset file, never on a preview or working copy.
    """
    path = str(path)
    with Image.open(path) as im:
        mode = im.mode
        if mode in ("I;16", "I;16L", "I;16B"):
            arr = np.array(im, dtype=np.uint16)
        elif mode == "L":
            arr = np.array(im, dtype=np.uint8).astype(np.uint16)
        elif mode in ("P", "RGB", "RGBA", "LA"):
            grey = im.convert("L")
            arr = np.array(grey, dtype=np.uint8).astype(np.uint16)
        else:
            raise ValueError(
                f"Unsupported image mode {mode!r} for {path}. "
                "Accepted: 16-bit grayscale (I;16 family), 8-bit grayscale (L), "
                "palette (P), and colour (RGB/RGBA) modes."
            )

    if arr.ndim != 2:
        raise ValueError(
            f"Expected a 2D grayscale image for {path}, got shape {arr.shape}."
        )

    return np.ascontiguousarray(arr)


def is_jpeg(path: str | Path) -> bool:
    """Return True if the file starts with JPEG magic bytes (FF D8), regardless of extension."""
    with open(str(path), "rb") as f:
        header = f.read(2)
    return header == b'\xff\xd8'


def get_bit_depth(path: str | Path) -> int:
    """
    Return the bit depth of the image at path as an integer (16, 8, or 0 for unknown).

    Always call on the original asset file, never on a preview or working copy.
    """
    with Image.open(str(path)) as im:
        mode = im.mode
    if mode in ("I;16", "I;16L", "I;16B", "I;16S", "F"):
        return 16
    if mode in ("L", "RGB", "RGBA", "P", "1"):
        return 8
    return 0


def _shift_mask(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Shift a boolean mask by (dy, dx); pixels shifted in from outside the
    array are False. out[y, x] == mask[y + dy, x + dx] wherever that index is
    in bounds, else False — so a pixel at the image edge always "sees" a
    False neighbor off-canvas, exactly like a real out-of-bounds read would."""
    h, w = mask.shape
    out = np.zeros_like(mask)

    y_dst_start, y_dst_end = max(0, -dy), min(h, h - dy)
    x_dst_start, x_dst_end = max(0, -dx), min(w, w - dx)
    if y_dst_start >= y_dst_end or x_dst_start >= x_dst_end:
        return out

    out[y_dst_start:y_dst_end, x_dst_start:x_dst_end] = mask[
        y_dst_start + dy:y_dst_end + dy,
        x_dst_start + dx:x_dst_end + dx,
    ]
    return out


def compute_saturation_stats(img: np.ndarray, bit_depth: int) -> SaturationStats:
    """
    Detect clipped (saturated) signal in a source image, distinguishing a
    saturated band (a solid contiguous region) from a dust speck (isolated
    hot pixels) via 3x3 binary erosion of the saturation mask.

    Must be called on the source array exactly as imported — before any
    levels, gamma, rotation, or flip. Saturation is a property of the
    acquisition, not of the display.
    """
    full_scale = 255 if bit_depth == 8 else 65535
    mask = img == full_scale

    total_pixels = int(img.size)
    saturated_count = int(np.count_nonzero(mask))
    max_value = int(img.max()) if img.size else 0

    solid_saturated_count = 0
    if saturated_count > 0:
        # Short-circuit above: with no saturated pixels the mask is all-False
        # and erosion is pointless work for the common case.
        eroded = mask.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                eroded &= _shift_mask(mask, dy, dx)
        solid_saturated_count = int(np.count_nonzero(eroded))

    return SaturationStats(
        max_value=max_value,
        full_scale=full_scale,
        saturated_count=saturated_count,
        total_pixels=total_pixels,
        saturated_fraction=(saturated_count / total_pixels) if total_pixels else 0.0,
        solid_saturated_count=solid_saturated_count,
    )
