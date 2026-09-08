# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for the Stage 2 .pbarchive hardening in pysternblot/storage.py:

- manifest binding (project_sha256s, format_version 2)
- path hardening against traversal / absolute / backslash member names
- two-pass validate-then-write import

No Qt and no display required — all tests use tmp_path for file I/O.

Run from repo root:
    pytest tests/test_archive_integrity.py -v
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from pysternblot.logchain import verify_log_chain
from pysternblot.models import AssetEntry, Blot, Project
from pysternblot.storage import Workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path, name: str = "ws") -> Workspace:
    return Workspace(root=tmp_path / name)


def _minimal_blot_dict(blot_id: str = "blot_01") -> dict:
    return {
        "id": blot_id,
        "asset_sha256": "abc123",
        "overlay_asset_sha256": None,
        "crop": {"x": 10, "y": 20, "w": 400, "h": 250, "mode": "absolute", "ladder_anchor": None},
        "ladder": {
            "lane_index": 0,
            "marker_set_id": "ms_default",
            "calibration_points": [
                {"y_px": 50, "kda": 55},
                {"y_px": 120, "kda": 36},
            ],
            "fit": None,
            "show_ticks": True,
        },
        "protein_label": {"text": "GAPDH", "align": "center", "font_size_pt": None},
        "display": {
            "invert": False,
            "gamma": 1.0,
            "auto_contrast": True,
            "overlay_alpha": 0.35,
            "overlay_visible": True,
            "rotation_deg": 0.0,
            "levels_black": 0,
            "levels_white": 65535,
            "levels_gamma": 1.0,
        },
        "overlay_ladder": None,
        "included_in_final": True,
    }


def _make_project_with_real_asset(ws: Workspace, tmp_path: Path) -> tuple[str, str]:
    """Import a real binary asset, create a project referencing it, return (project_id, sha)."""
    asset_file = tmp_path / f"fake_image_{id(tmp_path)}.tif"
    asset_file.write_bytes(b"\x00\x01" * 8)

    sha, dest = ws.import_asset(str(asset_file))

    proj_path = ws.create_new_project("Archive Test Project")
    project = ws.load_project(str(proj_path))

    project.assets[sha] = AssetEntry(
        sha256=sha,
        stored_original_path=str(dest),
        original_source_path=str(asset_file),
    )
    blot_dict = _minimal_blot_dict("blot_01")
    blot_dict["asset_sha256"] = sha
    project.panel.blots.append(Blot.model_validate(blot_dict))
    project.panel.layout.order.append("blot_01")
    ws.save_project(project)

    return project.project.id, sha


def _rewrite_zip_member(archive_path: Path, member_name: str, new_data: bytes) -> None:
    """Rewrite one member of a zip in place, leaving every other member untouched."""
    tmp = archive_path.with_suffix(".tmp")
    with zipfile.ZipFile(archive_path, "r") as zin, \
         zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == member_name:
                data = new_data
            zout.writestr(item, data)
    tmp.replace(archive_path)


def _snapshot(root: Path) -> set[Path]:
    return set(root.rglob("*")) if root.exists() else set()


# ===========================================================================
# 1. Clean round trip — verified, v2, no errors
# ===========================================================================

class TestCleanRoundTrip:

    def test_round_trip_is_verified_v2_with_no_errors(self, tmp_path):
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "clean.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        with zipfile.ZipFile(archive_path) as zf:
            manifest = json.loads(zf.read("pbarchive/manifest.json"))
        assert manifest["format_version"] == 2
        assert project_id in manifest["project_sha256s"]

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.archive_format_version == 2
        assert result.project_integrity_verified is True
        assert result.integrity_errors == []
        assert result.imported_project_ids == [project_id]
        assert result.imported_asset_count == 1


# ===========================================================================
# 2. Tamper: rewrite project.json content after export
# ===========================================================================

