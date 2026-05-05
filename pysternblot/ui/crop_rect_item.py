from __future__ import annotations

from PySide6.QtWidgets import QGraphicsRectItem
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QBrush


class CropRectItem(QGraphicsRectItem):
    """
    Movable + resizable crop rectangle.

    - Drag inside to move
    - Drag edges/corners to resize
    - Calls on_change(scene_rect: QRectF) whenever geometry changes
    - Calls on_commit(scene_rect: QRectF) on mouse release (end of interaction)

    Backward compatibility:
      - callback= behaves like on_change=
    """

    HANDLE_SIZE = 8.0  # px in scene coords (approx)

    # handle identifiers
    NONE = 0
    MOVE = 1
    TL = 2
    T = 3
    TR = 4
    R = 5
    BR = 6
    B = 7
    BL = 8
    L = 9

    def __init__(self, rect: QRectF, callback=None, *, on_change=None, on_commit=None,
                 on_move_commit=None, on_resize_commit=None):
        super().__init__(rect)

        # Backward compat + new API
        self._on_change = on_change if on_change is not None else callback
        self._on_commit = on_commit
        self._on_move_commit = on_move_commit
        self._on_resize_commit = on_resize_commit

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)

        self.setPen(QPen(Qt.black, 2, Qt.DashLine))
        self.setBrush(QBrush(Qt.transparent))

        self._active_handle = self.NONE
        self._press_scene_pos = QPointF()
        self._press_rect = QRectF()

        self._min_w = 10.0
        self._min_h = 10.0

    # ---------- internal helpers ----------

    def _emit_change(self):
        if callable(self._on_change):
            self._on_change(self.sceneBoundingRect())

    def _emit_commit(self):
        if callable(self._on_commit):
            self._on_commit(self.sceneBoundingRect())

    # ---------- handle geometry helpers ----------

    def _handle_rects(self) -> dict[int, QRectF]:
        r = self.rect()
        hs = self.HANDLE_SIZE
        x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

        def box(x, y):
            return QRectF(x - hs / 2.0, y - hs / 2.0, hs, hs)

        return {
            self.TL: box(x0, y0),
            self.T:  box(cx, y0),
            self.TR: box(x1, y0),
            self.R:  box(x1, cy),
            self.BR: box(x1, y1),
            self.B:  box(cx, y1),
            self.BL: box(x0, y1),
            self.L:  box(x0, cy),
        }

    def _pick_handle(self, pos_item: QPointF) -> int:
        for hid, hr in self._handle_rects().items():
            if hr.contains(pos_item):
                return hid
        if self.rect().contains(pos_item):
            return self.MOVE
        return self.NONE

    def _update_cursor(self, handle: int):
        if handle in (self.TL, self.BR):
            self.setCursor(Qt.SizeFDiagCursor)
        elif handle in (self.TR, self.BL):
            self.setCursor(Qt.SizeBDiagCursor)
        elif handle in (self.T, self.B):
            self.setCursor(Qt.SizeVerCursor)
        elif handle in (self.L, self.R):
            self.setCursor(Qt.SizeHorCursor)
        elif handle == self.MOVE:
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()

    # ---------- Qt overrides ----------

    def hoverMoveEvent(self, event):
        handle = self._pick_handle(event.pos())
        self._update_cursor(handle)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._active_handle = self._pick_handle(event.pos())
            self._press_scene_pos = event.scenePos()
            self._press_rect = QRectF(self.rect())

            # If resizing, disable the built-in move handling
            if self._active_handle != self.MOVE:
                self.setFlag(QGraphicsRectItem.ItemIsMovable, False)
            else:
                self.setFlag(QGraphicsRectItem.ItemIsMovable, True)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._active_handle in (self.NONE, self.MOVE):
            super().mouseMoveEvent(event)
            return

        # resizing
        delta = event.scenePos() - self._press_scene_pos
        r = QRectF(self._press_rect)

        dx, dy = float(delta.x()), float(delta.y())

        if self._active_handle in (self.TL, self.L, self.BL):
            r.setLeft(r.left() + dx)
        if self._active_handle in (self.TR, self.R, self.BR):
            r.setRight(r.right() + dx)
        if self._active_handle in (self.TL, self.T, self.TR):
            r.setTop(r.top() + dy)
        if self._active_handle in (self.BL, self.B, self.BR):
            r.setBottom(r.bottom() + dy)

        # enforce minimum size
        if r.width() < self._min_w:
            if self._active_handle in (self.TL, self.L, self.BL):
                r.setLeft(r.right() - self._min_w)
            else:
                r.setRight(r.left() + self._min_w)

        if r.height() < self._min_h:
            if self._active_handle in (self.TL, self.T, self.TR):
                r.setTop(r.bottom() - self._min_h)
            else:
                r.setBottom(r.top() + self._min_h)

        self.prepareGeometryChange()
        self.setRect(r)

        # live callback in scene coordinates
        self._emit_change()

        event.accept()

    def mouseReleaseEvent(self, event):
        # Restore movable after resizing
        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)

        was_move = self._active_handle == self.MOVE

        # one last live update + commit at end
        self._emit_change()
        self._emit_commit()

        # dispatch to specific commit callbacks if provided
        rect = self.sceneBoundingRect()
        if was_move:
            if callable(self._on_move_commit):
                self._on_move_commit(rect)
        else:
            if callable(self._on_resize_commit):
                self._on_resize_commit(rect)

        self._active_handle = self.NONE
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        # moving triggers this
        if change == QGraphicsRectItem.ItemPositionHasChanged:
            self._emit_change()
        return super().itemChange(change, value)