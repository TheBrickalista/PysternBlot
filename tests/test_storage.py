# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for pysternblot/storage.py

No Qt and no display required — all tests use tmp_path for file I/O and
never call any Qt-dependent storage methods (ensure_blot_crop_preview,
generate_crop_preview_tiff).

Run from repo root:
    pytest tests/test_storage.py -v
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import zipfile

from pysternblot.storage import Workspace, sha256_file, ImportArchiveResult, parse_typhoon_tag270
from pysternblot.models import (
    Blot,
    BlotChannel,
    CalibrationPoint,
    ConditionRow,
    Crop,
    Group,
    HeaderBlock,
    Ladder,
    LaneLayout,
    Layout,
    Panel,
    ProjectMeta,
    ProteinLabel,
    Project,
)

TESTS_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path) -> Workspace:
    return Workspace(root=tmp_path / "ws")


def _minimal_blot_dict(blot_id: str = "blot_01") -> dict:
    """Minimal blot dict for embedding in raw JSON fixtures."""
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


def _minimal_panel_dict(blots: list[dict] | None = None) -> dict:
    return {
        "style": {
            "font_family": "Arial",
            "font_size_pt": 9,
            "top_header_height_px": 70,
            "ladder_col_width_px": 60,
            "protein_col_width_px": 90,
            "gap_between_blots_px": 10,
            "border_enabled": True,
            "border_width_px": 1,
        },
        "lane_layout": {
            "mode": "manual_n_lanes",
            "n_lanes_manual": 2,
            "header_block": {
                "left_title": "",
                "groups": [{"label": "", "n_lanes": 2, "underline": True}],
                "condition_rows": [{"values": ["", ""], "unit_right": ""}],
                "span_rows": [],
            },
        },
        "blots": blots or [],
        "layout": {"stack_mode": "vertical_stack", "order": []},
        "legend": {"mode": "protein", "upper_rows": [], "lower_rows": []},
        "crop_template": {"w": 300.0, "h": 200.0},
    }


def _minimal_project_dict(blots: list[dict] | None = None, panel_extra: dict | None = None) -> dict:
    panel = _minimal_panel_dict(blots)
    if panel_extra:
        panel.update(panel_extra)
    return {
        "project": {
            "id": "proj_test",
            "name": "Test Project",
            "created_utc": "2024-01-01T00:00:00Z",
            "modified_utc": "2024-01-01T00:00:00Z",
            "app_version": "0.1.0",
            "license": "GPL-3.0-only",
        },
        "assets": {},
        "marker_sets": [],
        "panel": panel,
        "operation_log": [],
    }


def _write_project_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===========================================================================
# sha256_file
# ===========================================================================

class TestSha256File:

    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello world")
        result = sha256_file(str(f))
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_matches_hashlib_directly(self, tmp_path):
        f = tmp_path / "data.bin"
        content = b"pysternblot test content"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(str(f)) == expected

    def test_consistent_for_same_file(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"consistent")
        assert sha256_file(str(f)) == sha256_file(str(f))

    def test_different_content_gives_different_hash(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"AAA")
        f2.write_bytes(b"BBB")
        assert sha256_file(str(f1)) != sha256_file(str(f2))

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert sha256_file(str(f)) == expected


# ===========================================================================
# save_project / load_project round-trip
# ===========================================================================

class TestSaveLoadRoundTrip:

    def test_saved_project_loads_identically(self, tmp_path):
        ws = _make_workspace(tmp_path)
        data = _minimal_project_dict()
        project = Project.model_validate(data)

        saved_path = ws.save_project(project)
        loaded = ws.load_project(str(saved_path))

        assert loaded == project

    def test_saved_file_is_valid_json(self, tmp_path):
        ws = _make_workspace(tmp_path)
        project = Project.model_validate(_minimal_project_dict())
        path = ws.save_project(project)
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert parsed["project"]["id"] == "proj_test"

    def test_project_with_blot_round_trips(self, tmp_path):
        ws = _make_workspace(tmp_path)
        data = _minimal_project_dict(blots=[_minimal_blot_dict()])
        project = Project.model_validate(data)

        path = ws.save_project(project)
        loaded = ws.load_project(str(path))

        assert len(loaded.panel.blots) == 1
        assert loaded.panel.blots[0].id == "blot_01"
        assert loaded == project

    def test_multiple_saves_overwrite_cleanly(self, tmp_path):
        ws = _make_workspace(tmp_path)
        project = Project.model_validate(_minimal_project_dict())
        path = ws.save_project(project)
        path2 = ws.save_project(project)
        assert path == path2
        loaded = ws.load_project(str(path))
        assert loaded == project


