# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox,
)
from PySide6.QtCore import Qt, QEvent

from ..models import OverlayLadder, LadderBandAssignment


class _OverlayLadderMixin:
    def _refresh_overlay_ladder_ui(self):
        blot = self._get_active_blot()
        if blot is None or not hasattr(self, "overlay_ladder_combo"):
            return

        if getattr(blot, "overlay_ladder", None) is None:
            self.overlay_ladder_show_labels_cb.blockSignals(True)
            self.overlay_ladder_only_highlight_cb.blockSignals(True)

            self.overlay_ladder_show_labels_cb.setChecked(True)
            self.overlay_ladder_only_highlight_cb.setChecked(False)

            self.overlay_ladder_show_labels_cb.blockSignals(False)
            self.overlay_ladder_only_highlight_cb.blockSignals(False)
            return

        ladder = blot.overlay_ladder

        idx = self.overlay_ladder_combo.findData(ladder.marker_set_id)
        if idx >= 0:
            self.overlay_ladder_combo.blockSignals(True)
            self.overlay_ladder_combo.setCurrentIndex(idx)
            self.overlay_ladder_combo.blockSignals(False)

        self.overlay_ladder_show_labels_cb.blockSignals(True)
        self.overlay_ladder_only_highlight_cb.blockSignals(True)

        self.overlay_ladder_show_labels_cb.setChecked(bool(ladder.show_labels))
        self.overlay_ladder_only_highlight_cb.setChecked(bool(ladder.show_only_highlighted))

        self.overlay_ladder_show_labels_cb.blockSignals(False)
        self.overlay_ladder_only_highlight_cb.blockSignals(False)

    def _save_overlay_ladder_options(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        old_value = (
            blot.overlay_ladder.model_dump()
            if getattr(blot, "overlay_ladder", None) is not None
            else None
        )

        marker_set_id = self.overlay_ladder_combo.currentData()
        if not marker_set_id:
            QMessageBox.warning(self, "No ladder preset", "Please select a ladder preset.")
            return

        existing_bands = []
        if getattr(blot, "overlay_ladder", None) is not None:
            existing_bands = list(blot.overlay_ladder.bands)

        blot.overlay_ladder = OverlayLadder(
            marker_set_id=marker_set_id,
            bands=existing_bands,
            show_labels=bool(self.overlay_ladder_show_labels_cb.isChecked()),
            show_only_highlighted=bool(self.overlay_ladder_only_highlight_cb.isChecked()),
        )

        new_value = blot.overlay_ladder.model_dump()

        self.log_operation(
            "overlay_ladder_options_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="overlay_ladder",
            old_value=old_value,
            new_value=new_value,
        )

        self.current_project.marker_sets = list(self.marker_set_library.items)

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _open_overlay_ladder_dialog(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        marker_set_id = self.overlay_ladder_combo.currentData()
        if not marker_set_id:
            QMessageBox.warning(self, "No ladder preset", "Please select a ladder preset.")
            return

        marker_set = None
        for ms in self.marker_set_library.items:
            if ms.id == marker_set_id:
                marker_set = ms
                break

        if marker_set is None:
            QMessageBox.warning(self, "Missing ladder preset", "Selected ladder preset was not found.")
            return

        if self.overlay_ladder_dialog is not None:
            self.overlay_ladder_dialog.raise_()
            self.overlay_ladder_dialog.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.setWindowTitle("Overlay ladder assignments")
        dialog.resize(620, 520)
        dialog.setModal(False)

        self.overlay_ladder_dialog = dialog

        root = QVBoxLayout(dialog)

        title = QLabel("Assign overlay ladder bands")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        root.addWidget(title)

        info = QLabel(
            "Click Select next to a ladder band, then click the corresponding band "
            "on the provenance image."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["kDa", "Label", "Highlight", "Assigned y px", "Show final", "Action"])
        table.setAlternatingRowColors(True)
        root.addWidget(table)

        self.overlay_ladder_assignment_table = table
        table.itemChanged.connect(self._sync_overlay_ladder_visibility_from_table)

        btns = QHBoxLayout()

        clear_btn = QPushButton("Clear selected assignment")
        btns.addWidget(clear_btn)

        close_btn = QPushButton("Close")
        btns.addWidget(close_btn)

        btns.addStretch(1)
        root.addLayout(btns)

        def clear_selected():
            row = table.currentRow()
            if row < 0:
                return

            kda_item = table.item(row, 0)
            if kda_item is None:
                return

            kda = float(kda_item.text())

            blot = self._get_active_blot()
            if blot is None or getattr(blot, "overlay_ladder", None) is None:
                return

            old_value = blot.overlay_ladder.model_dump()

            blot.overlay_ladder.bands = [
                b for b in blot.overlay_ladder.bands
                if abs(float(b.kda) - kda) > 0.001
            ]

            self.log_operation(
                "overlay_ladder_assignment_cleared",
                target_type="blot",
                target_id=blot.id,
                asset_sha256=blot.asset_sha256,
                field="overlay_ladder.bands",
                old_value=old_value,
                new_value=blot.overlay_ladder.model_dump(),
                note=f"Cleared assignment for {kda:g} kDa band",
            )

            self.current_project.marker_sets = list(self.marker_set_library.items)

            self.workspace.save_project(self.current_project)
            self.refresh_previews()
            self._populate_overlay_ladder_assignment_table()

        def close_dialog():
            self.pending_overlay_ladder_kda = None
            self.overlay_ladder_dialog = None
            self.overlay_ladder_assignment_table = None
            dialog.close()

        def on_destroyed():
            self.pending_overlay_ladder_kda = None
            self.overlay_ladder_dialog = None
            self.overlay_ladder_assignment_table = None

        clear_btn.clicked.connect(clear_selected)
        close_btn.clicked.connect(close_dialog)
        dialog.destroyed.connect(on_destroyed)

        self._populate_overlay_ladder_assignment_table()
        dialog.show()

    def _on_protein_label_changed(self, *_args):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        target = self._get_active_channel_or_blot()
        if target is None:
            return

        old = str(target.protein_label.text or "")
        new = self.protein_label_combo.currentText().strip()

        target.protein_label.text = new

        self.log_operation(
            "protein_label_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="protein_label.text",
            old_value=old,
            new_value=new,
        )

        self._add_protein_label_suggestion(new)

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_antibody_name_changed(self, *_args):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        target = self._get_active_channel_or_blot()
        if target is None:
            return

        old = str(getattr(target, "antibody_name", "") or "")
        new = self.antibody_name_combo.currentText().strip()

        target.antibody_name = new

        self.log_operation(
            "antibody_name_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="antibody_name",
            old_value=old,
            new_value=new,
        )

        self._add_antibody_name_suggestion(new)

        self.workspace.save_project(self.current_project)

    def _on_protein_font_size_changed(self, value: int):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        target = self._get_active_channel_or_blot()
        if target is None:
            return

        old = target.protein_label.font_size_pt
        new = float(value)

        target.protein_label.font_size_pt = new

        self.log_operation(
            "protein_font_size_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="protein_label.font_size_pt",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def eventFilter(self, obj, event):
        if obj is self.prov_view.viewport() and event.type() == QEvent.MouseButtonPress:
            if self.pending_overlay_ladder_kda is not None:
                pos = event.position().toPoint()
                scene_pos = self.prov_view.mapToScene(pos)

                # In render.py provenance image starts at x0=10, y0=10
                image_y = float(scene_pos.y() - 10.0)

                self._assign_pending_overlay_ladder_band(image_y)
                return True

        return super().eventFilter(obj, event)

    def _assign_pending_overlay_ladder_band(self, image_y: float):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        kda = self.pending_overlay_ladder_kda
        if kda is None:
            return

        marker_set_id = self.overlay_ladder_combo.currentData()
        if not marker_set_id:
            return

        old_value = (
            blot.overlay_ladder.model_dump()
            if getattr(blot, "overlay_ladder", None) is not None
            else None
        )

        previous_show_in_final = True
        existing = []

        if getattr(blot, "overlay_ladder", None) is not None:
            for b in blot.overlay_ladder.bands:
                if abs(float(b.kda) - float(kda)) <= 0.001:
                    previous_show_in_final = bool(getattr(b, "show_in_final", True))
                else:
                    existing.append(b)

        existing.append(
            LadderBandAssignment(
                y_px=float(image_y),
                kda=float(kda),
                show_in_final=previous_show_in_final,
            )
        )

        existing.sort(key=lambda b: b.y_px)

        blot.overlay_ladder = OverlayLadder(
            marker_set_id=marker_set_id,
            bands=existing,
            show_labels=bool(self.overlay_ladder_show_labels_cb.isChecked()),
            show_only_highlighted=bool(self.overlay_ladder_only_highlight_cb.isChecked()),
        )

        self.log_operation(
            "overlay_ladder_band_assigned",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="overlay_ladder.bands",
            old_value=old_value,
            new_value=blot.overlay_ladder.model_dump(),
            note=f"Assigned {float(kda):g} kDa band to y={float(image_y):.1f}px",
        )

        self.pending_overlay_ladder_kda = None

        self.current_project.marker_sets = list(self.marker_set_library.items)

        self.workspace.save_project(self.current_project)
        self.refresh_previews()
        self._refresh_overlay_ladder_ui()

        if self.overlay_ladder_dialog is not None:
            self._populate_overlay_ladder_assignment_table()

    def _populate_overlay_ladder_assignment_table(self):
        table = self.overlay_ladder_assignment_table
        if table is None:
            return

        table.blockSignals(True)

        blot = self._get_active_blot()
        if blot is None:
            table.blockSignals(False)
            return

        marker_set_id = self.overlay_ladder_combo.currentData()
        marker_set = None

        for ms in self.marker_set_library.items:
            if ms.id == marker_set_id:
                marker_set = ms
                break

        if marker_set is None:
            table.setRowCount(0)
            table.blockSignals(False)
            return

        assigned_by_kda = {}
        if getattr(blot, "overlay_ladder", None) is not None:
            for assignment in blot.overlay_ladder.bands:
                assigned_by_kda[float(assignment.kda)] = assignment

        table.setRowCount(len(marker_set.bands))

        for row, band in enumerate(marker_set.bands):
            kda = float(band.kda)

            table.setItem(row, 0, QTableWidgetItem(f"{kda:g}"))
            table.setItem(row, 1, QTableWidgetItem(str(band.label or "")))
            table.setItem(row, 2, QTableWidgetItem("yes" if band.highlight else ""))
            assignment = assigned_by_kda.get(kda)

            table.setItem(
                row,
                3,
                QTableWidgetItem(
                    f"{float(assignment.y_px):.1f}" if assignment is not None else "—"
                )
            )

            show_item = QTableWidgetItem()
            show_item.setFlags(show_item.flags() | Qt.ItemIsUserCheckable)
            show_item.setCheckState(
                Qt.Checked
                if assignment is None or bool(getattr(assignment, "show_in_final", True))
                else Qt.Unchecked
            )
            table.setItem(row, 4, show_item)

            btn = QPushButton("Select")
            btn.clicked.connect(lambda _checked=False, value=kda: self._select_overlay_ladder_kda(value))
            table.setCellWidget(row, 5, btn)

        table.resizeColumnsToContents()
        table.blockSignals(False)

    def _select_overlay_ladder_kda(self, kda: float):
        self.pending_overlay_ladder_kda = float(kda)

    def _sync_overlay_ladder_visibility_from_table(self):
        table = self.overlay_ladder_assignment_table
        blot = self._get_active_blot()

        if table is None or blot is None or getattr(blot, "overlay_ladder", None) is None:
            return

        old_value = blot.overlay_ladder.model_dump()

        show_by_kda = {}

        for row in range(table.rowCount()):
            kda_item = table.item(row, 0)
            show_item = table.item(row, 4)

            if kda_item is None or show_item is None:
                continue

            kda = float(kda_item.text())
            show_by_kda[kda] = show_item.checkState() == Qt.Checked

        for assignment in blot.overlay_ladder.bands:
            kda = float(assignment.kda)
            if kda in show_by_kda:
                assignment.show_in_final = bool(show_by_kda[kda])

        self.log_operation(
            "overlay_ladder_visibility_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="overlay_ladder.bands.show_in_final",
            old_value=old_value,
            new_value=blot.overlay_ladder.model_dump(),
        )

        self.current_project.marker_sets = list(self.marker_set_library.items)
        self.workspace.save_project(self.current_project)
        self.refresh_previews()
