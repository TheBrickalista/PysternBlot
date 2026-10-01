import re
from pathlib import Path

import pytest

import pysternblot

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 has no stdlib tomllib
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def _grep(path: Path, pattern: str) -> str:
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.M)
    assert m, f"version string not found in {path}"
    return m.group(1)


pytestmark = pytest.mark.skipif(
    not (ROOT / "pyproject.toml").exists(),
    reason="source checkout only (metadata files are not shipped in the wheel)",
)


def test_all_version_strings_match():
    pkg = pysternblot.__version__
    assert pkg == _grep(ROOT / "pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    assert pkg == _grep(ROOT / "docs" / "conf.py", r'^release\s*=\s*"([^"]+)"')
    assert pkg == _grep(ROOT / "CITATION.cff", r'^version:\s*(\S+)')


def test_uv_lock_matches_package_version():
    """uv.lock records the project's own version; a bump without `uv lock` makes
    `uv sync --locked` fail in CI."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    entries = [p for p in lock["package"] if p["name"] == "pysternblot"]
    assert len(entries) == 1, "expected exactly one pysternblot entry in uv.lock"
    assert entries[0]["version"] == pysternblot.__version__


def test_changelog_documents_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{pysternblot.__version__}]" in text
