# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

import numpy as np
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtGui import QFont, QPixmap, QPen
from PySide6.QtCore import QRectF, Qt

from .models import Blot, Crop, MarkerBand, Project, LegendRow
from .ui.crop_rect_item import CropRectItem

from .image_utils import (
    load_image_uint16,
    load_image_as_uint16,
    apply_levels_uint16,
    rotate_uint16,
    uint16_to_qpixmap,
)


def _band_visible_on_channel(band: MarkerBand, wavelength_nm: Optional[int]) -> bool:
    """Returns True if the band should be rendered on a channel with the given wavelength.
    Empty channels list means visible everywhere (ECL and all NIR channels)."""
    if not band.channels:
        return True
    if wavelength_nm is None:
        return True
    return wavelength_nm in band.channels


def _ladder_row_for_blot(blot: Blot, marker_sets: list) -> int:
    """Returns the channel_index of the row that should display the ladder column.

    For ECL blots: always 0 (irrelevant, there is only one row).
    For NIR blots: the channel_index of the first channel whose wavelength_nm
    matches at least one assigned band's channels list.
    Falls back to channel_index 0 if no match is found (e.g. all bands have
    empty channels list, meaning show on all — in that case first row is correct).
    """
    if not blot.is_nir():
        return 0
    if blot.overlay_ladder is None or not blot.overlay_ladder.bands:
        return 0

    marker_set = next(
        (ms for ms in marker_sets if ms.id == blot.overlay_ladder.marker_set_id),
        None,
    )

    # Collect wavelengths that are explicitly restricted via MarkerBand.channels.
    # Bands with channels==[] are deliberately excluded — they mean "show everywhere".
    explicit_wavelengths: set[int] = set()
    if marker_set is not None:
        for assignment in blot.overlay_ladder.bands:
            preset_band = next(
                (b for b in marker_set.bands if abs(float(b.kda) - float(assignment.kda)) < 0.001),
                None,
            )
            if preset_band is not None and preset_band.channels:
                explicit_wavelengths.update(preset_band.channels)

    # All bands have channels==[] → fall back to first row (backward compatible).
    if not explicit_wavelengths:
        return 0

    # Return the channel_index of the first channel (sorted) whose wavelength matches.
    for ch in sorted(blot.channels, key=lambda c: c.channel_index):
        if ch.wavelength_nm is not None and ch.wavelength_nm in explicit_wavelengths:
            return ch.channel_index

    return 0


def _load_original_pixmap(workspace_root: Path, sha256: str) -> QPixmap:
    """
    Load assets/<sha256>/original.* as grayscale (16-bit or 8-bit source).
    """
    asset_dir = workspace_root / "assets" / sha256
    for p in asset_dir.glob("original.*"):
        try:
            arr = load_image_as_uint16(p)
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
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
) -> QPixmap:
    """
    Load original image, apply levels → rotate → flip in 16-bit.
    """
    asset_dir = workspace_root / "assets" / sha256
    original_path = None
    for p in asset_dir.glob("original.*"):
        original_path = p
        break

    if original_path is None:
        return QPixmap()

    try:
        img = load_image_as_uint16(original_path)
        img = apply_levels_uint16(img, black, white, gamma, invert)
        img = rotate_uint16(img, rotation_deg, expand=False)
        if flip_horizontal:
            img = np.fliplr(img)
        if flip_vertical:
            img = np.flipud(img)
        return uint16_to_qpixmap(np.ascontiguousarray(img))
    except Exception:
        return QPixmap()

def _load_preview_crop_pixmap(workspace_root: Path, sha256: str, blot_id: str) -> QPixmap:
    """
    Loads assets/<sha256>/preview_crop_<blot_id>.tif as true 16-bit grayscale.
    """
    p = workspace_root / "assets" / sha256 / f"preview_crop_{blot_id}.tif"
    return _load_pixmap_from_path(p)


def _load_pixmap_from_path(path: Path) -> QPixmap:
    if not path.exists():
        return QPixmap()
    try:
        arr = load_image_as_uint16(path)
        return uint16_to_qpixmap(arr)
    except Exception:
        return QPixmap()