# ===========================================================================
# Legacy migration: crop_template
# ===========================================================================

class TestLegacyCropTemplateMigration:

    def _legacy_project_dict_no_crop_template(self) -> dict:
        """Simulates a project.json written before crop_template was added."""
        data = _minimal_project_dict(blots=[_minimal_blot_dict()])
        data["panel"].pop("crop_template")  # remove the modern field
        return data

    def test_loads_without_crashing(self, tmp_path):
        ws = _make_workspace(tmp_path)
        data = self._legacy_project_dict_no_crop_template()
        path = tmp_path / "legacy" / "project.json"
        _write_project_json(path, data)
        project = ws.load_project(str(path))  # must not raise
        assert project is not None

    def test_seeds_crop_template_from_first_blot(self, tmp_path):
        ws = _make_workspace(tmp_path)
        data = self._legacy_project_dict_no_crop_template()
        # The first blot has crop w=400, h=250 (from _minimal_blot_dict)
        path = tmp_path / "legacy" / "project.json"
        _write_project_json(path, data)
        project = ws.load_project(str(path))
        assert project.panel.crop_template.w == 400.0
        assert project.panel.crop_template.h == 250.0

    def test_modern_project_crop_template_not_overwritten(self, tmp_path):
        ws = _make_workspace(tmp_path)
        data = _minimal_project_dict(blots=[_minimal_blot_dict()])
        # Modern project has crop_template: w=300, h=200; blot has w=400, h=250
        path = tmp_path / "modern" / "project.json"
        _write_project_json(path, data)
        project = ws.load_project(str(path))
        # crop_template from JSON (300×200) must be used, not blot's crop (400×250)
        assert project.panel.crop_template.w == 300.0
        assert project.panel.crop_template.h == 200.0

    def test_legacy_project_with_no_blots_does_not_crash(self, tmp_path):
        ws = _make_workspace(tmp_path)
        data = _minimal_project_dict(blots=[])
        data["panel"].pop("crop_template")
        path = tmp_path / "legacy_empty" / "project.json"
        _write_project_json(path, data)
        project = ws.load_project(str(path))
        # No blots → migration skipped; Pydantic default (300×200) applies
        assert project.panel.crop_template.w == 300.0
        assert project.panel.crop_template.h == 200.0


# ===========================================================================
# Legacy migration: included_in_final
# ===========================================================================

class TestLegacyIncludedInFinalMigration:

    def _legacy_blot_dict_no_flag(self, blot_id: str = "blot_01") -> dict:
        d = _minimal_blot_dict(blot_id)
        d.pop("included_in_final")
        return d

    def test_blot_without_included_in_final_defaults_to_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        blot = self._legacy_blot_dict_no_flag()
        data = _minimal_project_dict(blots=[blot])
        path = tmp_path / "legacy" / "project.json"
        _write_project_json(path, data)
        project = ws.load_project(str(path))
        assert project.panel.blots[0].included_in_final is True

    def test_multiple_legacy_blots_all_default_to_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        blots = [
            self._legacy_blot_dict_no_flag("blot_01"),
            self._legacy_blot_dict_no_flag("blot_02"),
            self._legacy_blot_dict_no_flag("blot_03"),
        ]
        data = _minimal_project_dict(blots=blots)
        path = tmp_path / "legacy" / "project.json"
        _write_project_json(path, data)
        project = ws.load_project(str(path))
        for blot in project.panel.blots:
            assert blot.included_in_final is True

    def test_explicit_false_is_preserved(self, tmp_path):
        ws = _make_workspace(tmp_path)
        blot = _minimal_blot_dict()
        blot["included_in_final"] = False
        data = _minimal_project_dict(blots=[blot])
        path = tmp_path / "modern" / "project.json"
        _write_project_json(path, data)
        project = ws.load_project(str(path))
        assert project.panel.blots[0].included_in_final is False


