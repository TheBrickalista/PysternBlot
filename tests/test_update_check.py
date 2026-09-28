# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

import json
import ssl
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
# fetch_latest_release: success and every failure category
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, amt=None):
        return self._body if amt is None else self._body[:amt]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _ExplodingResponse(_FakeResponse):
    def __init__(self, exc):
        self._exc = exc

    def read(self, amt=None):
        raise self._exc


def _urlopen(**kw):
    return patch.object(update_check.urllib.request, "urlopen", **kw)


def _fetch_error(**kw) -> update_check.UpdateCheckError:
    with _urlopen(**kw):
        with pytest.raises(update_check.UpdateCheckError) as info:
            update_check.fetch_latest_release()
    return info.value


def test_fetch_latest_release_success():
    body = json.dumps({"tag_name": "v9.9.9"}).encode()
    with _urlopen(return_value=_FakeResponse(body)):
        assert update_check.fetch_latest_release() == "v9.9.9"


def test_fetch_passes_explicit_certifi_context_to_urlopen():
    import certifi
    body = json.dumps({"tag_name": "v9.9.9"}).encode()
    with _urlopen(return_value=_FakeResponse(body)) as mock_open, \
         patch.object(update_check.ssl, "create_default_context",
                      wraps=update_check.ssl.create_default_context) as mock_ctx:
        update_check.fetch_latest_release()
    mock_ctx.assert_called_once_with(cafile=certifi.where())
    assert isinstance(mock_open.call_args.kwargs["context"], ssl.SSLContext)


def test_tls_failure_wrapped_in_urlerror_is_tls_certificate():
    # The real shape: urlopen wraps connection-time SSL errors in URLError.
    err = urllib.error.URLError(
        ssl.SSLCertVerificationError("certificate verify failed: unable to get local issuer certificate")
    )
    e = _fetch_error(side_effect=err)
    assert e.category == update_check.CATEGORY_TLS
    assert "certificate verify failed" in e.detail


def test_bare_ssl_error_during_read_is_tls_certificate():
    resp = _ExplodingResponse(ssl.SSLError("bad record mac"))
    e = _fetch_error(return_value=resp)
    assert e.category == update_check.CATEGORY_TLS


def test_missing_ca_bundle_is_tls_certificate():
    with patch.object(update_check, "build_ssl_context", side_effect=FileNotFoundError("cacert.pem")):
        with pytest.raises(update_check.UpdateCheckError) as info:
            update_check.fetch_latest_release()
    assert info.value.category == update_check.CATEGORY_TLS
    assert "CA bundle unavailable" in info.value.detail


@pytest.mark.parametrize("exc", [
    urllib.error.URLError("offline"),
    urllib.error.URLError(OSError(8, "nodename nor servname provided")),  # DNS
    TimeoutError("timed out"),
    ConnectionResetError("reset"),
])
def test_network_failures(exc):
    assert _fetch_error(side_effect=exc).category == update_check.CATEGORY_NETWORK


def _http_error(code):
    return urllib.error.HTTPError(update_check.GITHUB_RELEASES_LATEST_URL, code, "err", {}, None)


@pytest.mark.parametrize("code, rate_limited", [
    (403, True), (429, True), (404, False), (500, False), (503, False),
])
def test_http_errors_carry_status_and_rate_limit_flag(code, rate_limited):
    e = _fetch_error(side_effect=_http_error(code))
    assert e.category == update_check.CATEGORY_HTTP
    assert e.status_code == code
    assert e.rate_limited is rate_limited


def test_httperror_is_not_misclassified_as_network():
    # HTTPError subclasses URLError; it must be caught first.
    assert issubclass(urllib.error.HTTPError, urllib.error.URLError)
    assert _fetch_error(side_effect=_http_error(500)).category != update_check.CATEGORY_NETWORK


