# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox, QGraphicsScene
from PySide6.QtGui import QPainter, QImage, QPdfWriter, QPageSize, QFont, QPen
from PySide6.QtCore import Qt, QRectF, QRect, QSize
from PySide6.QtSvg import QSvgGenerator

from pathlib import Path

from ..image_utils import get_bit_depth
from ..render import (
    build_panel_scene,
    build_provenance_scene,
    draw_legend_into_scene,
    _load_rotated_display_pixmap,
    _band_visible_on_channel,
)
from ..integrity import (
    build_integrity_report,
    build_detailed_integrity_report,
    write_integrity_json,
    write_integrity_html,
)


def _nir_channel_path(base_path: str, channel_index: int, wavelength_nm: int | None) -> str:
    """Build a per-channel TIFF path by inserting a channel suffix before the extension."""
    p = Path(base_path)
    ext = p.suffix if p.suffix.lower() in (".tif", ".tiff") else ".tif"
    if wavelength_nm is not None:
        suffix = f"_ch{channel_index}_{wavelength_nm}nm"
    else:
        suffix = f"_ch{channel_index}"
    return str(p.parent / f"{p.stem}{suffix}{ext}")


def _compute_export_geometry(
    lz, crop, crop_template, pm_w: float, pm_h: float,
) -> tuple[float, float, float, float, float, float]:
    """Pure geometry helper for the legend-zone export (no Qt required).

    The legend zone (lz) and the figure crop box (crop.x/crop.y with
    crop_template.w/h) are independent rectangles in the same original-image
    pixel space. This computes their union — clamped to the pixmap bounds —
    so the exported crop always fully contains the figure crop box, plus the
    crop box's offset within that union (used to align the legend to the
    crop box rather than to the raw zone width).

    Returns (ex, ey, ew, eh, crop_off_x, crop_off_y).
    """
    cx, cy = float(crop.x), float(crop.y)
    cw, ch_ = float(crop_template.w), float(crop_template.h)

    ux = min(float(lz.x), cx)
    uy = min(float(lz.y), cy)
    ux2 = max(float(lz.x) + float(lz.w), cx + cw)
    uy2 = max(float(lz.y) + float(lz.h), cy + ch_)

    ux = max(0.0, min(ux, float(pm_w)))
    uy = max(0.0, min(uy, float(pm_h)))
    ux2 = max(0.0, min(ux2, float(pm_w)))
    uy2 = max(0.0, min(uy2, float(pm_h)))

    ex, ey = ux, uy
    ew, eh = max(0.0, ux2 - ux), max(0.0, uy2 - uy)

    crop_off_x = cx - ex
    crop_off_y = cy - ey

    return ex, ey, ew, eh, crop_off_x, crop_off_y


