# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QInputDialog,
    QPushButton, QVBoxLayout,
)
from PySide6.QtCore import Qt

from datetime import datetime, timezone, date
from pathlib import Path
import json, zipfile

from ..models import Blot, AssetEntry, OperationLogEntry


class _ProjectIOMixin:
    def _plain_log_value(self, value):
        if hasattr(value, "model_dump"):
            return value.model_dump()

        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    def log_operation(
        self,
        operation: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        asset_sha256: str | None = None,
        field: str | None = None,
        old_value=None,
        new_value=None,
        note: str | None = None,
    ):
        if not self.current_project:
            return

        if old_value == new_value and old_value is not None:
            return

        self.current_project.operation_log.append(
            OperationLogEntry(
                timestamp_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                operation=operation,
                target_type=target_type,
                target_id=target_id,
                asset_sha256=asset_sha256,
                field=field,
                old_value=self._plain_log_value(old_value),
                new_value=self._plain_log_value(new_value),
                note=note,
            )
        )

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project.json", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.current_project = self.workspace.load_project(path)
            self._sync_controls_from_project()
            self.legend_tab.bind(self.current_project, self._get_legend_suggestions, self._add_legend_suggestion)
            self.refresh_previews()
            self._refresh_overlay_ladder_ui()
            self.refresh_library()
            QMessageBox.information(self, "Loaded", path)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok or not name.strip():
            return
        try:
            proj_path = self.workspace.create_new_project(name.strip())
            self.current_project = self.workspace.load_project(str(proj_path))
            self._sync_controls_from_project()
            self.legend_tab.bind(self.current_project, self._get_legend_suggestions, self._add_legend_suggestion)
            self.refresh_previews()
            self._refresh_overlay_ladder_ui()
            self.refresh_library()
            QMessageBox.information(self, "Created", f"Project created:\n{proj_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def import_blot(self):
        if not self.current_project:
            QMessageBox.information(
                self,
                "No project",
                "Create or open a project first (New Project… or Open Project…)."
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import blot",
            "",
            "Images (*.tif *.tiff *.png *.jpg *.jpeg)"
        )
        if not path:
            return

        try:
            digest, dest = self.workspace.import_asset(path)

            self.current_project.assets[digest] = AssetEntry(
                sha256=digest,
                stored_original_path=str(dest),
                original_source_path=str(path),
                stored_preview_path=None,
            )

            blot_id = f"blot_{len(self.current_project.panel.blots) + 1:02d}"

            new_blot_dict = {
                "id": blot_id,
                "asset_sha256": digest,
                "overlay_asset_sha256": None,
                "crop": {"x": 50, "y": 50,
                         "w": self.current_project.panel.crop_template.w,
                         "h": self.current_project.panel.crop_template.h,
                         "mode": "absolute"},
                "ladder": {
                    "lane_index": 0,
                    "marker_set_id": "ms_default",
                    "calibration_points": [
                        {"y_px": 50, "kda": 55},
                        {"y_px": 120, "kda": 36}
                    ],
                    "show_ticks": True
                },
                "protein_label": {"text": "Protein", "align": "center", "font_size_pt": None,},
                "display": {
                    "invert": True,
                    "gamma": 1.0,
                    "auto_contrast": True,
                    "overlay_alpha": 0.35,
                    "overlay_visible": True,
                    "rotation_deg": 0.0,
                    "levels_black": 0,
                    "levels_white": 65535,
                    "levels_gamma": 1.0,
                },
            }

            new_blot = Blot.model_validate(new_blot_dict)

            self.current_project.panel.blots.append(new_blot)
            self.current_project.panel.layout.order.append(blot_id)
            self.log_operation(
                "blot_imported",
                target_type="blot",
                target_id=blot_id,
                asset_sha256=digest,
                field="panel.blots",
                old_value=None,
                new_value={
                    "blot_id": blot_id,
                    "asset_sha256": digest,
                    "source_path": str(path),
                },
            )
            self.active_blot_id = blot_id
            self._populate_prov_blot_combo()
            self._update_prov_label()

            self.workspace.save_project(self.current_project)

            QMessageBox.information(
                self,
                "Imported",
                f"Copied to:\n{dest}\n\nAttached to project as {blot_id}"
            )

            self.refresh_previews()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def import_membrane(self):
        if not self.current_project or not self.current_project.panel.blots:
            QMessageBox.information(
                self,
                "No blot to attach membrane",
                "Create/open a project and import a blot first."
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import membrane (overlay)",
            "",
            "Images (*.tif *.tiff *.png *.jpg *.jpeg)"
        )
        if not path:
            return

        try:
            digest, dest = self.workspace.import_asset(path)

            blot = self._get_active_blot()
            if blot is None:
                raise RuntimeError("No active blot available.")
            old_overlay = blot.overlay_asset_sha256
            blot.overlay_asset_sha256 = digest
            self.log_operation(
                "overlay_imported",
                target_type="blot",
                target_id=blot.id,
                asset_sha256=blot.asset_sha256,
                field="overlay_asset_sha256",
                old_value=old_overlay,
                new_value=digest,
                note=f"Overlay source: {path}",
            )

            # Optional: force overlay visible immediately
            blot.display.overlay_visible = True

            self.workspace.save_project(self.current_project)
            self.refresh_previews()
            self.refresh_library()

            QMessageBox.information(
                self,
                "Membrane imported",
                f"Copied to:\n{dest}\n\nLinked as overlay to blot: {getattr(blot, 'id', 'blot_01')}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_library_context_menu(self, pos):
        row = self.library_table.rowAt(pos.y())
        if row < 0:
            return

        menu = QMenu(self)
        open_action = menu.addAction("Open")
        rename_action = menu.addAction("Rename…")

        action = menu.exec(self.library_table.viewport().mapToGlobal(pos))

        if action == open_action:
            self._open_project_from_library(row, 0)
        elif action == rename_action:
            self._rename_project_from_library(row)

    def _rename_project_from_library(self, row: int):
        path_item = self.library_table.item(row, 5)
        name_item = self.library_table.item(row, 0)
        if path_item is None or name_item is None:
            return

        path = path_item.text().strip()
        old_name = name_item.text().strip()

        new_name, ok = QInputDialog.getText(self, "Rename Project", "New name:", text=old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return

        try:
            project = self.workspace.load_project(path)
            self.workspace.rename_project(project, new_name.strip())

            if self.current_project and self.current_project.project.id == project.project.id:
                self.current_project.project.name = new_name.strip()
                self._sync_controls_from_project()

            self.refresh_library()
        except Exception as e:
            QMessageBox.critical(self, "Error renaming project", str(e))

    def _first_blot(self):
        if not self.current_project or not self.current_project.panel.blots:
            return None
        return self.current_project.panel.blots[0]

    def export_library(self):
        projects_root = self.workspace.projects_dir
        if not projects_root.exists():
            QMessageBox.information(self, "No projects", "No projects found in workspace.")
            return

        project_entries = []
        for proj_json in sorted(projects_root.glob("*/project.json")):
            try:
                p = self.workspace.load_project(str(proj_json))
                project_entries.append({
                    "id": p.project.id,
                    "name": p.project.name,
                    "n_blots": len(p.panel.blots),
                })
            except Exception:
                pass

        if not project_entries:
            QMessageBox.information(self, "No projects", "No valid projects found in workspace.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Export Library Archive")
        dialog.resize(520, 420)

        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.addWidget(QLabel("Select projects to include in the archive:"))

        list_widget = QListWidget()
        list_widget.setSelectionMode(QListWidget.NoSelection)

        for entry in project_entries:
            item = QListWidgetItem(f"{entry['name']}\n{entry['id']}  ·  {entry['n_blots']} blots")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, entry["id"])
            list_widget.addItem(item)

        dlg_layout.addWidget(list_widget)

        def _set_all(state):
            for i in range(list_widget.count()):
                list_widget.item(i).setCheckState(state)

        sel_row = QHBoxLayout()
        sel_all_btn = QPushButton("Select All")
        desel_all_btn = QPushButton("Deselect All")
        sel_all_btn.clicked.connect(lambda: _set_all(Qt.Checked))
        desel_all_btn.clicked.connect(lambda: _set_all(Qt.Unchecked))
        sel_row.addWidget(sel_all_btn)
        sel_row.addWidget(desel_all_btn)
        sel_row.addStretch(1)
        dlg_layout.addLayout(sel_row)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("Export…")
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        dlg_layout.addWidget(btn_box)

        if dialog.exec() != QDialog.Accepted:
            return

        selected_ids = [
            list_widget.item(i).data(Qt.UserRole)
            for i in range(list_widget.count())
            if list_widget.item(i).checkState() == Qt.Checked
        ]

        if not selected_ids:
            QMessageBox.information(self, "Nothing selected", "Please select at least one project.")
            return

        default_name = f"PysternBlot_export_{date.today().strftime('%Y%m%d')}.pbarchive"
        dest_path, _ = QFileDialog.getSaveFileName(
            self, "Save Archive", default_name, "Pystern Blot Archive (*.pbarchive)"
        )
        if not dest_path:
            return

        try:
            from .. import __version__
            self.workspace.export_archive(selected_ids, Path(dest_path), __version__)

            with zipfile.ZipFile(dest_path, "r") as zf:
                manifest = json.loads(zf.read("pbarchive/manifest.json"))
            n_assets = len(manifest.get("asset_sha256s", []))

            QMessageBox.information(
                self,
                "Archive saved",
                f"Archive saved: {Path(dest_path).name}\n"
                f"{len(selected_ids)} projects, {n_assets} assets",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def import_library(self):
        src_path, _ = QFileDialog.getOpenFileName(
            self, "Open Archive", "", "Pystern Blot Archive (*.pbarchive)"
        )
        if not src_path:
            return

        try:
            from .. import __version__
            result = self.workspace.import_archive(Path(src_path), __version__)

            lines = [
                f"Imported: {len(result.imported_project_ids)} projects, "
                f"{result.imported_asset_count} assets",
                f"Skipped (already exist): {len(result.skipped_project_ids)} projects, "
                f"{result.skipped_asset_count} assets",
            ]

            if result.integrity_errors:
                lines.append("")
                lines.append("Integrity warnings:")
                for err in result.integrity_errors:
                    lines.append(f"  • {err}")

            icon = (
                QMessageBox.Warning if result.integrity_errors else QMessageBox.Information
            )
            msg = QMessageBox(self)
            msg.setIcon(icon)
            msg.setWindowTitle("Import complete")
            msg.setText("\n".join(lines))
            msg.exec()

            if result.imported_project_ids:
                self.refresh_library()

        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))
