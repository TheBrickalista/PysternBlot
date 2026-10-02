# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Strict RFC 8259 JSON output: no NaN / Infinity tokens in any file Pystern
Blot writes with json.dumps, and the operation-log chain is unaffected.

  - Existing chains still verify: a fixture project whose log was written by
    the unmodified v1.2.2 code (tests/fixtures/chained_log_project_1.2.2.json)
    verifies, and still verifies after a save/reload with the current code.
  - Each strict writer (integrity JSON, create_new_project, the three
    suggestion lists) sanitizes a NaN that reaches it instead of writing it.
  - Sources: a non-finite log value becomes None before it is hashed (so the
    chain survives a save/reload), and a non-finite kDa is rejected in the
    ladder-preset table.
  - A real written integrity report parses with a strict JSON parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from pysternblot.integrity import build_detailed_integrity_report, write_integrity_json
from pysternblot.jsonsafe import dumps_strict, finite_or_none
from pysternblot.logchain import append_log_entry, verify_log_chain
from pysternblot.models import MarkerSet, OperationLogEntry, Project
from pysternblot.storage import Workspace
from pysternblot.ui.marker_set_mixin import _MarkerSetMixin
from pysternblot.ui.project_io_mixin import _ProjectIOMixin

ROOT = Path(__file__).resolve().parents[1]
CHAINED_FIXTURE = ROOT / "tests" / "fixtures" / "chained_log_project_1.2.2.json"
TUTORIAL_ARCHIVE = ROOT / "examples" / "tutorial_example.pbarchive"


def _reject_constant(token):
    raise ValueError(f"non-RFC-8259 token in JSON output: {token}")


def strict_loads(text: str):
    """json.loads that fails on NaN / Infinity / -Infinity."""
    return json.loads(text, parse_constant=_reject_constant)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class _LogHost(_ProjectIOMixin):
    def __init__(self, project):
        self.current_project = project


# ===========================================================================
# Existing chains still verify (logchain.py is unchanged)
# ===========================================================================

class TestExistingChainsStillVerify:

    def test_fixture_written_by_1_2_2_verifies(self):
        project = Project.model_validate_json(CHAINED_FIXTURE.read_text(encoding="utf-8"))
        result = verify_log_chain(project)
        assert result.status == "ok", result.message
        assert result.n_chained == len(project.operation_log) == 7

    def test_fixture_still_verifies_after_save_and_reload(self, tmp_path):
        project = Project.model_validate_json(CHAINED_FIXTURE.read_text(encoding="utf-8"))
        ws = Workspace(tmp_path)
        ws.ensure()
        saved = ws.save_project(project)
        reloaded = ws.load_project(str(saved))
        assert verify_log_chain(reloaded).status == "ok"

    def test_new_log_path_leaves_fixture_values_untouched(self):
        """The sanitizing source returns ordinary values unchanged, so entries
        logged after this change hash exactly as they did before it."""
        project = Project.model_validate_json(CHAINED_FIXTURE.read_text(encoding="utf-8"))
        host = _LogHost(project)
        for entry in project.operation_log:
            for value in (entry.old_value, entry.new_value):
                assert host._plain_log_value(value) == value
                assert json.dumps(host._plain_log_value(value), sort_keys=True, ensure_ascii=False) == \
                    json.dumps(value, sort_keys=True, ensure_ascii=False)

    def test_tutorial_archive_chain_status_unchanged(self):
        with zipfile.ZipFile(TUTORIAL_ARCHIVE) as zf:
            names = [n for n in zf.namelist() if n.endswith("project.json")]
            assert names
            for name in names:
                project = Project.model_validate_json(zf.read(name))
                assert verify_log_chain(project).status == "not_chained"


# ===========================================================================
# Sources
# ===========================================================================

class TestLogValueSource:

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), np.float64("nan")])
    def test_non_finite_scalar_becomes_none(self, bad):
        assert _LogHost(None)._plain_log_value(bad) is None

    def test_non_finite_nested_and_model_values_become_none(self):
        host = _LogHost(None)
        assert host._plain_log_value({"a": [1.0, float("nan")], "b": "x"}) == {"a": [1.0, None], "b": "x"}

        entry = OperationLogEntry(timestamp_utc="t", operation="x", old_value=float("inf"))
        dumped = host._plain_log_value(entry)
        assert dumped["old_value"] is None and dumped["operation"] == "x"

    def test_nan_logged_value_keeps_chain_intact_after_save_and_reload(self, tmp_path):
        """Before the fix a NaN was hashed as the token NaN but saved as null,
        so the reloaded entry no longer matched its hash."""
        ws = Workspace(tmp_path)
        project = ws.load_project(str(ws.create_new_project("p")))
        host = _LogHost(project)
        host.log_operation("display_changed", field="levels_gamma", old_value=1.0, new_value=float("nan"))
        host.log_operation("display_changed", field="overlay_alpha", old_value=float("inf"), new_value=0.5)
        assert verify_log_chain(project).status == "ok"

        reloaded = ws.load_project(str(ws.save_project(project)))
        assert verify_log_chain(reloaded).status == "ok"
        assert reloaded.operation_log[0].new_value is None
        assert reloaded.operation_log[1].old_value is None