# ===========================================================================
# create_new_project
# ===========================================================================

class TestCreateNewProject:

    def test_creates_valid_project_json(self, tmp_path):
        ws = _make_workspace(tmp_path)
        path = ws.create_new_project("My Project")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["project"]["name"] == "My Project"

    def test_created_project_is_loadable(self, tmp_path):
        ws = _make_workspace(tmp_path)
        path = ws.create_new_project("Load Me")
        project = ws.load_project(str(path))
        assert project.project.name == "Load Me"

    def test_timestamps_are_timezone_aware(self, tmp_path):
        ws = _make_workspace(tmp_path)
        path = ws.create_new_project("Timestamp Test")
        data = json.loads(path.read_text(encoding="utf-8"))

        created = data["project"]["created_utc"]
        modified = data["project"]["modified_utc"]

        # Must end with Z (UTC marker)
        assert created.endswith("Z"), f"created_utc not UTC: {created!r}"
        assert modified.endswith("Z"), f"modified_utc not UTC: {modified!r}"

        # Must parse as timezone-aware datetime
        dt_created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        dt_modified = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        assert dt_created.tzinfo is not None
        assert dt_modified.tzinfo is not None

    def test_timestamps_are_not_naive(self, tmp_path):
        """Explicitly verify the stored datetimes are not naive (utcnow produces naive)."""
        ws = _make_workspace(tmp_path)
        path = ws.create_new_project("Naive Check")
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data["project"]["created_utc"]
        # A naive datetime formatted with isoformat() would end in e.g. "00:00"
        # not "Z" or "+00:00". The "Z" suffix proves timezone-awareness.
        assert "Z" in ts or "+00:00" in ts

    def test_includes_crop_template(self, tmp_path):
        ws = _make_workspace(tmp_path)
        path = ws.create_new_project("CropTemplate Test")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "crop_template" in data["panel"]
        assert data["panel"]["crop_template"]["w"] == 300.0
        assert data["panel"]["crop_template"]["h"] == 200.0

    def test_each_project_gets_unique_id(self, tmp_path):
        ws = _make_workspace(tmp_path)
        p1 = ws.create_new_project("A")
        p2 = ws.create_new_project("B")
        id1 = json.loads(p1.read_text())["project"]["id"]
        id2 = json.loads(p2.read_text())["project"]["id"]
        assert id1 != id2


# ===========================================================================
# Helpers for archive tests
# ===========================================================================

def _make_project_with_real_asset(ws: Workspace, tmp_path: Path) -> tuple[str, str]:
    """
    Import a real binary asset into *ws*, create a project that references it,
    return (project_id, asset_sha256).
    """
    # Create a fake 16-byte "image" file (content is arbitrary)
    asset_file = tmp_path / "fake_image.tif"
    asset_file.write_bytes(b"\x00\x01" * 8)

    sha, _dest = ws.import_asset(str(asset_file))

    proj_path = ws.create_new_project("Archive Test Project")
    project = ws.load_project(str(proj_path))

    # Patch the project so it references the asset via blot + assets dict
    from pysternblot.models import AssetEntry, Blot
    project.assets[sha] = AssetEntry(
        sha256=sha,
        stored_original_path=str(_dest),
        original_source_path=str(asset_file),
    )
    blot_dict = _minimal_blot_dict("blot_01")
    blot_dict["asset_sha256"] = sha
    project.panel.blots.append(Blot.model_validate(blot_dict))
    project.panel.layout.order.append("blot_01")
    ws.save_project(project)

    return project.project.id, sha


# ===========================================================================
# export_archive / import_archive
# ===========================================================================

