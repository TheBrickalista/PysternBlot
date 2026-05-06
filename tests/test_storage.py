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

from pysternblot.storage import Workspace, sha256_file
from pysternblot.models import (
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
    Blot,
)


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
