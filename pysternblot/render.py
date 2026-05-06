# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtGui import QFont, QPixmap, QPen
from PySide6.QtCore import QRectF, Qt

from .models import Project, LegendRow
from .ui.crop_rect_item import CropRectItem

from .image_utils import (
    load_image_uint16,
    apply_levels_uint16,
    rotate_uint16,
    uint16_to_qpixmap,
)


def _load_original_pixmap(workspace_root: Path, sha256: str) -> QPixmap:
    """
    Load assets/<sha256>/original.* as true 16-bit grayscale.
    """
    asset_dir = workspace_root / "assets" / sha256
    for p in asset_dir.glob("original.*"):
        try:
            arr = load_image_uint16(p)
            return uint16_to_qpixmap(arr)
        except Exception:
            continue
    return QPixmap()



def _load_rotated_display_pixmap(
    workspace_root: Path,
    sha256: str,
    rotation_deg: float = 0.0,
    black: int = 0,
    white: int = 65535,
    gamma: float = 1.0,
    invert: bool = False,
) -> QPixmap:
    """
    Load original image, apply levels in 16-bit, then rotate in 16-bit.
    """
    asset_dir = workspace_root / "assets" / sha256
    original_path = None
    for p in asset_dir.glob("original.*"):
        original_path = p
        break

    if original_path is None:
        return QPixmap()

    try:
        img = load_image_uint16(original_path)
        img = apply_levels_uint16(img, black, white, gamma, invert)
        img = rotate_uint16(img, rotation_deg, expand=False)
        return uint16_to_qpixmap(img)
    except Exception:
        return QPixmap()

def _load_preview_crop_pixmap(workspace_root: Path, sha256: str, blot_id: str) -> QPixmap:
    """
    Loads assets/<sha256>/preview_crop.tif as true 16-bit grayscale.
    """
    p = workspace_root / "assets" / sha256 / f"preview_crop_{blot_id}.tif"
    if not p.exists():
        return QPixmap()

    try:
        arr = load_image_uint16(p)
        return uint16_to_qpixmap(arr)
    except Exception:
        return QPixmap()


