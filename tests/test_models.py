# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for pysternblot/models.py

No Qt and no display required — pure Pydantic model tests.

Run from repo root:
    pytest tests/test_models.py -v
"""

from __future__ import annotations

import pytest

from pysternblot.models import (
    Blot,
    BlotChannel,
    CalibrationPoint,
    ConditionRow,
    Crop,
    CropTemplate,
    DisplaySettings,
    Group,
    HeaderBlock,
    Ladder,
    LadderBandAssignment,
    LaneLayout,
    Layout,
    LegendRow,
    LegendSettings,
    OperationLogEntry,
    OverlayLadder,
    Panel,
    ProjectMeta,
    ProteinLabel,
    Project,
    Style,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_ladder() -> Ladder:
    return Ladder(
        lane_index=0,
        marker_set_id="ms_default",
        calibration_points=[
            CalibrationPoint(y_px=50, kda=55),
            CalibrationPoint(y_px=120, kda=36),
        ],
    )


def _minimal_blot(blot_id: str = "blot_01", sha: str = "abc123") -> Blot:
    return Blot(
        id=blot_id,
        asset_sha256=sha,
        crop=Crop(x=10, y=20, w=300, h=200),
        ladder=_minimal_ladder(),
        protein_label=ProteinLabel(text="GAPDH"),
    )


def _minimal_panel(blots: list[Blot] | None = None) -> Panel:
    return Panel(
        lane_layout=LaneLayout(
            mode="manual_n_lanes",
            n_lanes_manual=2,
            header_block=HeaderBlock(
                left_title="",
                groups=[Group(label="", n_lanes=2)],
                condition_rows=[ConditionRow(values=["", ""])],
            ),
        ),
        blots=blots or [],
        layout=Layout(order=[]),
    )


def _minimal_project(blots: list[Blot] | None = None) -> Project:
    return Project(
        project=ProjectMeta(
            id="proj_test",
            name="Test Project",
            created_utc="2024-01-01T00:00:00Z",
            app_version="0.1.0",
        ),
        panel=_minimal_panel(blots),
    )


# ===========================================================================
# Round-trip serialization
# ===========================================================================

class TestRoundTrip:

    def test_empty_project_round_trips(self):
        project = _minimal_project()
        restored = Project.model_validate(project.model_dump())
        assert restored == project

    def test_project_with_blot_round_trips(self):
        blot = _minimal_blot()
        project = _minimal_project(blots=[blot])
        restored = Project.model_validate(project.model_dump())
        assert restored == project

    def test_json_round_trip(self):
        """model_dump_json → model_validate_json must produce an equal model."""
        project = _minimal_project(blots=[_minimal_blot()])
        json_str = project.model_dump_json()
        restored = Project.model_validate_json(json_str)
        assert restored == project

    def test_project_with_overlay_ladder_round_trips(self):
        blot = _minimal_blot()
        blot.overlay_ladder = OverlayLadder(
            marker_set_id="ms_default",
            bands=[LadderBandAssignment(y_px=80, kda=55)],
        )
        project = _minimal_project(blots=[blot])
        restored = Project.model_validate(project.model_dump())
        assert restored == project

    def test_project_with_operation_log_round_trips(self):
        project = _minimal_project()
        project.operation_log.append(
            OperationLogEntry(
                timestamp_utc="2024-01-01T12:00:00Z",
                operation="crop_committed",
                target_type="blot",
                target_id="blot_01",
                field="crop",
                old_value=None,
                new_value={"x": 10, "y": 20},
            )
        )
        restored = Project.model_validate(project.model_dump())
        assert restored == project


# ===========================================================================
# Blot.included_in_final default
# ===========================================================================

class TestIncludedInFinal:

    def test_defaults_to_true(self):
        blot = _minimal_blot()
        assert blot.included_in_final is True

    def test_can_be_set_false(self):
        blot = _minimal_blot()
        blot.included_in_final = False
        assert blot.included_in_final is False

    def test_survives_round_trip_when_false(self):
        blot = _minimal_blot()
        blot.included_in_final = False
        project = _minimal_project(blots=[blot])
        restored = Project.model_validate(project.model_dump())
        assert restored.panel.blots[0].included_in_final is False

    def test_omitted_field_defaults_to_true_on_validate(self):
        """A blot dict without included_in_final should deserialize to True."""
        blot_dict = _minimal_blot().model_dump()
        blot_dict.pop("included_in_final", None)
        restored = Blot.model_validate(blot_dict)
        assert restored.included_in_final is True


# ===========================================================================
# CropTemplate is panel-level, not per-blot
# ===========================================================================

class TestCropTemplate:

    def test_crop_template_lives_on_panel(self):
        panel = _minimal_panel()
        assert hasattr(panel, "crop_template")
        assert not hasattr(panel.blots, "crop_template")

    def test_default_crop_template_dimensions(self):
        panel = _minimal_panel()
        assert panel.crop_template.w == 300.0
        assert panel.crop_template.h == 200.0

    def test_custom_crop_template(self):
        panel = _minimal_panel()
        panel.crop_template = CropTemplate(w=450, h=300)
        assert panel.crop_template.w == 450.0
        assert panel.crop_template.h == 300.0

    def test_blot_crop_has_no_template_authority(self):
        """Blot.crop.w/h exist for backward compat but are not the authoritative size."""
        blot = _minimal_blot()
        panel = _minimal_panel(blots=[blot])
        # Changing crop_template doesn't touch blot.crop.w/h
        panel.crop_template = CropTemplate(w=999, h=888)
        assert blot.crop.w == 300.0
        assert blot.crop.h == 200.0

    def test_crop_template_survives_round_trip(self):
        panel = _minimal_panel()
        panel.crop_template = CropTemplate(w=512, h=384)
        project = Project(
            project=ProjectMeta(
                id="p",
                name="n",
                created_utc="2024-01-01T00:00:00Z",
                app_version="0.1.0",
            ),
            panel=panel,
        )
        restored = Project.model_validate(project.model_dump())
        assert restored.panel.crop_template.w == 512.0
        assert restored.panel.crop_template.h == 384.0


# ===========================================================================
# Adding a new blot doesn't affect other blots' crop positions
# ===========================================================================

class TestBlotIsolation:

    def test_adding_blot_does_not_alter_existing_blot_position(self):
        blot_a = _minimal_blot("blot_01", "sha_a")
        blot_a.crop.x = 100
        blot_a.crop.y = 200

        panel = _minimal_panel(blots=[blot_a])

        blot_b = _minimal_blot("blot_02", "sha_b")
        blot_b.crop.x = 50
        blot_b.crop.y = 75
        panel.blots.append(blot_b)

        assert panel.blots[0].crop.x == 100
        assert panel.blots[0].crop.y == 200

    def test_modifying_second_blot_position_is_independent(self):
        blot_a = _minimal_blot("blot_01", "sha_a")
        blot_b = _minimal_blot("blot_02", "sha_b")
        panel = _minimal_panel(blots=[blot_a, blot_b])

        original_x = panel.blots[0].crop.x
        panel.blots[1].crop.x = 999

        assert panel.blots[0].crop.x == original_x

    def test_blots_are_not_aliased(self):
        """Two blots must be distinct objects, not the same reference."""
        blot_a = _minimal_blot("blot_01", "sha_a")
        blot_b = _minimal_blot("blot_02", "sha_b")
        assert blot_a is not blot_b
        assert blot_a.crop is not blot_b.crop


# ===========================================================================
# LegendRow
# ===========================================================================

class TestLegendRow:

    def test_has_underline_field(self):
        row = LegendRow()
        assert hasattr(row, "underline")

    def test_underline_defaults_to_false(self):
        row = LegendRow()
        assert row.underline is False

    def test_underline_can_be_set_true(self):
        row = LegendRow(underline=True)
        assert row.underline is True

    def test_has_all_expected_fields(self):
        row = LegendRow(left="L", cells=["A", "B"], right="R", underline=True, font_size_pt=10.0)
        assert row.left == "L"
        assert row.cells == ["A", "B"]
        assert row.right == "R"
        assert row.underline is True
        assert row.font_size_pt == 10.0

    def test_font_size_pt_defaults_to_none(self):
        row = LegendRow()
        assert row.font_size_pt is None

    def test_round_trips(self):
        row = LegendRow(left="kDa", cells=["55", "37"], underline=True)
        restored = LegendRow.model_validate(row.model_dump())
        assert restored == row

    def test_only_one_legend_row_class(self):
        """There must not be duplicate LegendRow definitions — verify by import identity."""
        from pysternblot import models
        assert models.LegendRow is LegendRow


# ===========================================================================
# OperationLogEntry
# ===========================================================================

class TestOperationLogEntry:

    def test_minimal_entry_serializes(self):
        entry = OperationLogEntry(
            timestamp_utc="2024-06-01T10:00:00Z",
            operation="crop_committed",
        )
        data = entry.model_dump()
        assert data["operation"] == "crop_committed"
        assert data["timestamp_utc"] == "2024-06-01T10:00:00Z"

    def test_all_optional_fields_default_to_none(self):
        entry = OperationLogEntry(
            timestamp_utc="2024-06-01T10:00:00Z",
            operation="test_op",
        )
        assert entry.target_type is None
        assert entry.target_id is None
        assert entry.asset_sha256 is None
        assert entry.field is None
        assert entry.old_value is None
        assert entry.new_value is None
        assert entry.note is None

    def test_full_entry_round_trips(self):
        entry = OperationLogEntry(
            timestamp_utc="2024-06-01T10:00:00Z",
            operation="levels_changed",
            target_type="blot",
            target_id="blot_01",
            asset_sha256="deadbeef",
            field="display.levels_black",
            old_value=0,
            new_value=1000,
            note="User adjusted black point.",
        )
        restored = OperationLogEntry.model_validate(entry.model_dump())
        assert restored == entry

    def test_new_value_can_be_dict(self):
        """old_value / new_value are Any — must accept nested structures."""
        entry = OperationLogEntry(
            timestamp_utc="2024-06-01T10:00:00Z",
            operation="crop_committed",
            old_value={"x": 0, "y": 0},
            new_value={"x": 10, "y": 20, "w": 300, "h": 200},
        )
        restored = OperationLogEntry.model_validate(entry.model_dump())
        assert restored.new_value == {"x": 10, "y": 20, "w": 300, "h": 200}

    def test_appended_to_project_and_survives_round_trip(self):
        project = _minimal_project()
        project.operation_log.append(
            OperationLogEntry(
                timestamp_utc="2024-06-01T10:00:00Z",
                operation="levels_changed",
            )
        )
        restored = Project.model_validate(project.model_dump())
        assert len(restored.operation_log) == 1
        assert restored.operation_log[0].operation == "levels_changed"


# ===========================================================================
# Blot.antibody_name
# ===========================================================================

class TestAntibodyName:

    def test_blot_antibody_name_default(self):
        blot = _minimal_blot()
        assert blot.antibody_name == ""

    def test_blot_antibody_name_roundtrip(self):
        blot = _minimal_blot()
        blot.antibody_name = "anti-GAPDH"
        restored = Blot.model_validate(blot.model_dump())
        assert restored.antibody_name == "anti-GAPDH"

    def test_blot_backward_compat_no_antibody_name(self):
        blot_dict = _minimal_blot().model_dump()
        blot_dict.pop("antibody_name", None)
        restored = Blot.model_validate(blot_dict)
        assert restored.antibody_name == ""


# ===========================================================================
# Blot NIR extension — modality, channels, helpers
# ===========================================================================

def _minimal_blot_channel(index: int, sha: str = "sha_ch") -> BlotChannel:
    return BlotChannel(
        asset_sha256=sha,
        channel_index=index,
        wavelength_nm=785 - index * 100,  # 785, 685 for 0, 1
    )


class TestBlotNIRExtension:

    def test_blot_ecl_defaults(self):
        blot = _minimal_blot()
        assert blot.modality == "ecl"
        assert blot.channels == []
        assert blot.is_nir() is False

    def test_blot_nir_modality(self):
        blot = _minimal_blot()
        blot.modality = "nir_fluorescence"
        blot.channels = [
            _minimal_blot_channel(0, "sha_0"),
            _minimal_blot_channel(1, "sha_1"),
        ]
        assert blot.is_nir() is True
        assert len(blot.channels) == 2

    def test_get_display_channel_ecl(self):
        blot = _minimal_blot()
        sha, display = blot.get_display_channel()
        assert sha == blot.asset_sha256
        assert display is blot.display

    def test_get_display_channel_nir(self):
        blot = _minimal_blot()
        blot.modality = "nir_fluorescence"
        ch0 = _minimal_blot_channel(0, "sha_ch0")
        ch1 = _minimal_blot_channel(1, "sha_ch1")
        blot.channels = [ch0, ch1]

        sha0, disp0 = blot.get_display_channel(0)
        sha1, disp1 = blot.get_display_channel(1)

        assert sha0 == "sha_ch0"
        assert sha1 == "sha_ch1"
        assert disp0 is ch0.display
        assert disp1 is ch1.display

    def test_blot_channel_index_out_of_range(self):
        blot = _minimal_blot()
        blot.modality = "nir_fluorescence"
        blot.channels = [_minimal_blot_channel(0)]

        with pytest.raises(IndexError):
            blot.get_display_channel(99)

    def test_backward_compat_ecl_project_loads(self):
        """A Blot dict without modality or channels (old project.json) must load cleanly."""
        blot_dict = _minimal_blot().model_dump()
        blot_dict.pop("modality", None)
        blot_dict.pop("channels", None)
        restored = Blot.model_validate(blot_dict)
        assert restored.modality == "ecl"
        assert restored.channels == []


# ===========================================================================
# Render row expansion logic (mirrors build_panel_scene expansion in render.py)
# ===========================================================================

def _expand_render_rows(panel):
    """
    Inline expansion matching build_panel_scene — returns list of
    (blot, channel|None, is_first_row) tuples for included blots only.
    """
    order = list(getattr(panel.layout, "order", []))
    blot_by_id = {b.id: b for b in panel.blots if b.included_in_final}
    ordered = [blot_by_id[i] for i in order if i in blot_by_id] or list(blot_by_id.values())

    rows = []
    seen: set = set()
    for blot in ordered:
        if blot.is_nir():
            for ch in sorted(blot.channels, key=lambda c: c.channel_index):
                rows.append((blot, ch, blot.id not in seen))
                seen.add(blot.id)
        else:
            rows.append((blot, None, True))
    return rows


class TestRenderRowExpansion:

    def test_render_rows_ecl_blot(self):
        blot = _minimal_blot("ecl_01")
        panel = _minimal_panel(blots=[blot])
        rows = _expand_render_rows(panel)
        assert len(rows) == 1
        b, ch, is_first = rows[0]
        assert b is blot
        assert ch is None
        assert is_first is True

    def test_render_rows_nir_two_channels(self):
        blot = _minimal_blot("nir_01")
        blot.modality = "nir_fluorescence"
        blot.channels = [
            _minimal_blot_channel(1, "sha_1"),  # out-of-order on purpose
            _minimal_blot_channel(0, "sha_0"),
        ]
        panel = _minimal_panel(blots=[blot])
        rows = _expand_render_rows(panel)
        assert len(rows) == 2
        # must be sorted by channel_index
        b0, ch0, first0 = rows[0]
        b1, ch1, first1 = rows[1]
        assert ch0.channel_index == 0
        assert ch1.channel_index == 1
        assert first0 is True
        assert first1 is False  # ladder only on first row
        assert b0 is blot
        assert b1 is blot

    def test_render_rows_nir_single_channel(self):
        blot = _minimal_blot("nir_01")
        blot.modality = "nir_fluorescence"
        blot.channels = [_minimal_blot_channel(0, "sha_0")]
        panel = _minimal_panel(blots=[blot])
        rows = _expand_render_rows(panel)
        assert len(rows) == 1
        b, ch, is_first = rows[0]
        assert ch.channel_index == 0
        assert is_first is True

    def test_render_rows_excluded_blot(self):
        ecl = _minimal_blot("ecl_01")
        nir = _minimal_blot("nir_01")
        nir.modality = "nir_fluorescence"
        nir.channels = [_minimal_blot_channel(0, "sha_nir"), _minimal_blot_channel(1, "sha_nir2")]
        nir.included_in_final = False
        panel = _minimal_panel(blots=[ecl, nir])
        rows = _expand_render_rows(panel)
        # excluded NIR blot must produce zero rows regardless of channel count
        assert len(rows) == 1
        assert rows[0][0] is ecl
