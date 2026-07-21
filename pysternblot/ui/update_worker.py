# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..update_check import check_for_update


class _UpdateSignals(QObject):
    finished = Signal(object)  # emits dict | None


class UpdateCheckWorker(QRunnable):
    def __init__(self, enabled: bool, timeout: float = 3.0):
        super().__init__()
        self.enabled = enabled
        self.timeout = timeout
        self.signals = _UpdateSignals()

    @Slot()
    def run(self):
        try:
            result = check_for_update(self.enabled, self.timeout)
        except Exception:
            result = None
        self.signals.finished.emit(result)
