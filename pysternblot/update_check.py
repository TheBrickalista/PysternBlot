# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from importlib.metadata import version, PackageNotFoundError

GITHUB_RELEASES_LATEST_URL = "https://api.github.com/repos/TheBrickalista/PysternBlot/releases/latest"
RELEASES_PAGE_URL = "https://github.com/TheBrickalista/PysternBlot/releases/latest"
_USER_AGENT = "PysternBlot-update-check"

# The GitHub releases API response is a small JSON document (well under 10 KB
# in practice); 1 MB is generous headroom while still capping a malicious or
# misbehaving endpoint from streaming an unbounded body into memory.
MAX_RESPONSE_BYTES = 1 * 1024 * 1024

# Overrides the installed version for the update check ONLY (see
# get_update_check_version). Never read anywhere else: About, provenance and
# project files must always report the real version.
FAKE_VERSION_ENV = "PYSTERNBLOT_FAKE_VERSION"

OUTCOME_UP_TO_DATE = "up_to_date"
OUTCOME_UPDATE_AVAILABLE = "update_available"
OUTCOME_CHECK_FAILED = "check_failed"

CATEGORY_TLS = "tls_certificate"
CATEGORY_NETWORK = "network"
CATEGORY_HTTP = "http"
CATEGORY_BAD_RESPONSE = "bad_response"
# A programming error inside the check itself -- not one of the four expected
# failure modes, but still never allowed to look like "up to date".
CATEGORY_UNEXPECTED = "unexpected"

_log = logging.getLogger("pysternblot.update")


class UpdateCheckError(Exception):
    """A classified update-check failure."""

    def __init__(self, category: str, detail: str,
                 status_code: int | None = None, rate_limited: bool = False):
        super().__init__(detail)
        self.category = category
        self.detail = detail
        self.status_code = status_code
        self.rate_limited = rate_limited


@dataclass
class CheckResult:
    outcome: str
    current: str = ""
    latest: str = ""
    version_source: str = ""
    install_type: str = ""
    instruction: str = ""
    url: str = RELEASES_PAGE_URL
    category: str | None = None
    status_code: int | None = None
    rate_limited: bool = False
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.outcome == OUTCOME_CHECK_FAILED

    def update_info(self) -> dict:
        """The dict shape the update banner renders."""
        return {
            "current": self.current,
            "latest": self.latest,
            "install_type": self.install_type,
            "instruction": self.instruction,
            "url": self.url,
        }


def get_installed_version_with_source() -> tuple[str, str]:
    """(version, source) where source is "metadata", "fallback" or "none"."""
    try:
        return version("pysternblot"), "metadata"
    except PackageNotFoundError:
        pass
    try:
        from pysternblot import __version__
        return __version__, "fallback"
    except ImportError:
        return "", "none"


def get_installed_version() -> str:
    return get_installed_version_with_source()[0]


def get_update_check_version() -> tuple[str, str]:
    """The version the UPDATE CHECK compares against. Honors
    PYSTERNBLOT_FAKE_VERSION (source "fake"); every other caller must use
    get_installed_version so the override cannot leak."""
    fake = os.environ.get(FAKE_VERSION_ENV, "").strip()
    if fake:
        _log.warning(
            "%s=%s is set: the update check is comparing against this fake "
            "version, not the installed one.", FAKE_VERSION_ENV, fake,
        )
        return fake, "fake"
    return get_installed_version_with_source()


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


def build_ssl_context() -> ssl.SSLContext:
    """Verify against certifi's CA bundle explicitly: a frozen bundle cannot
    rely on the OS trust store being visible to its embedded OpenSSL."""
    import certifi
    return ssl.create_default_context(cafile=certifi.where())


