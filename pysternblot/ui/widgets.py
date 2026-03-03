# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
from PySide6.QtWidgets import QComboBox
from PySide6.QtCore import Signal

class EditableHistoryCombo(QComboBox):
    """
    Editable combobox that:
    - lets user select a previous entry
    - lets user type a new entry
    - emits committed(text) when a value is chosen/entered
    """
    committed = Signal(str)

    def __init__(self, items: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        if items:
            self.set_items(items)

        # When user selects an item
        self.activated.connect(self._on_activated)
        # When user presses Enter in the line edit
        if self.lineEdit():
            self.lineEdit().editingFinished.connect(self._on_editing_finished)

    def set_items(self, items: list[str]):
        current = self.currentText()
        self.blockSignals(True)
        self.clear()
        for it in items:
            self.addItem(it)
        self.blockSignals(False)
        if current:
            self.setCurrentText(current)

    def _on_activated(self, _index: int):
        txt = self.currentText().strip()
        if txt:
            self.committed.emit(txt)

    def _on_editing_finished(self):
        txt = self.currentText().strip()
        if txt:
            self.committed.emit(txt)