def build_panel_scene(project: Project, workspace_root: Path) -> QGraphicsScene:
    """
    Final Result view = (optional) legend + stacked cropped previews + protein labels.
    Alignment rules:
      - left legend text centered in ladder column
      - legend cells centered on lane centers across the image column
      - right legend text left-aligned in protein column
      - positions use QGraphicsTextItem.boundingRect() (more accurate than QFontMetrics)
    """
    scene = QGraphicsScene()
    s = project.panel.style
    font = QFont(s.font_family, int(s.font_size_pt))

    if not project.panel.blots:
        scene.addText("No blots in this project.", font)
        return scene

    # ---- layout constants ----
    x0, y0 = 20.0, 20.0
    ladder_w = float(s.ladder_col_width_px)
    gap_between_blots = float(s.gap_between_blots_px)
    protein_w = float(s.protein_col_width_px)

    left_col_x = x0
    img_col_x = x0 + ladder_w
    col_gap = 10.0  # gap between image and protein column

    # ---- stack order (only included blots appear in the final figure) ----
    order = list(getattr(project.panel.layout, "order", []))
    blot_by_id = {b.id: b for b in project.panel.blots if b.included_in_final}
    blots = [blot_by_id[i] for i in order if i in blot_by_id] or list(blot_by_id.values())

    # ---- preload pixmaps (and compute max image width for consistent column layout) ----
    pixmaps: list[QPixmap] = []
    for blot in blots:
        pm = _load_preview_crop_pixmap(workspace_root, blot.asset_sha256, blot.id)
        if pm.isNull():
            pm = _load_original_pixmap(workspace_root, blot.asset_sha256)
        pixmaps.append(pm)

    max_w = max((pm.width() for pm in pixmaps if not pm.isNull()), default=0)
    max_h = max((pm.height() for pm in pixmaps if not pm.isNull()), default=0)
    if max_w <= 0 or max_h <= 0:
        scene.addText("Could not load blot previews.", font).setPos(x0, y0)
        return scene

    img_col_w = float(max_w)
    right_col_x = img_col_x + img_col_w + col_gap

    # ---- helpers ----
    def _add_text(text: str, x: float, y: float) -> None:
        t = scene.addText(text, font)
        t.setDefaultTextColor(Qt.black)
        t.setPos(x, y)

    def _add_text_centered(text: str, cx: float, y: float) -> None:
        t = scene.addText(text, font)
        t.setDefaultTextColor(Qt.black)
        br = t.boundingRect()
        t.setPos(cx - br.width() / 2.0, y)

    def _add_text_centered_in_col(text: str, col_x: float, col_w: float, y: float) -> None:
        # center text in a fixed-width column
        t = scene.addText(text, font)
        t.setDefaultTextColor(Qt.black)
        br = t.boundingRect()
        t.setPos(col_x + (col_w - br.width()) / 2.0, y)

    # ---- legend row renderer ----
    def _draw_legend_row(row: LegendRow, y: float) -> float:
        """
        Returns next y.
        Placement strategy:
        1) if len(cells) == n_lanes -> per-lane centers
        2) elif len(cells) == len(groups) -> per-group centers (group spans use n_lanes)
        3) else -> evenly distribute across image width
        """
        
        row_font_size = float(row.font_size_pt) if getattr(row, "font_size_pt", None) is not None else float(s.font_size_pt)
        row_font = QFont(s.font_family, int(row_font_size))

        # ----- lane/group geometry -----
        hb = project.panel.lane_layout.header_block
        groups = list(getattr(hb, "groups", []) or [])
        n_lanes = int(hb.total_lanes() or 0)

        cells = list(row.cells or [])
        n_cells = len(cells)

        if n_lanes <= 0:
            # fallback: at least keep things on the image
            n_lanes = max(1, n_cells)

        # helper: accurate text centering using boundingRect (not QFontMetrics)
        def _add_text_centered(text: str, cx: float, y0: float) -> None:
            t = scene.addText(text, row_font)
            t.setDefaultTextColor(Qt.black)
            br = t.boundingRect()
            t.setPos(cx - br.width() / 2.0, y0)

        def _add_text_left(text: str, x: float, y0: float) -> None:
            t = scene.addText(text, row_font)
            t.setDefaultTextColor(Qt.black)
            t.setPos(x, y0)

        def _add_text_centered_in_col(text: str, col_x: float, col_w: float, y0: float) -> None:
            t = scene.addText(text, row_font)
            t.setDefaultTextColor(Qt.black)
            br = t.boundingRect()
            t.setPos(col_x + (col_w - br.width()) / 2.0, y0)

        # --- measure one text height once (and reuse) ---
        tmp = scene.addText("Ag", row_font)
        text_h = tmp.boundingRect().height()
        scene.removeItem(tmp)

        # Left label (centered in ladder column)
        if row.left:
            _add_text_centered_in_col(row.left, left_col_x, ladder_w, y)

        # ----- compute centers for the "cells" across the image column -----
        centers: list[float] = []

        # Case 1: per-lane labels
        if n_cells == n_lanes:
            lane_w = img_col_w / float(n_lanes)
            centers = [img_col_x + (i + 0.5) * lane_w for i in range(n_cells)]

        # Case 2: per-group labels (best when n_cells == len(groups))
        elif groups and n_cells == len(groups):
            lane_w = img_col_w / float(n_lanes)
            lane_cursor = 0
            for g in groups:
                span = int(getattr(g, "n_lanes", 1) or 1)
                start = lane_cursor
                end = lane_cursor + span
                cx = img_col_x + ((start + end) / 2.0) * lane_w
                centers.append(cx)
                lane_cursor = end

            centers = [min(max(img_col_x, c), img_col_x + img_col_w) for c in centers]

        # Case 3: evenly distribute across full image width
        else:
            if n_cells > 0:
                step = img_col_w / float(n_cells)
                centers = [img_col_x + (i + 0.5) * step for i in range(n_cells)]

        # draw center cells
        for cx, txt in zip(centers, cells):
            txt = (txt or "").strip()
            if not txt:
                continue
            _add_text_centered(txt, cx, y)

        # Right label (left aligned in protein column)
        if row.right:
            _add_text_left(row.right, right_col_x, y)

        # --- underline groups if requested for this row ---
        underline_drawn = False
        if bool(getattr(row, "underline", False)):

            # slightly below the text row
            underline_y = y + text_h + 4.0

            pen = QPen(Qt.black, 2)
            pen.setCapStyle(Qt.FlatCap)

            gap_px = 40.0  # visible gap between segments
            pad = gap_px / 2.0

            # Prefer true header groups only if there are *multiple* groups
            use_header_groups = bool(groups) and len(groups) > 1

            if use_header_groups and n_lanes > 0:
                # --- group-based segments using lane geometry ---
                lane_w = img_col_w / float(n_lanes)
                lane_cursor = 0

                for g in groups:
                    span = int(getattr(g, "n_lanes", 1) or 1)

                    x_start = img_col_x + lane_cursor * lane_w
                    x_end = img_col_x + (lane_cursor + span) * lane_w

                    x1 = x_start + pad
                    x2 = x_end - pad

                    if x2 > x1 + 1.0:
                        scene.addLine(x1, underline_y, x2, underline_y, pen)
                        underline_drawn = True

                    lane_cursor += span

            else:
                # --- fallback: derive segments from *this row's* non-empty cells ---
                blocks = [c for c in (cells or []) if (c or "").strip()]
                n_blocks = len(blocks)

                if n_blocks <= 1:
                    # one block -> one underline across entire image column
                    x1 = img_col_x + pad
                    x2 = img_col_x + img_col_w - pad
                    if x2 > x1 + 1.0:
                        scene.addLine(x1, underline_y, x2, underline_y, pen)
                        underline_drawn = True
                else:
                    block_w = img_col_w / float(n_blocks)

                    for i in range(n_blocks):
                        x_start = img_col_x + i * block_w
                        x_end = img_col_x + (i + 1) * block_w

                        x1 = x_start + pad
                        x2 = x_end - pad

                        if x2 > x1 + 1.0:
                            scene.addLine(x1, underline_y, x2, underline_y, pen)
                            underline_drawn = True
                # row spacing (account for underline)
        extra = 14.0 if underline_drawn else 8.0
        return y + text_h + extra
    
    
    y = y0

    # ---- upper legend ----
    legend = getattr(project.panel, "legend", None)
    if legend and getattr(legend, "upper_rows", None):
        for row in legend.upper_rows:
            y = _draw_legend_row(row, y)
        y += 10.0  # gap before first blot

    # ---- blots ----
    for blot, pm in zip(blots, pixmaps):
        if pm.isNull():
            t = scene.addText(f"Could not load image for blot: {blot.id}", font)
            t.setPos(x0, y)
            y += t.boundingRect().height() + 8.0
            continue

        img_item = scene.addPixmap(pm)
        img_item.setPos(img_col_x, y)

        if getattr(s, "border_enabled", True):
            pen = QPen(Qt.black, float(getattr(s, "border_width_px", 1)))
            pen.setCosmetic(True)
            scene.addRect(img_col_x, y, pm.width(), pm.height(), pen)

        # --- MW marker annotations on final cropped panel ---
        ladder = getattr(blot, "overlay_ladder", None)

        if ladder is not None and getattr(ladder, "bands", None):
            marker_library = getattr(project, "marker_sets", []) or []

            marker_set = next(
                (ms for ms in marker_library if ms.id == ladder.marker_set_id),
                None
            )

            marker_font = QFont(s.font_family, int(s.kda_label_font_size_pt))
            marker_font.setBold(True)

            marker_pen = QPen(Qt.black)
            marker_pen.setWidth(5)
            marker_pen.setCosmetic(True)

            marker_highlight_pen = QPen(Qt.black)
            marker_highlight_pen.setWidth(8)
            marker_highlight_pen.setCosmetic(True)

            crop_y = float(getattr(blot.crop, "y", 0.0))
            crop_h_scene = float(pm.height())

            tick_x0 = left_col_x + 45.0
            tick_x1 = img_col_x - 8.0

            for assignment in ladder.bands:
                if not bool(getattr(assignment, "show_in_final", True)):
                    continue
                
                crop_h_model = float(project.panel.crop_template.h)
                scale_y = float(pm.height()) / crop_h_model if crop_h_model > 0 else 1.0

                marker_y_in_crop = (float(assignment.y_px) - crop_y) * scale_y

                # Do not skip: show MW marker position relative to crop,
                # even if it falls slightly outside the cropped image.
                # This makes it clear where the marker lies relative to the crop.

                kda = float(assignment.kda)

                preset_band = None
                if marker_set is not None:
                    preset_band = next(
                        (b for b in marker_set.bands if abs(float(b.kda) - kda) < 0.001),
                        None
                    )

                # If marker_set is missing, do NOT silently hide everything.
                if bool(getattr(ladder, "show_only_highlighted", False)) and marker_set is not None:
                    if preset_band is None or not bool(getattr(preset_band, "highlight", False)):
                        continue

                is_highlighted = bool(getattr(preset_band, "highlight", False)) if preset_band else False
                pen = marker_highlight_pen if is_highlighted else marker_pen

                yy = y + marker_y_in_crop

                scene.addLine(tick_x0, yy, tick_x1, yy, pen)

                if bool(getattr(ladder, "show_labels", True)):
                    label = getattr(preset_band, "label", None) if preset_band else None
                    if not label:
                        label = f"{kda:g}"
                    label = f"{label} kDa"

                    text_item = scene.addText(label, marker_font)
                    text_item.setDefaultTextColor(Qt.black)
                    br = text_item.boundingRect()

                    text_item.setPos(
                        tick_x0 - 4.0 - br.width(),
                        yy - br.height() / 2.0,
                    )

        # Protein label on the right (vertically centered)
        protein_label = getattr(blot, "protein_label", None)
        label = getattr(protein_label, "text", "")

        if label:
            protein_font_size = getattr(protein_label, "font_size_pt", None)
            if protein_font_size is None:
                protein_font_size = s.font_size_pt

            protein_font = QFont(s.font_family, int(protein_font_size))

            t = scene.addText(label, protein_font)
            t.setDefaultTextColor(Qt.black)
            br = t.boundingRect()
            t.setPos(right_col_x, y + pm.height() / 2.0 - br.height() / 2.0)

        y += pm.height() + gap_between_blots

    # ---- lower legend ----
    if legend and getattr(legend, "lower_rows", None):
        y += 10.0
        for row in legend.lower_rows:
            y = _draw_legend_row(row, y)

    return scene

