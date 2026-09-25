# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

import logging

from ..update_check import (
    CATEGORY_UNEXPECTED, OUTCOME_CHECK_FAILED, CheckResult, check_for_update,
)

_log = logging.getLogger("pysternblot.update")


class _UpdateSignals(QObject):
    finished = Signal(object)  # emits CheckResult | None (None only if disabled)


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
        except Exception as exc:  # a bug in the check: report it, never look "up to date"
            _log.exception("Update check crashed")
            result = CheckResult(
                outcome=OUTCOME_CHECK_FAILED, category=CATEGORY_UNEXPECTED,
                detail=f"{type(exc).__name__}: {exc}",
            )
        self.signals.finished.emit(result)
