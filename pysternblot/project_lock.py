# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Advisory per-project edit lock: projects/<id>/.lock.

A PysternBlot window that opens a project for editing creates the lock
atomically (O_CREAT | O_EXCL) and removes it when it closes the project or
quits. Another window, or another installation such as the copy bundled in
Pyblication, then sees that the project is being edited and offers to open
it read-only.

The lock is advisory and only guards editing. Reading never needs it: the
library, the Pyblication plugin and .pbarchive export ignore it, and it is
not project content (it never enters an archive).

A lock is *stale* when it was written on this host by a process that is no
longer alive (a crash); it is then taken over without asking. Every lock
carries a random token, so a window whose lock was taken over ("Open
anyway") never removes the new holder's lock, and notices before its next
save that it no longer holds it (still_ours()).
"""

from __future__ import annotations

import datetime
import json
import os
import socket
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

LOCK_NAME = ".lock"

ACQUIRED = "acquired"
TOOK_OVER_STALE = "took_over_stale"
HELD_BY_OTHER = "held_by_other"

# Tokens of locks this process has written and not released (any window).
_live_tokens: set[str] = set()


@dataclass
class LockInfo:
    host: str
    pid: int
    app: str
    app_version: str
    created_utc: str
    executable: str = ""
    token: str = ""

    @classmethod
    def from_file(cls, path: Path) -> Optional["LockInfo"]:
        """The lock at path, or None if it is missing, unreadable or corrupt."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                host=str(data["host"]),
                pid=int(data["pid"]),
                app=str(data.get("app", "")),
                app_version=str(data.get("app_version", "")),
                created_utc=str(data.get("created_utc", "")),
                executable=str(data.get("executable", "")),
                token=str(data.get("token", "")),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def describe(self) -> str:
        """For the lock dialog and read-only banner; the time in local time."""
        app = f"{self.app} {self.app_version}".strip() or "PysternBlot"
        return (f"{app} on {self.host} (process {self.pid}), "
                f"since {format_lock_time(self.created_utc)}")


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_lock_time(
    created_utc: str,
    *,
    now: Optional[datetime.datetime] = None,
    tz: Optional[datetime.tzinfo] = None,
) -> str:
    """A lock's UTC ISO time, shown in local time: "today at 14:15", else
    "27 Nov 2026 at 14:15". The .lock file itself keeps UTC ISO. A time
    without an offset is taken as UTC; one that cannot be parsed is shown
    as written. now and tz (default: the local zone) are for tests."""
    try:
        when = datetime.datetime.fromisoformat(str(created_utc).replace("Z", "+00:00"))
    except ValueError:
        return str(created_utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    when = when.astimezone(tz)          # tz None: the local zone
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    now = now.astimezone(when.tzinfo)
    clock = f"{when.hour:02d}:{when.minute:02d}"
    if when.date() == now.date():
        return f"today at {clock}"
    return f"{when.day} {_MONTHS[when.month - 1]} {when.year} at {clock}"


@dataclass
class LockResult:
    status: str                         # ACQUIRED | TOOK_OVER_STALE | HELD_BY_OTHER
    token: Optional[str] = None         # ours, when acquired
    holder: Optional[LockInfo] = None   # the other holder (None: unreadable lock)

    @property
    def acquired(self) -> bool:
        return self.status in (ACQUIRED, TOOK_OVER_STALE)


def lock_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / LOCK_NAME


def _app_version() -> str:
    try:
        from pysternblot import __version__
        return str(__version__)
    except ImportError:
        return "unknown"


def _new_info() -> LockInfo:
    info = LockInfo(
        host=socket.gethostname(),
        pid=os.getpid(),
        app="PysternBlot",
        app_version=_app_version(),
        created_utc=datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat(),
        executable=sys.executable or "",
        token=uuid.uuid4().hex,
    )
    _live_tokens.add(info.token)
    return info


def _payload(info: LockInfo) -> bytes:
    return (json.dumps(asdict(info), indent=2) + "\n").encode("utf-8")


def pid_alive(pid: int) -> bool:
    """True if a process with this pid exists on this host. Errs on the
    side of "alive" when it cannot tell (the user is asked, never overridden)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) would *terminate* the process on Windows.
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by another user
    except OSError:
        return True
    return True


def is_stale(info: LockInfo, own_tokens: frozenset[str] = frozenset()) -> bool:
    """A lock written on this host by a process that is gone. A lock with
    our own pid that this process never wrote is also stale: the process
    that wrote it has exited and its pid was reused by us. One this process
    wrote (another window here) is live."""
    if info.host != socket.gethostname():
        return False
    if info.pid == os.getpid():
        return info.token not in own_tokens and info.token not in _live_tokens
    return not pid_alive(info.pid)


def _replace_with(path: Path, info: LockInfo) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".lock.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(_payload(info))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def acquire(project_dir: str | Path, own_tokens: frozenset[str] = frozenset()) -> LockResult:
    """Take the edit lock of project_dir, or report who holds it."""
    path = lock_path(project_dir)
    info = _new_info()
    holder = None
    for _attempt in range(2):           # a second try if released meanwhile
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = LockInfo.from_file(path)
            if holder is None and not path.exists():
                continue
            break
        with os.fdopen(fd, "wb") as f:
            f.write(_payload(info))
        return LockResult(ACQUIRED, token=info.token)

    if holder is None:                  # unreadable or corrupt: ask, never take
        return LockResult(HELD_BY_OTHER, holder=None)
    if holder.token and holder.token in own_tokens:
        return LockResult(ACQUIRED, token=holder.token)
    if not is_stale(holder, own_tokens):
        return LockResult(HELD_BY_OTHER, holder=holder)

    _replace_with(path, info)
    # Two windows may take over the same stale lock at once: the last write
    # wins, and the other sees a token that is not its own.
    after = LockInfo.from_file(path)
    if after is not None and after.token == info.token:
        return LockResult(TOOK_OVER_STALE, token=info.token, holder=holder)
    return LockResult(HELD_BY_OTHER, holder=after)


def force(project_dir: str | Path) -> str:
    """"Open anyway": replace whatever lock is there with ours; our token."""
    info = _new_info()
    _replace_with(lock_path(project_dir), info)
    return info.token


def still_ours(project_dir: str | Path, token: str) -> bool:
    holder = LockInfo.from_file(lock_path(project_dir))
    return holder is not None and holder.token == token


def release(project_dir: str | Path, token: Optional[str]) -> bool:
    """Remove the lock if it still carries our token. True if removed."""
    if not token:
        return False
    path = lock_path(project_dir)
    if not still_ours(project_dir, token):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    finally:
        _live_tokens.discard(token)
    return True
