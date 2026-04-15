# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt


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


def rotate_uint16(img: np.ndarray, rotation_deg: float) -> np.ndarray:
    """
    Rotate a uint16 grayscale image while preserving high bit depth.

    Uses Pillow in 32-bit integer mode ("I") for the transform, then clips
    back to uint16. No 8-bit conversion is involved.
    """
    if img.dtype != np.uint16:
        raise TypeError(f"Expected uint16 image, got {img.dtype}")

    if abs(float(rotation_deg)) < 1e-6:
        return np.ascontiguousarray(img)

    # Promote to Pillow's 32-bit integer mode for safer geometric transforms
    pil = Image.fromarray(img.astype(np.int32), mode="I")

    rotated = pil.rotate(
        float(rotation_deg),
        resample=Image.Resampling.BICUBIC,
        expand=True,
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

    Image.fromarray(img, mode="I;16").save(str(path), format="TIFF")


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


def uint16_to_qpixmap(img: np.ndarray) -> QPixmap:
    """
    Convert uint16 grayscale NumPy array to QPixmap through Grayscale16 QImage.
    """
    qimg = uint16_to_qimage(img)
    return QPixmap.fromImage(qimg, Qt.NoFormatConversion)