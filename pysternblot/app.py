# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
from PySide6.QtWidgets import QApplication
from pathlib import Path
from .storage import Workspace
from .ui.main_window import MainWindow

def default_workspace() -> Path:
    return Path.home() / ".pysternblot"

def run():
    app = QApplication([])
    ws = Workspace(default_workspace())
    ws.ensure()
    win = MainWindow(ws)
    win.show()
    app.exec()
