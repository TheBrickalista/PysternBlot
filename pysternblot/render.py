# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtGui import QFont
from PySide6.QtCore import QRectF, Qt
from .models import Project

def build_scene(project: Project) -> QGraphicsScene:
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