class _ExportMixin:
    def _has_8bit_blots(self) -> bool:
        if not self.current_project:
            return False
        for blot in self.current_project.panel.blots:
            try:
                path = self.workspace.asset_original_file(blot.asset_sha256)
                if get_bit_depth(path) == 8:
                    return True
            except Exception:
                pass
        return False

    def _warn_8bit_export(self) -> bool:
        """Show pre-export warning if any blot is from an 8-bit source. Returns True to proceed."""
        if not self._has_8bit_blots():
            return True
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("8-bit source images detected")
        msg.setText(
            "One or more blots in this figure were generated from 8-bit source "
            "images.\n\n"
            "8-bit images have limited dynamic range and are not recommended for "
            "quantification purposes. Please disclose the bit depth of source "
            "images if submitting this figure to a journal.\n\n"
            "This warning is recorded in the integrity report."
        )
        proceed_btn = msg.addButton("Proceed with export", QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        return msg.clickedButton() is proceed_btn

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

        if not self._warn_8bit_export():
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

        self.log_operation(
            "export_generated",
            target_type="export",
            target_id=self.current_project.project.id if self.current_project else None,
            field="final_png",
            old_value=None,
            new_value=str(path),
        )

        self.workspace.save_project(self.current_project)

        QMessageBox.information(self, "Exported", f"Saved PNG:\n{path}")

    def export_final_pdf(self):
        scene, rect = self._final_scene_and_rect()
        if scene is None:
            return

        if not self._warn_8bit_export():
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

        self.log_operation(
            "export_generated",
            target_type="export",
            target_id=self.current_project.project.id if self.current_project else None,
            field="final_pdf",
            old_value=None,
            new_value=str(path),
        )
        self.workspace.save_project(self.current_project)

        QMessageBox.information(self, "Exported", f"Saved PDF:\n{path}")

    def export_final_svg(self):
        scene, rect = self._final_scene_and_rect()
        if scene is None:
            return

        if not self._warn_8bit_export():
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

        self.log_operation(
            "export_generated",
            target_type="export",
            target_id=self.current_project.project.id if self.current_project else None,
            field="final_svg",
            old_value=None,
            new_value=str(path),
        )
        self.workspace.save_project(self.current_project)

        QMessageBox.information(self, "Exported", f"Saved SVG:\n{path}")

    def _export_provenance_scene_to_tiff(self, blot_id: str, path: str, nir_channel_index: int = 0):
        scene = build_provenance_scene(
            self.current_project,
            self.workspace.root,
            blot_id=blot_id,
            on_crop_commit=None,
            show_grid=False,
            nir_channel_index=nir_channel_index,
        )

        rect = scene.itemsBoundingRect()
        if not rect.isValid() or rect.isNull():
            raise RuntimeError("Original image scene is empty.")

        margin = 40

        img = QImage(
            int(rect.width() + 2 * margin),
            int(rect.height() + 2 * margin),
            QImage.Format_RGB888,
        )
        img.fill(Qt.white)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        target = QRectF(
            margin,
            margin,
            rect.width(),
            rect.height(),
        )

        scene.render(painter, target, rect)
        painter.end()

        if not img.save(path, "TIFF"):
            raise RuntimeError(f"Could not save TIFF:\n{path}")

    def export_current_original_tiff(self):
        if not self.current_project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return

        blot = self._get_active_blot()
        if blot is None:
            QMessageBox.information(self, "No blot", "No active blot to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Original Image TIFF",
            f"{blot.id}_original_annotated.tif",
            "TIFF (*.tif *.tiff)",
        )

        if not path:
            return

        if not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"

        try:
            if blot.is_nir():
                written: list[str] = []
                for ch in sorted(blot.channels, key=lambda c: c.channel_index):
                    ch_path = _nir_channel_path(path, ch.channel_index, ch.wavelength_nm)
                    self._export_provenance_scene_to_tiff(blot.id, ch_path, nir_channel_index=ch.channel_index)
                    self.log_operation(
                        "export_generated",
                        target_type="export",
                        target_id=blot.id,
                        asset_sha256=ch.asset_sha256,
                        field="original_annotated_tiff",
                        old_value=None,
                        new_value=ch_path,
                    )
                    written.append(ch_path)
                self.workspace.save_project(self.current_project)
                QMessageBox.information(self, "Exported", "Saved TIFFs:\n" + "\n".join(written))
            else:
                self._export_provenance_scene_to_tiff(blot.id, path)
                self.log_operation(
                    "export_generated",
                    target_type="export",
                    target_id=blot.id,
                    asset_sha256=blot.asset_sha256,
                    field="original_annotated_tiff",
                    old_value=None,
                    new_value=str(path),
                )
                self.workspace.save_project(self.current_project)
                QMessageBox.information(self, "Exported", f"Saved TIFF:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))

    def export_all_original_tiffs(self):
        if not self.current_project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for Original Image TIFF exports",
        )

        if not folder:
            return

        try:
            for blot in self.current_project.panel.blots:
                if blot.is_nir():
                    for ch in sorted(blot.channels, key=lambda c: c.channel_index):
                        base = str(Path(folder) / f"{blot.id}_original_annotated.tif")
                        path = _nir_channel_path(base, ch.channel_index, ch.wavelength_nm)
                        self._export_provenance_scene_to_tiff(blot.id, path, nir_channel_index=ch.channel_index)
                        self.log_operation(
                            "export_generated",
                            target_type="export",
                            target_id=blot.id,
                            asset_sha256=ch.asset_sha256,
                            field="original_annotated_tiff",
                            old_value=None,
                            new_value=path,
                        )
                else:
                    path = str(Path(folder) / f"{blot.id}_original_annotated.tif")
                    self._export_provenance_scene_to_tiff(blot.id, path)
                    self.log_operation(
                        "export_generated",
                        target_type="export",
                        target_id=blot.id,
                        asset_sha256=blot.asset_sha256,
                        field="original_annotated_tiff",
                        old_value=None,
                        new_value=path,
                    )
            self.workspace.save_project(self.current_project)

            QMessageBox.information(self, "Exported", f"Saved TIFFs to:\n{folder}")

        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))

    def _draw_legend_zone_markers(self, scene, blot, lz, image_x: float, image_w: float, y_img: float, ey: float) -> int:
        """Draws MW marker ticks/labels for the legend-zone export, reusing the same
        band-lookup/label/highlight-pen logic as build_panel_scene's marker block —
        but WITHOUT the figure's per-band curation filters (show_in_final,
        show_only_highlighted). The zone export always shows the complete assigned
        ladder, since it's a provenance/reference export, not the curated figure.
        The per-channel wavelength filter (_band_visible_on_channel) is kept: a band
        tagged to a different NIR channel genuinely doesn't belong on this image.

        Markers always render (never clipped to the drawn zone) — their y is derived
        directly from assignment.y_px relative to the expanded crop's origin (ey), and
        the crop box is always fully contained in that expanded crop by construction.

        Returns the number of bands actually drawn (for testability).
        """
        if not bool(getattr(lz, "show_markers", True)):
            return 0

        ladder = getattr(blot, "overlay_ladder", None)
        if ladder is None or not getattr(ladder, "bands", None):
            return 0

        style = self.current_project.panel.style
        marker_library = getattr(self.current_project, "marker_sets", []) or []
        marker_set = next(
            (ms for ms in marker_library if ms.id == ladder.marker_set_id), None
        )

        active_wavelength = None
        if blot.is_nir() and blot.channels:
            active_ch = next(
                (c for c in blot.channels if c.channel_index == self._active_nir_channel), None
            )
            if active_ch is not None:
                active_wavelength = active_ch.wavelength_nm

        marker_font = QFont(style.font_family, int(style.kda_label_font_size_pt))
        marker_font.setBold(False)

        marker_pen = QPen(Qt.black)
        marker_pen.setWidth(5)
        marker_pen.setCosmetic(True)

        marker_highlight_pen = QPen(Qt.black)
        marker_highlight_pen.setWidth(8)
        marker_highlight_pen.setCosmetic(True)

        TICK_LEN = 50.0
        GAP = 4.0
        side = getattr(lz, "marker_side", "left")

        if side == "right":
            tick_x0 = image_x + image_w + GAP
            tick_x1 = tick_x0 + TICK_LEN
        else:
            tick_x1 = image_x - GAP
            tick_x0 = tick_x1 - TICK_LEN

        drawn_count = 0

        for assignment in ladder.bands:
            # NOTE: no show_in_final / show_only_highlighted filtering here — the
            # zone export always shows the complete assigned ladder (see docstring).
            kda = float(assignment.kda)

            preset_band = None
            if marker_set is not None:
                preset_band = next(
                    (b for b in marker_set.bands if abs(float(b.kda) - kda) < 0.001), None
                )

            if blot.is_nir() and preset_band is not None:
                if not _band_visible_on_channel(preset_band, active_wavelength):
                    continue

            is_highlighted = bool(getattr(preset_band, "highlight", False)) if preset_band else False
            pen = marker_highlight_pen if is_highlighted else marker_pen

            marker_y = y_img + (float(assignment.y_px) - ey)

            scene.addLine(tick_x0, marker_y, tick_x1, marker_y, pen)
            drawn_count += 1

            if bool(getattr(ladder, "show_labels", True)):
                label = getattr(preset_band, "label", None) if preset_band else None
                if not label:
                    label = f"{kda:g}"
                label = f"{label} kDa"

                text_item = scene.addText(label, marker_font)
                text_item.setDefaultTextColor(Qt.black)
                br = text_item.boundingRect()

                if side == "right":
                    text_item.setPos(tick_x1 + GAP, marker_y - br.height() / 2.0)
                else:
                    text_item.setPos(tick_x0 - GAP - br.width(), marker_y - br.height() / 2.0)

        return drawn_count

    def export_legend_zone_png(self):
        if not self.current_project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return

        blot = self._get_active_blot()
        if blot is None:
            QMessageBox.information(self, "No blot", "No active blot to export.")
            return

        lz = getattr(blot, "legend_zone", None)
        if lz is None or not self.legend_zone_cb.isChecked():
            QMessageBox.information(
                self,
                "Legend export zone not set",
                "Enable and position the Legend export zone on the Original Image "
                "tab first (checkbox above the canvas).",
            )
            return

        try:
            sha256, display = blot.get_display_channel(self._active_nir_channel)
        except (IndexError, AttributeError):
            sha256, display = blot.asset_sha256, blot.display

        pm_full = _load_rotated_display_pixmap(
            self.workspace.root,
            sha256,
            float(getattr(display, "rotation_deg", 0.0) or 0.0),
            black=int(getattr(display, "levels_black", 0)),
            white=int(getattr(display, "levels_white", 65535)),
            gamma=float(getattr(display, "levels_gamma", 1.0)),
            invert=bool(getattr(display, "invert", False)),
            flip_horizontal=bool(getattr(display, "flip_horizontal", False)),
            flip_vertical=bool(getattr(display, "flip_vertical", False)),
        )
        if pm_full.isNull():
            QMessageBox.critical(self, "Export error", "Could not load blot image.")
            return

        crop = blot.get_channel_crop(self._active_nir_channel)
        crop_template = self.current_project.panel.crop_template

        ex, ey, ew, eh, crop_off_x, crop_off_y = _compute_export_geometry(
            lz, crop, crop_template, float(pm_full.width()), float(pm_full.height())
        )

        cropped = pm_full.copy(QRect(int(round(ex)), int(round(ey)), int(round(ew)), int(round(eh))))
        if cropped.isNull() or cropped.width() == 0 or cropped.height() == 0:
            QMessageBox.critical(self, "Export error", "Legend export zone is empty or out of bounds.")
            return

        scene = QGraphicsScene()
        x0, y0 = 20.0, 20.0
        ladder_w = float(self.current_project.panel.style.ladder_col_width_px)
        image_x = x0 + ladder_w
        img_col_x = image_x + crop_off_x
        img_col_w = float(crop_template.w)

        y_img = draw_legend_into_scene(scene, self.current_project, x0, y0, img_col_x, img_col_w)

        img_item = scene.addPixmap(cropped)
        img_item.setPos(image_x, y_img)

        self._draw_legend_zone_markers(scene, blot, lz, image_x, float(cropped.width()), y_img, ey)

        rect = scene.itemsBoundingRect()
        if not rect.isValid() or rect.isNull():
            QMessageBox.critical(self, "Export error", "Legend export zone scene is empty.")
            return

        if not self._warn_8bit_export():
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Zone + Legend as PNG",
            f"{blot.id}_legend_zone.png",
            "PNG (*.png)",
        )
        if not path:
            return

        if not path.lower().endswith(".png"):
            path += ".png"

        margin = 20
        scale = 2.0

        img = QImage(
            int((rect.width() + 2 * margin) * scale),
            int((rect.height() + 2 * margin) * scale),
            QImage.Format_ARGB32,
        )
        img.fill(Qt.white)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.scale(scale, scale)

        target = QRectF(margin, margin, rect.width(), rect.height())
        scene.render(painter, target, rect)
        painter.end()

        if not img.save(path):
            QMessageBox.critical(self, "Export error", "Could not save PNG.")
            return

        self.log_operation(
            "export_generated",
            target_type="export",
            target_id=blot.id,
            asset_sha256=blot.asset_sha256,
            field="legend_zone_png",
            old_value=None,
            new_value=str(path),
        )
        self.workspace.save_project(self.current_project)

        QMessageBox.information(self, "Exported", f"Saved PNG:\n{path}")

    def _current_project_json_path(self) -> Path | None:
        if not self.current_project:
            return None
        path = self.workspace.projects_dir / self.current_project.project.id / "project.json"
        return path if path.exists() else None

    def export_integrity_report(self):
        if not self.current_project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for Integrity Report export",
        )

        if not folder:
            return

        try:
            # Save current project state first, so the project hash matches the report.
            project_json_path = self.workspace.save_project(self.current_project)

            out_dir = Path(folder)
            base = self.current_project.project.name.strip() or self.current_project.project.id
            safe_base = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in base)

            json_path = out_dir / f"{safe_base}_integrity_report.json"
            html_path = out_dir / f"{safe_base}_integrity_report.html"

            report = build_integrity_report(
                self.current_project,
                self.workspace,
                project_json_path=project_json_path,
                exported_files=[],
            )

            write_integrity_json(report, json_path)
            write_integrity_html(report, html_path)

            self.log_operation(
                "integrity_report_generated",
                target_type="export",
                target_id=self.current_project.project.id,
                field="integrity_report",
                old_value=None,
                new_value={
                    "json": str(json_path),
                    "html": str(html_path),
                },
            )
            self.workspace.save_project(self.current_project)

            QMessageBox.information(
                self,
                "Integrity report exported",
                f"Saved:\n{json_path}\n{html_path}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Integrity report error", str(e))

    def export_detailed_integrity_report(self):
        if not self.current_project:
            QMessageBox.information(self, "No project", "Create or open a project first.")
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for Detailed Integrity Report export",
        )

        if not folder:
            return

        try:
            out_dir = Path(folder)
            base = self.current_project.project.name.strip() or self.current_project.project.id
            safe_base = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in base)

            json_path = out_dir / f"{safe_base}_detailed_integrity_report.json"
            html_path = out_dir / f"{safe_base}_detailed_integrity_report.html"

            # Log first, so the detailed report contains its own generation event.
            self.log_operation(
                "detailed_integrity_report_generated",
                target_type="export",
                target_id=self.current_project.project.id,
                field="detailed_integrity_report",
                old_value=None,
                new_value={
                    "json": str(json_path),
                    "html": str(html_path),
                },
            )

            project_json_path = self.workspace.save_project(self.current_project)

            report = build_detailed_integrity_report(
                self.current_project,
                self.workspace,
                project_json_path=project_json_path,
                exported_files=[],
            )

            write_integrity_json(report, json_path)
            write_integrity_html(report, html_path)

            QMessageBox.information(
                self,
                "Detailed integrity report exported",
                f"Saved:\n{json_path}\n{html_path}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Detailed integrity report error", str(e))
