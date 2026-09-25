# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""`--selfcheck`: a windowless diagnostic of the packaged app's update-check
plumbing (version lookup, CA bundle, one real HTTPS request to GitHub).

Exit codes:
    0  up_to_date / update_available
    2  rate limited (HTTP 403/429) -- the TLS handshake had already succeeded
    1  any other failure
"""

from __future__ import annotations

import os
import sys
import traceback

from . import update_check

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_RATE_LIMITED = 2


def parse_selfcheck_args(argv: list[str]) -> tuple[bool, str | None]:
    """Return (selfcheck_requested, result_file_path)."""
    if "--selfcheck" not in argv:
        return False, None
    out = None
    for i, arg in enumerate(argv):
        if arg == "--selfcheck-out" and i + 1 < len(argv):
            out = argv[i + 1]
        elif arg.startswith("--selfcheck-out="):
            out = arg.split("=", 1)[1]
    return True, out


def _collect(timeout: float) -> tuple[list[str], int]:
    lines: list[str] = []
    failed = False

    def add(key: str, value) -> None:
        lines.append(f"{key}: {value}")

    add("frozen", bool(getattr(sys, "frozen", False)))
    add("python", sys.version.split()[0])

    installed, source = update_check.get_installed_version_with_source()
    add("installed_version", installed or "(unknown)")
    add("installed_version_source", source)
    try:
        from . import __version__
        if source == "metadata" and installed != __version__:
            add("version_warning", f"metadata says {installed} but __version__ is {__version__}")
    except ImportError:
        pass
    if not installed:
        failed = True

    try:
        import certifi
        bundle = certifi.where()
        exists = os.path.isfile(bundle)
        add("certifi_bundle", bundle)
        add("certifi_bundle_exists", exists)
        if not exists:
            failed = True
    except Exception as exc:  # diagnostic tool: report anything, then fail
        add("certifi_bundle", f"unavailable ({type(exc).__name__}: {exc})")
        add("certifi_bundle_exists", False)
        failed = True

    check_version, check_source = update_check.get_update_check_version()
    add("update_check_version", f"{check_version} ({check_source})")

    result = update_check.check_for_update(True, timeout)
    add("outcome", result.outcome)
    if result.failed:
        add("category", result.category)
        add("status_code", result.status_code)
        add("rate_limited", result.rate_limited)
        add("detail", result.detail)
        add("message", update_check.describe_failure(result))
    else:
        add("latest_release", result.latest)

    if result.failed:
        code = EXIT_RATE_LIMITED if (result.rate_limited and not failed) else EXIT_FAILED
    else:
        code = EXIT_FAILED if failed else EXIT_OK
    return lines, code


def run_selfcheck(out_path: str | None = None, timeout: float = 10.0) -> int:
    try:
        lines, code = _collect(timeout)
    except Exception:  # never let the diagnostic itself crash silently
        lines, code = ["outcome: selfcheck_crashed", traceback.format_exc()], EXIT_FAILED
    lines.append(f"exit_code: {code}")
    text = "\n".join(lines) + "\n"

    # A windowed (no-console) build has sys.stdout None; the file is the
    # channel that always works.
    if sys.stdout is not None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    return code
