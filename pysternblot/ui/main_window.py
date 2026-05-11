# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QGraphicsView, QToolBar, QSlider, QComboBox, QPushButton, QDial, QCheckBox, QSpinBox, QFrame, QSizePolicy, QFrame, QTableWidget, QTableWidgetItem, QRadioButton, QButtonGroup
)
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtCore import Qt

import re
from pathlib import Path

from ..storage import Workspace
from ..render import build_panel_scene, build_provenance_scene
from ..models import (
    Blot,
)
from .legend_tab import LegendTab
from .zoomable_graphics_view import ZoomableGraphicsView

from .project_io_mixin import _ProjectIOMixin
from .marker_set_mixin import _MarkerSetMixin
from .overlay_ladder_mixin import _OverlayLadderMixin
from .export_mixin import _ExportMixin


class MainWindow(_ProjectIOMixin, _MarkerSetMixin, _OverlayLadderMixin, _ExportMixin, QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.workspace = workspace
        self.current_project = None
        self.active_blot_id = None
        self.prov_grid_visible = False
        self._active_nir_channel = 0
        self._nir_ch_btn_group = None

        self.pending_overlay_ladder_kda = None
        self.overlay_ladder_dialog = None
        self.overlay_ladder_assignment_table = None

        self.setWindowTitle("Pystern Blot")
        self.setMinimumSize(900, 600)
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
        self.library_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.library_table.customContextMenuRequested.connect(self._on_library_context_menu)

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

        self.tabs.addTab(lib, "Preferences")

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

        self.export_integrity_btn = QPushButton("Export Integrity Report")
        self.export_integrity_btn.clicked.connect(self.export_integrity_report)
        final_top.addWidget(self.export_integrity_btn)

        self.export_detailed_integrity_btn = QPushButton("Export Detailed Report")
        self.export_detailed_integrity_btn.clicked.connect(self.export_detailed_integrity_report)
        final_top.addWidget(self.export_detailed_integrity_btn)

        final_top.addStretch(1)

        final_l.addLayout(final_top)

        self.view = QGraphicsView()
        final_l.addWidget(self.view)

        self.tabs.addTab(final, "Figure")

        # Provenance tab
        prov = QWidget()
        prov_l = QVBoxLayout(prov)

        prov_rows = QVBoxLayout()
        prov_rows.setSpacing(4)

        prov_row1 = QHBoxLayout()
        prov_row1.addWidget(QLabel("Blot"))
        self.prov_blot_combo = QComboBox()
        self.prov_blot_combo.currentIndexChanged.connect(self._on_active_blot_changed)
        prov_row1.addWidget(self.prov_blot_combo)

        self.prov_up_btn = QPushButton("Up")
        self.prov_up_btn.clicked.connect(self._move_active_blot_up)
        prov_row1.addWidget(self.prov_up_btn)

        self.prov_down_btn = QPushButton("Down")
        self.prov_down_btn.clicked.connect(self._move_active_blot_down)
        prov_row1.addWidget(self.prov_down_btn)

        prov_row1.addWidget(QLabel("Rotate"))

        self.prov_rotate_dial = QDial()
        self.prov_rotate_dial.setRange(-100, 100)   # maps to -10.0° to +10.0°
        self.prov_rotate_dial.setSingleStep(1)
        self.prov_rotate_dial.setNotchesVisible(True)
        self.prov_rotate_dial.valueChanged.connect(self._on_rotation_changed)
        prov_row1.addWidget(self.prov_rotate_dial)

        self.prov_rotate_label = QLabel("0.0°")
        prov_row1.addWidget(self.prov_rotate_label)

        prov_row1.addSpacing(8)

        self._rotate_ccw_btn = QPushButton("↺")
        self._rotate_ccw_btn.setFixedWidth(32)
        self._rotate_ccw_btn.setToolTip("Rotate 90° counter-clockwise")
        self._rotate_ccw_btn.clicked.connect(self._on_rotate_ccw)
        prov_row1.addWidget(self._rotate_ccw_btn)

        self._rotate_cw_btn = QPushButton("↻")
        self._rotate_cw_btn.setFixedWidth(32)
        self._rotate_cw_btn.setToolTip("Rotate 90° clockwise")
        self._rotate_cw_btn.clicked.connect(self._on_rotate_cw)
        prov_row1.addWidget(self._rotate_cw_btn)

        self._flip_h_btn = QPushButton("⇔")
        self._flip_h_btn.setFixedWidth(32)
        self._flip_h_btn.setCheckable(True)
        self._flip_h_btn.setToolTip("Flip horizontal (mirror left-right)")
        self._flip_h_btn.clicked.connect(self._on_flip_horizontal)
        prov_row1.addWidget(self._flip_h_btn)

        self._flip_v_btn = QPushButton("↕")
        self._flip_v_btn.setFixedWidth(32)
        self._flip_v_btn.setCheckable(True)
        self._flip_v_btn.setToolTip("Flip vertical (mirror top-bottom)")
        self._flip_v_btn.clicked.connect(self._on_flip_vertical)
        prov_row1.addWidget(self._flip_v_btn)

        prov_row1.addSpacing(8)

        self.prov_grid_cb = QCheckBox("Grid")
        self.prov_grid_cb.toggled.connect(self._on_prov_grid_toggled)
        prov_row1.addWidget(self.prov_grid_cb)

        self.prov_fit_btn = QPushButton("Fit")
        self.prov_fit_btn.clicked.connect(lambda: self.prov_view.fit_scene())
        prov_row1.addWidget(self.prov_fit_btn)

        self.export_original_tiff_btn = QPushButton("Export Original TIFF")
        self.export_original_tiff_btn.clicked.connect(self.export_current_original_tiff)
        prov_row1.addWidget(self.export_original_tiff_btn)

        self.export_all_original_tiff_btn = QPushButton("Export All Originals")
        self.export_all_original_tiff_btn.clicked.connect(self.export_all_original_tiffs)
        prov_row1.addWidget(self.export_all_original_tiff_btn)

        prov_row1.addStretch(1)

        prov_row2 = QHBoxLayout()

        # NIR channel selector — hidden for ECL blots, shown for multi-channel NIR
        self._nir_ch_widget = QWidget()
        self._nir_ch_layout = QHBoxLayout(self._nir_ch_widget)
        self._nir_ch_layout.setContentsMargins(0, 0, 8, 0)
        self._nir_ch_layout.setSpacing(6)
        self._nir_ch_widget.setVisible(False)
        prov_row2.addWidget(self._nir_ch_widget)

        prov_row2.addWidget(QLabel("Protein"))
        self.protein_label_combo = QComboBox()
        self.protein_label_combo.setEditable(True)
        self.protein_label_combo.setInsertPolicy(QComboBox.NoInsert)
        self.protein_label_combo.setMinimumWidth(180)
        self.protein_label_combo.lineEdit().editingFinished.connect(self._on_protein_label_changed)
        self.protein_label_combo.activated.connect(self._on_protein_label_changed)
        prov_row2.addWidget(self.protein_label_combo)

        prov_row2.addWidget(QLabel("Antibody"))
        self.antibody_name_combo = QComboBox()
        self.antibody_name_combo.setEditable(True)
        self.antibody_name_combo.setInsertPolicy(QComboBox.NoInsert)
        self.antibody_name_combo.setMinimumWidth(180)
        self.antibody_name_combo.lineEdit().editingFinished.connect(self._on_antibody_name_changed)
        self.antibody_name_combo.activated.connect(self._on_antibody_name_changed)
        prov_row2.addWidget(self.antibody_name_combo)

        prov_row2.addWidget(QLabel("Size"))

        self.protein_font_size_spin = QSpinBox()
        self.protein_font_size_spin.setRange(4, 48)
        self.protein_font_size_spin.setValue(9)
        self.protein_font_size_spin.valueChanged.connect(self._on_protein_font_size_changed)
        prov_row2.addWidget(self.protein_font_size_spin)

        self.include_in_final_cb = QCheckBox("Include in final figure")
        self.include_in_final_cb.setChecked(True)
        self.include_in_final_cb.toggled.connect(self._on_include_in_final_toggled)
        prov_row2.addWidget(self.include_in_final_cb)

        prov_row2.addStretch(1)

        prov_rows.addLayout(prov_row1)
        prov_rows.addLayout(prov_row2)
        prov_l.addLayout(prov_rows)

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

        overlay_ladder_l.addSpacing(16)
        overlay_ladder_l.addWidget(QLabel("MW label size"))

        self.mw_label_size_spin = QSpinBox()
        self.mw_label_size_spin.setRange(4, 72)
        self.mw_label_size_spin.setValue(24)
        self.mw_label_size_spin.setSuffix(" pt")
        self.mw_label_size_spin.valueChanged.connect(self._on_mw_label_size_changed)
        overlay_ladder_l.addWidget(self.mw_label_size_spin)

        overlay_ladder_l.addStretch(1)

        prov_l.addWidget(overlay_ladder_frame)
        self.prov_view = ZoomableGraphicsView()
        self.prov_view.viewport().installEventFilter(self)
        prov_l.addWidget(self.prov_view)

        self.tabs.addTab(prov, "Original Image")

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
        export_lib_btn = self._make_home_button("Export Library…", self.export_library)
        import_lib_btn = self._make_home_button("Import Library…", self.import_library)

        btn_row.addWidget(new_btn)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(export_lib_btn)
        btn_row.addWidget(import_lib_btn)

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

        a_import_nir = QAction("Import NIR Blot…", self)
        a_import_nir.triggered.connect(self._on_import_nir_blot)
        tb.addAction(a_import_nir)

        a_import_mem = QAction("Import Membrane…", self)
        a_import_mem.triggered.connect(self.import_membrane)
        tb.addAction(a_import_mem)

        tb.addSeparator()

        a_export_lib = QAction("Export Library…", self)
        a_export_lib.triggered.connect(self.export_library)
        tb.addAction(a_export_lib)

        a_import_lib = QAction("Import Library…", self)
        a_import_lib.triggered.connect(self.import_library)
        tb.addAction(a_import_lib)

    def _sync_controls_from_project(self):
        self._populate_prov_blot_combo()
        self._update_prov_label()
        blot = self._get_active_blot()
        if not blot:
            return

        self._rebuild_nir_channel_selector(blot)

        _display = self._active_display() or blot.display
        rotation_deg = float(getattr(_display, "rotation_deg", 0.0) or 0.0)

        self.prov_rotate_dial.blockSignals(True)
        self.prov_rotate_dial.setValue(int(round(rotation_deg * 10.0)))
        self.prov_rotate_dial.blockSignals(False)

        self.prov_rotate_label.setText(f"{rotation_deg:.1f}°")

        self._flip_h_btn.blockSignals(True)
        self._flip_v_btn.blockSignals(True)
        self._flip_h_btn.setChecked(bool(getattr(_display, "flip_horizontal", False)))
        self._flip_v_btn.setChecked(bool(getattr(_display, "flip_vertical", False)))
        self._flip_h_btn.blockSignals(False)
        self._flip_v_btn.blockSignals(False)

        self.prov_grid_cb.blockSignals(True)
        self.prov_grid_cb.setChecked(bool(self.prov_grid_visible))
        self.prov_grid_cb.blockSignals(False)

        self.levels_black_slider.blockSignals(True)
        self.levels_white_slider.blockSignals(True)
        self.levels_gamma_slider.blockSignals(True)
        self.invert_cb.blockSignals(True)

        self.levels_black_slider.setValue(int(getattr(_display, "levels_black", 0)))
        self.levels_white_slider.setValue(int(getattr(_display, "levels_white", 65535)))
        self.levels_gamma_slider.setValue(int(round(float(getattr(_display, "levels_gamma", 1.0)) * 100.0)))
        self.invert_cb.setChecked(bool(getattr(_display, "invert", False)))

        self.black_value_lbl.setText(str(int(getattr(_display, "levels_black", 0))))
        self.white_value_lbl.setText(str(int(getattr(_display, "levels_white", 65535))))
        self.gamma_value_lbl.setText(f"{float(getattr(_display, 'levels_gamma', 1.0)):.2f}")

        self.levels_black_slider.blockSignals(False)
        self.levels_white_slider.blockSignals(False)
        self.levels_gamma_slider.blockSignals(False)
        self.invert_cb.blockSignals(False)

        # Overlay settings remain on blot.display (ECL-only concept)
        overlay_vis = getattr(blot.display, "overlay_visible", True)
        overlay_alpha = float(getattr(blot.display, "overlay_alpha", 0.35))

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

        _target = self._get_active_channel_or_blot()
        protein_text = str(getattr(getattr(_target, "protein_label", None), "text", "") or "")

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

        antibody_text = str(getattr(_target, "antibody_name", "") or "")

        self.antibody_name_combo.blockSignals(True)
        self.antibody_name_combo.clear()

        antibody_suggestions = self._get_antibody_name_suggestions()

        seen_ab = set(antibody_suggestions)
        for b in self.current_project.panel.blots:
            txt = str(getattr(b, "antibody_name", "") or "").strip()
            if txt and txt not in seen_ab:
                antibody_suggestions.append(txt)
                seen_ab.add(txt)

        self.antibody_name_combo.addItems(antibody_suggestions)
        self.antibody_name_combo.setEditText(antibody_text)

        self.antibody_name_combo.blockSignals(False)

        protein_font_size = getattr(getattr(_target, "protein_label", None), "font_size_pt", None)
        if protein_font_size is None:
            protein_font_size = getattr(self.current_project.panel.style, "font_size_pt", 9)

        self.protein_font_size_spin.blockSignals(True)
        self.protein_font_size_spin.setValue(int(round(float(protein_font_size))))
        self.protein_font_size_spin.blockSignals(False)

        self.include_in_final_cb.blockSignals(True)
        self.include_in_final_cb.setChecked(bool(getattr(blot, "included_in_final", True)))
        self.include_in_final_cb.blockSignals(False)

        self.mw_label_size_spin.blockSignals(True)
        self.mw_label_size_spin.setValue(
            int(round(float(getattr(self.current_project.panel.style, "kda_label_font_size_pt", 24.0))))
        )
        self.mw_label_size_spin.blockSignals(False)

        self._refresh_overlay_ladder_ui()

    def _on_legend_changed(self):
        if not self.current_project:
            return
        self.workspace.save_project(self.current_project)
        self._refresh_final_only(fit=True)

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
        if not self.current_project:
            return

        self.log_operation(
            "crop_committed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="crop",
            old_value=None,
            new_value=blot.crop,
            note="Crop rectangle committed after user interaction.",
        )

        # Persist the updated crop coordinates
        self.workspace.save_project(self.current_project)

        # Rebuild cached preview_crop for this blot (all channels for NIR)
        if blot.is_nir():
            for ch in blot.channels:
                try:
                    self.workspace.ensure_blot_crop_preview(
                        blot, self.current_project.panel, channel_index=ch.channel_index
                    )
                except Exception as e:
                    print(f"[preview] failed for {getattr(blot, 'id', '?')} ch{ch.channel_index}: {e}")
        else:
            try:
                self.workspace.ensure_blot_crop_preview(blot, self.current_project.panel)
            except Exception as e:
                print(f"[preview] failed for {getattr(blot, 'id', '?')}: {e}")

        # Refresh ONLY the final result scene (avoid resetting the crop rect mid-drag)
        panel_scene = build_panel_scene(self.current_project, self.workspace.root)
        self.view.setScene(panel_scene)
        self.view.fitInView(panel_scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def _on_mw_label_size_changed(self, value: int):
        if not self.current_project:
            return

        old = float(self.current_project.panel.style.kda_label_font_size_pt)
        new = float(value)

        self.current_project.panel.style.kda_label_font_size_pt = new

        self.log_operation(
            "kda_label_font_size_changed",
            target_type="project",
            target_id=self.current_project.project.id,
            field="panel.style.kda_label_font_size_pt",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self._refresh_final_only(fit=False)

    def _on_crop_resize_commit(self):
        """Called when the crop rectangle is resized (affects all blots via crop_template)."""
        if not self.current_project:
            return

        self.log_operation(
            "crop_template_resized",
            target_type="project",
            target_id=self.current_project.project.id,
            field="panel.crop_template",
            old_value=None,
            new_value={"w": self.current_project.panel.crop_template.w,
                       "h": self.current_project.panel.crop_template.h},
            note="Crop template resized; all blot previews regenerated.",
        )

        self.workspace.save_project(self.current_project)

        for blot in self.current_project.panel.blots:
            if blot.is_nir():
                for ch in blot.channels:
                    try:
                        self.workspace.ensure_blot_crop_preview(
                            blot, self.current_project.panel, channel_index=ch.channel_index
                        )
                    except Exception as e:
                        print(f"[preview] resize regen failed for {getattr(blot, 'id', '?')} ch{ch.channel_index}: {e}")
            else:
                try:
                    self.workspace.ensure_blot_crop_preview(blot, self.current_project.panel)
                except Exception as e:
                    print(f"[preview] resize regen failed for {getattr(blot, 'id', '?')}: {e}")

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

    def _get_antibody_name_suggestions(self) -> list[str]:
        return self.workspace.load_antibody_name_suggestions()

    def _add_antibody_name_suggestion(self, txt: str):
        txt = (txt or "").strip()
        if not txt:
            return
        items = self.workspace.load_antibody_name_suggestions()
        if txt not in items:
            items.append(txt)
            self.workspace.save_antibody_name_suggestions(items)

    def _get_active_channel_or_blot(self):
        """Return the active BlotChannel for NIR blots, or the blot itself for ECL.
        Centralises ECL/NIR dispatch for protein_label and antibody_name access."""
        blot = self._get_active_blot()
        if blot is None:
            return None
        if blot.is_nir() and blot.channels:
            idx = min(self._active_nir_channel, len(blot.channels) - 1)
            return blot.channels[idx]
        return blot

    def _active_display(self):
        """Return the DisplaySettings for the active channel (NIR) or blot (ECL)."""
        blot = self._get_active_blot()
        if blot is None:
            return None
        if blot.is_nir() and blot.channels:
            idx = min(self._active_nir_channel, len(blot.channels) - 1)
            return blot.channels[idx].display
        return blot.display

    def _rebuild_nir_channel_selector(self, blot) -> None:
        """Clear and rebuild the NIR channel radio buttons for the given blot.
        Hides the selector for ECL blots and single-channel NIR blots."""
        if self._nir_ch_btn_group is not None:
            self._nir_ch_btn_group.deleteLater()
            self._nir_ch_btn_group = None

        while self._nir_ch_layout.count():
            item = self._nir_ch_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not blot or not blot.is_nir() or len(blot.channels) <= 1:
            self._active_nir_channel = 0
            self._nir_ch_widget.setVisible(False)
            return

        self._nir_ch_widget.setVisible(True)
        lbl = QLabel("Channel:")
        self._nir_ch_layout.addWidget(lbl)

        btn_group = QButtonGroup(self._nir_ch_widget)
        for ch in blot.channels:
            label = f"Ch{ch.channel_index + 1}"
            if ch.wavelength_nm:
                label += f" — {ch.wavelength_nm}nm"
            if ch.filter_name:
                label += f" {ch.filter_name}"
            rb = QRadioButton(label)
            btn_group.addButton(rb, ch.channel_index)
            self._nir_ch_layout.addWidget(rb)

        # Set checked state before connecting — idClicked fires only on user click
        for ch in blot.channels:
            btn = btn_group.button(ch.channel_index)
            if btn:
                btn.setChecked(ch.channel_index == self._active_nir_channel)

        btn_group.idClicked.connect(self._on_nir_channel_changed)
        self._nir_ch_btn_group = btn_group

    def _on_nir_channel_changed(self, channel_index: int) -> None:
        self._active_nir_channel = channel_index
        self._sync_controls_from_project()
        self.refresh_previews()

    def toggle_overlay(self, checked: bool):
        blot = self._get_active_blot()
        if not blot or not self.current_project:
            return

        old = bool(blot.display.overlay_visible)
        new = bool(checked)

        blot.display.overlay_visible = new

        self.log_operation(
            "overlay_visible_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.overlay_visible",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def change_overlay_alpha(self, value: int):
        blot = self._get_active_blot()
        if not blot or not self.current_project:
            return

        old = float(blot.display.overlay_alpha)
        new = float(value) / 100.0

        blot.display.overlay_alpha = new
        self.alpha_value_lbl.setText(str(value))

        self.log_operation(
            "overlay_alpha_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.overlay_alpha",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def refresh_previews(self):
        if not self.current_project:
            return

        self._populate_prov_blot_combo()
        self._update_prov_label()

        # Ensure cached crop previews exist before rendering
        for blot in self.current_project.panel.blots:
            if blot.is_nir():
                for ch in blot.channels:
                    try:
                        self.workspace.ensure_blot_crop_preview(
                            blot, self.current_project.panel, channel_index=ch.channel_index
                        )
                    except Exception as e:
                        print(f"[preview] failed for {getattr(blot, 'id', '?')} ch{ch.channel_index}: {e}")
            else:
                try:
                    self.workspace.ensure_blot_crop_preview(blot, self.current_project.panel)
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
                on_crop_resize_commit=self._on_crop_resize_commit,
                show_grid=self.prov_grid_visible,
                nir_channel_index=self._active_nir_channel,
            )
            if prov_scene is None:
                raise RuntimeError("build_provenance_scene returned None (expected QGraphicsScene).")

            self.prov_view.setScene(prov_scene)
            self.prov_view.fit_scene()

        except Exception as e:
            QMessageBox.critical(self, "Render error", str(e))
            return

    def _on_crop_changed(self, blot):
        if not self.current_project:
            return
        # persist crop
        self.workspace.save_project(self.current_project)

        # regenerate cached preview for this blot (all channels for NIR)
        if blot.is_nir():
            for ch in blot.channels:
                try:
                    self.workspace.ensure_blot_crop_preview(
                        blot, self.current_project.panel, channel_index=ch.channel_index
                    )
                except Exception as e:
                    print(f"[preview] failed after crop move for ch{ch.channel_index}: {e}")
        else:
            try:
                self.workspace.ensure_blot_crop_preview(blot, self.current_project.panel)
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
            if blot.is_nir() and blot.channels:
                first_ch = min(blot.channels, key=lambda c: c.channel_index)
                first_asset = self.current_project.assets.get(first_ch.asset_sha256)
                if first_asset and first_asset.original_source_path:
                    stem = Path(first_asset.original_source_path).stem
                    prefix = re.sub(r"-?\[.*?\]$", "", stem)
                    display_name = f"{prefix} (NIR {len(blot.channels)}ch)"
                else:
                    display_name = f"{blot.id} (NIR {len(blot.channels)}ch)"
            else:
                display_name = blot.id
                asset = self.current_project.assets.get(blot.asset_sha256)
                if asset and asset.original_source_path:
                    display_name = Path(asset.original_source_path).name
            if not blot.included_in_final:
                display_name = f"⊘ {display_name}"
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

        old_order = list(order)

        order[i - 1], order[i] = order[i], order[i - 1]

        self.log_operation(
            "panel_order_changed",
            target_type="project",
            target_id=self.current_project.project.id,
            field="panel.layout.order",
            old_value=old_order,
            new_value=list(order),
            note=f"Moved {self.active_blot_id} up",
        )

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

        old_order = list(order)

        order[i + 1], order[i] = order[i], order[i + 1]

        self.log_operation(
            "panel_order_changed",
            target_type="project",
            target_id=self.current_project.project.id,
            field="panel.layout.order",
            old_value=old_order,
            new_value=list(order),
            note=f"Moved {self.active_blot_id} down",
        )

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_rotation_changed(self, value: int):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        _display = self._active_display()
        if _display is None:
            return

        old = float(_display.rotation_deg)
        new = float(value) / 10.0

        _display.rotation_deg = new

        self.log_operation(
            "rotation_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.rotation_deg",
            old_value=old,
            new_value=new,
        )

        self.prov_rotate_label.setText(f"{new:.1f}°")
        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_rotate_ccw(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return
        _display = self._active_display()
        if _display is None:
            return
        old = float(_display.rotation_deg)
        new = (old - 90.0) % 360.0
        _display.rotation_deg = new
        self.log_operation(
            "rotation_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.rotation_deg",
            old_value=old,
            new_value=new,
        )
        self.prov_rotate_label.setText(f"{new:.1f}°")
        self.prov_rotate_dial.blockSignals(True)
        self.prov_rotate_dial.setValue(int(round(new * 10.0)))
        self.prov_rotate_dial.blockSignals(False)
        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_rotate_cw(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return
        _display = self._active_display()
        if _display is None:
            return
        old = float(_display.rotation_deg)
        new = (old + 90.0) % 360.0
        _display.rotation_deg = new
        self.log_operation(
            "rotation_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.rotation_deg",
            old_value=old,
            new_value=new,
        )
        self.prov_rotate_label.setText(f"{new:.1f}°")
        self.prov_rotate_dial.blockSignals(True)
        self.prov_rotate_dial.setValue(int(round(new * 10.0)))
        self.prov_rotate_dial.blockSignals(False)
        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_flip_horizontal(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return
        _display = self._active_display()
        if _display is None:
            return
        old = bool(_display.flip_horizontal)
        new = not old
        _display.flip_horizontal = new
        self.log_operation(
            "flip_horizontal_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.flip_horizontal",
            old_value=old,
            new_value=new,
        )
        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_flip_vertical(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return
        _display = self._active_display()
        if _display is None:
            return
        old = bool(_display.flip_vertical)
        new = not old
        _display.flip_vertical = new
        self.log_operation(
            "flip_vertical_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.flip_vertical",
            old_value=old,
            new_value=new,
        )
        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_prov_grid_toggled(self, checked: bool):
        self.prov_grid_visible = bool(checked)
        self.refresh_previews()

    def _on_levels_changed(self):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        _display = self._active_display()
        if _display is None:
            return

        old_levels = {
            "black": int(_display.levels_black),
            "white": int(_display.levels_white),
            "gamma": float(_display.levels_gamma),
        }

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

        new_levels = {
            "black": black,
            "white": white,
            "gamma": gamma,
        }

        _display.levels_black = black
        _display.levels_white = white
        _display.levels_gamma = gamma

        self.log_operation(
            "levels_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.levels",
            old_value=old_levels,
            new_value=new_levels,
        )

        self.black_value_lbl.setText(str(black))
        self.white_value_lbl.setText(str(white))
        self.gamma_value_lbl.setText(f"{gamma:.2f}")

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_invert_toggled(self, checked: bool):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        _display = self._active_display()
        if _display is None:
            return

        old = bool(_display.invert)
        new = bool(checked)

        _display.invert = new

        self.log_operation(
            "invert_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="display.invert",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self.refresh_previews()

    def _on_include_in_final_toggled(self, checked: bool):
        blot = self._get_active_blot()
        if blot is None or not self.current_project:
            return

        old = bool(blot.included_in_final)
        new = bool(checked)

        blot.included_in_final = new

        self.log_operation(
            "included_in_final_changed",
            target_type="blot",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="included_in_final",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self._populate_prov_blot_combo()
        self._refresh_final_only(fit=True)

    def _on_border_toggled(self, checked: bool):
        if not self.current_project:
            return

        old = bool(self.current_project.panel.style.border_enabled)
        new = bool(checked)

        self.current_project.panel.style.border_enabled = new

        self.log_operation(
            "border_visibility_changed",
            target_type="project",
            target_id=self.current_project.project.id,
            field="panel.style.border_enabled",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self._refresh_final_only(fit=True)

    def _on_border_width_changed(self, value: int):
        if not self.current_project:
            return

        old = int(self.current_project.panel.style.border_width_px)
        new = int(value)

        self.current_project.panel.style.border_width_px = new

        self.log_operation(
            "border_width_changed",
            target_type="project",
            target_id=self.current_project.project.id,
            field="panel.style.border_width_px",
            old_value=old,
            new_value=new,
        )

        self.workspace.save_project(self.current_project)
        self._refresh_final_only(fit=True)

    def refresh_library(self):
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
