# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QInputDialog, QTableWidgetItem, QCheckBox
from PySide6.QtCore import Qt

import uuid

from ..models import MarkerSet, MarkerBand


class _MarkerSetMixin:
    def refresh_marker_sets(self):
        self.marker_set_combo.blockSignals(True)
        self.marker_set_combo.clear()

        self.marker_set_library = self.workspace.load_marker_sets()

        for marker_set in self.marker_set_library.items:
            self.marker_set_combo.addItem(marker_set.name, marker_set.id)

        if hasattr(self, "overlay_ladder_combo"):
            self.overlay_ladder_combo.blockSignals(True)
            self.overlay_ladder_combo.clear()

            for marker_set in self.marker_set_library.items:
                self.overlay_ladder_combo.addItem(marker_set.name, marker_set.id)

            self.overlay_ladder_combo.blockSignals(False)

        self.marker_set_combo.blockSignals(False)

        if self.marker_set_combo.count() > 0:
            self.marker_set_combo.setCurrentIndex(0)
            self._populate_marker_set_table(self.marker_set_library.items[0])
        else:
            self.marker_set_table.setRowCount(0)

    def _get_selected_marker_set(self):
        marker_set_id = self.marker_set_combo.currentData()
        if not marker_set_id:
            return None

        for marker_set in self.marker_set_library.items:
            if marker_set.id == marker_set_id:
                return marker_set

        return None

    def _on_marker_set_selected(self, _idx: int):
        marker_set = self._get_selected_marker_set()
        if marker_set is None:
            self.marker_set_table.setRowCount(0)
            return

        self._populate_marker_set_table(marker_set)

    def _populate_marker_set_table(self, marker_set: MarkerSet):
        self.marker_set_table.blockSignals(True)
        self.marker_set_table.setRowCount(len(marker_set.bands))

        for row, band in enumerate(marker_set.bands):
            self.marker_set_table.setItem(row, 0, QTableWidgetItem(str(band.kda)))
            self.marker_set_table.setItem(row, 1, QTableWidgetItem(str(band.label or "")))

            visible_item = QTableWidgetItem()
            visible_item.setFlags(visible_item.flags() | Qt.ItemIsUserCheckable)
            visible_item.setCheckState(Qt.Checked if band.visible else Qt.Unchecked)
            self.marker_set_table.setItem(row, 2, visible_item)

            highlight_item = QTableWidgetItem()
            highlight_item.setFlags(highlight_item.flags() | Qt.ItemIsUserCheckable)
            highlight_item.setCheckState(Qt.Checked if band.highlight else Qt.Unchecked)
            self.marker_set_table.setItem(row, 3, highlight_item)

            show_685 = 685 in band.channels and 785 not in band.channels
            show_785 = 785 in band.channels and 685 not in band.channels
            cb_685 = QCheckBox()
            cb_685.setChecked(show_685)
            cb_785 = QCheckBox()
            cb_785.setChecked(show_785)
            self.marker_set_table.setCellWidget(row, 4, cb_685)
            self.marker_set_table.setCellWidget(row, 5, cb_785)

        self.marker_set_table.blockSignals(False)
        self.marker_set_table.resizeColumnsToContents()

    def _marker_set_from_table(self, existing: MarkerSet) -> MarkerSet:
        bands = []

        for row in range(self.marker_set_table.rowCount()):
            kda_item = self.marker_set_table.item(row, 0)
            label_item = self.marker_set_table.item(row, 1)
            visible_item = self.marker_set_table.item(row, 2)
            highlight_item = self.marker_set_table.item(row, 3)

            if kda_item is None:
                continue

            txt = kda_item.text().strip()
            if not txt:
                continue

            kda = float(txt)
            label = label_item.text().strip() if label_item else ""

            cb_685 = self.marker_set_table.cellWidget(row, 4)
            cb_785 = self.marker_set_table.cellWidget(row, 5)
            show_685 = cb_685.isChecked() if cb_685 else False
            show_785 = cb_785.isChecked() if cb_785 else False

            if show_685 and not show_785:
                channels: list[int] = [685]
            elif show_785 and not show_685:
                channels = [785]
            else:
                channels = []

            bands.append(
                MarkerBand(
                    kda=kda,
                    label=label or None,
                    visible=visible_item.checkState() == Qt.Checked if visible_item else True,
                    highlight=highlight_item.checkState() == Qt.Checked if highlight_item else False,
                    channels=channels,
                )
            )

        bands.sort(key=lambda b: b.kda, reverse=True)

        return MarkerSet(
            id=existing.id,
            name=existing.name,
            unit=existing.unit,
            bands=bands,
        )

    def _save_marker_set_from_ui(self):
        marker_set = self._get_selected_marker_set()
        if marker_set is None:
            return

        try:
            updated = self._marker_set_from_table(marker_set)
        except Exception as e:
            QMessageBox.critical(self, "Invalid ladder preset", str(e))
            return

        for i, item in enumerate(self.marker_set_library.items):
            if item.id == updated.id:
                self.marker_set_library.items[i] = updated
                break

        self.workspace.save_marker_sets(self.marker_set_library)
        self.refresh_marker_sets()

    def _new_marker_set(self):
        name, ok = QInputDialog.getText(self, "New protein ladder", "Preset name:")
        if not ok or not name.strip():
            return

        new_set = MarkerSet(
            id=f"marker_set_{uuid.uuid4().hex[:8]}",
            name=name.strip(),
            unit="kDa",
            bands=[]
        )

        self.marker_set_library.items.append(new_set)
        self.workspace.save_marker_sets(self.marker_set_library)
        self.refresh_marker_sets()

        idx = self.marker_set_combo.findData(new_set.id)
        if idx >= 0:
            self.marker_set_combo.setCurrentIndex(idx)

    def _duplicate_marker_set(self):
        marker_set = self._get_selected_marker_set()
        if marker_set is None:
            return

        new_set = marker_set.model_copy(deep=True)
        new_set.id = f"marker_set_{uuid.uuid4().hex[:8]}"
        new_set.name = f"{marker_set.name} copy"

        self.marker_set_library.items.append(new_set)
        self.workspace.save_marker_sets(self.marker_set_library)
        self.refresh_marker_sets()

        idx = self.marker_set_combo.findData(new_set.id)
        if idx >= 0:
            self.marker_set_combo.setCurrentIndex(idx)

    def _delete_marker_set(self):
        marker_set = self._get_selected_marker_set()
        if marker_set is None:
            return

        if len(self.marker_set_library.items) <= 1:
            QMessageBox.information(
                self,
                "Cannot delete",
                "Keep at least one protein ladder preset."
            )
            return

        reply = QMessageBox.question(
            self,
            "Delete protein ladder preset",
            f"Delete '{marker_set.name}'?"
        )

        if reply != QMessageBox.Yes:
            return

        self.marker_set_library.items = [
            item for item in self.marker_set_library.items
            if item.id != marker_set.id
        ]

        self.workspace.save_marker_sets(self.marker_set_library)
        self.refresh_marker_sets()

    def _add_marker_band_row(self):
        row = self.marker_set_table.rowCount()
        self.marker_set_table.insertRow(row)

        self.marker_set_table.setItem(row, 0, QTableWidgetItem(""))
        self.marker_set_table.setItem(row, 1, QTableWidgetItem(""))

        visible_item = QTableWidgetItem()
        visible_item.setFlags(visible_item.flags() | Qt.ItemIsUserCheckable)
        visible_item.setCheckState(Qt.Checked)
        self.marker_set_table.setItem(row, 2, visible_item)

        highlight_item = QTableWidgetItem()
        highlight_item.setFlags(highlight_item.flags() | Qt.ItemIsUserCheckable)
        highlight_item.setCheckState(Qt.Unchecked)
        self.marker_set_table.setItem(row, 3, highlight_item)

        cb_685 = QCheckBox()
        cb_785 = QCheckBox()
        self.marker_set_table.setCellWidget(row, 4, cb_685)
        self.marker_set_table.setCellWidget(row, 5, cb_785)

    def _remove_selected_marker_band_row(self):
        row = self.marker_set_table.currentRow()
        if row >= 0:
            self.marker_set_table.removeRow(row)
