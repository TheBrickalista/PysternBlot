# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QLabel, QFileDialog,
    QMessageBox, QGraphicsView, QToolBar, QSlider
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt

from ..storage import Workspace
from ..render import build_panel_scene, build_provenance_scene


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.workspace = workspace
        self.current_project = None

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
        self.prov_view = QGraphicsView()
        prov_l.addWidget(self.prov_view)
        self.tabs.addTab(prov, "Provenance")

        self._toolbar()

    def _toolbar(self):
        tb = QToolBar("Main")
        self.addToolBar(tb)

        a_open = QAction("Open Project…", self)
        a_open.triggered.connect(self.open_project)
        tb.addAction(a_open)

        a_import = QAction("Import Blot…", self)
        a_import.triggered.connect(self.import_blot)
        tb.addAction(a_import)

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
            self.refresh_previews()
            QMessageBox.information(self, "Loaded", path)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def import_blot(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import blot", "", "Images (*.tif *.tiff *.png *.jpg *.jpeg)"
        )
        if not path:
            return
        try:
            digest, dest = self.workspace.import_asset(path)
            QMessageBox.information(self, "Imported", f"{dest}\nsha256={digest}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _first_blot(self):
        if not self.current_project or not self.current_project.panel.blots:
            return None
        return self.current_project.panel.blots[0]

    def _sync_controls_from_project(self):
        blot = self._first_blot()
        if not blot:
            return
        # Default values if fields aren’t present yet
        overlay_vis = getattr(getattr(blot, "display", None), "overlay_visible", True)
        overlay_alpha = float(getattr(getattr(blot, "display", None), "overlay_alpha", 0.35))

        self.a_overlay.setChecked(bool(overlay_vis))
        self.alpha_slider.setValue(int(round(overlay_alpha * 100)))

    def toggle_overlay(self, checked: bool):
        blot = self._first_blot()
        if not blot:
            return
        blot.display.overlay_visible = bool(checked)
        self.refresh_previews()

    def change_overlay_alpha(self, value: int):
        blot = self._first_blot()
        if not blot:
            return
        blot.display.overlay_alpha = float(value) / 100.0
        self.refresh_previews()

    def refresh_previews(self):
        if not self.current_project:
            return

        panel_scene = build_panel_scene(self.current_project)
        self.view.setScene(panel_scene)
        self.view.fitInView(panel_scene.itemsBoundingRect(), Qt.KeepAspectRatio)

        prov_scene = build_provenance_scene(self.current_project, self.workspace.root)
        self.prov_view.setScene(prov_scene)
        self.prov_view.fitInView(prov_scene.itemsBoundingRect(), Qt.KeepAspectRatio)