def _classify(exc: BaseException) -> UpdateCheckError:
    # Order matters. HTTPError is a URLError subclass, so it goes first.
    # ssl.SSLCertVerificationError is also a ValueError and an OSError, so
    # TLS is tested before bad_response and network.
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        return UpdateCheckError(
            CATEGORY_HTTP, f"HTTP {code}: {exc.reason}",
            status_code=code, rate_limited=code in (403, 429),
        )
    if isinstance(exc, urllib.error.URLError):
        # Connection-time TLS failures arrive as URLError(reason=SSLError).
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return UpdateCheckError(CATEGORY_TLS, f"{type(reason).__name__}: {reason}")
        return UpdateCheckError(CATEGORY_NETWORK, f"{type(exc).__name__}: {reason}")
    if isinstance(exc, ssl.SSLError):
        # Bare SSLError, e.g. raised while reading the body.
        return UpdateCheckError(CATEGORY_TLS, f"{type(exc).__name__}: {exc}")
    if isinstance(exc, OSError):  # TimeoutError, ConnectionError, ...
        return UpdateCheckError(CATEGORY_NETWORK, f"{type(exc).__name__}: {exc}")
    if isinstance(exc, (ValueError, KeyError, TypeError)):  # JSON/schema/decoding
        return UpdateCheckError(CATEGORY_BAD_RESPONSE, f"{type(exc).__name__}: {exc}")
    raise exc


def fetch_latest_release(timeout: float = 3.0) -> str:
    """Return the latest release tag, or raise UpdateCheckError."""
    try:
        context = build_ssl_context()
    except (OSError, ssl.SSLError, ImportError) as exc:
        raise UpdateCheckError(
            CATEGORY_TLS, f"CA bundle unavailable: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_LATEST_URL,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise UpdateCheckError(CATEGORY_BAD_RESPONSE, "Response exceeded the size limit.")
        data = json.loads(body)
        tag = data["tag_name"]
    except UpdateCheckError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _classify(exc) from exc

    if not isinstance(tag, str) or not re.search(r"\d", tag):
        raise UpdateCheckError(CATEGORY_BAD_RESPONSE, f"Unusable tag_name: {tag!r}")
    return tag


def describe_failure(result: CheckResult) -> str:
    """Plain-language message for a failed check (exception text is separate,
    in result.detail)."""
    cat = result.category
    if cat == CATEGORY_TLS:
        return ("Pystern Blot could not verify GitHub's security certificate, so "
                "the update check did not complete. This does NOT mean you are "
                "up to date.")
    if cat == CATEGORY_NETWORK:
        return ("Pystern Blot could not reach GitHub. Check your internet "
                "connection and try again. This does NOT mean you are up to date.")
    if cat == CATEGORY_HTTP:
        if result.rate_limited:
            return (f"GitHub is limiting update checks from this network "
                    f"(HTTP {result.status_code}). Try again later. This does "
                    f"NOT mean you are up to date.")
        return (f"GitHub returned an error (HTTP {result.status_code}), so the "
                f"update check did not complete.")
    if cat == CATEGORY_BAD_RESPONSE:
        return ("GitHub's reply could not be understood, so the update check "
                "did not complete.")
    return "The update check failed unexpectedly."


def should_show_auto_failure(result: CheckResult) -> bool:
    """Startup checks stay quiet for transient network trouble and rate
    limiting (logged only), but surface problems that will not fix themselves."""
    if not result.failed:
        return False
    if result.category == CATEGORY_NETWORK:
        return False
    if result.category == CATEGORY_HTTP and result.rate_limited:
        return False
    return True


def _failure(error: UpdateCheckError, current: str, source: str) -> CheckResult:
    return CheckResult(
        outcome=OUTCOME_CHECK_FAILED, current=current, version_source=source,
        category=error.category, status_code=error.status_code,
        rate_limited=error.rate_limited, detail=error.detail,
    )


def check_for_update(enabled: bool, timeout: float = 3.0) -> CheckResult | None:
    """None only when the check is disabled; otherwise always a CheckResult
    with one of three outcomes. A failure is never reported as up to date."""
    if not enabled:
        return None

    current, source = get_update_check_version()
    if not current:
        return _failure(
            UpdateCheckError(CATEGORY_BAD_RESPONSE,
                             "Could not determine the installed version."),
            current, source,
        )

    try:
        latest = fetch_latest_release(timeout)
    except UpdateCheckError as exc:
        _log.warning("Update check failed (%s): %s", exc.category, exc.detail)
        return _failure(exc, current, source)

    install_type = detect_install_type()
    if is_update_available(current, latest):
        return CheckResult(
            outcome=OUTCOME_UPDATE_AVAILABLE, current=current,
            latest=_normalize_tag(latest), version_source=source,
            install_type=install_type,
            instruction=update_instruction(install_type),
        )
    return CheckResult(
        outcome=OUTCOME_UP_TO_DATE, current=current,
        latest=_normalize_tag(latest), version_source=source,
        install_type=install_type,
    )
