from __future__ import annotations

from PySide6.QtWidgets import QGraphicsRectItem
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPen, QColor


class CropRectItem(QGraphicsRectItem):
    """
    Movable crop rectangle.

    - on_change(rect: QRectF): called often while dragging (scene rect)
    - on_commit(rect: QRectF): called once on mouse release (scene rect)
    """

    def __init__(self, rect: QRectF, on_change=None, on_commit=None):
        super().__init__(rect)
        self._on_change = on_change
        self._on_commit = on_commit

        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)

        self.setBrush(Qt.NoBrush)
        self.setPen(QPen(QColor(0, 0, 0), 2, Qt.DashLine))

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionHasChanged and self.scene() is not None:
            if callable(self._on_change):
                self._on_change(self.sceneBoundingRect())
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.scene() is None:
            return
        if callable(self._on_commit):
            self._on_commit(self.sceneBoundingRect())