@pytest.mark.parametrize("body", [
    b"this is not json {{{",
    json.dumps({"not_tag_name": "v9.9.9"}).encode(),
    json.dumps(["a", "list"]).encode(),
    json.dumps({"tag_name": None}).encode(),
    json.dumps({"tag_name": "nightly"}).encode(),
    b"\xff\xfe not utf-8",
    # Explicit id: pytest can't make a short id from a ~1 MB bytes value on
    # its own, and embedding the raw content produced a >1,000,000-character
    # node ID that hung a GitHub Actions run (see CHANGELOG "Unreleased").
    pytest.param(b"x" * (update_check.MAX_RESPONSE_BYTES + 10), id="oversize"),
])
def test_bad_response(body):
    e = _fetch_error(return_value=_FakeResponse(body))
    assert e.category == update_check.CATEGORY_BAD_RESPONSE


def test_unexpected_exception_is_not_swallowed():
    with _urlopen(side_effect=RuntimeError("bug")):
        with pytest.raises(RuntimeError):
            update_check.fetch_latest_release()


# ---------------------------------------------------------------------------
# check_for_update: the three outcomes
# ---------------------------------------------------------------------------

def _no_fake(monkeypatch):
    monkeypatch.delenv(update_check.FAKE_VERSION_ENV, raising=False)


def test_check_for_update_disabled_returns_none_without_network_call():
    with patch.object(update_check, "fetch_latest_release", Mock()) as mock_fetch:
        result = update_check.check_for_update(enabled=False)
    assert result is None
    mock_fetch.assert_not_called()


def test_update_available(monkeypatch):
    _no_fake(monkeypatch)
    with patch.object(update_check, "get_installed_version_with_source", return_value=("1.1.0", "metadata")), \
         patch.object(update_check, "fetch_latest_release", return_value="v1.2.0"), \
         patch.object(update_check, "detect_install_type", return_value="pip"):
        result = update_check.check_for_update(enabled=True)

    assert result.outcome == update_check.OUTCOME_UPDATE_AVAILABLE
    assert result.update_info() == {
        "current": "1.1.0",
        "latest": "1.2.0",
        "install_type": "pip",
        "instruction": update_check.update_instruction("pip"),
        "url": update_check.RELEASES_PAGE_URL,
    }


def test_up_to_date(monkeypatch):
    _no_fake(monkeypatch)
    with patch.object(update_check, "get_installed_version_with_source", return_value=("1.2.0", "metadata")), \
         patch.object(update_check, "fetch_latest_release", return_value="v1.2.0"):
        result = update_check.check_for_update(enabled=True)
    assert result.outcome == update_check.OUTCOME_UP_TO_DATE
    assert not result.failed


def test_older_release_is_up_to_date_not_update(monkeypatch):
    _no_fake(monkeypatch)
    with patch.object(update_check, "get_installed_version_with_source", return_value=("2.0.0", "metadata")), \
         patch.object(update_check, "fetch_latest_release", return_value="v1.2.0"):
        assert update_check.check_for_update(True).outcome == update_check.OUTCOME_UP_TO_DATE


@pytest.mark.parametrize("exc, category", [
    (urllib.error.URLError(ssl.SSLCertVerificationError("verify failed")), update_check.CATEGORY_TLS),
    (urllib.error.URLError("offline"), update_check.CATEGORY_NETWORK),
    (_http_error(503), update_check.CATEGORY_HTTP),
])
def test_failure_is_check_failed_never_up_to_date(monkeypatch, exc, category):
    _no_fake(monkeypatch)
    with patch.object(update_check, "get_installed_version_with_source", return_value=("1.2.0", "metadata")), \
         _urlopen(side_effect=exc):
        result = update_check.check_for_update(True)
    assert result.outcome == update_check.OUTCOME_CHECK_FAILED
    assert result.category == category
    assert result.detail


def test_rate_limited_result(monkeypatch):
    _no_fake(monkeypatch)
    with patch.object(update_check, "get_installed_version_with_source", return_value=("1.2.0", "metadata")), \
         _urlopen(side_effect=_http_error(429)):
        result = update_check.check_for_update(True)
    assert result.failed and result.rate_limited and result.status_code == 429


