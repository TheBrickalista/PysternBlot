# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import numpy as np
import tifffile
from PIL import Image, UnidentifiedImageError
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt

from .models import SaturationStats

# The TRUE on-disk sample format, as reported by load_tiff_source /
# get_bit_depth's internal detection. float16 is always promoted to float32
# in the returned array, but the source_dtype string still says "float16" --
# that distinction only matters for provenance (get_source_bits), never for
# in-memory arithmetic, which always sees float32.
SourceDtype = Literal["uint8", "uint16", "float16", "float32"]


def is_float_source(source_dtype: str) -> bool:
    return source_dtype in ("float16", "float32")


def _detect_source_dtype_lazy(path: str) -> SourceDtype | None:
    """
    Cheaply determine the source dtype WITHOUT decoding pixel data --
    Image.open() is lazy (reads only the header) and TiffPage.dtype is a
    metadata-only property, so this stays cheap enough to call on every UI
    refresh (levels-slider sync, badge visibility, histogram gating).

    Returns None if the format/mode is not recognised by either reader.
    """
    try:
        with Image.open(path) as im:
            mode = im.mode
        if mode in ("I;16", "I;16L", "I;16B"):
            return "uint16"
        if mode in ("L", "P", "RGB", "RGBA", "LA"):
            return "uint8"
        if mode == "F":
            return "float32"
        return None  # Pillow opened it but the mode is not one we handle
    except (UnidentifiedImageError, OSError):
        pass

    try:
        with tifffile.TiffFile(path) as tif:
            dtype = tif.series[0].levels[0].pages[0].dtype
    except Exception:
        return None

    if dtype == np.float16:
        return "float16"
    if dtype == np.float32:
        return "float32"
    if dtype == np.uint8:
        return "uint8"
    if dtype == np.uint16:
        return "uint16"
    return None


def load_tiff_source(path: str | Path) -> tuple[np.ndarray, SourceDtype]:
    """
    The single shared reader for both import paths ("Import blot" and NIR
    import) and for get_bit_depth's full-decode fallback. Routes on
    FORMAT, not on exceptions:

    - Pillow opens the file successfully: dispatch on im.mode. Modes
      I;16/I;16L/I;16B, L, P, RGB, RGBA, LA behave exactly as the pre-existing
      loader did -- existing uint8/uint16 imports are unaffected. Mode "F"
      (Pillow's own 32-bit float mode) goes to the float path too.
    - Pillow raises UnidentifiedImageError or OSError -- it cannot open the
      file at all, e.g. a tiled, multi-page float16 TIFF -- and ONLY then:
      fall back to tifffile, reading exclusively series[0].levels[0].pages[0],
      the full-resolution page. Pyramid levels 1+ are never read, and
      pages[-1] is never read. float16 is promoted to float32 in the
      returned array; uint8/uint16 pass through unchanged.

    Any other Pillow-openable mode, or any other tifffile sample format,
    raises ValueError -- the same "unsupported mode" contract the previous
    loader had, just now also covering the tifffile fallback path.

    Returns (array, source_dtype). source_dtype is the TRUE on-disk dtype
    ("float16" is reported even though the array itself is always float32 in
    memory for float sources -- see SourceDtype).
    """
    path = str(path)

    try:
        with Image.open(path) as im:
            mode = im.mode
            if mode in ("I;16", "I;16L", "I;16B"):
                arr = np.array(im, dtype=np.uint16)
                return np.ascontiguousarray(arr), "uint16"
            if mode == "L":
                arr = np.array(im, dtype=np.uint8)
                return np.ascontiguousarray(arr), "uint8"
            if mode in ("P", "RGB", "RGBA", "LA"):
                grey = im.convert("L")
                arr = np.array(grey, dtype=np.uint8)
                return np.ascontiguousarray(arr), "uint8"
            if mode == "F":
                arr = np.array(im, dtype=np.float32)
                return np.ascontiguousarray(arr), "float32"
            raise ValueError(
                f"Unsupported image mode {mode!r} for {path}. "
                "Accepted: 16-bit grayscale (I;16 family), 8-bit grayscale (L), "
                "palette (P), colour (RGB/RGBA/LA), and 32-bit float (F) modes."
            )
    except (UnidentifiedImageError, OSError):
        pass  # Pillow cannot open this file at all -- try tifffile below.

    with tifffile.TiffFile(path) as tif:
        page = tif.series[0].levels[0].pages[0]
        arr = page.asarray()

    if arr.ndim != 2:
        raise ValueError(
            f"Expected a 2D grayscale image for {path}, got shape {arr.shape}."
        )

    if arr.dtype == np.float16:
        return np.ascontiguousarray(arr.astype(np.float32)), "float16"
    if arr.dtype == np.float32:
        return np.ascontiguousarray(arr), "float32"
    if arr.dtype == np.uint8:
        return np.ascontiguousarray(arr), "uint8"
    if arr.dtype == np.uint16:
        return np.ascontiguousarray(arr), "uint16"

    raise ValueError(
        f"Unsupported TIFF sample format {arr.dtype} for {path} (read via the tifffile fallback)."
    )


