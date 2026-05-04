from __future__ import annotations

from PySide6.QtWidgets import QGraphicsView
from PySide6.QtGui import QMouseEvent, QWheelEvent, QPainter
from PySide6.QtCore import Qt, QPoint


class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._zoom = 0
        self._panning = False
        self._pan_start = QPoint()

        self.setRenderHints(
            QPainter.Antialiasing |
            QPainter.SmoothPixmapTransform |
            QPainter.TextAntialiasing
        )

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)

    # Shift + wheel = zoom
    # Wheel alone = normal scroll
    def wheelEvent(self, event: QWheelEvent):
        if self.scene() is None:
            super().wheelEvent(event)
            return

        if not (event.modifiers() & Qt.ShiftModifier):
            super().wheelEvent(event)
            return

        zoom_in_factor = 1.10
        zoom_out_factor = 1.0 / zoom_in_factor

        if event.angleDelta().y() > 0:
            factor = zoom_in_factor
            self._zoom += 1
        else:
            factor = zoom_out_factor
            self._zoom -= 1

        if self._zoom < -15:
            self._zoom = -15
            return

        self.scale(factor, factor)
        event.accept()

    # Left-drag empty area = pan
    # Left-drag crop handles/items still works because itemAt catches them
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())

            if item is None:
                self._panning = True
                self._pan_start = event.pos()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()

            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._panning and event.button() == Qt.LeftButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.fit_scene()
        event.accept()

    def fit_scene(self):
        if self.scene() is None:
            return

        rect = self.scene().itemsBoundingRect()
        if rect.isValid() and not rect.isNull():
            self.resetTransform()
            self._zoom = 0
            self.fitInView(rect, Qt.KeepAspectRatio)