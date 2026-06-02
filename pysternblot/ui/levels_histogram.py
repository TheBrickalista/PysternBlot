# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
LevelsHistogramWidget — compact QPainter-based intensity histogram for the
Levels panel in the Original Image tab.

Supports draggable black/white gate lines that emit gate_changed (continuous)
and gate_commit (on mouse release) signals for integration with the sliders.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPolygon
from PySide6.QtCore import Qt, Signal, QPoint


class LevelsHistogramWidget(QWidget):
    """
    Compact intensity histogram with adaptive x-axis zoom and draggable gates.

    Signals
    -------
    gate_changed(which, value)  — emitted on every mouse-move during a gate drag.
                                  which = "black" or "white", value in [0, max_val].
    gate_commit()               — emitted once on mouseRelease; signals the end of
                                  a drag so the caller can do one save+log cycle.

    Public API
    ----------
    set_image(arr, max_val)       — compute 256-bin log histogram, cache, repaint.
    set_precomputed(counts, edges, max_val) — install pre-computed data, repaint.
    set_gates(black, white)       — update gate positions, repaint (no recompute).
    clear()                       — reset to blank, repaint.
    """

    gate_changed = Signal(str, int)
    gate_commit  = Signal()

    _BINS: int          = 256
    _MARGIN_FRAC: float = 0.05   # margin beyond each gate as fraction of span
    _MIN_WINDOW: int    = 16     # minimum window to prevent near-zero division
    _HIT_TOLERANCE: int = 8      # px within which a click grabs a gate

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts: np.ndarray | None = None
        self._edges:  np.ndarray | None = None
        self._max_val: int = 65535
        self._black: int   = 0
        self._white: int   = 65535

        self._active_gate: str | None = None   # "black" or "white" while dragging

        self.setMinimumHeight(90)
        self.setFixedHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setToolTip(
            "Source-image intensity histogram (log scale).\n"
            "Drag the black or white gate line to adjust levels.\n"
            "The x-axis zooms to the selected window — closing the gates\n"
            "reveals fine structure in the band region."
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
        self._edges  = edges
        self._max_val = max_val
        self.update()

    def set_precomputed(
        self,
        counts: np.ndarray,
        edges: np.ndarray,
        max_val: int,
    ) -> None:
        """Install already-computed histogram data (avoids re-binning)."""
        self._counts  = counts
        self._edges   = edges
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
        self._edges  = None
        self.update()

    # ------------------------------------------------------------------
    # Window geometry helpers
    # ------------------------------------------------------------------

    def _window(self) -> tuple[float, float]:
        """Return (x_min, visible_range) for the current gate positions."""
        span = max(self._white - self._black, self._MIN_WINDOW)
        margin = max(1, int(span * self._MARGIN_FRAC))
        x_min = float(max(0, self._black - margin))
        x_max = float(min(self._max_val, self._white + margin))
        if x_max <= x_min:
            x_max = x_min + self._MIN_WINDOW
        return x_min, x_max - x_min

    def _to_px(self, intensity: float, w: int, x_min: float, vrange: float) -> int:
        return int(round((intensity - x_min) / vrange * w))

    def _to_intensity(self, px: float, w: int, x_min: float, vrange: float) -> int:
        raw = x_min + (px / w) * vrange
        return int(round(max(0.0, min(float(self._max_val), raw))))

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()

        # White background
        painter.fillRect(0, 0, w, h, QColor("#ffffff"))

        # 1 px light-grey border so the white panel has a visible edge
        painter.setPen(QPen(QColor("#cccccc"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(0, 0, w - 1, h - 1)

        if self._counts is None or self._edges is None or w < 4 or h < 4:
            painter.end()
            return

        x_min, visible_range = self._window()

        # ---- log-scale bar heights ----
        counts    = self._counts
        edges     = self._edges
        log_counts = np.log1p(counts.astype(np.float64))
        max_log   = log_counts.max()
        if max_log == 0.0:
            painter.end()
            return

        # 2 px top margin; 1 px bottom inset keeps bars off the border line
        draw_h = h - 3
        y_base = h - 1

        # ---- draw histogram bars — dark on white ----
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#1a1a1a")))

        bin_lo = edges[:-1]
        bin_hi = edges[1:]

        for i in range(len(counts)):
            lo = float(bin_lo[i])
            hi = float(bin_hi[i])

            if hi <= x_min or lo >= x_min + visible_range:
                continue

            clipped_lo = max(lo, x_min)
            clipped_hi = min(hi, x_min + visible_range)

            px0 = int(round((clipped_lo - x_min) / visible_range * w))
            px1 = int(round((clipped_hi - x_min) / visible_range * w))
            if px1 <= px0:
                px1 = px0 + 1

            bar_h = int(log_counts[i] / max_log * draw_h)
            if bar_h < 1:
                continue

            painter.drawRect(px0, y_base - bar_h, px1 - px0, bar_h)

        # ---- gate lines — both black, 2 px ----
        bx     = self._to_px(self._black, w, x_min, visible_range)
        bx     = max(0, min(bx, w - 1))
        wx_pos = self._to_px(self._white, w, x_min, visible_range)
        wx_pos = max(0, min(wx_pos, w - 1))

        painter.setPen(QPen(QColor("#000000"), 2))
        painter.drawLine(bx, 0, bx, h)
        painter.drawLine(wx_pos, 0, wx_pos, h)

        # ---- triangle markers — enable antialiasing ----
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#000000")))

        # Black gate: downward-pointing triangle at the TOP edge
        tri_b = QPolygon([
            QPoint(bx - 5, 0),
            QPoint(bx + 5, 0),
            QPoint(bx,     8),
        ])
        painter.drawPolygon(tri_b)

        # White gate: upward-pointing triangle at the BOTTOM edge
        tri_w = QPolygon([
            QPoint(wx_pos - 5, h),
            QPoint(wx_pos + 5, h),
            QPoint(wx_pos,     h - 8),
        ])
        painter.drawPolygon(tri_w)

        painter.end()

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        if self._counts is None:
            return super().mousePressEvent(event)

        x_min, vrange = self._window()
        w  = self.width()
        cx = event.position().x()

        bx     = self._to_px(self._black, w, x_min, vrange)
        wx_pos = self._to_px(self._white, w, x_min, vrange)

        dist_b = abs(cx - bx)
        dist_w = abs(cx - wx_pos)

        if dist_b <= self._HIT_TOLERANCE or dist_w <= self._HIT_TOLERANCE:
            self._active_gate = "black" if dist_b <= dist_w else "white"
            self.setCursor(Qt.SizeHorCursor)

        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._counts is None:
            self.unsetCursor()
            return super().mouseMoveEvent(event)

        x_min, vrange = self._window()
        w  = self.width()
        cx = event.position().x()

        if self._active_gate is not None:
            # ---- active drag: map pixel → intensity, clamp, emit ----
            new_val = self._to_intensity(cx, w, x_min, vrange)
            if self._active_gate == "black":
                new_val = max(0, min(new_val, self._white - 1))
            else:
                new_val = max(self._black + 1, min(new_val, self._max_val))

            # Update internal state for immediate visual feedback
            if self._active_gate == "black":
                self._black = new_val
            else:
                self._white = new_val
            self.update()

            self.gate_changed.emit(self._active_gate, new_val)
            self.setCursor(Qt.SizeHorCursor)

        else:
            # ---- hover: show resize cursor near either gate ----
            bx     = self._to_px(self._black, w, x_min, vrange)
            wx_pos = self._to_px(self._white, w, x_min, vrange)
            if abs(cx - bx) <= self._HIT_TOLERANCE or abs(cx - wx_pos) <= self._HIT_TOLERANCE:
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.unsetCursor()

        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._active_gate is not None:
            self._active_gate = None
            self.unsetCursor()
            self.gate_commit.emit()
        event.accept()
