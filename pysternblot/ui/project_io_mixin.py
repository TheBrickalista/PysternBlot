# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog

from datetime import datetime, timezone
import json

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

    def _first_blot(self):
        if not self.current_project or not self.current_project.panel.blots:
            return None
        return self.current_project.panel.blots[0]
