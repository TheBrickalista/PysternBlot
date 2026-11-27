"""project.json format version (migrations.py) and unknown-field round trip.

- a project written before versioning (no format_version) opens, and is
  stamped with the current version on its next save;
- a project from a newer PysternBlot is refused with a clear message, is
  never saved over, and is skipped by archive import;
- fields this version does not know survive load -> save, and do not break
  the operation-log chain or .pbarchive hashing;
- saves are atomic (temp file + os.replace).
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from pysternblot.logchain import append_log_entry, verify_log_chain
from pysternblot.migrations import (
    ProjectFormatTooNewError,
    migrate_project_dict,
    read_format_version,
)
from pysternblot.models import PROJECT_FORMAT_VERSION, OperationLogEntry
from pysternblot.plugin import _read_projects
from pysternblot.storage import Workspace

FIXTURE = Path(__file__).parent / "fixtures" / "chained_log_project_1.2.2.json"


@pytest.fixture
def ws(tmp_path):
    w = Workspace(root=tmp_path / "ws")
    w.ensure()
    return w


def _install(ws: Workspace, data: dict) -> Path:
    path = ws.projects_dir / data["project"]["id"] / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _new_project_data(ws: Workspace) -> tuple[Path, dict]:
    path = ws.create_new_project("Format test")
    return path, json.loads(path.read_text(encoding="utf-8"))


# ===========================================================================
# Versions
# ===========================================================================

class TestFormatVersion:

    def test_current_version_is_1(self):
        assert PROJECT_FORMAT_VERSION == 1

    def test_missing_version_means_0(self):
        assert read_format_version({"project": {}}) == 0
        assert read_format_version({}) == 0

    def test_new_project_is_stamped(self, ws):
        _path, data = _new_project_data(ws)
        assert data["project"]["format_version"] == PROJECT_FORMAT_VERSION

    def test_migration_stamps_without_changing_anything_else(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        migrated, old = migrate_project_dict(data)
        assert old == 0
        assert migrated["project"].pop("format_version") == 1
        assert migrated == data
        assert "format_version" not in data["project"]   # input untouched

    def test_old_project_without_version_opens(self, ws):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert "format_version" not in data["project"]
        path = _install(ws, data)
        project = ws.load_project(str(path))
        assert project.project.format_version == PROJECT_FORMAT_VERSION
        assert verify_log_chain(project).status == "ok"
        # No log entry for the 0 -> 1 stamp.
        assert len(project.operation_log) == len(data["operation_log"])

    def test_old_project_is_stamped_on_save(self, ws):
        path = _install(ws, json.loads(FIXTURE.read_text(encoding="utf-8")))
        ws.save_project(ws.load_project(str(path)))
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["project"]["format_version"] == PROJECT_FORMAT_VERSION
        assert verify_log_chain(ws.load_project(str(path))).status == "ok"


class TestNewerVersionRefused:

    def _newer(self, ws, path: Path | None = None) -> Path:
        if path is None:
            path, data = _new_project_data(ws)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
        data["project"]["format_version"] = PROJECT_FORMAT_VERSION + 1
        data["panel"]["some_future_field"] = {"x": 1}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def test_load_refuses_with_clear_message(self, ws):
        path = self._newer(ws)
        with pytest.raises(ProjectFormatTooNewError) as exc:
            ws.load_project(str(path))
        msg = str(exc.value)
        assert "saved by a newer PysternBlot" in msg
        assert "update" in msg.lower()
        assert exc.value.version == PROJECT_FORMAT_VERSION + 1

    def test_refused_file_is_untouched(self, ws):
        path = self._newer(ws)
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        with pytest.raises(ProjectFormatTooNewError):
            ws.load_project(str(path))
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime

    def test_unreadable_version_is_refused(self, ws):
        path, data = _new_project_data(ws)
        data["project"]["format_version"] = "two"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ProjectFormatTooNewError):
            ws.load_project(str(path))

    def test_save_never_overwrites_a_newer_file(self, ws):
        # Opened at v1, then a newer app upgraded the file meanwhile.
        path, _ = _new_project_data(ws)
        project = ws.load_project(str(path))
        self._newer(ws, path)
        before = path.read_bytes()
        with pytest.raises(ProjectFormatTooNewError):
            ws.save_project(project)
        assert path.read_bytes() == before
        assert not list(path.parent.glob(".project.*"))

    def test_set_archived_refuses_newer(self, ws):
        path = self._newer(ws)
        before = path.read_bytes()
        with pytest.raises(ProjectFormatTooNewError):
            ws.set_project_archived(str(path), True)
        assert path.read_bytes() == before

    def test_archive_import_skips_newer_project(self, ws, tmp_path):
        path, _ = _new_project_data(ws)
        pid = path.parent.name
        archive = tmp_path / "a.pbarchive"
        ws.export_archive([pid], archive, app_version="test")

        # Rewrite the archive with the project at a newer format (and a
        # matching manifest hash, so only the version can reject it).
        with zipfile.ZipFile(archive) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        name = f"pbarchive/projects/{pid}/project.json"
        data = json.loads(members[name])
        data["project"]["format_version"] = PROJECT_FORMAT_VERSION + 1
        members[name] = json.dumps(data, indent=2).encode("utf-8")
        manifest = json.loads(members["pbarchive/manifest.json"])
        import hashlib
        manifest["project_sha256s"][pid] = hashlib.sha256(members[name]).hexdigest()
        members["pbarchive/manifest.json"] = json.dumps(manifest).encode("utf-8")
        with zipfile.ZipFile(archive, "w") as zf:
            for n, b in members.items():
                zf.writestr(n, b)

        other = Workspace(root=tmp_path / "other")
        result = other.import_archive(archive, app_version="test")
        assert pid not in result.imported_project_ids
        assert any("newer PysternBlot" in e for e in result.integrity_errors)
        assert not (other.projects_dir / pid).exists()


# ===========================================================================
# Unknown fields
# ===========================================================================

class TestUnknownFieldsSurvive:

    def _with_unknowns(self, ws) -> Path:
        path = ws.create_new_project("Unknowns")
        project = ws.load_project(str(path))
        append_log_entry(project, OperationLogEntry(timestamp_utc="2026-01-01T00:00:00+00:00",
                                                    operation="project_created"))
        ws.save_project(project)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["future_top_level"] = [1, 2, 3]
        data["project"]["future_meta"] = "m"
        data["panel"]["future_panel"] = {"nested": True}
        data["panel"]["style"]["future_style"] = 7
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def test_round_trip(self, ws):
        path = self._with_unknowns(ws)
        ws.save_project(ws.load_project(str(path)))
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["future_top_level"] == [1, 2, 3]
        assert saved["project"]["future_meta"] == "m"
        assert saved["panel"]["future_panel"] == {"nested": True}
        assert saved["panel"]["style"]["future_style"] == 7

    def test_unknown_fields_in_blot_survive(self, ws):
        from pysternblot.models import Blot, Crop, ProteinLabel
        from test_source_export import _minimal_ladder, _minimal_project

        project = _minimal_project([Blot(
            id="b1", asset_sha256="a" * 64, crop=Crop(x=0, y=0, w=10, h=10),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text="P"),
        )])
        data = json.loads(project.model_dump_json())
        data["panel"]["blots"][0]["future_blot_field"] = "kept"
        data["panel"]["blots"][0]["crop"]["future_crop_field"] = 1.5
        path = _install(ws, data)
        ws.save_project(ws.load_project(str(path)))
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["panel"]["blots"][0]["future_blot_field"] == "kept"
        assert saved["panel"]["blots"][0]["crop"]["future_crop_field"] == 1.5

    def test_log_entry_with_unknown_field_still_verifies(self, ws):
        # A newer app adds a field to OperationLogEntry and hashes it.
        path = ws.create_new_project("Log extras")
        project = ws.load_project(str(path))
        entry = OperationLogEntry(timestamp_utc="2026-01-01T00:00:00+00:00",
                                  operation="future_op", future_entry_field={"a": 1})
        append_log_entry(project, entry)
        append_log_entry(project, OperationLogEntry(
            timestamp_utc="2026-01-01T00:00:01+00:00", operation="after"))
        ws.save_project(project)

        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["operation_log"][0]["future_entry_field"] == {"a": 1}
        reloaded = ws.load_project(str(path))
        assert verify_log_chain(reloaded).status == "ok"
        ws.save_project(reloaded)
        assert verify_log_chain(ws.load_project(str(path))).status == "ok"

    def test_archive_round_trip_keeps_unknowns_and_hashes_match(self, ws, tmp_path):
        path = self._with_unknowns(ws)
        pid = path.parent.name
        archive = tmp_path / "u.pbarchive"
        ws.export_archive([pid], archive, app_version="test")
        other = Workspace(root=tmp_path / "other")
        result = other.import_archive(archive, app_version="test")
        assert result.imported_project_ids == [pid]
        assert result.integrity_errors == []
        assert result.project_integrity_verified
        imported = json.loads((other.projects_dir / pid / "project.json").read_text())
        assert imported["future_top_level"] == [1, 2, 3]
        assert imported["panel"]["style"]["future_style"] == 7
        assert verify_log_chain(other.load_project(
            str(other.projects_dir / pid / "project.json"))).status == "ok"


# ===========================================================================
# Atomic save
# ===========================================================================

class TestAtomicSave:

    def test_failure_during_write_leaves_previous_file(self, ws, monkeypatch):
        path = ws.create_new_project("Atomic")
        project = ws.load_project(str(path))
        ws.save_project(project)
        before = path.read_bytes()

        project.project.name = "Changed"

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(os, "fsync", boom)
        with pytest.raises(OSError, match="disk full"):
            ws.save_project(project)
        assert path.read_bytes() == before
        assert sorted(p.name for p in path.parent.iterdir()) == ["project.json"]

    def test_failure_at_replace_leaves_previous_file(self, ws, monkeypatch):
        path = ws.create_new_project("Atomic")
        project = ws.load_project(str(path))
        before = path.read_bytes()
        project.project.name = "Changed"
        monkeypatch.setattr(os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
        with pytest.raises(OSError):
            ws.save_project(project)
        assert path.read_bytes() == before
        assert sorted(p.name for p in path.parent.iterdir()) == ["project.json"]

    def test_save_keeps_file_mode(self, ws):
        path = ws.create_new_project("Mode")
        os.chmod(path, 0o640)
        ws.save_project(ws.load_project(str(path)))
        assert path.stat().st_mode & 0o777 == 0o640

    def test_temp_files_are_never_listed_as_projects(self, ws):
        path = ws.create_new_project("Globs")
        # A temp file left by a crash mid-save, and an edit lock.
        (path.parent / ".project.abc123.json.tmp").write_text("{", encoding="utf-8")
        (path.parent / ".lock").write_text("{}", encoding="utf-8")
        assert [p for p, _ in _read_projects(ws.root)] == [path]
        assert sorted(ws.projects_dir.glob("*/project.json")) == [path]
