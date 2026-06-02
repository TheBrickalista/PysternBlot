# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
LevelsHistogramWidget — compact QPainter-based intensity histogram for the
Levels panel in the Original Image tab.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtCore import Qt


class LevelsHistogramWidget(QWidget):
    """
    Compact intensity histogram with adaptive x-axis zoom.

    Public API
    ----------
    set_image(arr, max_val)       — compute 256-bin log histogram, cache, repaint.
    set_precomputed(counts, edges, max_val) — install pre-computed data, repaint.
    set_gates(black, white)       — update gate lines, repaint (no recompute).
    clear()                       — reset to blank, repaint.
    """

    _BINS: int = 256
    _MARGIN_FRAC: float = 0.05   # visible margin beyond each gate as fraction of span
    _MIN_WINDOW: int = 16        # minimum window to prevent near-zero division

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts: np.ndarray | None = None
        self._edges: np.ndarray | None = None
        self._max_val: int = 65535
        self._black: int = 0
        self._white: int = 65535

        self.setMinimumHeight(90)
        self.setFixedHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(
            "Source-image intensity histogram (log scale).\n"
            "The x-axis zooms to the selected black/white window — "
            "closing the gates reveals fine structure in the band region."
        )

    # ------------------------------------------------------------------
    # Data setters
    # ------------------------------------------------------------------

    def set_image(self, arr: np.ndarray, max_val: int) -> None:
        """Compute and cache a 256-bin log histogram from a pixel array."""
        counts, edges = np.histogram(
            arr.ravel(), bins=self._BINS, range=(0, max_val)
        )
        self._counts = counts
        self._edges = edges
        self._max_val = max_val
        self.update()

    def set_precomputed(
        self,
        counts: np.ndarray,
        edges: np.ndarray,
        max_val: int,
    ) -> None:
        """Install already-computed histogram data (avoids re-binning)."""
        self._counts = counts
        self._edges = edges
        self._max_val = max_val
        self.update()

    def set_gates(self, black: int, white: int) -> None:
        """Update gate positions and repaint. Does not recompute the histogram."""
        self._black = int(black)
        self._white = int(white)
        self.update()

    def clear(self) -> None:
        """Reset to blank (no histogram data). Repaints to a plain background."""
        self._counts = None
        self._edges = None
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()

        # Background — dark inset, standard for histogram panels
        painter.fillRect(0, 0, w, h, QColor("#262626"))

        if self._counts is None or self._edges is None or w < 4 or h < 4:
            painter.end()
            return

        black = self._black
        white = self._white
        max_val = self._max_val

        # ---- adaptive x-axis window ----
        span = max(white - black, self._MIN_WINDOW)
        margin = max(1, int(span * self._MARGIN_FRAC))
        x_min = max(0, black - margin)
        x_max = min(max_val, white + margin)
        if x_max <= x_min:
            x_max = x_min + self._MIN_WINDOW
        visible_range = float(x_max - x_min)

        # ---- log-scale bar heights ----
        counts = self._counts
        edges = self._edges
        log_counts = np.log1p(counts.astype(np.float64))
        max_log = log_counts.max()
        if max_log == 0.0:
            painter.end()
            return

        # Leave 2px top margin so tallest bar doesn't clip the edge
        draw_h = h - 2

        # ---- draw histogram bars ----
        bar_color = QColor("#5a7a90")
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bar_color))

        bin_lo = edges[:-1]
        bin_hi = edges[1:]

        for i in range(len(counts)):
            lo = float(bin_lo[i])
            hi = float(bin_hi[i])

            if hi <= x_min or lo >= x_max:
                continue

            clipped_lo = max(lo, float(x_min))
            clipped_hi = min(hi, float(x_max))

            px0 = int(round((clipped_lo - x_min) / visible_range * w))
            px1 = int(round((clipped_hi - x_min) / visible_range * w))
            if px1 <= px0:
                px1 = px0 + 1

            bar_h = int(log_counts[i] / max_log * draw_h)
            if bar_h < 1:
                continue

            painter.drawRect(px0, h - bar_h, px1 - px0, bar_h)

        # ---- black gate line: dark, clearly darker than bars ----
        bx = int(round((black - x_min) / visible_range * w))
        bx = max(0, min(bx, w - 1))
        painter.setPen(QPen(QColor("#111111"), 2))
        painter.drawLine(bx, 0, bx, h)

        # Thin bright highlight at black gate to make it visible on dark background
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.drawLine(bx + 1, 0, bx + 1, h)

        # ---- white gate line: light, outlined for contrast on bright areas ----
        wx_pos = int(round((white - x_min) / visible_range * w))
        wx_pos = max(0, min(wx_pos, w - 1))
        painter.setPen(QPen(QColor("#dddddd"), 2))
        painter.drawLine(wx_pos, 0, wx_pos, h)

        painter.end()
