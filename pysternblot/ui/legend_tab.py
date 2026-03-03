# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal

from .widgets import EditableHistoryCombo
from ..models import LegendRow

class LegendTab(QWidget):
    """
    Legend tab editor:
    - top controls: mode, # upper rows, # lower rows
    - row editors: left + N cells + right + per-row N
    - emits changed() whenever it updates the project
    """
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._project = None
        self._get_suggestions = lambda: []
        self._add_suggestion = lambda s: None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # --- top strip ---
        top = QHBoxLayout()
        root.addLayout(top)

        top.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Protein", "protein")
        self.mode_combo.addItem("DNA", "dna")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        top.addWidget(self.mode_combo)

        top.addSpacing(12)

        top.addWidget(QLabel("# Upper rows"))
        self.upper_spin = QSpinBox()
        self.upper_spin.setRange(0, 30)
        self.upper_spin.valueChanged.connect(self._on_upper_count_changed)
        top.addWidget(self.upper_spin)

        top.addSpacing(12)

        top.addWidget(QLabel("# Lower rows"))
        self.lower_spin = QSpinBox()
        self.lower_spin.setRange(0, 30)
        self.lower_spin.valueChanged.connect(self._on_lower_count_changed)
        top.addWidget(self.lower_spin)

        top.addStretch(1)

        # --- scroll area for row editors ---
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        root.addWidget(self.scroll, 1)

        self.inner = QWidget()
        self.scroll.setWidget(self.inner)
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(0, 10, 0, 0)
        self.inner_layout.setSpacing(12)

        # containers for dynamic row widgets
        self._upper_row_widgets = []
        self._lower_row_widgets = []

    def bind(self, project, get_suggestions, add_suggestion):
        """
        Bind a Project and suggestion handlers.
        - get_suggestions(): list[str]
        - add_suggestion(str): None
        """
        self._project = project
        self._get_suggestions = get_suggestions
        self._add_suggestion = add_suggestion
        self.reload_from_project()

    def reload_from_project(self):
        if not self._project:
            return

        leg = self._project.panel.legend

        # set top controls without triggering rebuild loops
        self.mode_combo.blockSignals(True)
        idx = self.mode_combo.findData(leg.mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.blockSignals(False)

        self.upper_spin.blockSignals(True)
        self.upper_spin.setValue(len(leg.upper_rows))
        self.upper_spin.blockSignals(False)

        self.lower_spin.blockSignals(True)
        self.lower_spin.setValue(len(leg.lower_rows))
        self.lower_spin.blockSignals(False)

        self._rebuild_rows()

    # -------------------------
    # Row building
    # -------------------------

    def _clear_inner(self):
        # remove all widgets in inner_layout
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        self._upper_row_widgets = []
        self._lower_row_widgets = []

    def _rebuild_rows(self):
        if not self._project:
            return

        self._clear_inner()
        leg = self._project.panel.legend

        if leg.upper_rows:
            self.inner_layout.addWidget(self._section_label("Upper rows"))
            for i, row in enumerate(leg.upper_rows):
                w = LegendRowEditor(
                    title=f"Row {i+1}",
                    row=row,
                    get_suggestions=self._get_suggestions,
                    add_suggestion=self._add_suggestion,
                    on_row_changed=lambda: self._commit_and_emit(),
                )
                self._upper_row_widgets.append(w)
                self.inner_layout.addWidget(w)

        if leg.lower_rows:
            self.inner_layout.addWidget(self._section_label("Lower rows"))
            for i, row in enumerate(leg.lower_rows):
                w = LegendRowEditor(
                    title=f"Row {i+1}",
                    row=row,
                    get_suggestions=self._get_suggestions,
                    add_suggestion=self._add_suggestion,
                    on_row_changed=lambda: self._commit_and_emit(),
                )
                self._lower_row_widgets.append(w)
                self.inner_layout.addWidget(w)

        self.inner_layout.addStretch(1)

    def _section_label(self, text: str) -> QWidget:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight:600;")
        return lbl

    # -------------------------
    # Top controls handlers
    # -------------------------

    def _on_mode_changed(self, _idx: int):
        if not self._project:
            return
        self._project.panel.legend.mode = self.mode_combo.currentData()
        self._commit_and_emit()

    def _on_upper_count_changed(self, n: int):
        if not self._project:
            return
        rows = self._project.panel.legend.upper_rows
        self._resize_rows(rows, n)
        self._rebuild_rows()
        self._commit_and_emit()

    def _on_lower_count_changed(self, n: int):
        if not self._project:
            return
        rows = self._project.panel.legend.lower_rows
        self._resize_rows(rows, n)
        self._rebuild_rows()
        self._commit_and_emit()

    def _resize_rows(self, rows: list, n: int):
        while len(rows) < n:
            rows.append(LegendRow(left="", cells=[], right=""))
        while len(rows) > n:
            rows.pop()

    def _commit_and_emit(self):
        # Row editors directly mutate the row models; we just notify.
        self.changed.emit()


class LegendRowEditor(QFrame):
    def __init__(self, title: str, row: LegendRow, get_suggestions, add_suggestion, on_row_changed):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        self.row = row
        self.get_suggestions = get_suggestions
        self.add_suggestion = add_suggestion
        self.on_row_changed = on_row_changed

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        outer.addLayout(header)
        header.addWidget(QLabel(title))
        header.addStretch(1)

        header.addWidget(QLabel("# cells"))
        self.n_cells = QSpinBox()
        self.n_cells.setRange(0, 30)
        self.n_cells.setValue(len(self.row.cells))
        self.n_cells.valueChanged.connect(self._on_n_cells_changed)
        header.addWidget(self.n_cells)

        # main row layout: Left | cells... | Right
        self.row_layout = QHBoxLayout()
        self.row_layout.setSpacing(8)
        outer.addLayout(self.row_layout)

        self.left_combo = self._make_combo(self.row.left)
        self.row_layout.addWidget(QLabel("Left"))
        self.row_layout.addWidget(self.left_combo, 1)

        self.cells_container = QHBoxLayout()
        self.cells_container.setSpacing(6)
        self.row_layout.addSpacing(8)
        self.row_layout.addWidget(QLabel("Center"))
        self.row_layout.addLayout(self.cells_container, 4)

        self.right_combo = self._make_combo(self.row.right)
        self.row_layout.addSpacing(8)
        self.row_layout.addWidget(QLabel("Right"))
        self.row_layout.addWidget(self.right_combo, 1)

        self._rebuild_cells()

    def _make_combo(self, initial: str) -> EditableHistoryCombo:
        cb = EditableHistoryCombo(self.get_suggestions())
        cb.setCurrentText(initial or "")
        cb.committed.connect(lambda txt: self._commit_text(cb, txt))
        return cb

    def _commit_text(self, cb: EditableHistoryCombo, txt: str):
        txt = (txt or "").strip()
        if not txt:
            # allow clearing
            cb.setCurrentText("")
            self._sync_from_widgets()
            self.on_row_changed()
            return

        # store in history
        self.add_suggestion(txt)

        # refresh dropdown items (so new text appears everywhere)
        cb.set_items(self.get_suggestions())
        cb.setCurrentText(txt)

        self._sync_from_widgets()
        self.on_row_changed()

    def _sync_from_widgets(self):
        self.row.left = self.left_combo.currentText().strip()
        self.row.right = self.right_combo.currentText().strip()

        cells = []
        for cb in self._cell_combos:
            cells.append(cb.currentText().strip())
        self.row.cells = cells

    def _on_n_cells_changed(self, n: int):
        # resize row.cells to n
        while len(self.row.cells) < n:
            self.row.cells.append("")
        while len(self.row.cells) > n:
            self.row.cells.pop()

        self._rebuild_cells()
        self._sync_from_widgets()
        self.on_row_changed()

    def _clear_cells_container(self):
        while self.cells_container.count():
            item = self.cells_container.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

    def _rebuild_cells(self):
        self._clear_cells_container()
        self._cell_combos = []

        for i in range(len(self.row.cells)):
            cb = EditableHistoryCombo(self.get_suggestions())
            cb.setMinimumWidth(90)
            cb.setCurrentText(self.row.cells[i] or "")
            cb.committed.connect(lambda txt, idx=i, cbox=cb: self._on_cell_committed(idx, cbox, txt))
            self._cell_combos.append(cb)
            self.cells_container.addWidget(cb, 1)

    def _on_cell_committed(self, idx: int, cb: EditableHistoryCombo, txt: str):
        txt = (txt or "").strip()
        if txt:
            self.add_suggestion(txt)
            cb.set_items(self.get_suggestions())
            cb.setCurrentText(txt)

        self._sync_from_widgets()
        self.on_row_changed()