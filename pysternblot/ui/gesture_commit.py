# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
One operation-log entry per gesture for continuous controls.

While a slider, dial or spinbox is moving, the model and the screen update
on every tick, but nothing is logged or saved. When the gesture ends (slider
released, spinbox editing finished, or no tick for IDLE_COMMIT_MS), the
change is committed once: one log entry from the value before the gesture to
the final value, then one save.

Invariant: project.json on disk and the operation log never disagree. A value
reaches disk only together with the entry that records it, so every save and
every other log entry first flushes the pending change (see
_ProjectIOMixin._save_project / log_operation). If the app crashes
mid-gesture, the uncommitted change is lost from both, which is acceptable.

Screen updates during a gesture are debounced separately (REDRAW_DEBOUNCE_MS)
and use the narrowest refresh that the control can affect.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QAbstractSlider

# No tick for this long ends the gesture (keyboard, wheel and spinbox arrow
# changes have no "released" signal). While the source slider is held down
# (mouse drag paused), the timer re-arms instead and sliderReleased commits.
IDLE_COMMIT_MS = 700
# Screen redraws during a gesture are coalesced over this interval.
REDRAW_DEBOUNCE_MS = 80

# (operation, target_type, target_id, field, nir_channel_index_or_None)
GestureKey = tuple


class GestureCommitter(QObject):
    """Owns at most one pending continuous change.

    commit(project, key, old_value, new_value, log_kwargs) is called once per
    gesture by flush(); it logs the entry and saves the project.
    project_getter() returns the project a new gesture belongs to.
    """

    def __init__(
        self,
        commit: Callable[..., None],
        project_getter: Callable[[], Any],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._commit = commit
        self._project_getter = project_getter
        self._pending: Optional[dict] = None
        self._flushing = False
        self._redraw_fn: Optional[Callable[[], None]] = None

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_COMMIT_MS)
        self._idle.timeout.connect(self._on_idle_timeout)

        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.setInterval(REDRAW_DEBOUNCE_MS)
        self._redraw.timeout.connect(self.run_pending_redraw)

    # ------------------------------------------------------------- state
    @property
    def has_pending(self) -> bool:
        return self._pending is not None

    @property
    def is_flushing(self) -> bool:
        return self._flushing

    # ----------------------------------------------------------- updates
    def update(
        self, key: GestureKey, old_value, new_value, *, source=None, **log_kwargs,
    ) -> None:
        """Record one tick. old_value is kept from the first tick of the
        gesture; new_value, asset_sha256 and note follow the latest tick.
        source is the widget that produced the tick; if it is a slider held
        down by the mouse, the idle timer does not end the gesture."""
        if self._pending is not None and self._pending["key"] != key:
            self.flush()
        if self._pending is None:
            self._pending = {
                "key": key,
                "project": self._project_getter(),
                "old": old_value,
            }
        self._pending["new"] = new_value
        self._pending["source"] = source
        self._pending["log_kwargs"] = dict(log_kwargs)
        self._idle.start()   # restart: the gesture ends after IDLE_COMMIT_MS of quiet

    def request_redraw(self, fn: Callable[[], None]) -> None:
        """Run fn after REDRAW_DEBOUNCE_MS of no further requests."""
        self._redraw_fn = fn
        self._redraw.start()

    def run_pending_redraw(self) -> None:
        self._redraw.stop()
        fn, self._redraw_fn = self._redraw_fn, None
        if fn is not None:
            fn()

    # ------------------------------------------------------------ commit
    def _source_slider_down(self) -> bool:
        source = self._pending.get("source") if self._pending else None
        if not isinstance(source, QAbstractSlider):
            return False
        try:
            return bool(source.isSliderDown())
        except RuntimeError:   # the widget's C++ object is gone
            return False

    def _on_idle_timeout(self) -> None:
        """Idle commit, except while the mouse still holds the slider: a
        paused drag is not the end of the gesture. Re-arm and let
        sliderReleased (or any forced flush) commit."""
        if self._source_slider_down():
            self._idle.start()
            return
        self.flush()

    def flush(self) -> None:
        """Commit the pending change (one log entry, one save), then run any
        pending redraw so the screen matches the committed state.
        Reentrant calls (from the commit's own log_operation / save) are no-ops."""
        if self._flushing:
            return
        self._idle.stop()
        pending, self._pending = self._pending, None
        if pending is not None:
            self._flushing = True
            try:
                self._commit(
                    pending["project"], pending["key"], pending["old"], pending["new"],
                    pending["log_kwargs"],
                )
            finally:
                self._flushing = False
        self.run_pending_redraw()
