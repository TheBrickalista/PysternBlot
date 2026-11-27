# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""What the Pyblication plugin relies on in the app:

* An export's export_generated entry is on disk (project.json) before the
  export dialog reports success, so Pyblication can identify the file
  straight away.
* --project <id> opens that project; without it the app starts as before.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import test_export_hashes as th
from pysternblot import main as main_module
from pysternblot import paths, plugin
from pysternblot.ui import export_mixin as export_mixin_module
from pysternblot.ui import main_window as main_window_module

qapp = th.qapp  # the session QApplication fixture


@pytest.mark.parametrize(
    ("method", "ext"),
    [("export_final_png", ".png"), ("export_final_pdf", ".pdf"), ("export_final_svg", ".svg")],
)
def test_export_entry_is_on_disk_when_success_is_reported(qapp, tmp_path, monkeypatch, method, ext):
    win, project, _ = th._ecl_window(tmp_path)
    monkeypatch.setenv(paths.WORKSPACE_ENV, str(win.workspace.root))
    dest = tmp_path / f"figure{ext}"
    seen = {}

    def at_success(*args, **kwargs):
        # The moment the user is told "Exported": what is on disk now?
        on_disk = json.loads(
            (win.workspace.projects_dir / project.project.id / "project.json").read_text()
        )
        seen["logged"] = [
            e["new_value"]["sha256"]
            for e in on_disk["operation_log"]
            if e["operation"] == "export_generated"
        ]
        seen["identified"] = plugin.identify(str(dest))

    p1, p2, _p3, p4 = th._patched_dialogs(save_path=str(dest))
    with p1, p2, patch.object(
        export_mixin_module.QMessageBox, "information", side_effect=at_success
    ), p4 as critical:
        getattr(win, method)()
    assert not critical.called, critical.call_args
    assert seen["logged"] == [th._sha(dest)]
    assert seen["identified"]["project_id"] == project.project.id


def _saved_window(tmp_path):
    win, project, _ = th._ecl_window(tmp_path)
    win.workspace.save_project(project)
    win.current_project = None
    return win, project


def test_open_project_by_id(qapp, tmp_path):
    win, project = _saved_window(tmp_path)
    with patch.object(main_window_module.QMessageBox, "critical") as critical:
        win.open_project_by_id(project.project.id)
    assert not critical.called, critical.call_args
    assert win.current_project.project.id == project.project.id
    assert win.tabs.currentIndex() == 2  # Final Result, as a library double-click


def test_open_project_by_unknown_id_warns(qapp, tmp_path):
    win, _ = _saved_window(tmp_path)
    with patch.object(main_window_module.QMessageBox, "warning") as warning:
        win.open_project_by_id("proj_nope")
    assert warning.called and "proj_nope" in warning.call_args.args[2]
    assert win.current_project is None


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),
        (["--project", "proj_abc"], "proj_abc"),
        (["--project=proj_abc"], "proj_abc"),
        (["--project"], None),
        (["--project="], None),
        (["--selfcheck-out", "x"], None),
    ],
)
def test_parse_project_arg(argv, expected):
    assert main_module.parse_project_arg(argv) == expected


def test_main_routes_project_arg(monkeypatch):
    calls = []
    import pysternblot.app as app_module

    monkeypatch.setattr(app_module, "run", lambda **kw: calls.append(kw))
    main_module.main([])
    main_module.main(["--project", "proj_abc"])
    assert calls == [{}, {"project_id": "proj_abc"}]  # no argument: run() exactly as before