def derive_lane_groups(
    cell_groups: list[int],
) -> tuple[dict[int, tuple[int, int]], set[int]]:
    """Given per-lane group ids (0 = ungrouped), return:
      spans  — {group_id: (start_lane, end_lane)} for valid groups
               (contiguous run of >=2 lanes sharing that id).
      errors — set of group_ids whose occurrences are non-contiguous.

    Rules:
      - id 0 is always ignored.
      - Contiguous run of exactly 1 lane: valid but not in spans, not in errors.
      - Contiguous run of >=2 lanes: in spans.
      - Non-contiguous occurrences: in errors, not in spans.
    """
    spans: dict[int, tuple[int, int]] = {}
    errors: set[int] = set()
    ids = {g for g in cell_groups if g != 0}
    for gid in ids:
        positions = [i for i, g in enumerate(cell_groups) if g == gid]
        contiguous = positions[-1] - positions[0] == len(positions) - 1
        if not contiguous:
            errors.add(gid)
        elif len(positions) >= 2:
            spans[gid] = (positions[0], positions[-1])
    return spans, errors


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
    ordered_blots = [blot_by_id[i] for i in order if i in blot_by_id] or list(blot_by_id.values())

    # ---- expand into render rows: (blot, channel|None) ----
    # NIR blots produce one row per channel (sorted by channel_index).
    # ECL blots produce one row (channel=None).
    # Ladder bands render on every NIR row where they are visible:
    #   channels==[] → all rows; explicit channels → matching wavelength only.
    render_rows: list[tuple] = []
    for blot in ordered_blots:
        if blot.is_nir():
            for ch in sorted(blot.channels, key=lambda c: c.channel_index):
                if ch.included_in_final:
                    render_rows.append((blot, ch))
        else:
            render_rows.append((blot, None))

    # ---- preload pixmaps (and compute max image width for consistent column layout) ----
    pixmaps: list[QPixmap] = []
    for blot, ch in render_rows:
        if ch is not None:
            # NIR channel: load from per-channel cache
            p = workspace_root / "assets" / ch.asset_sha256 / f"preview_crop_{blot.id}_ch{ch.channel_index}.tif"
            pm = _load_pixmap_from_path(p)
            if pm.isNull():
                pm = _load_original_pixmap(workspace_root, ch.asset_sha256)
        else:
            pm = _load_preview_crop_pixmap(workspace_root, blot.asset_sha256, blot.id)
            if pm.isNull():
                pm = _load_original_pixmap(workspace_root, blot.asset_sha256)
        pixmaps.append(pm)

    if not render_rows:
        scene.addText("No blots in this project.", font)
        return scene

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
    def _draw_legend_row(
        row: LegendRow,
        y: float,
        lane_row: LegendRow | None = None,
        underline_above: bool = False,
    ) -> float:
        """
        Returns next y.

        lane_row: the row that provides lane geometry (cell count, cell_groups).
          - Upper-only block: pass lane_row=upper[-1] for every upper row; the last
            upper row is the per-lane reference, all rows above it group over it.
          - Mixed (upper + lower): pass lane_row=lower_rows[0] for upper rows.
          - Lower rows: pass lane_row=row (self-referential).

        underline_above: when True the underline sits above this row's text (y - 6),
          placing it between group-label rows above and per-lane labels below.
          When False (default / lower-rows path) it sits below (y + text_h + 4).

        Underlines fire only when lane_row is row (i.e. this IS the lane_ref row).
        """
        row_font_size = float(row.font_size_pt) if getattr(row, "font_size_pt", None) is not None else float(s.font_size_pt)
        row_font = QFont(s.font_family, int(row_font_size))

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

        # --- measure text height once ---
        tmp = scene.addText("Ag", row_font)
        text_h = tmp.boundingRect().height()
        scene.removeItem(tmp)

        # ----- lane geometry from the lane reference row -----
        _lr = lane_row if lane_row is not None else row
        n_lanes = max(1, len(_lr.cells)) if _lr.cells else 1
        lane_w = img_col_w / float(n_lanes)

        _raw_lg = list(getattr(_lr, "cell_groups", []) or [])
        _lane_cell_groups = (_raw_lg + [0] * n_lanes)[:n_lanes]
        spans, _errors = derive_lane_groups(_lane_cell_groups)

        # ----- this row's cells and per-cell group ids -----
        cells = list(row.cells or [])
        n_cells = len(cells)
        _raw_cg = list(getattr(row, "cell_groups", []) or [])
        cell_group_ids = (_raw_cg + [0] * n_cells)[:n_cells]

        # Left label (centered in ladder column)
        if row.left:
            _add_text_centered_in_col(row.left, left_col_x, ladder_w, y)

        # ----- compute per-cell centers -----
        own_step = img_col_w / float(n_cells) if n_cells > 0 else img_col_w
        centers: list[float] = []
        for i in range(n_cells):
            gid = cell_group_ids[i]
            if gid != 0 and gid in spans:
                a, b = spans[gid]
                cx = img_col_x + (a + b + 1) / 2.0 * lane_w
            else:
                cx = img_col_x + (i + 0.5) * own_step
            centers.append(cx)

        for cx, txt in zip(centers, cells):
            txt = (txt or "").strip()
            if not txt:
                continue
            _add_text_centered(txt, cx, y)

        # Right label (left aligned in protein column)
        if row.right:
            _add_text_left(row.right, right_col_x, y)

        # ----- underlines: lane-reference row only -----
        underline_drawn = False
        if lane_row is row and spans:
            # Option (a): when we are the last row of an upper block that has rows
            # above it, draw the line ABOVE our text so it sits in the gap between
            # group labels and per-lane labels.  For lower-rows (underline_above=False)
            # keep the original below-text position.
            underline_y = (y - 6.0) if underline_above else (y + text_h + 4.0)
            pen = QPen(Qt.black, 2)
            pen.setCapStyle(Qt.FlatCap)
            gap_px = 40.0
            pad = gap_px / 2.0
            for gid, (a, b) in spans.items():
                x_start = img_col_x + a * lane_w
                x_end = img_col_x + (b + 1) * lane_w
                x1 = x_start + pad
                x2 = x_end - pad
                if x2 > x1 + 1.0:
                    scene.addLine(x1, underline_y, x2, underline_y, pen)
                    underline_drawn = True

        # When the underline is above our text it is already in the preceding gap,
        # so no extra trailing space is needed.  Only inflate spacing for the
        # original below-text case.
        extra = 14.0 if (underline_drawn and not underline_above) else 8.0
        return y + text_h + extra
    
    
    y = y0

    # ---- upper legend ----
    legend = getattr(project.panel, "legend", None)
    if legend and getattr(legend, "upper_rows", None):
        upper = legend.upper_rows
        if getattr(legend, "lower_rows", None):
            # Mixed: upper rows reference the first lower row for lane geometry.
            # Underline guard (lane_row is row) never fires here — lower rows draw theirs.
            _lane_ref = legend.lower_rows[0]
            for row in upper:
                y = _draw_legend_row(row, y, lane_row=_lane_ref)
        else:
            # Upper-only (common case): the last upper row is the per-lane reference.
            # Every row above it groups over it.  Underline draws above the lane_ref
            # text only when there are group-label rows above it.
            _lane_ref = upper[-1]
            _ul_above = len(upper) > 1
            for row in upper:
                y = _draw_legend_row(row, y, lane_row=_lane_ref, underline_above=_ul_above)
        y += 10.0  # gap before first blot

    # ---- render rows ----
    for (blot, ch), pm in zip(render_rows, pixmaps):
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

        # --- MW marker annotations — per-band filter controls which rows each band appears on ---
        ladder = getattr(blot, "overlay_ladder", None)

        if ladder is not None and getattr(ladder, "bands", None):
            marker_library = getattr(project, "marker_sets", []) or []

            marker_set = next(
                (ms for ms in marker_library if ms.id == ladder.marker_set_id),
                None
            )

            marker_font = QFont(s.font_family, int(s.kda_label_font_size_pt))
            marker_font.setBold(False)

            marker_pen = QPen(Qt.black)
            marker_pen.setWidth(5)
            marker_pen.setCosmetic(True)

            marker_highlight_pen = QPen(Qt.black)
            marker_highlight_pen.setWidth(8)
            marker_highlight_pen.setCosmetic(True)

            _row_crop = blot.get_channel_crop(ch.channel_index) if ch is not None else blot.crop
            crop_y = float(getattr(_row_crop, "y", 0.0))
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

                # Per-channel filter: NIR rows only show bands whose channels list includes
                # this channel's wavelength (empty channels list = visible everywhere).
                if ch is not None and preset_band is not None:
                    if not _band_visible_on_channel(preset_band, ch.wavelength_nm):
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

        # Protein label on the right (vertically centered) — per-channel for NIR
        protein_label = ch.protein_label if ch is not None else getattr(blot, "protein_label", None)
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
            y = _draw_legend_row(row, y, lane_row=row)

    return scene