def test_unknown_installed_version_is_a_failure_not_up_to_date(monkeypatch):
    _no_fake(monkeypatch)
    with patch.object(update_check, "get_installed_version_with_source", return_value=("", "none")), \
         patch.object(update_check, "fetch_latest_release", return_value="v1.2.0") as mock_fetch:
        result = update_check.check_for_update(True)
    assert result.failed and result.category == update_check.CATEGORY_BAD_RESPONSE
    mock_fetch.assert_not_called()


def test_check_for_update_enabled_frozen_install_type(monkeypatch):
    _no_fake(monkeypatch)
    with patch.object(update_check, "get_installed_version_with_source", return_value=("1.0.0", "metadata")), \
         patch.object(update_check, "fetch_latest_release", return_value="v2.0.0"), \
         patch.object(update_check, "detect_install_type", return_value="frozen"):
        result = update_check.check_for_update(enabled=True)

    assert result.install_type == "frozen"
    assert update_check.RELEASES_PAGE_URL in result.instruction


# ---------------------------------------------------------------------------
# Messages and the auto-check quiet rules
# ---------------------------------------------------------------------------

def _failed(category, **kw):
    return update_check.CheckResult(outcome=update_check.OUTCOME_CHECK_FAILED, category=category, **kw)


def test_failure_messages_never_claim_up_to_date():
    for r in [
        _failed(update_check.CATEGORY_TLS), _failed(update_check.CATEGORY_NETWORK),
        _failed(update_check.CATEGORY_HTTP, status_code=500),
        _failed(update_check.CATEGORY_HTTP, status_code=429, rate_limited=True),
        _failed(update_check.CATEGORY_BAD_RESPONSE), _failed(update_check.CATEGORY_UNEXPECTED),
    ]:
        msg = update_check.describe_failure(r)
        assert "latest release" not in msg.lower()
        assert "you are running" not in msg.lower()


def test_rate_limit_message_mentions_status():
    msg = update_check.describe_failure(_failed(update_check.CATEGORY_HTTP, status_code=429, rate_limited=True))
    assert "429" in msg and "limiting" in msg


@pytest.mark.parametrize("result, shown", [
    (_failed(update_check.CATEGORY_TLS), True),
    (_failed(update_check.CATEGORY_BAD_RESPONSE), True),
    (_failed(update_check.CATEGORY_HTTP, status_code=500), True),
    (_failed(update_check.CATEGORY_UNEXPECTED), True),
    (_failed(update_check.CATEGORY_NETWORK), False),
    (_failed(update_check.CATEGORY_HTTP, status_code=403, rate_limited=True), False),
    (_failed(update_check.CATEGORY_HTTP, status_code=429, rate_limited=True), False),
    (update_check.CheckResult(outcome=update_check.OUTCOME_UP_TO_DATE), False),
])
def test_should_show_auto_failure(result, shown):
    assert update_check.should_show_auto_failure(result) is shown


# ---------------------------------------------------------------------------
# PYSTERNBLOT_FAKE_VERSION affects the update check only
# ---------------------------------------------------------------------------

def test_fake_version_overrides_update_check_only(monkeypatch):
    monkeypatch.setenv(update_check.FAKE_VERSION_ENV, "1.0.0")

    assert update_check.get_update_check_version() == ("1.0.0", "fake")
    # Everything else still sees the real version.
    real, source = update_check.get_installed_version_with_source()
    assert real != "1.0.0" and source in ("metadata", "fallback")
    assert update_check.get_installed_version() == real

    import pysternblot
    assert pysternblot.__version__ != "1.0.0"

    with patch.object(update_check, "fetch_latest_release", return_value="v1.2.0"):
        result = update_check.check_for_update(True)
    assert result.outcome == update_check.OUTCOME_UPDATE_AVAILABLE
    assert result.current == "1.0.0" and result.version_source == "fake"


