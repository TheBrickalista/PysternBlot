# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
from PySide6.QtWidgets import QMainWindow, QWidget, QTabWidget, QVBoxLayout, QLabel, QFileDialog, QMessageBox, QGraphicsView, QToolBar
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
from ..storage import Workspace
from ..render import build_scene

class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.workspace = workspace
        self.current_project = None

        self.setWindowTitle("Pystern Blot")
        self.resize(1100, 700)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        lib = QWidget()
        lib_l = QVBoxLayout(lib)
        lib_l.addWidget(QLabel("Library (skeleton): Open a project.json to preview."))
        self.tabs.addTab(lib, "Library")

        final = QWidget()
        final_l = QVBoxLayout(final)
        self.view = QGraphicsView()
        final_l.addWidget(self.view)
        self.tabs.addTab(final, "Final Result")

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

        a_refresh = QAction("Refresh Preview", self)
        a_refresh.triggered.connect(self.refresh_preview)
        tb.addAction(a_refresh)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project.json", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.current_project = self.workspace.load_project(path)
            self.refresh_preview()
            QMessageBox.information(self, "Loaded", path)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def import_blot(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import blot", "", "Images (*.tif *.tiff *.png *.jpg *.jpeg)")
        if not path:
            return
        try:
            digest, dest = self.workspace.import_asset(path)
            QMessageBox.information(self, "Imported", f"{dest}\nsha256={digest}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def refresh_preview(self):
        if not self.current_project:
            return
        scene = build_scene(self.current_project)
        self.view.setScene(scene)
        self.view.fitInView(scene.itemsBoundingRect(), Qt.KeepAspectRatio)