def bridge_float_to_uint16(arr: np.ndarray, source_dtype: str = "float32") -> tuple[np.ndarray, dict]:
    """
    Explicit, disclosed linear rescale of a float32 source into uint16, for
    the existing display/crop/preview pipeline -- which is uint16
    throughout and is not being rewritten to be dtype-polymorphic here.

    uint16 = round(v * 65535 / source_max); 0 stays 0. Deliberately NOT a
    percentile stretch: tested on a real LI-COR file, a 0.1-99.9 percentile
    clip lost 183 band-peak pixels irreversibly, while this scale-only
    mapping clips nothing and preserves proportionality exactly. Initial
    display contrast is instead produced by the caller setting
    DisplaySettings.levels_black/white to the 0.1/99.9 percentiles of *this*
    bridged array -- an adjustable, non-destructive display parameter, not a
    step baked into the data itself.

    Edge cases -- never silent, always recorded in the returned dict:
    - source max <= 0 (all-zero or all-negative source): no division;
      scale_factor is None and every pixel maps to 0.
    - NaN/Inf: mapped to 0; their count is recorded (nonfinite_count).
    - negative values: clipped to 0 (uint16 cannot represent negative), but
      never silently -- source_min and the clipped-pixel count are recorded.

    Returns (uint16_array, scale_info). scale_info always has the same keys
    (method, source_dtype, source_min, source_max, scale_factor,
    nonfinite_count, negative_clipped_count), so its shape is predictable
    regardless of which edge cases fired.
    """
    if arr.dtype != np.float32:
        raise TypeError(f"Expected float32 source, got {arr.dtype}")

    finite_mask = np.isfinite(arr)
    nonfinite_count = int(arr.size - np.count_nonzero(finite_mask))

    if finite_mask.any():
        finite_vals = arr[finite_mask]
        source_min = float(finite_vals.min())
        source_max = float(finite_vals.max())
    else:
        source_min = None
        source_max = None

    # Nonfinite pixels carry no usable signal and must never enter the
    # scale-factor computation -- treat them as 0 from here on.
    work = np.where(finite_mask, arr, 0.0).astype(np.float64)

    negative_clipped_count = 0
    if source_min is not None and source_min < 0.0:
        negative_clipped_count = int(np.count_nonzero(finite_mask & (arr < 0.0)))
        work = np.clip(work, 0.0, None)

    if source_max is not None and source_max > 0.0:
        scale_factor = 65535.0 / source_max
        out = np.round(work * scale_factor)
    else:
        scale_factor = None
        out = np.zeros_like(work)

    out = np.clip(out, 0, 65535).astype(np.uint16)

    scale_info = {
        "method": "linear_scale_to_max",
        "source_dtype": source_dtype,
        "source_min": source_min,
        "source_max": source_max,
        "scale_factor": scale_factor,
        "nonfinite_count": nonfinite_count,
        "negative_clipped_count": negative_clipped_count,
    }
    return np.ascontiguousarray(out), scale_info


def get_source_bits(path: str | Path) -> int | None:
    """
    Return the TIFF BitsPerSample tag value for the source's full-resolution
    page, or None if unavailable (not a TIFF, tag absent, unreadable).

    For a float16 LI-COR source this is 16 -- the true on-disk sample width
    -- never the 32 that get_bit_depth() reports after promoting float16 to
    float32 in memory. Metadata-only: does not decode pixel data.
    """
    path = str(path)
    try:
        with tifffile.TiffFile(path) as tif:
            page = tif.series[0].levels[0].pages[0]
            tag = page.tags.get(258)  # BitsPerSample
            if tag is None:
                return None
            value = tag.value
            if isinstance(value, (tuple, list)):
                value = value[0]
            return int(value)
    except Exception:
        return None


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
    Load a grayscale image as uint16, accepting 8-bit, 16-bit, and float
    (16- or 32-bit) sources.

    - uint8/uint16 sources behave exactly as before: loaded directly, no
      promotion, no rescale. Existing imports are unaffected.
    - float sources are bridged into uint16 via bridge_float_to_uint16 (a
      linear scale to the source's own maximum). This is a DISPLAY-ONLY
      representation for the existing uint16 pipeline (levels, rotate, crop,
      preview cache, panel rendering, histogram); the true float values
      never reach this return value. Callers that need the true float array
      -- saturation assessment, provenance -- must call load_tiff_source
      directly and must not call this function.

    Always call on the original asset file, never on a preview or working copy.
    """
    arr, source_dtype = load_tiff_source(path)
    if is_float_source(source_dtype):
        bridged, _scale_info = bridge_float_to_uint16(arr, source_dtype)
        return bridged
    return arr if arr.dtype == np.uint16 else arr.astype(np.uint16)


def is_jpeg(path: str | Path) -> bool:
    """Return True if the file starts with JPEG magic bytes (FF D8), regardless of extension."""
    with open(str(path), "rb") as f:
        header = f.read(2)
    return header == b'\xff\xd8'


def get_bit_depth(path: str | Path) -> int:
    """
    Return the bit depth of the image at path: 8, 16, 32 (any float source,
    after float16 is promoted to float32 in memory), or 0 for unknown.

    Metadata-only -- does not decode pixel data, so this stays cheap enough
    to call on every UI refresh. For a float source's true on-disk sample
    width (16 for float16), see get_source_bits instead.

    Always call on the original asset file, never on a preview or working copy.
    """
    source_dtype = _detect_source_dtype_lazy(str(path))
    if source_dtype == "uint8":
        return 8
    if source_dtype == "uint16":
        return 16
    if source_dtype is not None and is_float_source(source_dtype):
        return 32
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