class TestProjectTamperDetection:

    def test_tampered_project_json_is_rejected(self, tmp_path):
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "tampered.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        with zipfile.ZipFile(archive_path) as zf:
            proj_bytes = zf.read(f"pbarchive/projects/{project_id}/project.json")
        proj_data = json.loads(proj_bytes)
        proj_data["project"]["name"] = "Tampered Name"
        _rewrite_zip_member(
            archive_path,
            f"pbarchive/projects/{project_id}/project.json",
            json.dumps(proj_data, indent=2).encode("utf-8"),
        )

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_project_ids == []
        assert result.project_integrity_verified is False
        assert any("mismatch" in e.lower() for e in result.integrity_errors)
        assert not (dst_ws.projects_dir / project_id).exists()

    def test_tampered_operation_log_entry_is_detected(self, tmp_path):
        """Stage 1 + Stage 2 together: an edited old_value inside the chained
        operation log must trip the manifest hash, even though the entry's
        own entry_hash/prev_hash fields are untouched by this particular edit."""
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        # Give the project a real logged operation to tamper with.
        project = src_ws.load_project(str(src_ws.projects_dir / project_id / "project.json"))
        src_ws.rename_project(project, "Renamed For Archive Test")

        archive_path = tmp_path / "logtamper.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        with zipfile.ZipFile(archive_path) as zf:
            proj_bytes = zf.read(f"pbarchive/projects/{project_id}/project.json")
        proj_data = json.loads(proj_bytes)

        rename_entries = [
            e for e in proj_data["operation_log"] if e["operation"] == "project_renamed"
        ]
        assert rename_entries, "fixture must contain a project_renamed log entry"
        rename_entries[0]["old_value"] = "Something else entirely"

        _rewrite_zip_member(
            archive_path,
            f"pbarchive/projects/{project_id}/project.json",
            json.dumps(proj_data, indent=2).encode("utf-8"),
        )

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_project_ids == []
        assert any("mismatch" in e.lower() for e in result.integrity_errors)
        assert not (dst_ws.projects_dir / project_id).exists()


# ===========================================================================
# 4. Hand-built v1 archive
# ===========================================================================

class TestV1ArchiveCompatibility:

    def test_v1_archive_imports_unverified_without_errors(self, tmp_path):
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)
        project = src_ws.load_project(str(src_ws.projects_dir / project_id / "project.json"))
        proj_bytes = project.model_dump_json(indent=2).encode("utf-8")

        asset_path = src_ws.asset_original_file(sha)
        asset_bytes = asset_path.read_bytes()

        manifest = {
            "format": "pbarchive",
            "format_version": 1,
            "created_utc": "2024-01-01T00:00:00Z",
            "app_version": "0.1.0",
            "project_ids": [project_id],
            "asset_sha256s": [sha],
        }

        archive_path = tmp_path / "v1.pbarchive"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("pbarchive/manifest.json", json.dumps(manifest, indent=2))
            zf.writestr(f"pbarchive/projects/{project_id}/project.json", proj_bytes)
            zf.writestr(f"pbarchive/assets/{sha}/{asset_path.name}", asset_bytes)

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.archive_format_version == 1
        assert result.project_integrity_verified is False
        assert result.integrity_errors == []
        assert result.imported_project_ids == [project_id]


# ===========================================================================
# 5 & 6. Path hardening against traversal, backslash, absolute paths
# ===========================================================================