class TestExportArchiveRoundtrip:

    def test_export_archive_roundtrip(self, tmp_path):
        ws = _make_workspace(tmp_path)
        project_id, sha = _make_project_with_real_asset(ws, tmp_path)

        archive_path = tmp_path / "export.pbarchive"
        ws.export_archive([project_id], archive_path, "0.1.0")

        assert archive_path.exists()

        with zipfile.ZipFile(archive_path, "r") as zf:
            names = zf.namelist()

            # manifest must be present
            assert "pbarchive/manifest.json" in names

            manifest = json.loads(zf.read("pbarchive/manifest.json"))
            assert manifest["format"] == "pbarchive"
            assert manifest["format_version"] == 1
            assert project_id in manifest["project_ids"]
            assert sha in manifest["asset_sha256s"]

            # project.json must be present
            assert f"pbarchive/projects/{project_id}/project.json" in names

            # asset original must be present (name starts with "original.")
            asset_entries = [n for n in names if n.startswith(f"pbarchive/assets/{sha}/")]
            assert len(asset_entries) == 1
            assert asset_entries[0].split("/")[-1].startswith("original.")

            # preview caches must NOT be included
            assert not any("preview_crop" in n for n in names)


class TestImportArchiveRoundtrip:

    def test_import_archive_roundtrip(self, tmp_path):
        src_ws = _make_workspace(tmp_path / "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "transfer.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        dst_ws = _make_workspace(tmp_path / "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_project_ids == [project_id]
        assert result.skipped_project_ids == []
        assert result.imported_asset_count == 1
        assert result.skipped_asset_count == 0
        assert result.integrity_errors == []

        # Project should be present and loadable in the destination workspace
        proj_path = dst_ws.projects_dir / project_id / "project.json"
        assert proj_path.exists()
        imported = dst_ws.load_project(str(proj_path))
        assert imported.project.id == project_id

        # Operation log must contain the import entry
        import_entries = [
            e for e in imported.operation_log
            if e.operation == "imported_from_archive"
        ]
        assert len(import_entries) == 1
        assert import_entries[0].target_id == project_id
        assert "transfer.pbarchive" in (import_entries[0].note or "")

        # Asset must be present on disk
        asset_path = dst_ws.asset_original_file(sha)
        assert asset_path.exists()


class TestImportArchiveSkipsExistingProject:

    def test_import_archive_skips_existing_project(self, tmp_path):
        src_ws = _make_workspace(tmp_path / "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "export.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        dst_ws = _make_workspace(tmp_path / "dest")

        # First import
        result1 = dst_ws.import_archive(archive_path, "0.1.0")
        assert project_id in result1.imported_project_ids

        # Record state after first import
        proj_path = dst_ws.projects_dir / project_id / "project.json"
        content_after_first = proj_path.read_bytes()

        # Second import — project already exists
        result2 = dst_ws.import_archive(archive_path, "0.1.0")
        assert project_id in result2.skipped_project_ids
        assert project_id not in result2.imported_project_ids

        # Project file must be identical (not re-written or corrupted)
        assert proj_path.read_bytes() == content_after_first


class TestImportArchiveIntegrityError:

    def test_import_archive_integrity_error(self, tmp_path):
        src_ws = _make_workspace(tmp_path / "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        # Build a valid archive first, then corrupt the asset inside
        good_archive = tmp_path / "good.pbarchive"
        src_ws.export_archive([project_id], good_archive, "0.1.0")

        bad_archive = tmp_path / "bad.pbarchive"
        with zipfile.ZipFile(good_archive, "r") as zin, \
             zipfile.ZipFile(bad_archive, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.startswith("pbarchive/assets/"):
                    data = b"corrupted content"  # SHA256 will not match the path name
                zout.writestr(item, data)

        dst_ws = _make_workspace(tmp_path / "dest")
        result = dst_ws.import_archive(bad_archive, "0.1.0")

        assert len(result.integrity_errors) > 0
        # Corrupt asset must NOT have been written to disk
        assert not (dst_ws.assets_dir / sha).exists()


class TestExportArchiveMissingAsset:

    def test_export_archive_missing_asset_raises(self, tmp_path):
        ws = _make_workspace(tmp_path)

        proj_path = ws.create_new_project("Ghost Asset Project")
        project = ws.load_project(str(proj_path))

        # Inject a blot referencing a SHA that has no file on disk
        ghost_sha = "a" * 64
        from pysternblot.models import Blot
        blot_dict = _minimal_blot_dict("blot_01")
        blot_dict["asset_sha256"] = ghost_sha
        project.panel.blots.append(Blot.model_validate(blot_dict))
        project.panel.layout.order.append("blot_01")
        ws.save_project(project)

        archive_path = tmp_path / "should_not_exist.pbarchive"

        with pytest.raises(FileNotFoundError, match=ghost_sha):
            ws.export_archive([project.project.id], archive_path, "0.1.0")


# ===========================================================================
# parse_typhoon_tag270
# ===========================================================================

# Exact Tag 270 text extracted from the two instrument files.
# Mixed CRLF / LF exactly as stored by the scanner firmware.
_IRLONG_TAG270 = (
    "Serial number=36651188\r\n"
    "Date time=Thu May  7 14:32:30 2026\n"
    "Username=Cytiva\r\n"
    "Method name=-\r\n"
    "File name=20260507-142651-[IRlong].tif\r\n"
    "Laser and filter name=[IRlong]\r\n"
    "Laser name=785 nm\r\n"
    "Filter name=Through + IRlong 825BP30\r\n"
    "PMT type=Multi-alkali\r\n"
    "PMT HV=399 V\r\n"
    "Pixel size=50 micrometer\r\n"
    "Shading=On\r\n"
    "Scan speed=Normal\r\n"
    "Scan mode=Fluorescence\r\n"
    "Stage and area name=Fluor\r\n"
    "Scan number=1/2\r\n"
    "Orientation=bottom-left\r\n"
    "Firmware version=310\r\n"
    "FPGA version=11\r\n"
    "Laser power=Fluor\r\n"
    "Filter=3/1\r\n"
    "Main start position=0[mm]\r\n"
    "Sub start position=0[mm]\r\n"
    "Correction1=1\r\n"
    "Correction2=On\r\n"
    "Correction3=On\r\n"
    "Correction3A=Off\r\n"
    "Correction4=On\r\n"
    "Correction5=On\r\n"
    "Correction6=On\r\n"
    "Correction7=26532/26553\r\n"
    "Correction8=Off\r\n"
    "Correction8_DateTime=-\r\n"
    "Correction9=Off\r\n"
    "Correction9_DateTime=-\r\n"
    "Shading=C:\\ProgramData\\Cytiva\\Amersham TYPHOON\\Data\\ShadingData\\"
    "Fluorescence_5_6_15_16.shading\r\n"
    "Shading_DateTime=2024/10/26 09:04:04\r\n"
    "CorrectionA=Off\n"
    "Correction10=Off\r\n"
    "Invert=Off\r\n"
    "Sub motor mode=1\r\n"
    "Signal Process1=Off\r\n"
    "Signal Process2=Log\r\n"
    "Software=Amersham TYPHOON Scanner Control Software 4.0.0.4\r\n"
    "\x00"
)

_IRSHORT_TAG270 = (
    "Serial number=36651188\r\n"
    "Date time=Thu May  7 14:38:43 2026\n"
    "Username=Cytiva\r\n"
    "Method name=-\r\n"
    "File name=20260507-142651-[IRshort].tif\r\n"
    "Laser and filter name=[IRshort]\r\n"
    "Laser name=685 nm\r\n"
    "Filter name=Through + IRshort 720BP20\r\n"
    "PMT type=Multi-alkali\r\n"
    "PMT HV=360 V\r\n"
    "Pixel size=50 micrometer\r\n"
    "Shading=On\r\n"
    "Scan speed=Normal\r\n"
    "Scan mode=Fluorescence\r\n"
    "Stage and area name=Fluor\r\n"
    "Scan number=2/2\r\n"
    "Orientation=bottom-left\r\n"
    "Firmware version=310\r\n"
    "FPGA version=11\r\n"
    "Laser power=Fluor\r\n"
    "Filter=2/1\r\n"
    "Main start position=0[mm]\r\n"
    "Sub start position=0[mm]\r\n"
    "Correction1=1\r\n"
    "Correction2=On\r\n"
    "Correction3=On\r\n"
    "Correction3A=Off\r\n"
    "Correction4=On\r\n"
    "Correction5=On\r\n"
    "Correction6=On\r\n"
    "Correction7=26534/26553\r\n"
    "Correction8=Off\r\n"
    "Correction8_DateTime=-\r\n"
    "Correction9=Off\r\n"
    "Correction9_DateTime=-\r\n"
    "Shading=C:\\ProgramData\\Cytiva\\Amersham TYPHOON\\Data\\ShadingData\\"
    "Fluorescence_4_5_15_16.shading\r\n"
    "Shading_DateTime=2024/10/26 09:04:04\r\n"
    "CorrectionA=Off\n"
    "Correction10=Off\r\n"
    "Invert=Off\r\n"
    "Sub motor mode=1\r\n"
    "Signal Process1=Off\r\n"
    "Signal Process2=Log\r\n"
    "Software=Amersham TYPHOON Scanner Control Software 4.0.0.4\r\n"
    "\x00"
)


class TestParseTyphoonTag270:

    def test_parse_typhoon_tag270_irlong(self):
        """Parse the exact Tag 270 string from the IRlong file and verify key fields."""
        meta = parse_typhoon_tag270(_IRLONG_TAG270)
        assert meta["laser_nm"] == 785
        assert meta["filter_name"] == "IRlong 825BP30"
        assert meta["channel_index"] == 0
        assert meta["channel_total"] == 2

    def test_parse_typhoon_tag270_irshort(self):
        """Parse the exact Tag 270 string from the IRshort file and verify key fields."""
        meta = parse_typhoon_tag270(_IRSHORT_TAG270)
        assert meta["laser_nm"] == 685
        assert meta["filter_name"] == "IRshort 720BP20"
        assert meta["channel_index"] == 1
        assert meta["channel_total"] == 2

    def test_parse_typhoon_tag270_malformed(self):
        """Garbage input must never raise — must return a dict."""
        result = parse_typhoon_tag270("not valid at all !!!\x00\xff")
        assert isinstance(result, dict)

    def test_parse_typhoon_tag270_empty(self):
        """Empty string must return a dict of all-None values."""
        result = parse_typhoon_tag270("")
        assert isinstance(result, dict)
        assert result["laser_nm"] is None
        assert result["channel_index"] is None


# ===========================================================================
# import_nir_blot_typhoon
# ===========================================================================

class TestImportNirBlotTyphoon:

    def test_import_nir_blot_typhoon(self, tmp_path):
        """
        import_nir_blot_typhoon with both real Typhoon files must:
        - Return 2 BlotChannel objects sorted by channel_index ascending
        - Populate wavelength_nm correctly from Tag 270
        - Populate asset_sha256 matching the actual file hashes
        - Write both assets to the workspace assets directory
        - Append one log entry per channel to project.operation_log
        """
        ws = _make_workspace(tmp_path)
        proj_path = ws.create_new_project("NIR Test")
        project = ws.load_project(str(proj_path))

        ch_short = TESTS_DIR / "20260507-142651-[IRshort].tif"
        ch_long = TESTS_DIR / "20260507-142651-[IRlong].tif"

        if not ch_short.exists() or not ch_long.exists():
            pytest.skip("Typhoon test files not found in tests/")

        # Pass in reverse order to verify sort-by-channel_index
        channels = ws.import_nir_blot_typhoon([ch_short, ch_long], project)

        assert len(channels) == 2
        assert all(isinstance(c, BlotChannel) for c in channels)

        # Sorted ascending: channel_index 0 (IRlong/785nm) first
        assert channels[0].channel_index == 0
        assert channels[1].channel_index == 1
        assert channels[0].wavelength_nm == 785
        assert channels[1].wavelength_nm == 685

        # SHA256 must match the actual files
        sha_long = sha256_file(str(ch_long))
        sha_short = sha256_file(str(ch_short))
        assert channels[0].asset_sha256 == sha_long
        assert channels[1].asset_sha256 == sha_short

        # Assets must exist on disk
        ws.asset_original_file(sha_long)
        ws.asset_original_file(sha_short)

        # One log entry per channel
        nir_entries = [
            e for e in project.operation_log
            if e.operation == "nir_channel_imported"
        ]
        assert len(nir_entries) == 2


# ===========================================================================
# ensure_blot_crop_preview — ECL and NIR cache filename behaviour
# ===========================================================================

def _make_uint16_tiff(path, width: int = 10, height: int = 8) -> None:
    """Write a minimal valid 16-bit grayscale TIFF to *path*."""
    import numpy as np
    from PIL import Image
    arr = np.zeros((height, width), dtype=np.uint16)
    arr[2, 3] = 32768
    img = Image.frombuffer("I;16", (width, height), arr.tobytes(), "raw", "I;16", 0, 1)
    img.save(str(path))


def _minimal_blot_model(blot_id: str, sha: str) -> "Blot":
    from pysternblot.models import (
        Blot, Crop, Ladder, CalibrationPoint, ProteinLabel, CropTemplate,
    )
    return Blot(
        id=blot_id,
        asset_sha256=sha,
        crop=Crop(x=0, y=0, w=8, h=6),
        ladder=Ladder(
            lane_index=0,
            marker_set_id="ms_default",
            calibration_points=[
                CalibrationPoint(y_px=2, kda=55),
                CalibrationPoint(y_px=5, kda=36),
            ],
        ),
        protein_label=ProteinLabel(text="Test"),
    )


class TestEnsureBlotCropPreviewNIR:

    def test_ensure_blot_crop_preview_ecl_unaffected(self, tmp_path):
        """ECL blot cache filename is preview_crop_<id>.tif — unchanged."""
        ws = _make_workspace(tmp_path)
        ws.ensure()

        # Plant a real 16-bit TIFF in the asset store
        sha = "a" * 64
        asset_dir = ws.assets_dir / sha
        asset_dir.mkdir(parents=True, exist_ok=True)
        _make_uint16_tiff(asset_dir / "original.tif")

        from pysternblot.models import CropTemplate, Panel, LaneLayout, HeaderBlock, Group, ConditionRow, Layout, LegendSettings
        blot = _minimal_blot_model("blot_01", sha)

        class _FakePanel:
            crop_template = CropTemplate(w=6, h=4)

        out = ws.ensure_blot_crop_preview(blot, _FakePanel())
        assert out.name == "preview_crop_blot_01.tif"
        assert out.exists()

    def test_ensure_blot_crop_preview_nir_channel_cache_name(self, tmp_path):
        """NIR channels produce preview_crop_<id>_ch<n>.tif, one file per channel."""
        ws = _make_workspace(tmp_path)
        ws.ensure()

        # Two distinct assets for the two NIR channels
        sha0 = "0" * 64
        sha1 = "1" * 64
        for sha in (sha0, sha1):
            d = ws.assets_dir / sha
            d.mkdir(parents=True, exist_ok=True)
            _make_uint16_tiff(d / "original.tif")

        from pysternblot.models import BlotChannel, DisplaySettings, ProteinLabel, CropTemplate

        blot = _minimal_blot_model("blot_nir", sha0)
        blot.modality = "nir_fluorescence"
        blot.channels = [
            BlotChannel(asset_sha256=sha0, channel_index=0),
            BlotChannel(asset_sha256=sha1, channel_index=1),
        ]

        class _FakePanel:
            crop_template = CropTemplate(w=6, h=4)

        out0 = ws.ensure_blot_crop_preview(blot, _FakePanel(), channel_index=0)
        out1 = ws.ensure_blot_crop_preview(blot, _FakePanel(), channel_index=1)

        assert out0.name == "preview_crop_blot_nir_ch0.tif"
        assert out1.name == "preview_crop_blot_nir_ch1.tif"
        # Must be in the respective channel's asset directory
        assert out0.parent == ws.assets_dir / sha0
        assert out1.parent == ws.assets_dir / sha1
        # Both files must exist
        assert out0.exists()
        assert out1.exists()
        # Must be distinct paths
        assert out0 != out1
