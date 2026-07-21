# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

from PySide6.QtCore import QSettings

KEY_PROMPTED = "updates/prompted"
KEY_ENABLED = "updates/check_enabled"


def _settings() -> QSettings:
    return QSettings()  # org/app configured in app.py


def has_been_prompted() -> bool:
    return _settings().value(KEY_PROMPTED, False, type=bool)


def set_prompted(value: bool = True) -> None:
    _settings().setValue(KEY_PROMPTED, value)


def update_check_enabled() -> bool:
    return _settings().value(KEY_ENABLED, False, type=bool)


def set_update_check_enabled(value: bool) -> None:
    _settings().setValue(KEY_ENABLED, value)
