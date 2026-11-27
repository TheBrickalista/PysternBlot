# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Final-figure PDF meets Pyblication's panel contract (ARCHITECTURE.md §7):

  - page = the figure's scene rect (whole points, zero margins), one page;
  - every image XObject lossless (FlateDecode, never DCTDecode), 8-bit,
    at the native pixel size of the crop the figure draws, no soft mask;
  - text live, embedded TrueType (/FontFile2), never Type 3;
  - no transparency;
  - the SVG export declares the same physical size (mm) as the PDF page.

CI has no poppler, so the PDF bytes are inspected directly: Qt writes its
object dictionaries uncompressed (only streams are Flate-compressed).
A control test writes the same scene the old way (A4, margin, no lossless
hint) and checks that these assertions do catch it.
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication

from pysternblot.models import AssetEntry, Blot, BlotChannel, Crop, CropTemplate, ProteinLabel
from pysternblot.render import build_panel_scene
from pysternblot.ui.export_mixin import _figure_size_pt

from test_source_export import (
    _encode_png_uint16,
    _make_main_window,
    _minimal_ladder,
    _minimal_project,
    _patched_dialogs,
    _write_asset,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# Fixtures: an ECL blot with a non-square crop, a two-channel NIR blot
# ---------------------------------------------------------------------------

def _gradient_asset(ws_dir: Path, h: int, w: int, offset: int) -> str:
    yy, xx = np.mgrid[0:h, 0:w]
    arr = ((xx * 211 + yy * 97 + offset) % 60000 + 1000).astype(np.uint16)
    return _write_asset(ws_dir, _encode_png_uint16(arr), ".png")


def _asset_entry(ws_dir, sha):
    return AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.png"))


def _ecl_window(tmp_path):
    ws_dir = tmp_path / "ws"
    sha = _gradient_asset(ws_dir, 90, 150, 0)
    blot = Blot(
        id="blot_pdf", asset_sha256=sha, crop=Crop(x=10, y=20, w=123.0, h=41.0),
        ladder=_minimal_ladder(), protein_label=ProteinLabel(text="Actin"),
    )
    project = _minimal_project([blot], assets={sha: _asset_entry(ws_dir, sha)})
    project.panel.crop_template = CropTemplate(w=123.0, h=41.0)
    win = _make_main_window(tmp_path, project)
    win.active_blot_id = blot.id
    previews = [ws_dir / "assets" / sha / f"preview_crop_{blot.id}.tif"]
    return win, project, previews


def _nir_window(tmp_path):
    ws_dir = tmp_path / "ws"
    sha_a = _gradient_asset(ws_dir, 80, 120, 0)
    sha_b = _gradient_asset(ws_dir, 80, 120, 5000)
    blot = Blot(
        id="nir_pdf", asset_sha256=sha_a, crop=Crop(x=4, y=6, w=97.0, h=33.0),
        ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        modality="nir_fluorescence",
        channels=[
            BlotChannel(asset_sha256=sha_a, channel_index=0, wavelength_nm=685),
            BlotChannel(asset_sha256=sha_b, channel_index=1, wavelength_nm=785),
        ],
    )
    project = _minimal_project([blot], assets={s: _asset_entry(ws_dir, s) for s in (sha_a, sha_b)})
    project.panel.crop_template = CropTemplate(w=97.0, h=33.0)
    win = _make_main_window(tmp_path, project)
    win.active_blot_id = blot.id
    previews = [
        ws_dir / "assets" / sha_a / f"preview_crop_{blot.id}_ch0.tif",
        ws_dir / "assets" / sha_b / f"preview_crop_{blot.id}_ch1.tif",
    ]
    return win, project, previews


def _export(win, method: str, dest: Path) -> None:
    p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
    with p1, p2, p3, p4 as critical_mock:
        getattr(win, method)()
    assert not critical_mock.called, f"export raised: {critical_mock.call_args}"
    assert dest.exists()


def _native_sizes(previews: list[Path]) -> list[tuple[int, int]]:
    """(width, height) of each crop the figure draws, from the preview files
    the export itself regenerated."""
    sizes = []
    for p in previews:
        h, w = tifffile.imread(p).shape[:2]
        sizes.append((w, h))
    return sorted(sizes)


def _scene_size_pt(win, project) -> tuple[int, int]:
    scene = build_panel_scene(project, win.workspace.root)
    return _figure_size_pt(scene.itemsBoundingRect())


# ---------------------------------------------------------------------------
# PDF byte inspection
# ---------------------------------------------------------------------------

_DICT = rb"<<(?:[^<>]|<<[^<>]*>>)*>>"


def _image_dicts(pdf: bytes) -> list[bytes]:
    return [m.group(0) for m in re.finditer(_DICT, pdf) if re.search(rb"/Subtype\s*/Image\b", m.group(0))]


def _int(key: bytes, d: bytes) -> int:
    return int(re.search(rb"/" + key + rb"\s+(\d+)", d).group(1))


def _image_sizes(pdf: bytes) -> list[tuple[int, int]]:
    return sorted((_int(b"Width", d), _int(b"Height", d)) for d in _image_dicts(pdf))


def _media_boxes(pdf: bytes) -> list[tuple[float, ...]]:
    return [tuple(float(v) for v in m.group(1).split())
            for m in re.finditer(rb"/MediaBox\s*\[([^\]]*)\]", pdf)]


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf))


