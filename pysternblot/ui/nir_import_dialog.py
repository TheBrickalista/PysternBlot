# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout,
)

from ..storage import parse_typhoon_tag270


class NirImportDialog(QDialog):
    """Dialog for importing one or two NIR channel TIFF files (Typhoon convention)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import NIR Blot")
        self.resize(560, 250)

        self._ch1_path: Path | None = None
        self._ch2_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # --- Channel 1 ---
        ch1_lbl = QLabel("Channel 1 (required)")
        ch1_lbl.setStyleSheet("font-weight: 600;")
        layout.addWidget(ch1_lbl)

        ch1_row = QHBoxLayout()
        self._ch1_edit = QLineEdit()
        self._ch1_edit.setPlaceholderText("Select channel 1 file…")
        self._ch1_edit.setReadOnly(True)
        ch1_row.addWidget(self._ch1_edit)
        ch1_browse = QPushButton("Browse…")
        ch1_browse.clicked.connect(lambda: self._browse(1))
        ch1_row.addWidget(ch1_browse)
        layout.addLayout(ch1_row)

        self._ch1_meta_lbl = QLabel("Wavelength: —    Filter: —")
        layout.addWidget(self._ch1_meta_lbl)

        layout.addSpacing(8)

        # --- Channel 2 ---
        ch2_lbl = QLabel("Channel 2 (optional)")
        ch2_lbl.setStyleSheet("font-weight: 600;")
        layout.addWidget(ch2_lbl)

        ch2_row = QHBoxLayout()
        self._ch2_edit = QLineEdit()
        self._ch2_edit.setPlaceholderText("Select channel 2 file…")
        self._ch2_edit.setReadOnly(True)
        ch2_row.addWidget(self._ch2_edit)
        ch2_browse = QPushButton("Browse…")
        ch2_browse.clicked.connect(lambda: self._browse(2))
        ch2_row.addWidget(ch2_browse)
        ch2_clear = QPushButton("Clear")
        ch2_clear.clicked.connect(self._clear_ch2)
        ch2_row.addWidget(ch2_clear)
        layout.addLayout(ch2_row)

        self._ch2_meta_lbl = QLabel("Wavelength: —    Filter: —")
        layout.addWidget(self._ch2_meta_lbl)

        layout.addStretch(1)

        # --- Buttons ---
        self._btn_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self._btn_box.button(QDialogButtonBox.Ok).setText("Import")
        self._btn_box.button(QDialogButtonBox.Ok).setEnabled(False)
        self._btn_box.accepted.connect(self.accept)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse(self, channel: int) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select Channel {channel} file",
            "",
            "TIFF images (*.tif *.tiff)",
        )
        if not path:
            return
        p = Path(path)
        if channel == 1:
            self._ch1_path = p
            self._ch1_edit.setText(str(p))
            self._ch1_meta_lbl.setText(self._read_meta(p))
        else:
            self._ch2_path = p
            self._ch2_edit.setText(str(p))
            self._ch2_meta_lbl.setText(self._read_meta(p))
        self._update_import_btn()

    def _clear_ch2(self) -> None:
        self._ch2_path = None
        self._ch2_edit.clear()
        self._ch2_meta_lbl.setText("Wavelength: —    Filter: —")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_meta(self, path: Path) -> str:
        try:
            from PIL import Image
            with Image.open(str(path)) as im:
                tag_text = ""
                if hasattr(im, "tag_v2"):
                    tag_text = im.tag_v2.get(270, "") or ""
            meta = parse_typhoon_tag270(str(tag_text))
            wl = meta.get("laser_nm")
            fn = meta.get("filter_name")
            wl_str = f"{wl} nm" if wl is not None else "unknown"
            fn_str = fn if fn else "unknown"
            return f"Wavelength: {wl_str}    Filter: {fn_str}"
        except Exception:
            return "Wavelength: unknown    Filter: unknown"

    def _update_import_btn(self) -> None:
        enabled = self._ch1_path is not None and self._ch1_path.is_file()
        self._btn_box.button(QDialogButtonBox.Ok).setEnabled(enabled)

    # ------------------------------------------------------------------
    # Properties exposed to caller
    # ------------------------------------------------------------------

    @property
    def channel1_path(self) -> Path:
        return self._ch1_path

    @property
    def channel2_path(self) -> Path | None:
        return self._ch2_path
