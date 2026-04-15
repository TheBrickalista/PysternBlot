# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog,
    QMessageBox, QGraphicsView, QToolBar, QSlider, QInputDialog, QComboBox, QPushButton, QDial, QCheckBox, QSpinBox, QFrame, QSizePolicy, QFrame, QTableWidget, QTableWidgetItem 
)
from PySide6.QtGui import QAction, QPixmap
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
        self.prov_grid_visible = False

        self.setWindowTitle("Pystern Blot")
        self.resize(1100, 700)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Home tab
        home = self._build_home_tab()
        self.tabs.addTab(home, "Home")

        # Library tab
        lib = QWidget()
        lib_l = QVBoxLayout(lib)
        lib_l.setContentsMargins(16, 16, 16, 16)
        lib_l.setSpacing(10)

        lib_top = QHBoxLayout()
        lib_title = QLabel("Projects")
        lib_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lib_top.addWidget(lib_title)

        lib_top.addStretch(1)

        self.lib_refresh_btn = QPushButton("Refresh Library")
        self.lib_refresh_btn.clicked.connect(self.refresh_library)
        lib_top.addWidget(self.lib_refresh_btn)

        lib_l.addLayout(lib_top)

        self.library_table = QTableWidget()
        self.library_table.setColumnCount(6)
        self.library_table.setHorizontalHeaderLabels([
            "Name", "Project ID", "Created", "Modified", "# Blots", "Path"
        ])
        self.library_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.library_table.setSelectionMode(QTableWidget.SingleSelection)
        self.library_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.library_table.setAlternatingRowColors(True)
        self.library_table.cellDoubleClicked.connect(self._open_project_from_library)

        lib_l.addWidget(self.library_table)

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

        prov_top.addWidget(QLabel("Rotate"))

        self.prov_rotate_dial = QDial()
        self.prov_rotate_dial.setRange(-100, 100)   # maps to -10.0° to +10.0°
        self.prov_rotate_dial.setSingleStep(1)
        self.prov_rotate_dial.setNotchesVisible(True)
        self.prov_rotate_dial.valueChanged.connect(self._on_rotation_changed)
        prov_top.addWidget(self.prov_rotate_dial)

        self.prov_rotate_label = QLabel("0.0°")
        prov_top.addWidget(self.prov_rotate_label)

        self.prov_grid_cb = QCheckBox("Grid")
        self.prov_grid_cb.toggled.connect(self._on_prov_grid_toggled)
        prov_top.addWidget(self.prov_grid_cb)

        prov_top.addStretch(1)

        prov_l.addLayout(prov_top)

        self.prov_label = QLabel("Current blot: —")
        prov_l.addWidget(self.prov_label)

        # --- Display controls frame ---
        display_frame = QFrame()
        display_frame.setFrameShape(QFrame.StyledPanel)
        display_frame.setStyleSheet("""
            QFrame {
                background: #f4f4f4;
                border: 1px solid #d2d2d2;
                border-radius: 8px;
            }
        """)
        display_layout = QVBoxLayout(display_frame)
        display_layout.setContentsMargins(10, 8, 10, 10)
        display_layout.setSpacing(8)

        display_title = QLabel("Display")
        display_title.setStyleSheet("font-weight: 600; color: #333333;")
        display_layout.addWidget(display_title)

        # Row 1: Overlay + Alpha
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        self.overlay_cb = QCheckBox("Overlay")
        self.overlay_cb.toggled.connect(self.toggle_overlay)
        row1.addWidget(self.overlay_cb)

        alpha_lbl = QLabel("Alpha")
        alpha_lbl.setMinimumWidth(45)
        row1.addWidget(alpha_lbl)

        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setMinimum(0)
        self.alpha_slider.setMaximum(100)
        self.alpha_slider.setValue(35)
        self.alpha_slider.setFixedWidth(160)
        self.alpha_slider.valueChanged.connect(self.change_overlay_alpha)
        row1.addWidget(self.alpha_slider)

        self.alpha_value_lbl = QLabel("35")
        self.alpha_value_lbl.setMinimumWidth(30)
        row1.addWidget(self.alpha_value_lbl)

        row1.addStretch(1)
        display_layout.addLayout(row1)

        # Row 2: Invert + Gamma
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.invert_cb = QCheckBox("Invert")
        self.invert_cb.toggled.connect(self._on_invert_toggled)
        row2.addWidget(self.invert_cb)

        gamma_lbl = QLabel("Gamma")
        gamma_lbl.setMinimumWidth(45)
        row2.addWidget(gamma_lbl)

        self.levels_gamma_slider = QSlider(Qt.Horizontal)
        self.levels_gamma_slider.setRange(10, 300)
        self.levels_gamma_slider.setValue(100)
        self.levels_gamma_slider.setFixedWidth(160)
        self.levels_gamma_slider.valueChanged.connect(self._on_levels_changed)
        row2.addWidget(self.levels_gamma_slider)

        self.gamma_value_lbl = QLabel("1.00")
        self.gamma_value_lbl.setMinimumWidth(40)
        row2.addWidget(self.gamma_value_lbl)

        row2.addStretch(1)
        display_layout.addLayout(row2)

        # Row 3: Black + White
        row3 = QHBoxLayout()
        row3.setSpacing(10)

        black_lbl = QLabel("Black")
        black_lbl.setMinimumWidth(45)
        row3.addWidget(black_lbl)

        self.levels_black_slider = QSlider(Qt.Horizontal)
        self.levels_black_slider.setRange(0, 255)
        self.levels_black_slider.setValue(0)
        self.levels_black_slider.setFixedWidth(180)
        self.levels_black_slider.valueChanged.connect(self._on_levels_changed)
        row3.addWidget(self.levels_black_slider)

        self.black_value_lbl = QLabel("0")
        self.black_value_lbl.setMinimumWidth(30)
        row3.addWidget(self.black_value_lbl)

        row3.addSpacing(16)

        white_lbl = QLabel("White")
        white_lbl.setMinimumWidth(45)
        row3.addWidget(white_lbl)

        self.levels_white_slider = QSlider(Qt.Horizontal)
        self.levels_white_slider.setRange(0, 255)
        self.levels_white_slider.setValue(255)
        self.levels_white_slider.setFixedWidth(180)
        self.levels_white_slider.valueChanged.connect(self._on_levels_changed)
        row3.addWidget(self.levels_white_slider)

        self.white_value_lbl = QLabel("255")
        self.white_value_lbl.setMinimumWidth(30)
        row3.addWidget(self.white_value_lbl)

        row3.addStretch(1)
        display_layout.addLayout(row3)

        prov_l.addWidget(display_frame)

        self.prov_view = QGraphicsView()
        prov_l.addWidget(self.prov_view)

        self.tabs.addTab(prov, "Provenance")

        # Legend tab
        self.legend_tab = LegendTab()
        self.legend_tab.changed.connect(self._on_legend_changed)
        self.tabs.addTab(self.legend_tab, "Legend")

        self._toolbar()

        self.refresh_library()

    def _build_home_tab(self) -> QWidget:
        home = QWidget()
        root = QVBoxLayout(home)
        root.setContentsMargins(30, 30, 30, 30)
        root.setSpacing(14)

        root.addStretch(1)

        # --- Logo ---
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)

        logo_path = Path(__file__).parent.parent / "resources" / "pb_logo.png"
        if logo_path.exists():
            pm = QPixmap(str(logo_path))
            if not pm.isNull():
                pm = pm.scaledToWidth(500, Qt.SmoothTransformation)
                logo_label.setPixmap(pm)
            else:
                logo_label.setText("Logo load failed")
        else:
            logo_label.setText("Logo not found")

        root.addWidget(logo_label)

        # Title block
        title_wrap = QWidget()
        title_layout = QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)

        title = QLabel("Pystern Blot")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: 700; color: #222222;")
        title_layout.addWidget(title)

        subtitle = QLabel("Organize, crop and assemble publication-ready blot panels")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #666666;")
        title_layout.addWidget(subtitle)

        root.addWidget(title_wrap)

        # Button row
        btn_row_wrap = QWidget()
        btn_row = QHBoxLayout(btn_row_wrap)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(18)

        btn_row.addStretch(1)

        new_btn = self._make_home_button("New Project", self.new_project)
        open_btn = self._make_home_button("Open Project", self.open_project)
        import_btn = self._make_home_button("Import Blot", self.import_blot)

        btn_row.addWidget(new_btn)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(import_btn)

        btn_row.addStretch(1)

        root.addWidget(btn_row_wrap)

        root.addStretch(2)

        return home
    
    def _make_home_button(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        btn.setMinimumSize(170, 80)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn.setStyleSheet("""
            QPushButton {
                background: #f4f4f4;
                border: 1px solid #d2d2d2;
                border-radius: 10px;
                padding: 12px 18px;
                font-size: 14px;
                font-weight: 600;
                color: #222222;
            }
            QPushButton:hover {
                background: #ebebeb;
                border: 1px solid #bfbfbf;
            }
            QPushButton:pressed {
                background: #e0e0e0;
            }
        """)
        return btn

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

        self.border_cb = QCheckBox("Outline")
        self.border_cb.toggled.connect(self._on_border_toggled)
        tb.addWidget(self.border_cb)

        tb.addWidget(QLabel("Width"))
        self.border_width_spin = QSpinBox()
        self.border_width_spin.setRange(1, 10)
        self.border_width_spin.setValue(1)
        self.border_width_spin.valueChanged.connect(self._on_border_width_changed)
        tb.addWidget(self.border_width_spin)

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
                    "overlay_visible": True,
                    "rotation_deg": 0.0,
                    "levels_black": 0,
                    "levels_white": 255,
                    "levels_gamma": 1.0,
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

    def _sync_controls_from_project(self):
        self._populate_prov_blot_combo()
        self._update_prov_label()
        blot = self._get_active_blot()
        if not blot:
            return
        
        rotation_deg = float(getattr(getattr(blot, "display", None), "rotation_deg", 0.0) or 0.0)

        self.prov_rotate_dial.blockSignals(True)
        self.prov_rotate_dial.setValue(int(round(rotation_deg * 10.0)))
        self.prov_rotate_dial.blockSignals(False)

        self.prov_rotate_label.setText(f"{rotation_deg:.1f}°")

        self.prov_grid_cb.blockSignals(True)
        self.prov_grid_cb.setChecked(bool(self.prov_grid_visible))
        self.prov_grid_cb.blockSignals(False)

        self.levels_black_slider.blockSignals(True)
        self.levels_white_slider.blockSignals(True)
        self.levels_gamma_slider.blockSignals(True)
        self.invert_cb.blockSignals(True)

        self.levels_black_slider.setValue(int(getattr(getattr(blot, "display", None), "levels_black", 0)))
        self.levels_white_slider.setValue(int(getattr(getattr(blot, "display", None), "levels_white", 255)))
        self.levels_gamma_slider.setValue(int(round(float(getattr(getattr(blot, "display", None), "levels_gamma", 1.0)) * 100.0)))
        self.invert_cb.setChecked(bool(getattr(getattr(blot, "display", None), "invert", False)))

        self.black_value_lbl.setText(str(int(getattr(getattr(blot, "display", None), "levels_black", 0))))
        self.white_value_lbl.setText(str(int(getattr(getattr(blot, "display", None), "levels_white", 255))))
        self.gamma_value_lbl.setText(f"{float(getattr(getattr(blot, 'display', None), 'levels_gamma', 1.0)):.2f}")

        self.levels_black_slider.blockSignals(False)
        self.levels_white_slider.blockSignals(False)
        self.levels_gamma_slider.blockSignals(False)
        self.invert_cb.blockSignals(False)

        # Default values if fields aren’t present yet
        overlay_vis = getattr(getattr(blot, "display", None), "overlay_visible", True)
        overlay_alpha = float(getattr(getattr(blot, "display", None), "overlay_alpha", 0.35))

        self.overlay_cb.blockSignals(True)
        self.alpha_slider.blockSignals(True)

        self.overlay_cb.setChecked(bool(overlay_vis))
        self.alpha_slider.setValue(int(round(overlay_alpha * 100)))
        self.alpha_value_lbl.setText(str(int(round(overlay_alpha * 100))))

        self.overlay_cb.blockSignals(False)
        self.alpha_slider.blockSignals(False)

        self.border_cb.blockSignals(True)
        self.border_width_spin.blockSignals(True)

        self.border_cb.setChecked(bool(getattr(self.current_project.panel.style, "border_enabled", True)))
        self.border_width_spin.setValue(int(getattr(self.current_project.panel.style, "border_width_px", 1)))

        self.border_cb.blockSignals(False)
        self.border_width_spin.blockSignals(False)

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
        self.alpha_value_lbl.setText(str(value))
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
            on_crop_commit=self._on_crop_commit,
            show_grid=self.prov_grid_visible
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

    def _on_rotation_changed(self, value: int):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        # Map dial integer to degrees
        rotation_deg = float(value) / 10.0
        blot.display.rotation_deg = rotation_deg

        self.prov_rotate_label.setText(f"{rotation_deg:.1f}°")
        self.workspace.save_project(self.current_project)
        self.refresh_previews()


    def _on_prov_grid_toggled(self, checked: bool):
        self.prov_grid_visible = bool(checked)
        self.refresh_previews()

    def _on_levels_changed(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        black = int(self.levels_black_slider.value())
        white = int(self.levels_white_slider.value())
        gamma = float(self.levels_gamma_slider.value()) / 100.0

        sender = self.sender()

        if white <= black:
            if sender is self.levels_black_slider:
                white = min(255, black + 1)
                self.levels_white_slider.blockSignals(True)
                self.levels_white_slider.setValue(white)
                self.levels_white_slider.blockSignals(False)
            else:
                black = max(0, white - 1)
                self.levels_black_slider.blockSignals(True)
                self.levels_black_slider.setValue(black)
                self.levels_black_slider.blockSignals(False)

        blot.display.levels_black = black
        blot.display.levels_white = white
        blot.display.levels_gamma = gamma

        self.black_value_lbl.setText(str(black))
        self.white_value_lbl.setText(str(white))
        self.gamma_value_lbl.setText(f"{gamma:.2f}")

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_invert_toggled(self, checked: bool):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        blot.display.invert = bool(checked)
        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_border_toggled(self, checked: bool):
        if not self.current_project:
            return
        self.current_project.panel.style.border_enabled = bool(checked)
        self.workspace.save_project(self.current_project)
        self._refresh_final_only(fit=True)

    def _on_border_width_changed(self, value: int):
        if not self.current_project:
            return
        self.current_project.panel.style.border_width_px = int(value)
        self.workspace.save_project(self.current_project)
        self._refresh_final_only(fit=True)

    def refresh_library(self):
        """
        Scan workspace/projects/*/project.json and populate the Library table.
        """
        self.library_table.setRowCount(0)

        projects_root = self.workspace.projects_dir
        if not projects_root.exists():
            return

        rows = []

        for project_json in sorted(projects_root.glob("*/project.json")):
            try:
                project = self.workspace.load_project(str(project_json))

                name = getattr(project.project, "name", "")
                project_id = getattr(project.project, "id", "")
                created = getattr(project.project, "created_utc", "")
                modified = getattr(project.project, "modified_utc", "")
                n_blots = len(getattr(project.panel, "blots", []) or [])

                rows.append({
                    "name": name,
                    "project_id": project_id,
                    "created": created,
                    "modified": modified,
                    "n_blots": n_blots,
                    "path": str(project_json),
                })

            except Exception as e:
                print(f"[library] failed to read {project_json}: {e}")

        # Sort by modified descending
        rows.sort(key=lambda r: r["modified"], reverse=True)

        self.library_table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            self.library_table.setItem(row_idx, 0, QTableWidgetItem(str(row["name"])))
            self.library_table.setItem(row_idx, 1, QTableWidgetItem(str(row["project_id"])))
            self.library_table.setItem(row_idx, 2, QTableWidgetItem(str(row["created"])))
            self.library_table.setItem(row_idx, 3, QTableWidgetItem(str(row["modified"])))
            self.library_table.setItem(row_idx, 4, QTableWidgetItem(str(row["n_blots"])))
            self.library_table.setItem(row_idx, 5, QTableWidgetItem(str(row["path"])))

        self.library_table.resizeColumnsToContents()
        self.library_table.setColumnWidth(5, 360)  # path column

    def _open_project_from_library(self, row: int, _column: int):
        item = self.library_table.item(row, 5)  # path column
        if item is None:
            return

        path = item.text().strip()
        if not path:
            return

        try:
            self.current_project = self.workspace.load_project(path)
            self._sync_controls_from_project()
            self.legend_tab.bind(
                self.current_project,
                self._get_legend_suggestions,
                self._add_legend_suggestion
            )
            self.refresh_previews()
            self.tabs.setCurrentIndex(2)  # Final Result tab with current ordering: Home, Library, Final Result...
        except Exception as e:
            QMessageBox.critical(self, "Error opening project", str(e))