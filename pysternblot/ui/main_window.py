# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog,
    QMessageBox, QGraphicsView, QToolBar, QSlider, QInputDialog, QComboBox, QPushButton
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt

from pathlib import Path


from ..storage import Workspace
from ..render import build_panel_scene, build_provenance_scene
from ..models import Blot, AssetEntry
from .legend_tab import LegendTab

class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.workspace = workspace
        self.current_project = None
        self.active_blot_id = None

        self.setWindowTitle("Pystern Blot")
        self.resize(1100, 700)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Library tab (placeholder)
        lib = QWidget()
        lib_l = QVBoxLayout(lib)
        lib_l.addWidget(QLabel("Library (skeleton): Open a project.json to preview."))
        self.tabs.addTab(lib, "Library")

        # Final Result tab
        final = QWidget()
        final_l = QVBoxLayout(final)
        self.view = QGraphicsView()
        final_l.addWidget(self.view)
        self.tabs.addTab(final, "Final Result")

        # Provenance tab
        prov = QWidget()
        prov_l = QVBoxLayout(prov)

        prov_top = QHBoxLayout()
        prov_top.addWidget(QLabel("Blot"))
        self.prov_blot_combo = QComboBox()
        self.prov_blot_combo.currentIndexChanged.connect(self._on_active_blot_changed)
        prov_top.addWidget(self.prov_blot_combo)

        # 👇 ADD HERE
        self.prov_up_btn = QPushButton("Up")
        self.prov_up_btn.clicked.connect(self._move_active_blot_up)
        prov_top.addWidget(self.prov_up_btn)

        self.prov_down_btn = QPushButton("Down")
        self.prov_down_btn.clicked.connect(self._move_active_blot_down)
        prov_top.addWidget(self.prov_down_btn)

        prov_top.addStretch(1)

        prov_l.addLayout(prov_top)

        self.prov_label = QLabel("Current blot: —")
        prov_l.addWidget(self.prov_label)

        self.prov_view = QGraphicsView()
        prov_l.addWidget(self.prov_view)

        self.tabs.addTab(prov, "Provenance")

        # Legend tab
        self.legend_tab = LegendTab()
        self.legend_tab.changed.connect(self._on_legend_changed)
        self.tabs.addTab(self.legend_tab, "Legend")

        self._toolbar()

    def _toolbar(self):
        tb = QToolBar("Main")
        self.addToolBar(tb)
        
        a_new = QAction("New Project…", self)
        a_new.triggered.connect(self.new_project)
        tb.addAction(a_new)

        a_open = QAction("Open Project…", self)
        a_open.triggered.connect(self.open_project)
        tb.addAction(a_open)

        a_import = QAction("Import Blot…", self)
        a_import.triggered.connect(self.import_blot)
        tb.addAction(a_import)
        
        a_import_mem = QAction("Import Membrane…", self)
        a_import_mem.triggered.connect(self.import_membrane)
        tb.addAction(a_import_mem)

        tb.addSeparator()

        # Overlay toggle (membrane overlay on provenance view)
        self.a_overlay = QAction("Overlay", self)
        self.a_overlay.setCheckable(True)
        self.a_overlay.setChecked(True)
        self.a_overlay.triggered.connect(self.toggle_overlay)
        tb.addAction(self.a_overlay)

        # Overlay alpha slider (0–100 mapped to 0.0–1.0)
        tb.addWidget(QLabel(" alpha "))
        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setMinimum(0)
        self.alpha_slider.setMaximum(100)
        self.alpha_slider.setValue(35)
        self.alpha_slider.setFixedWidth(120)
        self.alpha_slider.valueChanged.connect(self.change_overlay_alpha)
        tb.addWidget(self.alpha_slider)

        tb.addSeparator()

        a_refresh = QAction("Refresh", self)
        a_refresh.triggered.connect(self.refresh_previews)
        tb.addAction(a_refresh)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project.json", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.current_project = self.workspace.load_project(path)
            self._sync_controls_from_project()
            self.legend_tab.bind(self.current_project, self._get_legend_suggestions, self._add_legend_suggestion)
            self.refresh_previews()
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
                "crop": {"x": 50, "y": 50, "w": 300, "h": 200, "mode": "absolute"},
                "ladder": {
                    "lane_index": 0,
                    "marker_set_id": "ms_default",
                    "calibration_points": [
                        {"y_px": 50, "kda": 55},
                        {"y_px": 120, "kda": 36}
                    ],
                    "show_ticks": True
                },
                "protein_label": {"text": "Protein", "align": "center"},
                "display": {
                    "invert": False,
                    "gamma": 1.0,
                    "auto_contrast": True,
                    "overlay_alpha": 0.35,
                    "overlay_visible": True
                },
            }

            new_blot = Blot.model_validate(new_blot_dict)

            self.current_project.panel.blots.append(new_blot)
            self.current_project.panel.layout.order.append(blot_id)
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

            # v0.1: attach to first blot (later we’ll support selecting which blot)
            blot = self._get_active_blot()
            if blot is None:
                raise RuntimeError("No active blot available.")
            blot.overlay_asset_sha256 = digest

            # Optional: force overlay visible immediately
            blot.display.overlay_visible = True

            self.workspace.save_project(self.current_project)
            self.refresh_previews()

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

    def _sync_controls_from_project(self):
        self._populate_prov_blot_combo()
        self._update_prov_label()
        blot = self._get_active_blot()
        if not blot:
            return
        # Default values if fields aren’t present yet
        overlay_vis = getattr(getattr(blot, "display", None), "overlay_visible", True)
        overlay_alpha = float(getattr(getattr(blot, "display", None), "overlay_alpha", 0.35))

        self.a_overlay.setChecked(bool(overlay_vis))
        self.alpha_slider.setValue(int(round(overlay_alpha * 100)))

    def _on_legend_changed(self):
        if not self.current_project:
            return
        self.workspace.save_project(self.current_project)
        self._refresh_final_only(fit=True)  # or fit=False if you don't want jumping


    def _refresh_final_only(self, fit: bool = True):
        if not self.current_project:
            return

        panel_scene = build_panel_scene(self.current_project, self.workspace.root)
        if panel_scene is None:
            raise RuntimeError("build_panel_scene returned None (expected QGraphicsScene).")

        self.view.setScene(panel_scene)

        if fit:
            rect = panel_scene.itemsBoundingRect()
            if rect.isValid() and not rect.isNull():
                self.view.fitInView(rect, Qt.KeepAspectRatio)

    def _on_crop_commit(self, blot: Blot):
        """
        Called when user releases the crop rectangle.
        Regenerates cached crop preview and refreshes Final Result.
        """
        if not self.current_project:
            return

        # Persist the updated crop coordinates
        self.workspace.save_project(self.current_project)

        # Rebuild cached preview_crop.png for this blot
        try:
            self.workspace.ensure_blot_crop_preview(blot)
        except Exception as e:
            print(f"[preview] failed for {getattr(blot, 'id', '?')}: {e}")

        # Refresh ONLY the final result scene (avoid resetting the crop rect mid-drag)
        panel_scene = build_panel_scene(self.current_project, self.workspace.root)
        self.view.setScene(panel_scene)
        self.view.fitInView(panel_scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def _get_legend_suggestions(self) -> list[str]:
        return self.workspace.load_legend_suggestions()

    def _add_legend_suggestion(self, txt: str):
        txt = (txt or "").strip()
        if not txt:
            return
        items = self.workspace.load_legend_suggestions()
        if txt not in items:
            items.append(txt)
            self.workspace.save_legend_suggestions(items)

    def toggle_overlay(self, checked: bool):
        blot = self._get_active_blot()
        if not blot:
            return
        blot.display.overlay_visible = bool(checked)
        self.refresh_previews()

    def change_overlay_alpha(self, value: int):
        blot = self._get_active_blot()
        if not blot:
            return
        blot.display.overlay_alpha = float(value) / 100.0
        self.refresh_previews()

    def refresh_previews(self):
        if not self.current_project:
            return
        
        self._populate_prov_blot_combo()
        self._update_prov_label()

        # Option 2: ensure cached crop previews exist before rendering
        for blot in self.current_project.panel.blots:
            try:
                self.workspace.ensure_blot_crop_preview(blot)
            except Exception as e:
                print(f"[preview] failed for {getattr(blot, 'id', '?')}: {e}")

        try:
            panel_scene = build_panel_scene(self.current_project, self.workspace.root)
            if panel_scene is None:
                raise RuntimeError("build_panel_scene returned None (expected QGraphicsScene).")

            self.view.setScene(panel_scene)
            self.view.fitInView(panel_scene.itemsBoundingRect(), Qt.KeepAspectRatio)

            prov_scene = build_provenance_scene(
                self.current_project,
                self.workspace.root,
                blot_id=self.active_blot_id,
                on_crop_commit=self._on_crop_commit
            )
            if prov_scene is None:
                raise RuntimeError("build_provenance_scene returned None (expected QGraphicsScene).")

            self.prov_view.setScene(prov_scene)
            self.prov_view.fitInView(prov_scene.itemsBoundingRect(), Qt.KeepAspectRatio)

        except Exception as e:
            QMessageBox.critical(self, "Render error", str(e))
            return

    def _on_crop_changed(self, blot):
        if not self.current_project:
            return
        # persist crop
        self.workspace.save_project(self.current_project)

        # regenerate cached preview for this blot
        try:
            self.workspace.ensure_blot_crop_preview(blot)
        except Exception as e:
            print(f"[preview] failed after crop move: {e}")

        # refresh both views
        self.refresh_previews()

    def _populate_prov_blot_combo(self):
        self.prov_blot_combo.blockSignals(True)
        self.prov_blot_combo.clear()

        if not self.current_project or not self.current_project.panel.blots:
            self.active_blot_id = None
            self.prov_blot_combo.blockSignals(False)
            return

        for blot in self.current_project.panel.blots:
            display_name = blot.id
            asset = self.current_project.assets.get(blot.asset_sha256)
            if asset and asset.original_source_path:
                display_name = Path(asset.original_source_path).name
            self.prov_blot_combo.addItem(display_name, blot.id)

        idx = -1
        if self.active_blot_id is not None:
            idx = self.prov_blot_combo.findData(self.active_blot_id)

        if idx < 0:
            idx = 0

        self.prov_blot_combo.setCurrentIndex(idx)
        self.active_blot_id = self.prov_blot_combo.currentData()

        self.prov_blot_combo.blockSignals(False)

    def _on_active_blot_changed(self, _idx: int):
        if not self.current_project:
            return

        prev_blot = self._get_active_blot()
        blot_id = self.prov_blot_combo.currentData()
        new_blot = next((b for b in self.current_project.panel.blots if b.id == blot_id), None)

        if prev_blot and new_blot and prev_blot is not new_blot:
            # keep same crop size, but allow independent position
            new_blot.crop.w = prev_blot.crop.w
            new_blot.crop.h = prev_blot.crop.h

        self.active_blot_id = blot_id
        self._update_prov_label()
        self.refresh_previews()

    def _get_active_blot(self):
        if not self.current_project or not self.current_project.panel.blots:
            return None
        if self.active_blot_id:
            for blot in self.current_project.panel.blots:
                if blot.id == self.active_blot_id:
                    return blot
        return self.current_project.panel.blots[0]
    
    def _update_prov_label(self):
        blot = self._get_active_blot()

        if blot is None:
            self.prov_label.setText("Current blot: —")
            return

        asset = self.current_project.assets.get(blot.asset_sha256)

        if asset and asset.original_source_path:
            name = Path(asset.original_source_path).name
        else:
            name = blot.id  # fallback

        self.prov_label.setText(f"Current blot: {name}")

    def _move_active_blot_up(self):
        if not self.current_project or not self.active_blot_id:
            return

        order = self.current_project.panel.layout.order
        if self.active_blot_id not in order:
            return

        i = order.index(self.active_blot_id)
        if i <= 0:
            return

        order[i - 1], order[i] = order[i], order[i - 1]

        self.workspace.save_project(self.current_project)
        self.refresh_previews()


    def _move_active_blot_down(self):
        if not self.current_project or not self.active_blot_id:
            return

        order = self.current_project.panel.layout.order
        if self.active_blot_id not in order:
            return

        i = order.index(self.active_blot_id)
        if i >= len(order) - 1:
            return

        order[i + 1], order[i] = order[i], order[i + 1]

        self.workspace.save_project(self.current_project)
        self.refresh_previews()