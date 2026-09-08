# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for pysternblot/logchain.py

Pure model/logic tests — no Qt, no display required.

Run from repo root:
    pytest tests/test_logchain.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pysternblot.logchain import (
    GENESIS_HASH,
    append_log_entry,
    canonical_payload,
    compute_entry_hash,
    verify_log_chain,
)
from pysternblot.models import (
    Group,
    HeaderBlock,
    LaneLayout,
    Layout,
    OperationLogEntry,
    Panel,
    Project,
    ProjectMeta,
    ConditionRow,
)
from pysternblot.storage import Workspace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_panel() -> Panel:
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
        blots=[],
        layout=Layout(order=[]),
    )


def _minimal_project(project_id: str = "proj_test") -> Project:
    return Project(
        project=ProjectMeta(
            id=project_id,
            name="Test Project",
            created_utc="2024-01-01T00:00:00Z",
            app_version="0.1.0",
        ),
        panel=_minimal_panel(),
    )


def _entry(op: str = "crop_committed", **kwargs) -> OperationLogEntry:
    return OperationLogEntry(
        timestamp_utc="2024-06-01T10:00:00Z",
        operation=op,
        **kwargs,
    )


# ===========================================================================
# append_log_entry / chain construction
# ===========================================================================

class TestAppendLogEntry:

    def test_appending_n_entries_produces_ok_chain(self):
        project = _minimal_project()
        n = 5
        for i in range(n):
            append_log_entry(project, _entry(f"op_{i}"))

        result = verify_log_chain(project)
        assert result.status == "ok"
        assert result.n_chained == n
        assert result.n_entries == n

    def test_first_entry_prev_hash_is_genesis(self):
        project = _minimal_project()
        append_log_entry(project, _entry())
        assert project.operation_log[0].prev_hash == GENESIS_HASH

    def test_each_entry_hash_is_set_and_chains_to_next_prev_hash(self):
        project = _minimal_project()
        append_log_entry(project, _entry("a"))
        append_log_entry(project, _entry("b"))
        first, second = project.operation_log
        assert first.entry_hash is not None
        assert second.prev_hash == first.entry_hash

    def test_empty_project_log_verifies_ok(self):
        project = _minimal_project()
        result = verify_log_chain(project)
        assert result.status == "ok"
        assert result.n_entries == 0
        assert result.n_chained == 0


# ===========================================================================
# Tamper detection
# ===========================================================================

class TestTamperDetection:

    def test_mutating_old_value_breaks_chain_at_index(self):
        project = _minimal_project()
        for i in range(4):
            append_log_entry(project, _entry(f"op_{i}", old_value=i, new_value=i + 1))

        k = 2
        project.operation_log[k].old_value = 999

        result = verify_log_chain(project)
        assert result.status == "broken"
        assert result.first_broken_index == k

    def test_deleting_entry_breaks_chain_at_index(self):
        project = _minimal_project()
        for i in range(4):
            append_log_entry(project, _entry(f"op_{i}"))

        k = 1
        del project.operation_log[k]

        result = verify_log_chain(project)
        assert result.status == "broken"
        assert result.first_broken_index == k

    def test_swapping_adjacent_entries_breaks_chain(self):
        project = _minimal_project()
        for i in range(4):
            append_log_entry(project, _entry(f"op_{i}"))

        log = project.operation_log
        log[1], log[2] = log[2], log[1]

        result = verify_log_chain(project)
        assert result.status == "broken"

    def test_tampering_entry_hash_itself_breaks_chain(self):
        project = _minimal_project()
        for i in range(3):
            append_log_entry(project, _entry(f"op_{i}"))

        project.operation_log[1].entry_hash = "f" * 64

        result = verify_log_chain(project)
        assert result.status == "broken"
        assert result.first_broken_index == 1


# ===========================================================================
# Pre-1.2.0 (unchained) projects
# ===========================================================================

class TestUnchainedProjects:

    def test_unhashed_log_is_not_chained_not_broken(self):
        project = _minimal_project()
        project.operation_log.append(_entry("legacy_op"))
        project.operation_log.append(_entry("legacy_op_2"))

        result = verify_log_chain(project)
        assert result.status == "not_chained"
        assert result.n_entries == 2
        assert result.n_chained == 0

    def test_appending_to_unhashed_log_yields_partial(self):
        project = _minimal_project()
        project.operation_log.append(_entry("legacy_op"))
        project.operation_log.append(_entry("legacy_op_2"))

        append_log_entry(project, _entry("new_chained_op"))

        result = verify_log_chain(project)
        assert result.status == "partial"
        assert result.chained_from_index == 2
        assert result.n_chained == 1
        assert result.n_entries == 3

    def test_first_chained_entry_after_legacy_log_has_genesis_prev_hash(self):
        project = _minimal_project()
        project.operation_log.append(_entry("legacy_op"))
        append_log_entry(project, _entry("new_chained_op"))

        assert project.operation_log[1].prev_hash == GENESIS_HASH


# ===========================================================================
# canonical_payload determinism
# ===========================================================================

class TestCanonicalPayload:

    def test_identical_entries_hash_identically(self):
        e1 = _entry("crop_committed", old_value={"x": 1}, new_value={"x": 2})
        e2 = _entry("crop_committed", old_value={"x": 1}, new_value={"x": 2})
        assert compute_entry_hash(e1) == compute_entry_hash(e2)

    def test_hash_survives_project_json_round_trip(self):
        project = _minimal_project()
        append_log_entry(project, _entry("crop_committed", old_value={"x": 1}, new_value={"x": 2}))

        original_hash = project.operation_log[0].entry_hash

        restored = Project.model_validate_json(project.model_dump_json())
        assert restored.operation_log[0].entry_hash == original_hash
        assert compute_entry_hash(restored.operation_log[0]) == original_hash

    def test_nested_dict_key_order_does_not_affect_hash(self):
        e1 = _entry("crop_committed", old_value={"a": 1, "b": {"y": 2, "x": 1}})
        e2 = _entry("crop_committed", old_value={"b": {"x": 1, "y": 2}, "a": 1})
        assert compute_entry_hash(e1) == compute_entry_hash(e2)

    def test_none_fields_are_serialised_as_null_not_omitted(self):
        e1 = _entry("op", old_value=None)
        e2 = _entry("op")
        # Both should be equivalent (old_value defaults to None) and hash the same.
        assert compute_entry_hash(e1) == compute_entry_hash(e2)
        assert '"old_value":null' in canonical_payload(e1)

    def test_prev_hash_is_included_in_payload(self):
        e = _entry("op")
        e.prev_hash = "a" * 64
        assert '"prev_hash":"' + "a" * 64 + '"' in canonical_payload(e)

    def test_entry_hash_is_excluded_from_payload(self):
        e = _entry("op")
        e.entry_hash = "b" * 64
        assert "entry_hash" not in canonical_payload(e)


# ===========================================================================
# Full round trip through storage
# ===========================================================================

class TestStorageRoundTrip:

    def test_save_and_load_project_preserves_ok_chain(self, tmp_path: Path):
        workspace = Workspace(root=tmp_path / "ws")
        workspace.ensure()

        project = _minimal_project()
        for i in range(3):
            append_log_entry(project, _entry(f"op_{i}", old_value=i, new_value=i + 1))

        assert verify_log_chain(project).status == "ok"

        path = workspace.save_project(project)
        reloaded = workspace.load_project(str(path))

        result = verify_log_chain(reloaded)
        assert result.status == "ok"
        assert result.n_chained == 3