def _check_contract(pdf: bytes, native: list[tuple[int, int]], size_pt: tuple[int, int]) -> None:
    assert b"/DCTDecode" not in pdf, "an image is JPEG-encoded"
    images = _image_dicts(pdf)
    assert images, "no image XObject"
    for d in images:
        assert re.search(rb"/Filter\s*/FlateDecode", d), d
        assert _int(b"BitsPerComponent", d) == 8, d
        assert re.search(rb"/ColorSpace\s*/Device(RGB|Gray)", d), d
        assert b"/SMask" not in d, f"image has a soft mask: {d!r}"
    assert _image_sizes(pdf) == native
    assert _pages(pdf) == 1
    assert _media_boxes(pdf) == [(0.0, 0.0, float(size_pt[0]), float(size_pt[1]))]


# ===========================================================================
# PDF
# ===========================================================================

@pytest.mark.parametrize("make", [_ecl_window, _nir_window], ids=["ecl", "nir_two_channels"])
def test_pdf_meets_panel_contract(qapp, tmp_path, make):
    win, project, previews = make(tmp_path)
    dest = tmp_path / "figure.pdf"
    _export(win, "export_final_pdf", dest)
    pdf = dest.read_bytes()

    native = _native_sizes(previews)
    assert len(native) == len(previews)
    _check_contract(pdf, native, _scene_size_pt(win, project))


def test_pdf_crops_are_native_and_non_square(qapp, tmp_path):
    # The fixture's crop is 123 x 41: a resampled or rescaled image would show.
    win, project, previews = _ecl_window(tmp_path)
    dest = tmp_path / "figure.pdf"
    _export(win, "export_final_pdf", dest)
    assert _image_sizes(dest.read_bytes()) == [(123, 41)]


def test_pdf_fonts_embedded_truetype_never_type3(qapp, tmp_path):
    win, _project, _ = _ecl_window(tmp_path)
    dest = tmp_path / "figure.pdf"
    _export(win, "export_final_pdf", dest)
    pdf = dest.read_bytes()
    assert b"/FontFile2" in pdf
    assert b"/Type3" not in pdf
    assert b"/FontFile3" not in pdf


def test_pdf_has_no_transparency(qapp, tmp_path):
    win, _project, _ = _nir_window(tmp_path)
    dest = tmp_path / "figure.pdf"
    _export(win, "export_final_pdf", dest)
    pdf = dest.read_bytes()
    for value in re.findall(rb"/(?:CA|ca)\s+([0-9.]+)", pdf):
        assert float(value) == 1.0
    for m in re.finditer(rb"/SMask\s*(/\w+|\d+ \d+ R)", pdf):
        assert m.group(1) == b"/None"


# ===========================================================================
# SVG has the same physical size
# ===========================================================================

def _svg_size(svg: str) -> tuple[float, float, list[float]]:
    head = svg[svg.index("<svg"):]
    head = head[: head.index(">")]
    w = float(re.search(r'\bwidth="([0-9.]+)mm"', head).group(1))
    h = float(re.search(r'\bheight="([0-9.]+)mm"', head).group(1))
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', head).group(1).split()]
    return w, h, vb


@pytest.mark.parametrize("make", [_ecl_window, _nir_window], ids=["ecl", "nir_two_channels"])
def test_svg_and_pdf_have_the_same_size_in_mm(qapp, tmp_path, make):
    win, project, _ = make(tmp_path)
    pdf_path, svg_path = tmp_path / "figure.pdf", tmp_path / "figure.svg"
    _export(win, "export_final_pdf", pdf_path)
    _export(win, "export_final_svg", svg_path)

    (box,) = _media_boxes(pdf_path.read_bytes())
    w_mm, h_mm, viewbox = _svg_size(svg_path.read_text(encoding="utf-8"))
    assert w_mm == pytest.approx(box[2] * 25.4 / 72, abs=0.01)
    assert h_mm == pytest.approx(box[3] * 25.4 / 72, abs=0.01)
    assert viewbox == [0.0, 0.0, box[2], box[3]]
    assert (box[2], box[3]) == _scene_size_pt(win, project)


def test_figure_size_rounds_up_to_whole_points():
    assert _figure_size_pt(QRectF(0, 0, 1079.6875, 301.5)) == (1080, 302)
    assert _figure_size_pt(QRectF(-5, -3, 200.0, 100.0)) == (200, 100)


# ===========================================================================
# Control: the old export settings fail these checks
# ===========================================================================

def _write_old_style_pdf(scene, rect, path: str) -> None:
    """The export as it was before this fix: A4, 20-unit margin, fit to the
    page, no LosslessImageRendering hint."""
    margin = 20
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(300)
    painter = QPainter(writer)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    page_rect = writer.pageLayout().paintRectPixels(writer.resolution())
    scale = min(page_rect.width() / (rect.width() + 2 * margin),
                page_rect.height() / (rect.height() + 2 * margin))
    painter.scale(scale, scale)
    scene.render(painter, QRectF(margin, margin, rect.width(), rect.height()), rect)
    painter.end()


def test_control_old_export_settings_fail_the_checks(qapp, tmp_path):
    win, project, previews = _ecl_window(tmp_path)
    scene, rect = win._final_scene_and_rect()       # regenerates the previews
    path = tmp_path / "old.pdf"
    _write_old_style_pdf(scene, rect, str(path))
    pdf = path.read_bytes()

    assert b"/DCTDecode" in pdf
    (box,) = _media_boxes(pdf)
    assert (round(box[2]), round(box[3])) == (595, 842)
    with pytest.raises(AssertionError):
        _check_contract(pdf, _native_sizes(previews), _figure_size_pt(rect))
