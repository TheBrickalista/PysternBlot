import re
from pathlib import Path

import pytest

import pysternblot

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


def test_changelog_documents_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{pysternblot.__version__}]" in text
