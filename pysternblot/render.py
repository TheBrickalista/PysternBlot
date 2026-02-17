# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtCore import QRectF, Qt

from .models import Project


def _load_original_pixmap(workspace_root: Path, sha256: str) -> QPixmap:
    """
    Loads assets/<sha256>/original.* using Qt image plugins.
    Note: Qt may fail on some 16-bit TIFFs. If you hit that, tell me and we’ll switch loader.
    """
    asset_dir = workspace_root / "assets" / sha256
    for p in asset_dir.glob("original.*"):
        pm = QPixmap(str(p))
        if not pm.isNull():
            return pm
    return QPixmap()


def build_panel_scene(project: Project) -> QGraphicsScene:
    """Current placeholder panel scene (kept simple for now)."""
    scene = QGraphicsScene()
    s = project.panel.style
    font = QFont(s.font_family, int(s.font_size_pt))

    t = scene.addText(project.project.name, font)
    t.setDefaultTextColor(Qt.black)
    t.setPos(10, 10)

    top = s.top_header_height_px
    w = s.ladder_col_width_px + 600 + s.protein_col_width_px
    h = top + 2 * 250 + s.gap_between_blots_px
    scene.addRect(QRectF(10, 40, w, h))
    return scene


def build_provenance_scene(project: Project, workspace_root: Path) -> QGraphicsScene:
    """
    Provenance view = full copied original blot + (optional) membrane overlay + crop rectangle.
    v0.1: uses the first blot in the project.
    """
    scene = QGraphicsScene()
    s = project.panel.style
    font = QFont(s.font_family, int(s.font_size_pt))

    if not project.panel.blots:
        scene.addText("No blots in this project.", font)
        return scene

    blot = project.panel.blots[0]

    pm = _load_original_pixmap(workspace_root, blot.asset_sha256)
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
        ov = _load_original_pixmap(workspace_root, overlay_sha)
        if not ov.isNull():
            ov_item = scene.addPixmap(ov)
            ov_item.setOpacity(overlay_alpha)
            ov_item.setPos(x0, y0)

    # Crop box overlay (assumes crop coords are in image pixel space)
    c = blot.crop
    crop_rect = QRectF(x0 + float(c.x), y0 + float(c.y), float(c.w), float(c.h))
    scene.addRect(crop_rect)

    # Footer label
    label = getattr(getattr(blot, "protein_label", None), "text", "Blot")
    footer = scene.addText(f"Provenance: {label}", font)
    footer.setPos(x0, y0 + pm.height() + 10)

    return scene
