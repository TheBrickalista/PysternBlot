# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for CropRectItem handle hit detection, visual/hit size separation, and resize math."""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QPen
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

from pysternblot.ui.crop_rect_item import CropRectItem


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def item(qapp):
    rect = QRectF(0, 0, 200, 100)
    return CropRectItem(rect)


# ---------------------------------------------------------------------------
# 1. Sizes
# ---------------------------------------------------------------------------

class TestHandleSizes:
    def test_hit_larger_than_visual(self):
        assert CropRectItem.HANDLE_HIT > CropRectItem.HANDLE_VISUAL

    def test_handle_size_alias_equals_visual(self):
        assert CropRectItem.HANDLE_SIZE == CropRectItem.HANDLE_VISUAL


# ---------------------------------------------------------------------------
# 2. Hit tolerance — corners
# ---------------------------------------------------------------------------

class TestHitToleranceCorner:

    def _offset_point(self, rect: QRectF, corner: int, offset: float) -> QPointF:
        """Return a point `offset` px away from the exact corner in both axes."""
        if corner == CropRectItem.TL:
            return QPointF(rect.left() - offset, rect.top() - offset)
        if corner == CropRectItem.TR:
            return QPointF(rect.right() + offset, rect.top() - offset)
        if corner == CropRectItem.BR:
            return QPointF(rect.right() + offset, rect.bottom() + offset)
        if corner == CropRectItem.BL:
            return QPointF(rect.left() - offset, rect.bottom() + offset)
        raise ValueError(corner)

    @pytest.mark.parametrize("corner", [
        CropRectItem.TL, CropRectItem.TR, CropRectItem.BR, CropRectItem.BL,
    ])
    def test_9px_offset_inside_hit_box(self, item, corner):
        # 9px is outside old 8px visual box but inside new 20px hit box
        pt = self._offset_point(item.rect(), corner, 9.0)
        assert item._pick_handle(pt) == corner

    @pytest.mark.parametrize("corner", [
        CropRectItem.TL, CropRectItem.TR, CropRectItem.BR, CropRectItem.BL,
    ])
    def test_11px_offset_outside_hit_box(self, item, corner):
        # 11px exceeds the 10px half-radius of the 20px hit box
        pt = self._offset_point(item.rect(), corner, 11.0)
        assert item._pick_handle(pt) != corner


# ---------------------------------------------------------------------------
# 3. Hit tolerance — edges
# ---------------------------------------------------------------------------

class TestHitToleranceEdge:

    def _midpoint_offset(self, rect: QRectF, edge: int, offset: float) -> QPointF:
        cx = (rect.left() + rect.right()) / 2.0
        cy = (rect.top() + rect.bottom()) / 2.0
        if edge == CropRectItem.T:
            return QPointF(cx, rect.top() - offset)
        if edge == CropRectItem.B:
            return QPointF(cx, rect.bottom() + offset)
        if edge == CropRectItem.L:
            return QPointF(rect.left() - offset, cy)
        if edge == CropRectItem.R:
            return QPointF(rect.right() + offset, cy)
        raise ValueError(edge)

    @pytest.mark.parametrize("edge", [
        CropRectItem.T, CropRectItem.B, CropRectItem.L, CropRectItem.R,
    ])
    def test_9px_offset_inside_hit_box(self, item, edge):
        pt = self._midpoint_offset(item.rect(), edge, 9.0)
        assert item._pick_handle(pt) == edge

    @pytest.mark.parametrize("edge", [
        CropRectItem.T, CropRectItem.B, CropRectItem.L, CropRectItem.R,
    ])
    def test_11px_offset_outside_hit_box(self, item, edge):
        pt = self._midpoint_offset(item.rect(), edge, 11.0)
        assert item._pick_handle(pt) != edge


# ---------------------------------------------------------------------------
# 4. MOVE zone
# ---------------------------------------------------------------------------

class TestMoveZone:
    def test_center_returns_move(self, item):
        r = item.rect()
        center = QPointF((r.left() + r.right()) / 2.0, (r.top() + r.bottom()) / 2.0)
        assert item._pick_handle(center) == CropRectItem.MOVE

    def test_interior_away_from_handles_returns_move(self, item):
        # A point well inside, away from any edge
        pt = QPointF(item.rect().left() + 30, item.rect().top() + 30)
        assert item._pick_handle(pt) == CropRectItem.MOVE


# ---------------------------------------------------------------------------
# 5. NONE zone
# ---------------------------------------------------------------------------

class TestNoneZone:
    def test_far_outside_returns_none(self, item):
        pt = QPointF(-500, -500)
        assert item._pick_handle(pt) == CropRectItem.NONE

    def test_just_outside_handle_and_rect_returns_none(self, item):
        # 15px past corner is outside both rect and hit zone (half-hit = 10px)
        r = item.rect()
        pt = QPointF(r.left() - 15, r.top() - 15)
        assert item._pick_handle(pt) == CropRectItem.NONE


# ---------------------------------------------------------------------------
# 6 & 7. Resize math via mouse events
# ---------------------------------------------------------------------------

def _make_mouse_event(event_type: QEvent.Type, scene_pos: QPointF, button=Qt.LeftButton):
    ev = QGraphicsSceneMouseEvent(event_type)
    ev.setScenePos(scene_pos)
    ev.setLastScenePos(scene_pos)
    ev.setPos(scene_pos)
    ev.setLastPos(scene_pos)
    ev.setButton(button)
    if event_type == QEvent.Type.GraphicsSceneMouseRelease:
        ev.setButtons(Qt.NoButton)
    else:
        ev.setButtons(button)
    return ev


class TestResizeMath:

    def test_tl_corner_resize_expands_top_left(self, item):
        """Drag TL corner by (-10, -10) → rect grows 10px wider and 10px taller."""
        r = item.rect()  # QRectF(0, 0, 200, 100)
        tl_scene = QPointF(r.left(), r.top())  # (0, 0)

        press_ev = _make_mouse_event(QEvent.Type.GraphicsSceneMousePress, tl_scene)
        item.mousePressEvent(press_ev)

        move_target = QPointF(tl_scene.x() - 10, tl_scene.y() - 10)
        move_ev = _make_mouse_event(QEvent.Type.GraphicsSceneMouseMove, move_target)
        item.mouseMoveEvent(move_ev)

        result = item.rect()
        assert abs(result.width() - (r.width() + 10)) < 0.5
        assert abs(result.height() - (r.height() + 10)) < 0.5

    def test_r_edge_resize_increases_width_only(self, item):
        """Drag R edge by (+20, 0) → width grows 20px, height unchanged."""
        item.setRect(QRectF(0, 0, 200, 100))
        r = item.rect()
        cy = (r.top() + r.bottom()) / 2.0
        r_edge_scene = QPointF(r.right(), cy)  # (200, 50)

        press_ev = _make_mouse_event(QEvent.Type.GraphicsSceneMousePress, r_edge_scene)
        item.mousePressEvent(press_ev)

        move_target = QPointF(r_edge_scene.x() + 20, r_edge_scene.y())
        move_ev = _make_mouse_event(QEvent.Type.GraphicsSceneMouseMove, move_target)
        item.mouseMoveEvent(move_ev)

        result = item.rect()
        assert abs(result.width() - (r.width() + 20)) < 0.5
        assert abs(result.height() - r.height()) < 0.5