def test_fake_version_is_logged(monkeypatch, caplog):
    monkeypatch.setenv(update_check.FAKE_VERSION_ENV, "1.0.0")
    with caplog.at_level("WARNING", logger="pysternblot.update"):
        update_check.get_update_check_version()
    assert "PYSTERNBLOT_FAKE_VERSION=1.0.0" in caplog.text


def test_fake_version_not_used_by_about_or_project_metadata(monkeypatch):
    monkeypatch.setenv(update_check.FAKE_VERSION_ENV, "1.0.0")
    from pysternblot.storage import Workspace
    import tempfile, pathlib
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()) / "ws")
    ws.ensure()
    proj = ws.load_project(str(ws.create_new_project("p")))
    assert proj.project.app_version != "1.0.0"


# ---------------------------------------------------------------------------
# --selfcheck
# ---------------------------------------------------------------------------

from pysternblot import main as main_module
from pysternblot import selfcheck


def _run_main(argv, tmp_path):
    out = tmp_path / "out.txt"
    with patch("pysternblot.app.run", side_effect=AssertionError("window must not open")):
        with pytest.raises(SystemExit) as info:
            main_module.main(argv + ["--selfcheck-out", str(out)])
    return info.value.code, out.read_text(encoding="utf-8")


def test_selfcheck_ok_writes_file_and_exits_0(tmp_path, monkeypatch):
    _no_fake(monkeypatch)
    body = json.dumps({"tag_name": "v9.9.9"}).encode()
    with _urlopen(return_value=_FakeResponse(body)):
        code, text = _run_main(["--selfcheck"], tmp_path)
    assert code == 0
    assert "outcome: update_available" in text
    assert "installed_version_source:" in text
    assert "certifi_bundle_exists: True" in text
    assert "exit_code: 0" in text


def test_selfcheck_tls_failure_exits_1(tmp_path, monkeypatch):
    _no_fake(monkeypatch)
    err = urllib.error.URLError(ssl.SSLCertVerificationError("verify failed"))
    with _urlopen(side_effect=err):
        code, text = _run_main(["--selfcheck"], tmp_path)
    assert code == 1
    assert "category: tls_certificate" in text


def test_selfcheck_rate_limited_exits_2(tmp_path, monkeypatch):
    _no_fake(monkeypatch)
    with _urlopen(side_effect=_http_error(429)):
        code, text = _run_main(["--selfcheck"], tmp_path)
    assert code == 2
    assert "rate_limited: True" in text


def test_selfcheck_network_failure_exits_1(tmp_path, monkeypatch):
    _no_fake(monkeypatch)
    with _urlopen(side_effect=urllib.error.URLError("offline")):
        code, _ = _run_main(["--selfcheck"], tmp_path)
    assert code == 1


def test_selfcheck_missing_certifi_bundle_fails(tmp_path, monkeypatch):
    _no_fake(monkeypatch)
    body = json.dumps({"tag_name": "v9.9.9"}).encode()
    with _urlopen(return_value=_FakeResponse(body)), \
         patch("certifi.where", return_value=str(tmp_path / "missing.pem")):
        code, text = _run_main(["--selfcheck"], tmp_path)
    assert code == 1
    assert "certifi_bundle_exists: False" in text


def test_selfcheck_works_without_stdout(tmp_path, monkeypatch):
    _no_fake(monkeypatch)
    monkeypatch.setattr(sys, "stdout", None)
    body = json.dumps({"tag_name": "v9.9.9"}).encode()
    with _urlopen(return_value=_FakeResponse(body)):
        code, text = _run_main(["--selfcheck"], tmp_path)
    assert code == 0 and "exit_code: 0" in text


def test_parse_selfcheck_args():
    assert selfcheck.parse_selfcheck_args([]) == (False, None)
    assert selfcheck.parse_selfcheck_args(["--selfcheck"]) == (True, None)
    assert selfcheck.parse_selfcheck_args(["--selfcheck", "--selfcheck-out", "x.txt"]) == (True, "x.txt")
    assert selfcheck.parse_selfcheck_args(["--selfcheck", "--selfcheck-out=y.txt"]) == (True, "y.txt")
