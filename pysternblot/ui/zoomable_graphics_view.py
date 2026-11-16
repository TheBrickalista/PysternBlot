from __future__ import annotations

from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent, QPainter
from PySide6.QtCore import Qt, QPoint


class ZoomableGraphicsView(QGraphicsView):
    """Graphics view with shift+wheel zoom, drag-to-pan and a "fit mode".

    Fit mode: the view is in fit mode initially and after fit_scene() (Fit
    button, double-click). A user zoom or pan leaves it. set_scene_keep_view()
    replaces the scene and fits it in fit mode, or keeps the user's zoom and
    pan otherwise, so redraws do not throw the user's view away.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._zoom = 0
        self._panning = False
        self._pan_start = QPoint()
        self._fit_mode = True

        # Only user interaction with a scrollbar emits actionTriggered (not
        # setValue from fitting or scene changes), so it marks a user pan.
        self.horizontalScrollBar().actionTriggered.connect(self._leave_fit_mode)
        self.verticalScrollBar().actionTriggered.connect(self._leave_fit_mode)

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
            before = self._scroll_values()
            super().wheelEvent(event)
            if self._scroll_values() != before:
                self._leave_fit_mode()          # wheel scroll = user pan
            return

        zoom_in_factor = 1.10
        zoom_out_factor = 1.0 / zoom_in_factor

        if event.angleDelta().y() > 0:
            factor = zoom_in_factor
            self._zoom += 1
            if self._zoom > 20:
                self._zoom = 20
                return
        else:
            factor = zoom_out_factor
            self._zoom -= 1

        if self._zoom < -15:
            self._zoom = -15
            return

        self.scale(factor, factor)
        self._leave_fit_mode()                  # user zoom
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        before = self._scroll_values()
        super().keyPressEvent(event)
        if self._scroll_values() != before:
            self._leave_fit_mode()              # arrow / page keys = user pan

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
            if not delta.isNull():
                self._leave_fit_mode()          # drag = user pan

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
        self._fit_mode = True

    # ------------------------------------------------------------ fit mode
    @property
    def in_fit_mode(self) -> bool:
        return self._fit_mode

    def _leave_fit_mode(self, *_args) -> None:
        self._fit_mode = False

    def _scroll_values(self) -> tuple[int, int]:
        return self.horizontalScrollBar().value(), self.verticalScrollBar().value()

    def set_scene_keep_view(self, scene: QGraphicsScene, *, force_fit: bool = False) -> None:
        """Replace the scene. In fit mode (or with force_fit) fit the new
        scene; otherwise keep the current zoom and the scene point at the
        viewport centre, so a redraw does not reset the user's view."""
        if force_fit or self._fit_mode or self.scene() is None:
            self.setScene(scene)
            self.fit_scene()
            return

        old_rect = self.sceneRect()
        old_scroll = self._scroll_values()
        centre = self.mapToScene(self.viewport().rect().center())
        transform = self.transform()

        self.setScene(scene)
        self.setTransform(transform)            # zoom kept, so _zoom stays valid
        if self.sceneRect() == old_rect:
            # Same extent: restore the exact scroll position (no drift).
            self.horizontalScrollBar().setValue(old_scroll[0])
            self.verticalScrollBar().setValue(old_scroll[1])
        else:
            self.centerOn(centre)