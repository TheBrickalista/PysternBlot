# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error
from importlib.metadata import version, PackageNotFoundError

GITHUB_RELEASES_LATEST_URL = "https://api.github.com/repos/TheBrickalista/PysternBlot/releases/latest"
RELEASES_PAGE_URL = "https://github.com/TheBrickalista/PysternBlot/releases/latest"
_USER_AGENT = "PysternBlot-update-check"


def get_installed_version() -> str:
    try:
        return version("pysternblot")
    except PackageNotFoundError:
        try:
            from pysternblot import __version__
            return __version__
        except Exception:
            return ""
    except Exception:
        return ""


def detect_install_type() -> str:
    try:
        return "frozen" if getattr(sys, "frozen", False) else "pip"
    except Exception:
        return "pip"


def update_instruction(install_type: str) -> str:
    if install_type == "frozen":
        return "Download the latest release from " + RELEASES_PAGE_URL
    return "Run: pip install -U pysternblot"


def _normalize_tag(tag: str) -> str:
    if not tag:
        return ""
    t = tag.strip()
    if t[:1] in ("v", "V"):
        t = t[1:]
    return t


def _parse_version(v: str) -> tuple:
    try:
        try:
            from packaging.version import Version
            return (0, Version(v))
        except ImportError:
            pass
        except Exception:
            pass

        nums = tuple(int(x) for x in re.findall(r"\d+", v)[:4])
        return (1, nums)
    except Exception:
        return (1, ())


def is_update_available(current: str, latest: str) -> bool:
    try:
        cur_norm = _normalize_tag(current)
        lat_norm = _normalize_tag(latest)
        if not cur_norm or not lat_norm:
            return False

        parsed_current = _parse_version(cur_norm)
        parsed_latest = _parse_version(lat_norm)

        return parsed_latest > parsed_current
    except Exception:
        return False


def fetch_latest_release(timeout: float = 3.0) -> str | None:
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_LATEST_URL,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        data = json.loads(body)
        return str(data["tag_name"])
    except Exception:
        return None


def check_for_update(enabled: bool, timeout: float = 3.0) -> dict | None:
    try:
        if not enabled:
            return None

        current = get_installed_version()
        latest = fetch_latest_release(timeout)
        if latest is None:
            return None

        if is_update_available(current, latest):
            install_type = detect_install_type()
            return {
                "current": current,
                "latest": _normalize_tag(latest),
                "install_type": install_type,
                "instruction": update_instruction(install_type),
                "url": RELEASES_PAGE_URL,
            }

        return None
    except Exception:
        return None
