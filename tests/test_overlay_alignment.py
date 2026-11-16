# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
The membrane overlay is drawn with the blot's flips (and rotation/levels).

Using the blot's own real-TIFF asset as its overlay makes the expected
result exact: for every flip combination, the overlay pixmap in the
Original Image scene must equal the blot pixmap, and an annotated context
TIFF exported with the overlay at full opacity must equal the same export
without an overlay.
"""

from __future__ import annotations

import os
import sys
from itertools import product

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem

from pysternblot.render import build_provenance_scene

from test_refresh_scope_staleness import ECL_A, NIR, _window as _real_tiff_window

FLIPS = list(product([False, True], repeat=2))          # (flip_h, flip_v)
FLIP_IDS = [f"h{int(h)}v{int(v)}" for h, v in FLIPS]


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _with_self_overlay(win, blot_id, flip_h, flip_v, *, alpha, rotation=1.5, channel=None):
    blot = next(b for b in win.current_project.panel.blots if b.id == blot_id)
    blot.overlay_asset_sha256 = blot.asset_sha256 if channel is None else \
        next(c for c in blot.channels if c.channel_index == channel).asset_sha256
    blot.display.overlay_visible = True
    blot.display.overlay_alpha = alpha
    display = blot.display if channel is None else \
        next(c for c in blot.channels if c.channel_index == channel).display
    display.flip_horizontal = flip_h
    display.flip_vertical = flip_v
    display.rotation_deg = rotation
    return blot


def _blot_and_overlay_images(scene, alpha):
    items = [i for i in scene.items() if isinstance(i, QGraphicsPixmapItem)]
    overlay = [i for i in items if i.opacity() == pytest.approx(alpha)]
    image = [i for i in items if i.opacity() == 1.0]
    assert len(overlay) == 1 and len(image) == 1, [i.opacity() for i in items]
    assert overlay[0].pos() == image[0].pos()
    return image[0].pixmap().toImage(), overlay[0].pixmap().toImage()


@pytest.mark.parametrize("flip_h,flip_v", FLIPS, ids=FLIP_IDS)
def test_overlay_pixmap_matches_blot_pixmap_for_every_flip(qapp, tmp_path, flip_h, flip_v):
    win = _real_tiff_window(tmp_path)
    blot = _with_self_overlay(win, ECL_A, flip_h, flip_v, alpha=0.35)

    # Uncached path (as the context TIFF export calls it) ...
    scene = build_provenance_scene(win.current_project, win.workspace.root, blot_id=blot.id)
    image, overlay = _blot_and_overlay_images(scene, 0.35)
    assert overlay == image
    # ... and the on-screen view (pixmap cache path).
    win.active_blot_id = blot.id
    image_v, overlay_v = _blot_and_overlay_images(win._build_provenance_scene_for_view(), 0.35)
    assert overlay_v == image_v == image


@pytest.mark.parametrize("flip_h,flip_v", [(True, False), (False, True), (True, True)],
                         ids=["h1v0", "h0v1", "h1v1"])
def test_overlay_follows_the_active_nir_channel_flips(qapp, tmp_path, flip_h, flip_v):
    win = _real_tiff_window(tmp_path)
    _with_self_overlay(win, NIR, flip_h, flip_v, alpha=0.35, rotation=-3.0, channel=1)
    scene = build_provenance_scene(win.current_project, win.workspace.root,
                                   blot_id=NIR, nir_channel_index=1)
    image, overlay = _blot_and_overlay_images(scene, 0.35)
    assert overlay == image


def _context_tiff(win, blot_id, path) -> QImage:
    win._export_provenance_scene_to_tiff(blot_id, str(path))
    img = QImage(str(path))
    assert not img.isNull()
    return img


@pytest.mark.parametrize("flip_h,flip_v", [(True, False), (False, True), (True, True)],
                         ids=["h1v0", "h0v1", "h1v1"])
def test_context_tiff_overlay_region_matches_blot_with_flip(qapp, tmp_path, flip_h, flip_v):
    # Overlay at full opacity covers the blot: if it is aligned (and it is the
    # same image), the export equals the export without an overlay.
    win = _real_tiff_window(tmp_path)
    blot = _with_self_overlay(win, ECL_A, flip_h, flip_v, alpha=1.0)
    with_overlay = _context_tiff(win, blot.id, tmp_path / "with.tif")

    blot.overlay_asset_sha256 = None
    without_overlay = _context_tiff(win, blot.id, tmp_path / "without.tif")

    assert with_overlay.size() == without_overlay.size()
    assert with_overlay == without_overlay
