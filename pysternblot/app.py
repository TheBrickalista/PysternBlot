# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
from PySide6.QtWidgets import QApplication
from .paths import default_workspace  # also importable as pysternblot.app.default_workspace
from .storage import Workspace
from .ui.main_window import MainWindow

def run(project_id: str | None = None):
    app = QApplication([])
    app.setOrganizationName("IRCAN")
    app.setApplicationName("PysternBlot")
    ws = Workspace(default_workspace())
    ws.ensure()
    win = MainWindow(ws)
    win.show()
    if project_id:
        win.open_project_by_id(project_id)
    win.maybe_prompt_and_check_updates()
    app.exec()
