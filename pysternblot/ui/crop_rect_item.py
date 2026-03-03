from PySide6.QtWidgets import QGraphicsRectItem
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPen


class CropRectItem(QGraphicsRectItem):
    """
    Movable crop rectangle.
    Emits changed signal when moved.
    """

    def __init__(self, rect: QRectF, callback):
        super().__init__(rect)
        self._callback = callback  # function(new_rect: QRectF)

        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)

        self.setPen(QPen(Qt.black, 2))

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionHasChanged:
            r = self.sceneBoundingRect()
            self._callback(r)
        return super().itemChange(change, value)