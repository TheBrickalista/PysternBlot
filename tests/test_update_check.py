# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

import json
import sys
import urllib.error
from unittest.mock import Mock, patch

import pytest

from pysternblot import update_check


# ---------------------------------------------------------------------------
# get_installed_version
# ---------------------------------------------------------------------------

def test_get_installed_version_returns_nonempty_str():
    v = update_check.get_installed_version()
    assert isinstance(v, str)
    assert v != ""


# ---------------------------------------------------------------------------
# detect_install_type
# ---------------------------------------------------------------------------

def test_detect_install_type_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert update_check.detect_install_type() == "frozen"


def test_detect_install_type_pip_when_absent(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert update_check.detect_install_type() == "pip"


# ---------------------------------------------------------------------------
# update_instruction
# ---------------------------------------------------------------------------

def test_update_instruction_frozen_mentions_releases_url():
    msg = update_check.update_instruction("frozen")
    assert update_check.RELEASES_PAGE_URL in msg


def test_update_instruction_pip_mentions_pip_install():
    msg = update_check.update_instruction("pip")
    assert "pip install -U pysternblot" in msg


def test_update_instruction_unknown_defaults_to_pip():
    msg = update_check.update_instruction("something-else")
    assert "pip install -U pysternblot" in msg


# ---------------------------------------------------------------------------
# _normalize_tag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("v1.2.3", "1.2.3"),
    ("V1.2.3", "1.2.3"),
    (" 1.0 ", "1.0"),
    ("", ""),
])
def test_normalize_tag(raw, expected):
    assert update_check._normalize_tag(raw) == expected


def test_normalize_tag_none_ish_handled():
    assert update_check._normalize_tag(None) == ""


# ---------------------------------------------------------------------------
# is_update_available
# ---------------------------------------------------------------------------

def test_is_update_available_newer_latest_is_true():
    assert update_check.is_update_available("1.1.0", "1.2.0") is True


def test_is_update_available_equal_is_false():
    assert update_check.is_update_available("1.1.0", "1.1.0") is False


def test_is_update_available_older_latest_is_false():
    assert update_check.is_update_available("1.2.0", "1.1.0") is False


def test_is_update_available_v_prefix_on_latest():
    assert update_check.is_update_available("1.1.0", "v1.2.0") is True


def test_is_update_available_v_prefix_on_current():
    assert update_check.is_update_available("v1.1.0", "1.1.0") is False


def test_is_update_available_v_prefix_on_both_equal():
    assert update_check.is_update_available("v1.1.0", "V1.1.0") is False


def test_is_update_available_garbage_input_returns_false_never_raises():
    assert update_check.is_update_available("not-a-version", "also-garbage") is False


def test_is_update_available_empty_strings_returns_false():
    assert update_check.is_update_available("", "") is False
    assert update_check.is_update_available("1.0.0", "") is False
    assert update_check.is_update_available("", "1.0.0") is False


# ---------------------------------------------------------------------------
# fetch_latest_release
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_fetch_latest_release_success():
    body = json.dumps({"tag_name": "v9.9.9"}).encode()
    with patch.object(update_check.urllib.request, "urlopen", return_value=_FakeResponse(body)):
        result = update_check.fetch_latest_release()
    assert result == "v9.9.9"


def test_fetch_latest_release_urlopen_raises_url_error_returns_none():
    with patch.object(
        update_check.urllib.request, "urlopen",
        side_effect=urllib.error.URLError("offline"),
    ):
        assert update_check.fetch_latest_release() is None


def test_fetch_latest_release_missing_tag_name_returns_none():
    body = json.dumps({"not_tag_name": "v9.9.9"}).encode()
    with patch.object(update_check.urllib.request, "urlopen", return_value=_FakeResponse(body)):
        assert update_check.fetch_latest_release() is None


def test_fetch_latest_release_invalid_json_returns_none():
    body = b"this is not json {{{"
    with patch.object(update_check.urllib.request, "urlopen", return_value=_FakeResponse(body)):
        assert update_check.fetch_latest_release() is None


# ---------------------------------------------------------------------------
# check_for_update
# ---------------------------------------------------------------------------

def test_check_for_update_disabled_returns_none_without_network_call():
    with patch.object(update_check, "fetch_latest_release", Mock()) as mock_fetch:
        result = update_check.check_for_update(enabled=False)
    assert result is None
    mock_fetch.assert_not_called()


def test_check_for_update_enabled_with_newer_version_returns_dict():
    with patch.object(update_check, "get_installed_version", return_value="1.1.0"), \
         patch.object(update_check, "fetch_latest_release", return_value="v1.2.0"), \
         patch.object(update_check, "detect_install_type", return_value="pip"):
        result = update_check.check_for_update(enabled=True)

    assert result == {
        "current": "1.1.0",
        "latest": "1.2.0",
        "install_type": "pip",
        "instruction": update_check.update_instruction("pip"),
        "url": update_check.RELEASES_PAGE_URL,
    }


def test_check_for_update_enabled_with_equal_version_returns_none():
    with patch.object(update_check, "get_installed_version", return_value="1.1.0"), \
         patch.object(update_check, "fetch_latest_release", return_value="v1.1.0"):
        result = update_check.check_for_update(enabled=True)
    assert result is None


def test_check_for_update_enabled_with_no_release_available_returns_none():
    with patch.object(update_check, "get_installed_version", return_value="1.1.0"), \
         patch.object(update_check, "fetch_latest_release", return_value=None):
        result = update_check.check_for_update(enabled=True)
    assert result is None


def test_check_for_update_enabled_frozen_install_type():
    with patch.object(update_check, "get_installed_version", return_value="1.0.0"), \
         patch.object(update_check, "fetch_latest_release", return_value="v2.0.0"), \
         patch.object(update_check, "detect_install_type", return_value="frozen"):
        result = update_check.check_for_update(enabled=True)

    assert result["install_type"] == "frozen"
    assert update_check.RELEASES_PAGE_URL in result["instruction"]
