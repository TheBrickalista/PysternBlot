# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for scripts/make_version_file.py: the x.y.z version parser shared
with build-macos.yml's inline PlistBuddy step, and the Windows PyInstaller
version-file generator (issue #187 -- neither bundle carried the app
version in its OS metadata before this).

Run from repo root:
    pytest tests/test_make_version_file.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_version_file as mvf  # noqa: E402


def _write_pyproject(tmp_path: Path, version: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------

class TestParseVersion:

    def test_valid_x_y_z(self, tmp_path):
        p = _write_pyproject(tmp_path, "1.2.1")
        assert mvf.parse_version(p) == (1, 2, 1)

    def test_valid_multi_digit_components(self, tmp_path):
        p = _write_pyproject(tmp_path, "12.34.567")
        assert mvf.parse_version(p) == (12, 34, 567)

    def test_zero_version(self, tmp_path):
        p = _write_pyproject(tmp_path, "0.0.0")
        assert mvf.parse_version(p) == (0, 0, 0)

    def test_reads_this_repos_actual_pyproject(self):
        root = Path(__file__).resolve().parents[1]
        version = mvf.parse_version(root / "pyproject.toml")
        assert len(version) == 3
        assert all(isinstance(c, int) for c in version)

    @pytest.mark.parametrize("bad", [
        "1.3.0rc1",       # pre-release suffix
        "1.3.0+build.1",  # build metadata suffix
        "1.3",            # two-part
        "1.3.0.0",        # four-part
        "1.3.a",          # non-integer component
        "v1.3.0",         # leading v
        "1.3.0 ",         # trailing whitespace
        " 1.3.0",         # leading whitespace
        "",                # empty
        "latest",
    ])
    def test_rejects_non_conforming_versions(self, tmp_path, bad):
        p = _write_pyproject(tmp_path, bad)
        with pytest.raises(mvf.InvalidVersionError):
            mvf.parse_version(p)

    def test_missing_version_key_raises(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "x"\n', encoding="utf-8")
        with pytest.raises(mvf.InvalidVersionError):
            mvf.parse_version(p)

    def test_accepts_str_and_path(self, tmp_path):
        p = _write_pyproject(tmp_path, "2.0.0")
        assert mvf.parse_version(str(p)) == mvf.parse_version(p)


# ---------------------------------------------------------------------------
# render_version_file: 4-part padding and required fields
# ---------------------------------------------------------------------------

class TestRenderVersionFile:

    def test_pads_to_four_parts(self):
        text = mvf.render_version_file((1, 2, 3))
        assert "filevers=(1, 2, 3, 0)" in text
        assert "prodvers=(1, 2, 3, 0)" in text
        assert "u'1.2.3.0'" in text  # FileVersion / ProductVersion strings

    def test_contains_required_string_fields(self):
        text = mvf.render_version_file((1, 2, 1))
        assert "StringStruct(u'ProductName', u'PysternBlot')" in text
        assert "StringStruct(u'CompanyName', u'PysternBlot contributors')" in text
        assert "StringStruct(u'LegalCopyright', u'GPL-3.0-or-later')" in text
        assert "StringStruct(u'OriginalFilename', u'PysternBlot.exe')" in text
        assert "StringStruct(u'FileDescription'," in text
        # FileDescription is one line: no embedded newline in its value.
        desc_line = next(l for l in text.splitlines() if "FileDescription" in l)
        assert desc_line.count("\n") == 0

    def test_is_syntactically_valid_python(self):
        text = mvf.render_version_file((1, 2, 1))
        compile(text, "<version_file>", "exec")  # raises SyntaxError if malformed

    def test_zero_version_pads_correctly(self):
        text = mvf.render_version_file((0, 0, 0))
        assert "filevers=(0, 0, 0, 0)" in text
        assert "u'0.0.0.0'" in text


# ---------------------------------------------------------------------------
# main(): end-to-end CLI behaviour
# ---------------------------------------------------------------------------

class TestMain:

    def test_writes_file_and_returns_0(self, tmp_path):
        pyproject = _write_pyproject(tmp_path, "3.1.4")
        out = tmp_path / "out" / "version_file.txt"
        code = mvf.main([str(pyproject), str(out)])
        assert code == 0
        assert out.exists()
        assert "filevers=(3, 1, 4, 0)" in out.read_text()

    def test_creates_parent_directories(self, tmp_path):
        pyproject = _write_pyproject(tmp_path, "1.0.0")
        out = tmp_path / "a" / "b" / "c" / "version_file.txt"
        assert mvf.main([str(pyproject), str(out)]) == 0
        assert out.exists()

    def test_invalid_version_returns_nonzero_and_writes_nothing(self, tmp_path, capsys):
        pyproject = _write_pyproject(tmp_path, "1.3.0rc1")
        out = tmp_path / "version_file.txt"
        code = mvf.main([str(pyproject), str(out)])
        assert code != 0
        assert not out.exists()
        assert "::error::" in capsys.readouterr().err

    def test_defaults_to_pyproject_toml_and_build_version_file(self, tmp_path, monkeypatch):
        pyproject = _write_pyproject(tmp_path, "4.5.6")
        monkeypatch.chdir(tmp_path)
        assert mvf.main([]) == 0
        assert (tmp_path / "build" / "version_file.txt").exists()
