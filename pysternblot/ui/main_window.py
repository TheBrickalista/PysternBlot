# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog,
    QMessageBox, QGraphicsView, QToolBar, QSlider, QInputDialog, QComboBox, QPushButton, QDial, QCheckBox, QSpinBox, QFrame, QSizePolicy, QFrame, QTableWidget, QTableWidgetItem, QDialog
)
from PySide6.QtGui import QAction, QPixmap, QPainter, QImage, QPdfWriter, QPageSize
from PySide6.QtCore import Qt, QEvent, QRectF, QSize
from PySide6.QtSvg import QSvgGenerator

from pathlib import Path
import uuid


from ..storage import Workspace
from ..render import build_panel_scene, build_provenance_scene
from ..models import (
    Blot, AssetEntry,
    MarkerSet, MarkerBand, MarkerSetLibrary,
    OverlayLadder, LadderBandAssignment,
)
from .legend_tab import LegendTab


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.workspace = workspace
        self.current_project = None
        self.active_blot_id = None
        self.prov_grid_visible = False

        self.pending_overlay_ladder_kda = None
        self.overlay_ladder_dialog = None
        self.overlay_ladder_assignment_table = None

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

                # --- Protein ladder presets ---
        ladder_frame = QFrame()
        ladder_frame.setFrameShape(QFrame.StyledPanel)
        ladder_frame.setStyleSheet("""
            QFrame {
                background: #f7f7f7;
                border: 1px solid #d2d2d2;
                border-radius: 8px;
            }
        """)

        ladder_l = QVBoxLayout(ladder_frame)
        ladder_l.setContentsMargins(10, 10, 10, 10)
        ladder_l.setSpacing(8)

        ladder_title = QLabel("Protein ladder presets")
        ladder_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        ladder_l.addWidget(ladder_title)

        ladder_top = QHBoxLayout()

        ladder_top.addWidget(QLabel("Preset"))

        self.marker_set_combo = QComboBox()
        self.marker_set_combo.setMinimumWidth(260)
        self.marker_set_combo.currentIndexChanged.connect(self._on_marker_set_selected)
        ladder_top.addWidget(self.marker_set_combo)

        self.marker_set_new_btn = QPushButton("New")
        self.marker_set_new_btn.clicked.connect(self._new_marker_set)
        ladder_top.addWidget(self.marker_set_new_btn)

        self.marker_set_duplicate_btn = QPushButton("Duplicate")
        self.marker_set_duplicate_btn.clicked.connect(self._duplicate_marker_set)
        ladder_top.addWidget(self.marker_set_duplicate_btn)

        self.marker_set_delete_btn = QPushButton("Delete")
        self.marker_set_delete_btn.clicked.connect(self._delete_marker_set)
        ladder_top.addWidget(self.marker_set_delete_btn)

        self.marker_set_save_btn = QPushButton("Save")
        self.marker_set_save_btn.clicked.connect(self._save_marker_set_from_ui)
        ladder_top.addWidget(self.marker_set_save_btn)

        ladder_top.addStretch(1)

        ladder_l.addLayout(ladder_top)

        self.marker_set_table = QTableWidget()
        self.marker_set_table.setColumnCount(4)
        self.marker_set_table.setHorizontalHeaderLabels([
            "kDa", "Label", "Visible", "Highlight"
        ])
        self.marker_set_table.setAlternatingRowColors(True)
        ladder_l.addWidget(self.marker_set_table)

        ladder_buttons = QHBoxLayout()

        self.marker_band_add_btn = QPushButton("Add band")
        self.marker_band_add_btn.clicked.connect(self._add_marker_band_row)
        ladder_buttons.addWidget(self.marker_band_add_btn)

        self.marker_band_remove_btn = QPushButton("Remove selected band")
        self.marker_band_remove_btn.clicked.connect(self._remove_selected_marker_band_row)
        ladder_buttons.addWidget(self.marker_band_remove_btn)

        ladder_buttons.addStretch(1)
        ladder_l.addLayout(ladder_buttons)

        lib_l.addWidget(ladder_frame)

        self.tabs.addTab(lib, "Library")

        # Final Result tab
        final = QWidget()
        final_l = QVBoxLayout(final)

        final_top = QHBoxLayout()

        self.border_cb = QCheckBox("Outline")
        self.border_cb.toggled.connect(self._on_border_toggled)
        final_top.addWidget(self.border_cb)

        final_top.addWidget(QLabel("Width"))

        self.border_width_spin = QSpinBox()
        self.border_width_spin.setRange(1, 10)
        self.border_width_spin.setValue(1)
        self.border_width_spin.valueChanged.connect(self._on_border_width_changed)
        final_top.addWidget(self.border_width_spin)

        self.final_refresh_btn = QPushButton("Refresh")
        self.final_refresh_btn.clicked.connect(self.refresh_previews)
        final_top.addWidget(self.final_refresh_btn)

        self.export_png_btn = QPushButton("Export PNG")
        self.export_png_btn.clicked.connect(self.export_final_png)
        final_top.addWidget(self.export_png_btn)

        self.export_pdf_btn = QPushButton("Export PDF")
        self.export_pdf_btn.clicked.connect(self.export_final_pdf)
        final_top.addWidget(self.export_pdf_btn)

        self.export_svg_btn = QPushButton("Export SVG")
        self.export_svg_btn.clicked.connect(self.export_final_svg)
        final_top.addWidget(self.export_svg_btn)

        final_top.addStretch(1)

        final_l.addLayout(final_top)

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

        prov_top.addSpacing(16)

        prov_top.addWidget(QLabel("Protein"))
        self.protein_label_combo = QComboBox()
        self.protein_label_combo.setEditable(True)
        self.protein_label_combo.setInsertPolicy(QComboBox.NoInsert)
        self.protein_label_combo.setMinimumWidth(180)
        self.protein_label_combo.lineEdit().editingFinished.connect(self._on_protein_label_changed)
        self.protein_label_combo.activated.connect(self._on_protein_label_changed)
        prov_top.addWidget(self.protein_label_combo)

        prov_top.addWidget(QLabel("Size"))

        self.protein_font_size_spin = QSpinBox()
        self.protein_font_size_spin.setRange(4, 48)
        self.protein_font_size_spin.setValue(9)
        self.protein_font_size_spin.valueChanged.connect(self._on_protein_font_size_changed)
        prov_top.addWidget(self.protein_font_size_spin)

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
        self.levels_black_slider.setRange(0, 65535)
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
        self.levels_white_slider.setRange(0, 65535)
        self.levels_white_slider.setValue(65535)
        self.levels_white_slider.setFixedWidth(180)
        self.levels_white_slider.valueChanged.connect(self._on_levels_changed)
        row3.addWidget(self.levels_white_slider)

        self.white_value_lbl = QLabel("65535")
        self.white_value_lbl.setMinimumWidth(30)
        row3.addWidget(self.white_value_lbl)

        row3.addStretch(1)
        display_layout.addLayout(row3)

        prov_l.addWidget(display_frame)

        # --- Overlay ladder annotation compact controls ---
        overlay_ladder_frame = QFrame()
        overlay_ladder_frame.setFrameShape(QFrame.StyledPanel)
        overlay_ladder_frame.setStyleSheet("""
            QFrame {
                background: #f4f4f4;
                border: 1px solid #d2d2d2;
                border-radius: 8px;
            }
        """)

        overlay_ladder_l = QHBoxLayout(overlay_ladder_frame)
        overlay_ladder_l.setContentsMargins(10, 8, 10, 8)
        overlay_ladder_l.setSpacing(10)

        overlay_ladder_title = QLabel("Overlay ladder")
        overlay_ladder_title.setStyleSheet("font-weight: 600; color: #333333;")
        overlay_ladder_l.addWidget(overlay_ladder_title)

        overlay_ladder_l.addWidget(QLabel("Preset"))

        self.overlay_ladder_combo = QComboBox()
        self.overlay_ladder_combo.setMinimumWidth(260)
        overlay_ladder_l.addWidget(self.overlay_ladder_combo)

        self.overlay_ladder_show_labels_cb = QCheckBox("Show labels")
        self.overlay_ladder_show_labels_cb.setChecked(True)
        overlay_ladder_l.addWidget(self.overlay_ladder_show_labels_cb)

        self.overlay_ladder_only_highlight_cb = QCheckBox("Only highlighted")
        overlay_ladder_l.addWidget(self.overlay_ladder_only_highlight_cb)

        self.overlay_ladder_save_btn = QPushButton("Save options")
        self.overlay_ladder_save_btn.clicked.connect(self._save_overlay_ladder_options)
        overlay_ladder_l.addWidget(self.overlay_ladder_save_btn)

        self.overlay_ladder_edit_btn = QPushButton("Edit assignments…")
        self.overlay_ladder_edit_btn.clicked.connect(self._open_overlay_ladder_dialog)
        overlay_ladder_l.addWidget(self.overlay_ladder_edit_btn)

        overlay_ladder_l.addStretch(1)

        prov_l.addWidget(overlay_ladder_frame)
        self.prov_view = QGraphicsView()
        self.prov_view.viewport().installEventFilter(self)
        prov_l.addWidget(self.prov_view)

        self.tabs.addTab(prov, "Provenance")

        # Legend tab
        self.legend_tab = LegendTab()
        self.legend_tab.changed.connect(self._on_legend_changed)
        self.tabs.addTab(self.legend_tab, "Legend")

        self._toolbar()

        self.refresh_library()

        self.refresh_marker_sets()

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
        self.levels_white_slider.setValue(int(getattr(getattr(blot, "display", None), "levels_white", 65535)))
        self.levels_gamma_slider.setValue(int(round(float(getattr(getattr(blot, "display", None), "levels_gamma", 1.0)) * 100.0)))
        self.invert_cb.setChecked(bool(getattr(getattr(blot, "display", None), "invert", False)))

        self.black_value_lbl.setText(str(int(getattr(getattr(blot, "display", None), "levels_black", 0))))
        self.white_value_lbl.setText(str(int(getattr(getattr(blot, "display", None), "levels_white", 65535))))
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

        protein_text = str(getattr(getattr(blot, "protein_label", None), "text", "") or "")

        self.protein_label_combo.blockSignals(True)
        self.protein_label_combo.clear()

        protein_suggestions = self._get_protein_label_suggestions()

        # also include labels already present in current project if missing
        seen = set(protein_suggestions)
        for b in self.current_project.panel.blots:
            txt = str(getattr(getattr(b, "protein_label", None), "text", "") or "").strip()
            if txt and txt not in seen:
                protein_suggestions.append(txt)
                seen.add(txt)

        self.protein_label_combo.addItems(protein_suggestions)
        self.protein_label_combo.setEditText(protein_text)

        self.protein_label_combo.blockSignals(False)

        protein_font_size = getattr(getattr(blot, "protein_label", None), "font_size_pt", None)
        if protein_font_size is None:
            protein_font_size = getattr(self.current_project.panel.style, "font_size_pt", 9)

        self.protein_font_size_spin.blockSignals(True)
        self.protein_font_size_spin.setValue(int(round(float(protein_font_size))))
        self.protein_font_size_spin.blockSignals(False)

        self._refresh_overlay_ladder_ui()

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

    def _get_protein_label_suggestions(self) -> list[str]:
        return self.workspace.load_protein_label_suggestions()

    def _add_protein_label_suggestion(self, txt: str):
        txt = (txt or "").strip()
        if not txt:
            return
        items = self.workspace.load_protein_label_suggestions()
        if txt not in items:
            items.append(txt)
            self.workspace.save_protein_label_suggestions(items)

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

        blot_id = self.prov_blot_combo.currentData()
        self.active_blot_id = blot_id

        self._update_prov_label()
        self._sync_controls_from_project()
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
                white = min(65535, black + 1)
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

            bands.append(
                MarkerBand(
                    kda=kda,
                    label=label or None,
                    visible=visible_item.checkState() == Qt.Checked if visible_item else True,
                    highlight=highlight_item.checkState() == Qt.Checked if highlight_item else False,
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

    def _remove_selected_marker_band_row(self):
        row = self.marker_set_table.currentRow()
        if row >= 0:
            self.marker_set_table.removeRow(row)

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

            blot.overlay_ladder.bands = [
                b for b in blot.overlay_ladder.bands
                if abs(float(b.kda) - kda) > 0.001
            ]

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

    def _on_protein_label_changed(self, *_args):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        text = self.protein_label_combo.currentText().strip()
        blot.protein_label.text = text

        self._add_protein_label_suggestion(text)

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_protein_font_size_changed(self, value: int):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        blot.protein_label.font_size_pt = float(value)

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

        self.current_project.marker_sets = list(self.marker_set_library.items)
        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _final_scene_and_rect(self):
        if not self.current_project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return None, None

        scene = build_panel_scene(self.current_project, self.workspace.root)
        if scene is None:
            QMessageBox.critical(self, "Export error", "Could not build final result scene.")
            return None, None

        rect = scene.itemsBoundingRect()
        if not rect.isValid() or rect.isNull():
            QMessageBox.critical(self, "Export error", "Final result scene is empty.")
            return None, None

        return scene, rect
    
    def export_final_png(self):
        scene, rect = self._final_scene_and_rect()
        if scene is None:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Final Result as PNG",
            "",
            "PNG (*.png)"
        )
        if not path:
            return

        if not path.lower().endswith(".png"):
            path += ".png"

        margin = 20
        scale = 2.0  # higher resolution export

        img = QImage(
            int((rect.width() + 2 * margin) * scale),
            int((rect.height() + 2 * margin) * scale),
            QImage.Format_ARGB32
        )
        img.fill(Qt.white)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.scale(scale, scale)

        target = QRectF(
            margin,
            margin,
            rect.width(),
            rect.height()
        )

        scene.render(painter, target, rect)
        painter.end()

        if not img.save(path):
            QMessageBox.critical(self, "Export error", "Could not save PNG.")
            return

        QMessageBox.information(self, "Exported", f"Saved PNG:\n{path}")

    def export_final_pdf(self):
        scene, rect = self._final_scene_and_rect()
        if scene is None:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Final Result as PDF",
            "",
            "PDF (*.pdf)"
        )
        if not path:
            return

        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        margin = 20

        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setResolution(300)

        painter = QPainter(writer)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        page_rect = writer.pageLayout().paintRectPixels(writer.resolution())

        scale_x = page_rect.width() / (rect.width() + 2 * margin)
        scale_y = page_rect.height() / (rect.height() + 2 * margin)
        scale = min(scale_x, scale_y)

        painter.scale(scale, scale)

        target = QRectF(
            margin,
            margin,
            rect.width(),
            rect.height()
        )

        scene.render(painter, target, rect)
        painter.end()

        QMessageBox.information(self, "Exported", f"Saved PDF:\n{path}")

    def export_final_svg(self):
        scene, rect = self._final_scene_and_rect()
        if scene is None:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Final Result as SVG",
            "",
            "SVG (*.svg)"
        )
        if not path:
            return

        if not path.lower().endswith(".svg"):
            path += ".svg"

        margin = 20

        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(
            QSize(
                int(rect.width() + 2 * margin),
                int(rect.height() + 2 * margin)
            )
        )
        generator.setViewBox(
            QRectF(
                0,
                0,
                rect.width() + 2 * margin,
                rect.height() + 2 * margin
            )
        )
        generator.setTitle("Pystern Blot Final Result")
        generator.setDescription("Exported from Pystern Blot")

        painter = QPainter(generator)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        target = QRectF(
            margin,
            margin,
            rect.width(),
            rect.height()
        )

        scene.render(painter, target, rect)
        painter.end()

        QMessageBox.information(self, "Exported", f"Saved SVG:\n{path}")