def build_provenance_scene(
    project: Project,
    workspace_root: Path,
    blot_id: str | None = None,
    on_crop_commit=None,
    on_crop_resize_commit=None,
    show_grid: bool = False,
) -> QGraphicsScene:
    """
    Provenance view = full original blot + optional membrane overlay + interactive crop rectangle.
    Uses blot_id if provided; falls back to the first blot in the project.
    """
    scene = QGraphicsScene()
    s = project.panel.style
    font = QFont(s.font_family, int(s.font_size_pt))

    if not project.panel.blots:
        scene.addText("No blots in this project.", font)
        return scene

    blot = None
    if blot_id:
        for b in project.panel.blots:
            if b.id == blot_id:
                blot = b
                break
    if blot is None:
        blot = project.panel.blots[0]

    rotation_deg = float(getattr(getattr(blot, "display", None), "rotation_deg", 0.0) or 0.0)

    display = getattr(blot, "display", None)
    black = int(getattr(display, "levels_black", 0))
    white = int(getattr(display, "levels_white", 65535))
    gamma = float(getattr(display, "levels_gamma", 1.0))
    invert = bool(getattr(display, "invert", False))

    pm = _load_rotated_display_pixmap(
        workspace_root,
        blot.asset_sha256,
        rotation_deg,
        black=black,
        white=white,
        gamma=gamma,
        invert=invert,
    )
    if pm.isNull():
        scene.addText(
            "Could not load blot image from workspace assets.\n"
            "Try importing a PNG/JPG first; TIFF 16-bit may require a different loader.",
            font
        )
        return scene

    # Full blot image
    x0, y0 = 10.0, 10.0
    img_item = scene.addPixmap(pm)
    img_item.setPos(x0, y0)

    # Optional membrane overlay (same size/alignment expected)
    overlay_sha = getattr(blot, "overlay_asset_sha256", None)
    overlay_visible = getattr(getattr(blot, "display", None), "overlay_visible", True)
    overlay_alpha = float(getattr(getattr(blot, "display", None), "overlay_alpha", 0.35))

    if overlay_sha and overlay_visible:
        ov = _load_rotated_display_pixmap(
            workspace_root,
            overlay_sha,
            rotation_deg,
            black=black,
            white=white,
            gamma=gamma,
            invert=invert,
        )
        if not ov.isNull():
            ov_item = scene.addPixmap(ov)
            ov_item.setOpacity(overlay_alpha)
            ov_item.setPos(x0, y0)

    # Optional grid overlay
    if show_grid:
        grid_step = 50.0
        grid_pen = QPen(Qt.lightGray, 1, Qt.SolidLine)
        grid_pen.setCosmetic(True)

        gx = x0
        while gx <= x0 + pm.width():
            scene.addLine(gx, y0, gx, y0 + pm.height(), grid_pen)
            gx += grid_step

        gy = y0
        while gy <= y0 + pm.height():
            scene.addLine(x0, gy, x0 + pm.width(), gy, grid_pen)
            gy += grid_step
            
    # Crop box overlay (crop coords are in image pixel space)
    c = blot.crop
    ct = project.panel.crop_template

    def _apply_from_scene_rect(scene_rect: QRectF) -> None:
        # Convert scene coords -> image pixel coords
        x = float(scene_rect.x() - x0)
        y = float(scene_rect.y() - y0)
        w = float(scene_rect.width())
        h = float(scene_rect.height())

        if w < 1: w = 1
        if h < 1: h = 1
        if x < 0: x = 0
        if y < 0: y = 0
        if x + w > pm.width():  x = max(0.0, float(pm.width()) - w)
        if y + h > pm.height(): y = max(0.0, float(pm.height()) - h)

        blot.crop.x = x
        blot.crop.y = y
        # w/h go to the shared template so all blots resize together
        ct.w = w
        ct.h = h

    def _on_move_commit(scene_rect: QRectF) -> None:
        _apply_from_scene_rect(scene_rect)
        if callable(on_crop_commit):
            on_crop_commit(blot)

    def _on_resize_commit(scene_rect: QRectF) -> None:
        _apply_from_scene_rect(scene_rect)
        if callable(on_crop_resize_commit):
            on_crop_resize_commit()

    crop_rect = QRectF(
        x0 + float(c.x),
        y0 + float(c.y),
        float(ct.w),
        float(ct.h),
    )

    rect_item = CropRectItem(
        crop_rect,
        on_change=_apply_from_scene_rect,
        on_move_commit=_on_move_commit,
        on_resize_commit=_on_resize_commit,
    )
    scene.addItem(rect_item)

    # --- Overlay ladder annotations ---
    ladder = getattr(blot, "overlay_ladder", None)

    if ladder is not None and getattr(ladder, "bands", None):
        marker_library = getattr(project, "marker_sets", []) or []

        marker_set = next(
            (ms for ms in marker_library if ms.id == ladder.marker_set_id),
            None
        )

        tick_pen = QPen(Qt.black)
        tick_pen.setWidth(5)
        tick_pen.setCosmetic(True)

        highlight_pen = QPen(Qt.black)
        highlight_pen.setWidth(8)
        highlight_pen.setCosmetic(True)

        label_font = QFont(s.font_family, int(s.kda_label_font_size_pt))
        label_font.setBold(True)

        # For now, draw on the left of the image.
        tick_x0 = x0 - 65.0
        tick_x1 = x0 - 15.0
        label_x = x0 - 125.0

        for assignment in ladder.bands:
            y = y0 + float(assignment.y_px)
            kda = float(assignment.kda)

            preset_band = None
            if marker_set is not None:
                preset_band = next(
                    (b for b in marker_set.bands if abs(float(b.kda) - kda) < 0.001),
                    None
                )

            if bool(getattr(ladder, "show_only_highlighted", False)):
                if preset_band is None or not bool(getattr(preset_band, "highlight", False)):
                    continue

            is_highlighted = bool(getattr(preset_band, "highlight", False)) if preset_band else False
            pen = highlight_pen if is_highlighted else tick_pen

            scene.addLine(tick_x0, y, tick_x1, y, pen)

            if bool(getattr(ladder, "show_labels", True)):
                label = getattr(preset_band, "label", None) if preset_band else None
                if not label:
                    label = f"{kda:g}"
                label = f"{label} kDa"

                text_item = scene.addText(label, label_font)
                text_item.setDefaultTextColor(Qt.black)
                br = text_item.boundingRect()
                text_item.setPos(label_x, y - br.height() / 2.0)

    return scene