def build_provenance_scene(
    project: Project,
    workspace_root: Path,
    blot_id: str | None = None,
    on_crop_commit=None,
    on_crop_resize_commit=None,
    show_grid: bool = False,
    nir_channel_index: int = 0,
) -> QGraphicsScene:
    """
    Provenance view = full original blot + optional membrane overlay + interactive crop rectangle.
    Uses blot_id if provided; falls back to the first blot in the project.

    For NIR blots, nir_channel_index selects which channel's image and display settings to show.
    Default 0 means existing ECL callers are unaffected.
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

    # For NIR blots, get sha256 and display from the selected channel.
    try:
        sha256, display = blot.get_display_channel(nir_channel_index)
    except (IndexError, AttributeError):
        sha256, display = blot.asset_sha256, blot.display

    rotation_deg = float(getattr(display, "rotation_deg", 0.0) or 0.0)
    black = int(getattr(display, "levels_black", 0))
    white = int(getattr(display, "levels_white", 65535))
    gamma = float(getattr(display, "levels_gamma", 1.0))
    invert = bool(getattr(display, "invert", False))
    flip_h = bool(getattr(display, "flip_horizontal", False))
    flip_v = bool(getattr(display, "flip_vertical", False))

    pm = _load_rotated_display_pixmap(
        workspace_root,
        sha256,
        rotation_deg,
        black=black,
        white=white,
        gamma=gamma,
        invert=invert,
        flip_horizontal=flip_h,
        flip_vertical=flip_v,
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
    c = blot.get_channel_crop(nir_channel_index)
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

        # Per-channel crop position: each NIR channel stores its own x/y.
        # ECL blots always update blot.crop directly.
        _cur = blot.get_channel_crop(nir_channel_index)
        blot.set_channel_crop(
            nir_channel_index,
            Crop(x=x, y=y, w=_cur.w, h=_cur.h, mode=_cur.mode),
        )
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

        # Determine active channel wavelength for NIR per-channel filtering.
        _active_wavelength: Optional[int] = None
        if blot.is_nir() and blot.channels:
            _active_ch = next(
                (c for c in blot.channels if c.channel_index == nir_channel_index), None
            )
            if _active_ch is not None:
                _active_wavelength = _active_ch.wavelength_nm

        tick_pen = QPen(Qt.black)
        tick_pen.setWidth(5)
        tick_pen.setCosmetic(True)

        highlight_pen = QPen(Qt.black)
        highlight_pen.setWidth(8)
        highlight_pen.setCosmetic(True)

        label_font = QFont(s.font_family, int(s.kda_label_font_size_pt))
        label_font.setBold(True)

        TICK_LENGTH = 50.0
        TICK_GAP    = 15.0
        LABEL_GAP   =  4.0

        img_right = x0 + float(pm.width())

        if getattr(ladder, "side", "left") == "right":
            tick_x0 = img_right + TICK_GAP
            tick_x1 = img_right + TICK_GAP + TICK_LENGTH
        else:
            tick_x1 = x0 - TICK_GAP
            tick_x0 = x0 - TICK_GAP - TICK_LENGTH

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

            # Per-channel filter: for NIR blots only show bands matching the active channel.
            if blot.is_nir() and preset_band is not None:
                if not _band_visible_on_channel(preset_band, _active_wavelength):
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

                if getattr(ladder, "side", "left") == "right":
                    text_item.setPos(tick_x1 + LABEL_GAP, y - br.height() / 2.0)
                else:
                    text_item.setPos(tick_x0 - br.width() - LABEL_GAP, y - br.height() / 2.0)

    return scene