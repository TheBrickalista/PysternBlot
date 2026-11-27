# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""Workspace location, without Qt.

Kept free of PySide6 so that headless callers (the Pyblication plugin,
command-line tools) can find the workspace without importing the GUI.
"""

from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ENV = "PYSTERNBLOT_WORKSPACE"


def default_workspace() -> Path:
    """~/.pysternblot, overridable with PYSTERNBLOT_WORKSPACE (tests, demos)."""
    env = os.environ.get(WORKSPACE_ENV)
    return Path(env).expanduser() if env else Path.home() / ".pysternblot"
