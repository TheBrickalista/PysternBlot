"""Per-project edit lock (project_lock.py) and read-only mode.

- opening a project creates projects/<id>/.lock; closing removes it;
- a lock held by another live process -> read-only (default), open anyway
  or cancel; a stale lock (same host, dead pid) is taken over silently;
- read-only blocks every save and log entry, shows a banner and a single
  notice; a lock taken over by another window switches this one to
  read-only before its next save;
- reading never needs the lock and the lock is never project content.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pysternblot import project_lock
from pysternblot.plugin import _read_projects
from pysternblot.storage import ProjectReadOnlyError, Workspace
from pysternblot.ui import project_io_mixin
from pysternblot.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def ws(tmp_path):
    w = Workspace(root=tmp_path / "ws")
    w.ensure()
    return w


@pytest.fixture
def dialogs(monkeypatch):
    """Record every message box instead of showing it."""
    shown: list[tuple[str, str, str]] = []

    def recorder(kind):
        def _show(_parent, title, text, *a, **k):
            shown.append((kind, title, text))
        return _show

    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(project_io_mixin.QMessageBox, kind, staticmethod(recorder(kind)))
    return shown


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _write_other_lock(project_dir: Path, *, pid: int, host: str | None = None) -> str:
    info = project_lock.LockInfo(
        host=host or socket.gethostname(), pid=pid, app="PysternBlot",
        app_version="9.9.9", created_utc="2026-01-01T00:00:00+00:00",
        executable="/other/python", token="other-token",
    )
    project_lock.lock_path(project_dir).write_text(
        json.dumps(project_lock.asdict(info)), encoding="utf-8")
    return info.token


def _lock_of(project_dir: Path) -> project_lock.LockInfo | None:
    return project_lock.LockInfo.from_file(project_lock.lock_path(project_dir))


# ===========================================================================
# project_lock (no Qt)
# ===========================================================================

class TestLockFile:

    def test_acquire_creates_lock_with_fields(self, tmp_path):
        result = project_lock.acquire(tmp_path)
        assert result.status == project_lock.ACQUIRED
        data = json.loads((tmp_path / ".lock").read_text(encoding="utf-8"))
        assert data["host"] == socket.gethostname()
        assert data["pid"] == os.getpid()
        assert data["app"] == "PysternBlot"
        assert data["app_version"]
        assert data["created_utc"]
        assert data["token"] == result.token

    def test_release_removes_own_lock(self, tmp_path):
        result = project_lock.acquire(tmp_path)
        assert project_lock.release(tmp_path, result.token)
        assert not (tmp_path / ".lock").exists()

    def test_release_keeps_a_lock_it_does_not_own(self, tmp_path):
        _write_other_lock(tmp_path, pid=os.getppid())
        assert not project_lock.release(tmp_path, "not-mine")
        assert (tmp_path / ".lock").exists()

    def test_second_acquire_is_held_by_other(self, tmp_path):
        _write_other_lock(tmp_path, pid=os.getppid())
        result = project_lock.acquire(tmp_path)
        assert result.status == project_lock.HELD_BY_OTHER
        assert result.holder.app_version == "9.9.9"
        assert _lock_of(tmp_path).token == "other-token"

    def test_other_host_is_never_stale(self, tmp_path):
        _write_other_lock(tmp_path, pid=_dead_pid(), host="another-machine.example")
        assert project_lock.acquire(tmp_path).status == project_lock.HELD_BY_OTHER

    def test_stale_lock_is_taken_over(self, tmp_path):
        _write_other_lock(tmp_path, pid=_dead_pid())
        result = project_lock.acquire(tmp_path)
        assert result.status == project_lock.TOOK_OVER_STALE
        assert _lock_of(tmp_path).token == result.token
        assert _lock_of(tmp_path).pid == os.getpid()

    def test_own_pid_with_foreign_token_is_stale(self, tmp_path):
        _write_other_lock(tmp_path, pid=os.getpid())
        assert project_lock.acquire(tmp_path).status == project_lock.TOOK_OVER_STALE

    def test_corrupt_lock_is_not_taken(self, tmp_path):
        (tmp_path / ".lock").write_text("not json", encoding="utf-8")
        result = project_lock.acquire(tmp_path)
        assert result.status == project_lock.HELD_BY_OTHER
        assert result.holder is None
        assert (tmp_path / ".lock").read_text(encoding="utf-8") == "not json"

    def test_force_replaces_and_still_ours(self, tmp_path):
        _write_other_lock(tmp_path, pid=os.getppid())
        token = project_lock.force(tmp_path)
        assert project_lock.still_ours(tmp_path, token)
        assert not project_lock.still_ours(tmp_path, "other-token")

    def test_pid_alive(self):
        assert project_lock.pid_alive(os.getpid())
        assert not project_lock.pid_alive(_dead_pid())


class TestWorkspaceLocks:

    def test_saves_refused_for_read_only_ids(self, ws):
        path = ws.create_new_project("RO")
        project = ws.load_project(str(path))
        before = path.read_bytes()
        ws.read_only_ids.add(project.project.id)
        project.project.name = "changed"
        with pytest.raises(ProjectReadOnlyError):
            ws.save_project(project)
        assert path.read_bytes() == before

    def test_rename_refused_when_locked_elsewhere(self, ws):
        path = ws.create_new_project("Locked")
        _write_other_lock(path.parent, pid=os.getppid())
        before = path.read_bytes()
        with pytest.raises(ProjectReadOnlyError, match="another PysternBlot"):
            ws.rename_project(ws.load_project(str(path)), "New")
        with pytest.raises(ProjectReadOnlyError):
            ws.set_project_archived(str(path), True)
        assert path.read_bytes() == before

    def test_reading_ignores_the_lock(self, ws, tmp_path):
        path = ws.create_new_project("Read")
        pid = path.parent.name
        _write_other_lock(path.parent, pid=os.getppid())
        ws.load_project(str(path))                    # no lock needed
        assert [p for p, _ in _read_projects(ws.root)] == [path]
        archive = tmp_path / "x.pbarchive"
        ws.export_archive([pid], archive, app_version="test")
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
        assert not any(".lock" in n for n in names)
        assert f"pbarchive/projects/{pid}/project.json" in names

    def test_release_removes_folder_left_empty(self, ws):
        ws.project_dir("proj_external").mkdir(parents=True)
        assert ws.acquire_lock("proj_external").acquired
        ws.release_lock("proj_external")
        assert not ws.project_dir("proj_external").exists()

    @pytest.mark.parametrize("stray", ["notes.txt", ".hidden", ".project.abc.json.tmp"])
    def test_release_keeps_folder_with_a_stray_file(self, ws, stray):
        folder = ws.project_dir("proj_stray")
        folder.mkdir(parents=True)
        (folder / stray).write_bytes(b"keep me")
        assert ws.acquire_lock("proj_stray").acquired
        ws.release_lock("proj_stray")
        assert not (folder / ".lock").exists()          # our lock is gone
        assert (folder / stray).read_bytes() == b"keep me"
        assert sorted(p.name for p in folder.iterdir()) == [stray]

    def test_release_keeps_folder_with_subfolder(self, ws):
        folder = ws.project_dir("proj_sub")
        (folder / "sub").mkdir(parents=True)
        assert ws.acquire_lock("proj_sub").acquired
        ws.release_lock("proj_sub")
        assert (folder / "sub").is_dir()

    def test_release_keeps_project_folder(self, ws):
        path = ws.create_new_project("Kept")
        pid = path.parent.name
        assert ws.acquire_lock(pid).acquired
        ws.release_lock(pid)
        assert path.is_file()
        assert sorted(p.name for p in path.parent.iterdir()) == ["project.json"]

    def test_folder_untouched_when_lock_is_not_ours(self, ws):
        # Lock taken over by another window: release removes nothing at all,
        # not even an otherwise empty folder.
        folder = ws.project_dir("proj_taken")
        folder.mkdir(parents=True)
        assert ws.acquire_lock("proj_taken").acquired
        _write_other_lock(folder, pid=os.getppid())
        ws.release_lock("proj_taken")
        assert _lock_of(folder).token == "other-token"

    def test_release_of_unheld_project_touches_nothing(self, ws):
        folder = ws.project_dir("proj_never_locked")
        folder.mkdir(parents=True)
        ws.release_lock("proj_never_locked")              # no token held
        assert folder.is_dir()

    def test_release_only_touches_its_own_folder(self, ws):
        a, b = ws.project_dir("proj_a"), ws.project_dir("proj_b")
        a.mkdir(parents=True)
        b.mkdir(parents=True)                             # empty sibling
        assert ws.acquire_lock("proj_a").acquired
        ws.release_lock("proj_a")
        assert not a.exists()
        assert b.is_dir()
        assert ws.projects_dir.is_dir()


# ===========================================================================
# MainWindow
# ===========================================================================

@pytest.fixture
def make_win(qapp, ws, dialogs):
    windows = []

    def _make(choice: str | None = None):
        w = MainWindow(ws)
        asked = []

        def _ask(holder):
            asked.append(holder)
            assert choice is not None, "lock dialog was not expected"
            return choice

        w._ask_lock_choice = _ask
        w.asked = asked
        windows.append(w)
        return w

    yield _make
    for w in windows:
        w.close()


def _project(ws) -> Path:
    return ws.create_new_project("Locked project")


class TestWindowLocks:

    def test_lock_created_on_open_and_removed_on_close(self, make_win, ws):
        path = _project(ws)
        win = make_win()
        win.open_project_at(str(path))
        lock = _lock_of(path.parent)
        assert lock is not None and lock.pid == os.getpid()
        assert win.current_project.project.id == path.parent.name
        assert not win._is_read_only()
        win.close()
        assert not (path.parent / ".lock").exists()

    def test_switching_project_releases_previous_lock(self, make_win, ws):
        a, b = _project(ws), _project(ws)
        win = make_win()
        win.open_project_at(str(a))
        win.open_project_at(str(b))
        assert not (a.parent / ".lock").exists()
        assert (b.parent / ".lock").exists()

    def test_second_open_is_read_only(self, make_win, ws, dialogs):
        path = _project(ws)
        first = make_win()
        first.open_project_at(str(path))
        first_token = _lock_of(path.parent).token
        # A second window (its own workspace object: another process).
        second = MainWindow(Workspace(root=ws.root))
        second._ask_lock_choice = lambda holder: "read_only"
        try:
            second.open_project_at(str(path))
            assert second._is_read_only()
            assert not second.read_only_banner.isHidden()
            assert "read-only" in second.windowTitle()
            assert _lock_of(path.parent).token == first_token
        finally:
            second.close()
        # The read-only window never owned the lock: closing keeps it.
        assert _lock_of(path.parent).token == first_token

    def test_stale_lock_taken_over_without_asking(self, make_win, ws):
        path = _project(ws)
        _write_other_lock(path.parent, pid=_dead_pid())
        win = make_win(choice=None)
        win.open_project_at(str(path))
        assert win.asked == []
        assert not win._is_read_only()
        assert _lock_of(path.parent).pid == os.getpid()

    def test_open_anyway_takes_the_lock(self, make_win, ws):
        path = _project(ws)
        _write_other_lock(path.parent, pid=os.getppid())
        win = make_win(choice="anyway")
        win.open_project_at(str(path))
        assert not win._is_read_only()
        assert _lock_of(path.parent).token == ws.held_locks[path.parent.name]

    def test_cancel_keeps_current_project(self, make_win, ws):
        a, b = _project(ws), _project(ws)
        win = make_win(choice="cancel")
        win.open_project_at(str(a))
        _write_other_lock(b.parent, pid=os.getppid())
        win.open_project_at(str(b))
        assert win.current_project.project.id == a.parent.name
        assert (a.parent / ".lock").exists()
        assert _lock_of(b.parent).token == "other-token"


class TestReadOnlyBlocks:

    def _read_only_win(self, make_win, ws):
        path = _project(ws)
        _write_other_lock(path.parent, pid=os.getppid())
        win = make_win(choice="read_only")
        win.open_project_at(str(path))
        assert win._is_read_only()
        return win, path

    def test_saves_and_log_entries_are_blocked(self, make_win, ws, dialogs):
        win, path = self._read_only_win(make_win, ws)
        before = path.read_bytes()
        n = len(win.current_project.operation_log)
        win.log_operation("project_renamed", target_type="project",
                          old_value="a", new_value="b")
        win.current_project.project.name = "changed in memory"
        win._save_project()
        assert len(win.current_project.operation_log) == n
        assert path.read_bytes() == before

    def test_gesture_commit_is_blocked(self, make_win, ws):
        win, path = self._read_only_win(make_win, ws)
        before = path.read_bytes()
        win._commit_gesture(win.current_project,
                            ("border_width_changed", "project", "x", "f", None), 1, 2, {})
        assert path.read_bytes() == before
        assert win.current_project.operation_log == []

    def test_first_blocked_change_notifies_once(self, make_win, ws, dialogs):
        win, _path = self._read_only_win(make_win, ws)
        dialogs.clear()
        for i in range(3):
            win.log_operation("x", old_value=i, new_value=i + 1)
            win._save_project()
        notices = [d for d in dialogs if "not saved" in d[2]]
        assert len(notices) == 1
        assert "not saved" in win.statusBar().currentMessage()

    def test_exports_and_imports_refused(self, make_win, ws, dialogs, monkeypatch):
        win, path = self._read_only_win(make_win, ws)
        monkeypatch.setattr(project_io_mixin.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: pytest.fail("import dialog opened")))
        dialogs.clear()
        win.import_blot()
        win.export_final_png()
        assert len(dialogs) == 2
        assert all("read-only" in d[2] for d in dialogs)


class TestLostLock:

    def test_taken_over_lock_switches_to_read_only(self, make_win, ws, dialogs):
        path = _project(ws)
        win = make_win()
        win.open_project_at(str(path))
        assert not win._is_read_only()
        # Another PysternBlot chose "Open anyway".
        project_lock.force(path.parent)
        other_token = _lock_of(path.parent).token
        before = path.read_bytes()
        dialogs.clear()

        win.log_operation("x", old_value=1, new_value=2)
        win._save_project()

        assert path.read_bytes() == before
        assert win._is_read_only()
        assert not win.read_only_banner.isHidden()
        assert "read-only" in win.windowTitle()
        assert any("took over editing" in d[2] for d in dialogs)
        # Closing must not remove the new holder's lock.
        win.close()
        assert _lock_of(path.parent).token == other_token

    def test_no_lock_held_means_no_check(self, ws, qapp):
        # Hosts that set current_project directly (most UI tests) still save.
        path = _project(ws)
        win = MainWindow(ws)
        try:
            win.current_project = ws.load_project(str(path))
            win.current_project.project.name = "saved"
            win._save_project()
            assert json.loads(path.read_text())["project"]["name"] == "saved"
        finally:
            win.close()


class TestLibraryNewerFormat:

    def test_newer_project_listed_and_refused(self, make_win, ws, dialogs):
        path = _project(ws)
        data = json.loads(path.read_text())
        data["project"]["format_version"] = 99
        path.write_text(json.dumps(data))
        win = make_win()
        win.refresh_library()
        names = [win.library_table.item(r, 0).text() for r in range(win.library_table.rowCount())]
        assert any("needs a newer PysternBlot" in n for n in names)


# ===========================================================================
# Holder's start time in local time (dialog and banner); UTC in the file
# ===========================================================================

class TestLockTimeDisplay:
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    PARIS_WINTER = _tz(_td(hours=1))
    NOW = _dt(2026, 11, 27, 16, 0, tzinfo=_tz.utc)

    def _fmt(self, iso, tz=PARIS_WINTER, now=NOW):
        return project_lock.format_lock_time(iso, now=now, tz=tz)

    def test_today(self):
        assert self._fmt("2026-11-27T13:15:00+00:00") == "today at 14:15"

    def test_other_day(self):
        assert self._fmt("2026-11-26T13:15:00+00:00") == "26 Nov 2026 at 14:15"

    def test_day_is_decided_in_local_time(self):
        # 23:30 UTC on the 26th is 00:30 on the 27th in UTC+1: today.
        assert self._fmt("2026-11-26T23:30:00+00:00") == "today at 00:30"
        # ...but in UTC it is still the 26th.
        assert self._fmt("2026-11-26T23:30:00+00:00",
                         tz=self._tz.utc) == "26 Nov 2026 at 23:30"

    def test_z_suffix_and_naive_are_utc(self):
        assert self._fmt("2026-11-27T13:15:00Z") == "today at 14:15"
        assert self._fmt("2026-11-27T13:15:00") == "today at 14:15"

    def test_single_digit_day_and_padding(self):
        assert self._fmt("2026-03-05T08:04:00+00:00") == "5 Mar 2026 at 09:04"

    def test_unparseable_is_shown_as_written(self):
        assert self._fmt("unknown time") == "unknown time"

    def test_default_is_local_zone(self):
        # No tz: the machine's local zone, which is what astimezone() gives.
        iso = "2026-11-27T13:15:00+00:00"
        local = self._dt.fromisoformat(iso).astimezone()
        got = project_lock.format_lock_time(iso, now=local)
        assert got == f"today at {local.hour:02d}:{local.minute:02d}"

    def test_file_keeps_utc_iso(self, tmp_path):
        project_lock.acquire(tmp_path)
        raw = json.loads((tmp_path / ".lock").read_text(encoding="utf-8"))["created_utc"]
        parsed = self._dt.fromisoformat(raw)
        assert parsed.utcoffset() == self._td(0)
        assert "today" not in raw and " at " not in raw

    def test_dialog_and_banner_show_local_time(self, make_win, ws, monkeypatch):
        path = _project(ws)
        _write_other_lock(path.parent, pid=os.getppid())   # 2026-01-01T00:00 UTC
        expected = project_lock.format_lock_time("2026-01-01T00:00:00+00:00")
        shown = {}

        def fake_exec(box):
            shown["text"] = box.text()
            for b in box.buttons():
                if b.text() == "Open read-only":
                    box_clicked = b
            monkeypatch.setattr(box, "clickedButton", lambda: box_clicked)
            return 0

        monkeypatch.setattr(project_io_mixin.QMessageBox, "exec", fake_exec)
        win = MainWindow(ws)
        try:
            win.open_project_at(str(path))
            assert f"since {expected}" in shown["text"]
            assert "2026-01-01T00:00:00" not in shown["text"]
            assert f"since {expected}" in win.read_only_banner.text()
            assert win._is_read_only()
        finally:
            win.close()