class TestPathHardening:

    def _build_malicious_archive(self, tmp_path: Path, member_name: str, project_id: str) -> Path:
        """A minimal, otherwise-well-formed archive whose sole project member
        uses an unsafe *member_name*."""
        proj = Project.model_validate({
            "project": {
                "id": project_id,
                "name": "Evil",
                "created_utc": "2024-01-01T00:00:00Z",
                "app_version": "0.1.0",
            },
            "panel": {
                "lane_layout": {
                    "mode": "manual_n_lanes",
                    "n_lanes_manual": 1,
                    "header_block": {
                        "left_title": "",
                        "groups": [{"label": "", "n_lanes": 1}],
                        "condition_rows": [{"values": [""]}],
                    },
                },
                "blots": [],
                "layout": {"order": []},
            },
        })
        proj_bytes = proj.model_dump_json(indent=2).encode("utf-8")
        proj_sha = hashlib.sha256(proj_bytes).hexdigest()

        manifest = {
            "format": "pbarchive",
            "format_version": 2,
            "created_utc": "2024-01-01T00:00:00Z",
            "app_version": "0.1.0",
            "project_ids": [project_id],
            "asset_sha256s": [],
            "project_sha256s": {project_id: proj_sha},
        }

        archive_path = tmp_path / "evil.pbarchive"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("pbarchive/manifest.json", json.dumps(manifest, indent=2))
            zf.writestr(member_name, proj_bytes)

        return archive_path

    def test_dotdot_traversal_member_is_rejected(self, tmp_path):
        dst_ws = _make_workspace(tmp_path, "dest")
        dst_ws.ensure()
        before = _snapshot(dst_ws.root)

        archive_path = self._build_malicious_archive(
            tmp_path, "pbarchive/projects/../project.json", "../../../evil"
        )
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_project_ids == []
        assert result.integrity_errors  # some rejection message recorded

        after = _snapshot(dst_ws.root)
        assert after == before, "import must not write anything for a rejected member"

        # Explicitly confirm nothing landed one level above projects_dir.
        assert not (dst_ws.root / "project.json").exists()

    def test_backslash_member_name_is_rejected(self, tmp_path):
        dst_ws = _make_workspace(tmp_path, "dest")
        dst_ws.ensure()
        before = _snapshot(dst_ws.root)

        archive_path = self._build_malicious_archive(
            tmp_path, "pbarchive\\projects\\evil\\project.json", "evil"
        )
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_project_ids == []
        assert result.integrity_errors

        after = _snapshot(dst_ws.root)
        assert after == before

    def test_absolute_member_name_is_rejected(self, tmp_path):
        dst_ws = _make_workspace(tmp_path, "dest")
        dst_ws.ensure()
        before = _snapshot(dst_ws.root)

        archive_path = self._build_malicious_archive(
            tmp_path, "/etc/pbarchive/projects/evil/project.json", "evil"
        )
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_project_ids == []
        assert result.integrity_errors

        after = _snapshot(dst_ws.root)
        assert after == before


# ===========================================================================
# 7. Non-hex asset directory component
# ===========================================================================

class TestAssetComponentValidation:

    def test_non_hex_asset_directory_is_rejected_without_writing(self, tmp_path):
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "badasset.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        # Relabel the asset's directory to something that is charset-safe
        # but not a valid hex digest, so it can never hash-match its content.
        tmp = archive_path.with_suffix(".tmp")
        with zipfile.ZipFile(archive_path, "r") as zin, \
             zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                name = item.filename
                if name.startswith(f"pbarchive/assets/{sha}/"):
                    name = name.replace(f"pbarchive/assets/{sha}/", "pbarchive/assets/not-a-hex-digest/")
                zout.writestr(name, data)
        tmp.replace(archive_path)

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_asset_count == 0
        assert any("mismatch" in e.lower() or "sha256" in e.lower() for e in result.integrity_errors)
        assert not (dst_ws.assets_dir / "not-a-hex-digest").exists()
        assert not (dst_ws.assets_dir / sha).exists()


# ===========================================================================
# 8. Manifest/archive inventory cross-check
# ===========================================================================

class TestManifestInventoryCrossCheck:

    def test_asset_listed_but_absent_from_archive_is_flagged(self, tmp_path):
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "missing_asset.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        ghost_sha = "f" * 64
        with zipfile.ZipFile(archive_path) as zf:
            manifest = json.loads(zf.read("pbarchive/manifest.json"))
        manifest["asset_sha256s"].append(ghost_sha)
        _rewrite_zip_member(
            archive_path, "pbarchive/manifest.json", json.dumps(manifest, indent=2).encode("utf-8")
        )

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert any(
            "listed in the manifest but not found in the archive" in e
            for e in result.integrity_errors
        )
        # The real, correctly-referenced asset/project must still import fine.
        assert result.imported_project_ids == [project_id]
        assert result.imported_asset_count == 1


# ===========================================================================
# 9. Chain integrity survives the archive round trip
# ===========================================================================

class TestChainSurvivesRoundTrip:

    def test_imported_project_chain_is_ok_including_import_entry(self, tmp_path):
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "chain.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")
        assert result.imported_project_ids == [project_id]

        imported = dst_ws.load_project(str(dst_ws.projects_dir / project_id / "project.json"))

        chain = verify_log_chain(imported)
        assert chain.status == "ok"

        ops = [e.operation for e in imported.operation_log]
        assert "imported_from_archive" in ops
