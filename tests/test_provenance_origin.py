# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
render.PROVENANCE_IMAGE_ORIGIN is the single source for where the image sits
in the Original Image scene. With the constant patched to another value,
a click still records the same image y for a ladder band, and the image,
crop rectangle and band marker still line up.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsPixmapItem

from pysternblot import render
from pysternblot.ui.crop_rect_item import CropRectItem

from test_view_zoom_preserved import _shown, _show_tab_of

IMAGE_X, IMAGE_Y = 520, 413          # an image pixel inside Chemi_16 (1200 x 1648)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_default_origin_is_unchanged():
    assert render.PROVENANCE_IMAGE_ORIGIN == (10.0, 10.0)


@pytest.mark.parametrize("origin", [(10.0, 10.0), (37.0, 53.0)], ids=["default", "patched"])
def test_click_and_items_follow_the_origin(qapp, tmp_path, origin):
    with patch.object(render, "PROVENANCE_IMAGE_ORIGIN", origin):
        win = _shown(tmp_path)
        _show_tab_of(win, win.prov_view)
        blot = win._get_active_blot()
        kda = float(win.marker_set_library.items[0].bands[0].kda)
        win._save_overlay_ladder_options()       # overlay ladder on, scene rebuilt
        ox, oy = origin

        # Image and crop rectangle positions.
        scene = win.prov_view.scene()
        (image,) = [i for i in scene.items()
                    if isinstance(i, QGraphicsPixmapItem) and i.opacity() == 1.0]
        assert (image.pos().x(), image.pos().y()) == (ox, oy)
        (crop_item,) = [i for i in scene.items() if isinstance(i, CropRectItem)]
        r = crop_item.crop_scene_rect()
        assert (r.x(), r.y()) == (ox + blot.crop.x, oy + blot.crop.y)

        # A real click at image pixel (IMAGE_X, IMAGE_Y) records y_px == IMAGE_Y.
        view = win.prov_view
        view.resetTransform()                    # 1 viewport px == 1 scene unit
        view.centerOn(ox + IMAGE_X, oy + IMAGE_Y)
        win.pending_overlay_ladder_kda = kda
        vp = view.mapFromScene(QPointF(ox + IMAGE_X, oy + IMAGE_Y))
        assert view.mapToScene(vp) == QPointF(ox + IMAGE_X, oy + IMAGE_Y)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, vp)
        (band,) = win._get_active_blot().overlay_ladder.bands
        assert band.y_px == float(IMAGE_Y)
        assert win.pending_overlay_ladder_kda is None

        # The band's tick in the rebuilt scene is drawn at origin + y_px.
        scene = win.prov_view.scene()
        ticks = [i for i in scene.items() if isinstance(i, QGraphicsLineItem)
                 and i.line().y1() == i.line().y2() == oy + band.y_px]
        assert ticks, "band marker not at origin + y_px"
        tick = ticks[0].line()
        assert max(tick.x1(), tick.x2()) <= ox         # left of the image (side="left")

        # A crop move still maps back to image pixels.
        (crop_item,) = [i for i in scene.items() if isinstance(i, CropRectItem)]
        x_before, y_before = blot.crop.x, blot.crop.y
        crop_item.moveBy(11.0, -7.0)
        crop_item._on_move_commit(crop_item.crop_scene_rect())
        assert (blot.crop.x, blot.crop.y) == (x_before + 11.0, y_before - 7.0)