class _PresetHost(_MarkerSetMixin):
    def __init__(self, kda_text: str):
        self.marker_set_table = QTableWidget(1, 6)
        self.marker_set_table.setItem(0, 0, QTableWidgetItem(kda_text))
        self.marker_set_table.setItem(0, 1, QTableWidgetItem("band"))


class TestPresetKdaSource:

    @pytest.mark.parametrize("text", ["inf", "Infinity", "nan", "-inf"])
    def test_non_finite_kda_is_rejected(self, qapp, text):
        host = _PresetHost(text)
        with pytest.raises(ValueError):
            host._marker_set_from_table(MarkerSet(id="m", name="n", bands=[]))

    def test_finite_kda_is_accepted(self, qapp):
        ms = _PresetHost("250")._marker_set_from_table(MarkerSet(id="m", name="n", bands=[]))
        assert [b.kda for b in ms.bands] == [250.0]


# ===========================================================================
# Each strict writer sanitizes a NaN that reaches it
# ===========================================================================

class TestWritersSanitize:

    def test_dumps_strict_helper(self):
        text = dumps_strict({"a": float("nan"), "b": [float("inf"), 1.5], "c": (float("-inf"),)})
        assert strict_loads(text) == {"a": None, "b": [None, 1.5], "c": [None]}
        same = {"x": [1.0, {"y": 2.0}]}
        assert finite_or_none(same) is same

    def test_integrity_json_writer(self, tmp_path):
        report = {"levels": {"gamma": float("nan")}, "points": [{"kda": float("inf")}]}
        path = write_integrity_json(report, tmp_path / "report.json")
        text = path.read_text(encoding="utf-8")
        assert "NaN" not in text and "Infinity" not in text
        assert strict_loads(text) == {"levels": {"gamma": None}, "points": [{"kda": None}]}

    def test_create_new_project_writer(self, tmp_path):
        ws = Workspace(tmp_path)
        path = ws.create_new_project("p", app_version=float("nan"))
        data = strict_loads(path.read_text(encoding="utf-8"))
        assert data["project"]["app_version"] is None

    @pytest.mark.parametrize("save, filename", [
        ("save_legend_suggestions", "legend_suggestions.json"),
        ("save_protein_label_suggestions", "protein_label_suggestions.json"),
        ("save_antibody_name_suggestions", "antibody_name_suggestions.json"),
    ])
    def test_suggestion_writers(self, tmp_path, save, filename):
        ws = Workspace(tmp_path)
        getattr(ws, save)([float("nan"), "β-actin", float("inf")])
        text = (ws.presets_dir / filename).read_text(encoding="utf-8")
        assert strict_loads(text) == {"items": ["nan", "β-actin", "inf"]}  # stringified, never a token


# ===========================================================================
# A real integrity report parses strictly
# ===========================================================================

def _png_uint16(h: int, w: int) -> bytes:
    import struct
    import zlib
    arr = np.full((h, w), 30000, dtype=np.uint16)

    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row.astype(">u2").tobytes() for row in arr)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class TestWrittenIntegrityReportIsStrict:

    def test_report_from_project_with_non_finite_values(self, qapp, tmp_path):
        """A project.json carrying NaN/Infinity tokens (hand-edited or from
        another tool) loads non-finite floats into the model; the written
        report must still be strict JSON."""
        ws = Workspace(tmp_path)
        ws.ensure()
        png = _png_uint16(40, 60)
        sha = hashlib.sha256(png).hexdigest()
        (ws.assets_dir / sha).mkdir(parents=True)
        (ws.assets_dir / sha / "original.png").write_bytes(png)

        project = ws.load_project(str(ws.create_new_project("p")))
        data = json.loads(project.model_dump_json())
        data["panel"]["blots"] = [{
            "id": "b1", "asset_sha256": sha,
            "crop": {"x": 0, "y": 0, "w": 60, "h": 40},
            "ladder": {"lane_index": 0, "marker_set_id": "ms1",
                       "calibration_points": [{"y_px": 5, "kda": "__NAN__"}, {"y_px": 30, "kda": 36}]},
            "protein_label": {"text": "x"},
        }]
        data["panel"]["layout"]["order"] = ["b1"]
        text = json.dumps(data).replace('"__NAN__"', "NaN")
        project = Project.model_validate_json(text)
        append_log_entry(project, OperationLogEntry(timestamp_utc="t", operation="x", new_value=float("inf")))

        report = build_detailed_integrity_report(project, ws)
        out = write_integrity_json(report, tmp_path / "integrity.json").read_text(encoding="utf-8")

        parsed = strict_loads(out)
        blot = parsed["blots"][0]
        assert blot["ladder"]["calibration_points"][0]["kda"] is None
        assert parsed["operation_log"][-1]["new_value"] is None
