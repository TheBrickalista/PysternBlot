# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Issue #203: every exported file records its SHA-256 in the operation log,
and integrity reports list each export, re-verified against the file on disk.

  - export_mixin: each export_generated entry carries
    new_value={"path", "format", "sha256", "size_bytes"}; no entry is logged
    when the output could not be written (PDF/SVG painter inactive).
  - integrity.collect_exports: ok / changed / missing / not_recorded /
    superseded, legacy string entries, source_asset_exported, malformed values.
  - build_integrity_report / write_integrity_html / write_integrity_json.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImageWriter
from PySide6.QtWidgets import QApplication

from pysternblot.integrity import (
    build_detailed_integrity_report,
    build_integrity_report,
    collect_exports,
    write_integrity_html,
    write_integrity_json,
)
from pysternblot.logchain import append_log_entry, verify_log_chain
from pysternblot.models import (
    AssetEntry,
    Blot,
    BlotChannel,
    Crop,
    CropTemplate,
    LegendZone,
    OperationLogEntry,
    Project,
    ProteinLabel,
)
from pysternblot.storage import Workspace

from test_source_export import (
    _encode_png_uint16,
    _make_main_window,
    _minimal_ladder,
    _minimal_project,
    _patched_dialogs,
    _write_asset,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_NO_EXPORTS = ROOT / "tests" / "fixtures" / "chained_log_project_1.2.2.json"

HAS_TIFF = b"tiff" in [bytes(f) for f in QImageWriter.supportedImageFormats()]


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _exports_logged(project: Project) -> list[OperationLogEntry]:
    return [e for e in project.operation_log if e.operation == "export_generated"]


def _png_asset(ws_dir: Path, value: int) -> str:
    arr = np.full((64, 64), value, dtype=np.uint16)
    return _write_asset(ws_dir, _encode_png_uint16(arr), ".png")


def _ecl_window(tmp_path):
    ws_dir = tmp_path / "ws"
    sha = _png_asset(ws_dir, 32768)
    blot = Blot(
        id="blot_01", asset_sha256=sha, crop=Crop(x=0, y=0, w=64.0, h=64.0),
        ladder=_minimal_ladder(), protein_label=ProteinLabel(text="Actin"),
    )
    project = _minimal_project([blot], assets={
        sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.png")),
    })
    project.panel.crop_template = CropTemplate(w=64.0, h=64.0)
    win = _make_main_window(tmp_path, project)
    win.active_blot_id = blot.id
    return win, project, blot


def _nir_window(tmp_path):
    ws_dir = tmp_path / "ws"
    sha_685 = _png_asset(ws_dir, 20000)
    sha_785 = _png_asset(ws_dir, 40000)
    blot = Blot(
        id="nir_blot", asset_sha256=sha_685, crop=Crop(x=0, y=0, w=64.0, h=64.0),
        ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        modality="nir_fluorescence",
        channels=[
            BlotChannel(asset_sha256=sha_685, channel_index=0, wavelength_nm=685),
            BlotChannel(asset_sha256=sha_785, channel_index=1, wavelength_nm=785),
        ],
    )
    project = _minimal_project([blot], assets={
        s: AssetEntry(sha256=s, stored_original_path=str(ws_dir / "assets" / s / "original.png"))
        for s in (sha_685, sha_785)
    })
    project.panel.crop_template = CropTemplate(w=64.0, h=64.0)
    win = _make_main_window(tmp_path, project)
    win.active_blot_id = blot.id
    return win, project, blot, sha_685, sha_785


# ===========================================================================
# 1. Final PNG / PDF / SVG exports record the hash
# ===========================================================================

@pytest.mark.parametrize("method, ext, fmt, field", [
    ("export_final_png", ".png", "png", "final_png"),
    ("export_final_pdf", ".pdf", "pdf", "final_pdf"),
    ("export_final_svg", ".svg", "svg", "final_svg"),
])
def test_final_export_records_hash(qapp, tmp_path, method, ext, fmt, field):
    win, project, _blot = _ecl_window(tmp_path)
    dest = tmp_path / f"figure{ext}"

    p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
    with p1, p2, p3 as info_mock, p4 as critical_mock:
        getattr(win, method)()
    assert not critical_mock.called, f"export raised: {critical_mock.call_args}"
    assert dest.exists()

    entries = _exports_logged(project)
    assert len(entries) == 1
    value = entries[0].new_value
    assert value == {
        "path": str(dest), "format": fmt, "sha256": _sha(dest), "size_bytes": dest.stat().st_size,
    }
    assert entries[0].field == field
    assert entries[0].target_type == "export"
    assert verify_log_chain(project).status == "ok"
    assert value["sha256"][:12] in info_mock.call_args.args[-1]


# ===========================================================================
# 2. Annotated TIFF (single and NIR per channel) and legend-zone PNG
# ===========================================================================

@pytest.mark.skipif(not HAS_TIFF, reason="Qt TIFF plugin not available")
def test_annotated_tiff_single_records_hash(qapp, tmp_path):
    win, project, blot = _ecl_window(tmp_path)
    dest = tmp_path / "annotated.tif"
    p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
    with p1, p2, p3, p4 as critical_mock:
        win.export_current_original_tiff()
    assert not critical_mock.called, f"export raised: {critical_mock.call_args}"

    (entry,) = _exports_logged(project)
    assert entry.new_value["format"] == "tiff"
    assert entry.new_value["sha256"] == _sha(dest)
    assert entry.asset_sha256 == blot.asset_sha256
    assert verify_log_chain(project).status == "ok"


@pytest.mark.skipif(not HAS_TIFF, reason="Qt TIFF plugin not available")
def test_annotated_tiff_nir_one_entry_per_channel_each_hashing_its_file(qapp, tmp_path):
    win, project, _blot, sha_685, sha_785 = _nir_window(tmp_path)
    base = tmp_path / "nir.tif"
    p1, p2, p3, p4 = _patched_dialogs(save_path=str(base))
    with p1, p2, p3, p4 as critical_mock:
        win.export_current_original_tiff()
    assert not critical_mock.called, f"export raised: {critical_mock.call_args}"

    entries = _exports_logged(project)
    assert [e.asset_sha256 for e in entries] == [sha_685, sha_785]
    paths = [Path(e.new_value["path"]) for e in entries]
    assert [p.name for p in paths] == ["nir_ch0_685nm.tif", "nir_ch1_785nm.tif"]
    for entry, path in zip(entries, paths):
        assert entry.new_value["sha256"] == _sha(path)
    assert entries[0].new_value["sha256"] != entries[1].new_value["sha256"]
    assert verify_log_chain(project).status == "ok"


def test_legend_zone_png_on_nir_blot_records_active_channel_asset(qapp, tmp_path):
    win, project, blot, sha_685, sha_785 = _nir_window(tmp_path)
    blot.legend_zone = LegendZone(x=0, y=0, w=64, h=64, show_markers=False)
    win.legend_zone_cb.setChecked(True)
    win._active_nir_channel = 1          # the 785 nm channel is the one drawn
    dest = tmp_path / "zone.png"

    p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
    with p1, p2, p3, p4 as critical_mock:
        win.export_legend_zone_png()
    assert not critical_mock.called, f"export raised: {critical_mock.call_args}"

    (entry,) = _exports_logged(project)
    assert entry.field == "legend_zone_png"
    assert entry.asset_sha256 == sha_785 != blot.asset_sha256
    assert entry.new_value["sha256"] == _sha(dest)
    assert entry.new_value["format"] == "png"


# ===========================================================================
# 3. Unwritable PDF / SVG: error shown, nothing logged
# ===========================================================================

@pytest.mark.parametrize("method, name", [("export_final_pdf", "x.pdf"), ("export_final_svg", "x.svg")])
def test_unwritable_pdf_svg_logs_nothing(qapp, tmp_path, method, name):
    win, project, _blot = _ecl_window(tmp_path)
    dest = tmp_path / "nope" / name          # parent directory does not exist
    n_before = len(project.operation_log)

    p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
    with p1, p2, p3, p4 as critical_mock:
        getattr(win, method)()

    critical_mock.assert_called_once()
    assert "Could not write" in critical_mock.call_args.args[-1]
    assert _exports_logged(project) == []
    assert len(project.operation_log) == n_before
    assert not dest.exists()


# ===========================================================================
# 4. collect_exports (pure, no Qt)
# ===========================================================================

def _empty_project() -> Project:
    return _minimal_project([])


def _log(project: Project, operation: str, *, field: str, new_value, asset_sha256=None, target_id="t"):
    append_log_entry(project, OperationLogEntry(
        timestamp_utc="2026-11-04T10:00:00+00:00", operation=operation, target_type="export",
        target_id=target_id, asset_sha256=asset_sha256, field=field, old_value=None, new_value=new_value,
    ))


def _log_export(project: Project, path: Path, fmt: str = "png", field: str = "final_png"):
    _log(project, "export_generated", field=field, new_value={
        "path": str(path), "format": fmt, "sha256": _sha(path), "size_bytes": path.stat().st_size,
    })


class TestCollectExports:

    def test_ok_then_changed_after_editing_one_byte(self, tmp_path):
        f = tmp_path / "fig.png"
        f.write_bytes(b"\x89PNG exported bytes")
        project = _empty_project()
        _log_export(project, f)

        (rec,) = collect_exports(project)
        assert rec["status"] == "ok"
        assert rec["current_sha256"] == rec["recorded_sha256"] == _sha(f)
        assert rec["format"] == "png" and rec["log_index"] == 0

        data = bytearray(f.read_bytes())
        data[3] ^= 0xFF
        f.write_bytes(bytes(data))
        (rec,) = collect_exports(project)
        assert rec["status"] == "changed"
        assert rec["current_sha256"] == _sha(f) != rec["recorded_sha256"]

    def test_deleted_file_is_missing(self, tmp_path):
        f = tmp_path / "fig.pdf"
        f.write_bytes(b"%PDF-1.4 ...")
        project = _empty_project()
        _log_export(project, f, fmt="pdf", field="final_pdf")
        f.unlink()
        (rec,) = collect_exports(project)
        assert rec["status"] == "missing" and rec["current_sha256"] is None

    def test_legacy_string_entry_is_not_recorded(self, tmp_path):
        project = _empty_project()
        _log(project, "export_generated", field="final_png", new_value="/some/path.png")
        (rec,) = collect_exports(project)
        assert rec["status"] == "not_recorded"
        assert rec["format"] == "png"
        assert rec["path"] == "/some/path.png"
        assert rec["recorded_sha256"] is None
        assert verify_log_chain(project).status == "ok"

    def test_legacy_entry_reports_current_hash_when_file_exists(self, tmp_path):
        f = tmp_path / "old.svg"
        f.write_text("<svg/>")
        project = _empty_project()
        _log(project, "export_generated", field="final_svg", new_value=str(f))
        (rec,) = collect_exports(project)
        assert rec["status"] == "not_recorded"
        assert rec["format"] == "svg"
        assert rec["current_sha256"] == _sha(f)

    def test_same_path_twice_first_superseded_second_ok(self, tmp_path):
        f = tmp_path / "fig.png"
        project = _empty_project()
        f.write_bytes(b"first")
        _log_export(project, f)
        f.write_bytes(b"second")
        # same file, reached through a different spelling of the path
        _log(project, "export_generated", field="final_png", new_value={
            "path": str(tmp_path / "." / "fig.png"), "format": "png", "sha256": _sha(f), "size_bytes": 6,
        })
        first, second = collect_exports(project)
        assert first["status"] == "superseded"
        assert first["current_sha256"] is None
        assert second["status"] == "ok"

    def test_source_asset_exported_uses_asset_hash(self, tmp_path):
        f = tmp_path / "source.tif"
        f.write_bytes(os.urandom(256))
        project = _empty_project()
        _log(project, "source_asset_exported", field="source_asset", new_value=str(f), asset_sha256=_sha(f))
        (rec,) = collect_exports(project)
        assert rec["operation"] == "source_asset_exported"
        assert rec["format"] == "source"
        assert rec["recorded_sha256"] == rec["asset_sha256"] == _sha(f)
        assert rec["status"] == "ok"

    def test_malformed_values_are_skipped(self, tmp_path):
        project = _empty_project()
        for bad in ({"foo": 1}, 42, None, "", {"path": 7}, ["a"]):
            _log(project, "export_generated", field="final_png", new_value=bad)
        _log(project, "something_else", field="final_png", new_value="/x.png")
        assert collect_exports(project) == []

    def test_each_distinct_path_hashed_once(self, tmp_path, monkeypatch):
        import pysternblot.integrity as integrity
        f = tmp_path / "fig.png"
        f.write_bytes(b"data")
        project = _empty_project()
        _log_export(project, f)
        _log(project, "source_asset_exported", field="source_asset", new_value=str(f), asset_sha256=_sha(f))
        calls = []
        real = integrity.sha256_file
        monkeypatch.setattr(integrity, "sha256_file", lambda p: calls.append(p) or real(p))
        collect_exports(project)
        assert len(calls) == 1


# ===========================================================================
# 5. Reports: exports, summary, schema v3, HTML table, strict JSON
# ===========================================================================

def _reject_constant(token):
    raise ValueError(f"non-RFC-8259 token: {token}")


class TestReports:

    def _project_with_exports(self, tmp_path):
        ok = tmp_path / "fig<1>&co.png"          # user-chosen path with HTML metacharacters
        ok.write_bytes(b"png bytes")
        gone = tmp_path / "gone.pdf"
        gone.write_bytes(b"pdf bytes")
        project = _empty_project()
        _log_export(project, ok)
        _log_export(project, gone, fmt="pdf", field="final_pdf")
        gone.unlink()
        _log(project, "export_generated", field="final_svg", new_value="/legacy/figure.svg")
        return project, ok

    def test_report_lists_exports_with_summary_and_schema_v3(self, tmp_path):
        project, ok = self._project_with_exports(tmp_path)
        ws = Workspace(tmp_path / "ws")
        listed = tmp_path / "extra.txt"
        listed.write_text("x")

        report = build_integrity_report(project, ws, exported_files=[listed])
        assert report["schema"] == "pysternblot.integrity_report.v3"
        assert [r["status"] for r in report["exports"]] == ["ok", "missing", "not_recorded", "listed"]
        listed_row = report["exports"][-1]
        assert listed_row["operation"] is None and listed_row["current_sha256"] == _sha(listed)
        summary = report["exports_summary"]
        assert summary["ok"] == summary["missing"] == summary["not_recorded"] == summary["listed"] == 1
        assert summary["changed"] == summary["superseded"] == summary["unreadable"] == 0
        assert summary["total"] == 4

        detailed = build_detailed_integrity_report(project, ws)
        assert detailed["schema"] == "pysternblot.detailed_integrity_report.v3"
        assert len(detailed["exports"]) == 3

    def test_html_table_and_strict_json(self, tmp_path):
        project, ok = self._project_with_exports(tmp_path)
        report = build_integrity_report(project, Workspace(tmp_path / "ws"))

        html_text = write_integrity_html(report, tmp_path / "r.html").read_text(encoding="utf-8")
        assert "<h2>Exported files</h2>" in html_text
        assert _sha(ok) in html_text                       # full recorded hash
        assert "fig&lt;1&gt;&amp;co.png" in html_text       # escaped path
        assert "fig<1>&co.png" not in html_text
        assert "Matches the file on disk." in html_text
        assert "Not found at the recorded path" in html_text
        assert "Hash not recorded (exported by an earlier version)." in html_text
        assert html_text.index("Blot provenance") < html_text.index("Exported files")

        json_path = write_integrity_json(report, tmp_path / "r.json")
        loaded = json.loads(json_path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        assert loaded["exports"] == report["exports"]
        assert loaded["exports_summary"] == report["exports_summary"]


# ===========================================================================
# 6. Old project with no export entries
# ===========================================================================

def test_old_project_without_exports(tmp_path):
    project = Project.model_validate_json(FIXTURE_NO_EXPORTS.read_text(encoding="utf-8"))
    report = build_integrity_report(project, Workspace(tmp_path / "ws"))
    assert report["exports"] == []
    assert report["exports_summary"]["total"] == 0
    html_text = write_integrity_html(report, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<h2>Exported files</h2>" in html_text
    assert "No exports recorded in this project's operation log." in html_text
    assert verify_log_chain(project).status == "ok"
