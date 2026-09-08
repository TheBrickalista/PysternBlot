# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for Stage 5 resource limits on untrusted input:

- decompression / member-count / total-size / compression-ratio limits on
  import_archive() (pysternblot/storage.py)
- response size cap on fetch_latest_release() (pysternblot/update_check.py)
- identifier sanitisation for preview-cache filenames (pysternblot/storage.py)

Constants are monkeypatched down to small values throughout — no large
payloads are generated, except test 7, which deliberately uses the real
production constants to prove they do not reject a normal archive.

Run from repo root:
    pytest tests/test_archive_limits.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zipfile
from pathlib import Path

import pytest

import pysternblot.storage as storage_module
import pysternblot.update_check as update_check_module
from pysternblot.models import AssetEntry, Blot, Panel, HeaderBlock, Group, ConditionRow, LaneLayout, Layout, Crop, Ladder, CalibrationPoint, ProteinLabel, Project, ProjectMeta
from pysternblot.storage import Workspace, _safe_cache_component


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path, name: str = "ws") -> Workspace:
    ws = Workspace(root=tmp_path / name)
    ws.ensure()
    return ws


def _snapshot(root: Path) -> set[Path]:
    return set(root.rglob("*")) if root.exists() else set()


def _manifest(
    *,
    project_ids: list[str] | None = None,
    asset_sha256s: list[str] | None = None,
    project_sha256s: dict[str, str] | None = None,
    format_version: int = 2,
) -> dict:
    m = {
        "format": "pbarchive",
        "format_version": format_version,
        "created_utc": "2024-01-01T00:00:00Z",
        "app_version": "0.1.0",
        "project_ids": project_ids or [],
        "asset_sha256s": asset_sha256s or [],
    }
    if format_version >= 2:
        m["project_sha256s"] = project_sha256s or {}
    return m


def _write_archive(path: Path, manifest: dict, members: dict[str, bytes]) -> None:
    """Write a .pbarchive zip with the given manifest and raw member bytes."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pbarchive/manifest.json", json.dumps(manifest))
        for name, data in members.items():
            zf.writestr(name, data)


def _lie_about_uncompressed_size(archive_path: Path, member_name: str, declared_size: int) -> None:
    """
    Patch ONLY the central directory's uncompressed-size field for
    *member_name* to *declared_size*, leaving the real compressed data (and
    its CRC-32, computed over the true content) untouched.

    This is what ZipFile.getinfo(name).file_size reads from — CPython builds
    every ZipInfo entirely from the central directory, never the local file
    header — so this reproduces a central directory that lies about a
    member's size while the actual bytes on disk are unchanged.
    """
    data = bytearray(archive_path.read_bytes())
    sig = b"PK\x01\x02"
    name_bytes = member_name.encode()
    idx = 0
    while True:
        idx = data.find(sig, idx)
        if idx == -1:
            raise AssertionError(f"central directory record for {member_name!r} not found")
        fname_len = struct.unpack_from("<H", data, idx + 28)[0]
        fname = bytes(data[idx + 46: idx + 46 + fname_len])
        if fname == name_bytes:
            struct.pack_into("<I", data, idx + 24, declared_size)
            archive_path.write_bytes(data)
            return
        idx += 4


def _minimal_blot_dict(blot_id: str = "blot_01", sha: str = "abc123") -> dict:
    return {
        "id": blot_id,
        "asset_sha256": sha,
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
            "invert": False, "gamma": 1.0, "auto_contrast": True,
            "overlay_alpha": 0.35, "overlay_visible": True, "rotation_deg": 0.0,
            "levels_black": 0, "levels_white": 65535, "levels_gamma": 1.0,
        },
        "overlay_ladder": None,
        "included_in_final": True,
    }


def _make_project_with_real_asset(ws: Workspace, tmp_path: Path) -> tuple[str, str]:
    asset_file = tmp_path / f"fake_image_{id(tmp_path)}.tif"
    asset_file.write_bytes(b"\x00\x01" * 8)
    sha, dest = ws.import_asset(str(asset_file))

    proj_path = ws.create_new_project("Archive Test Project")
    project = ws.load_project(str(proj_path))
    project.assets[sha] = AssetEntry(sha256=sha, stored_original_path=str(dest))
    project.panel.blots.append(Blot.model_validate(_minimal_blot_dict("blot_01", sha)))
    project.panel.layout.order.append("blot_01")
    ws.save_project(project)
    return project.project.id, sha


# ===========================================================================
# 1. Per-member cap: declared-honest oversized member is rejected
# ===========================================================================

class TestPerMemberCap:

    def test_oversized_member_rejected_no_file_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_module, "MAX_MEMBER_UNCOMPRESSED_BYTES", 100)

        sha = "a" * 64
        archive_path = tmp_path / "big.pbarchive"
        _write_archive(
            archive_path,
            _manifest(asset_sha256s=[sha]),
            {f"pbarchive/assets/{sha}/original.tif": os.urandom(1000)},
        )

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        result = dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert any("size" in e.lower() for e in result.integrity_errors)
        assert result.imported_asset_count == 0
        assert after == before, "a rejected member must leave no trace on disk"


# ===========================================================================
# 2. Declared size lies small; real content is large — must still be caught
# ===========================================================================

class TestLiedDeclaredSize:

    def test_understated_file_size_is_still_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_module, "MAX_MEMBER_UNCOMPRESSED_BYTES", 1000)

        sha = "b" * 64
        member_name = f"pbarchive/assets/{sha}/original.tif"
        real_content = os.urandom(50_000)  # far beyond the 1000-byte cap

        archive_path = tmp_path / "lied.pbarchive"
        _write_archive(archive_path, _manifest(asset_sha256s=[sha]), {member_name: real_content})

        # The central directory now claims this member is only 10 bytes —
        # comfortably under the 1000-byte cap — while the real compressed
        # data on disk still decompresses to the full 50,000 bytes.
        _lie_about_uncompressed_size(archive_path, member_name, 10)

        with zipfile.ZipFile(archive_path) as zf:
            assert zf.getinfo(member_name).file_size == 10, "sanity: the lie took"

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        result = dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert result.imported_asset_count == 0
        assert result.integrity_errors, "the lie must be caught, not silently accepted"
        assert after == before, "no file may be written for a member whose real size lied"


# ===========================================================================
# 3. Several individually-legal members exceed the aggregate cap
# ===========================================================================

class TestAggregateTotalCap:

    def test_total_exceeding_cap_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_module, "MAX_MEMBER_UNCOMPRESSED_BYTES", 10_000)
        monkeypatch.setattr(storage_module, "MAX_TOTAL_UNCOMPRESSED_BYTES", 25_000)

        shas = [hashlib.sha256(f"member{i}".encode()).hexdigest() for i in range(4)]
        members = {}
        for sha in shas:
            data = os.urandom(9_000)  # individually well under the 10,000 cap
            # Content must hash to its own path name for the asset to pass
            # the SHA check once read — use the real hash of the data instead.
            real_sha = hashlib.sha256(data).hexdigest()
            members[f"pbarchive/assets/{real_sha}/original.tif"] = data

        # 4 * 9000 = 36,000 > 25,000 total cap, even though each is individually legal.
        archive_path = tmp_path / "many.pbarchive"
        _write_archive(archive_path, _manifest(asset_sha256s=list(members)), members)

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        result = dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert any("total" in e.lower() for e in result.integrity_errors)
        assert result.imported_asset_count == 0
        assert after == before, "aggregate overflow must abort the whole import"


# ===========================================================================
# 4. Member-count cap: rejected before any member is read
# ===========================================================================

class TestMemberCountCap:

    def test_too_many_members_rejected_before_reading(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_module, "MAX_ARCHIVE_MEMBERS", 5)

        members = {f"pbarchive/junk/{i}.bin": b"x" for i in range(20)}
        archive_path = tmp_path / "swarm.pbarchive"
        _write_archive(archive_path, _manifest(), members)

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        with pytest.raises(ValueError, match="too many members"):
            dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert after == before


# ===========================================================================
# 5. Compression ratio cap
# ===========================================================================

class TestCompressionRatioCap:

    def test_high_ratio_member_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_module, "MAX_COMPRESSION_RATIO", 10)

        sha = "c" * 64
        # Highly compressible: a long run of zero bytes, real DEFLATE ratio
        # is easily in the thousands-to-one range.
        data = bytes(200_000)
        archive_path = tmp_path / "bomb.pbarchive"
        _write_archive(
            archive_path, _manifest(asset_sha256s=[sha]),
            {f"pbarchive/assets/{sha}/original.tif": data},
        )

        with zipfile.ZipFile(archive_path) as zf:
            info = zf.getinfo(f"pbarchive/assets/{sha}/original.tif")
            ratio = info.file_size / max(info.compress_size, 1)
            assert ratio > 10, "sanity: the fixture really does compress > 10:1"

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        result = dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert any("ratio" in e.lower() for e in result.integrity_errors)
        assert result.imported_asset_count == 0
        assert after == before


# ===========================================================================
# 5b. JSON members (manifest.json, project.json) are exempt from the ratio
#     check; binary assets are not.
#
# NOTE on the achieved ratio: a realistic, log-heavy project.json was
# measured (via zipfile.ZipFile.writestr(), the exact path export_archive()
# uses) to compress at ~200-230:1 regardless of entry count (tested from
# 4,000 up to 300,000 entries) or entry size. This is a hard ceiling from
# DEFLATE's match-length encoding (a match token covers at most 258 bytes,
# at roughly 1.5-2 encoded bytes per token), not a limitation of this
# fixture's construction — it does not climb toward 1000:1 no matter how
# large the log grows. That means a realistic project.json currently sits
# comfortably under the production MAX_COMPRESSION_RATIO=1000 on its own,
# so test_log_heavy_project_json_imports_with_production_constants below
# does not by itself prove the exemption is load-bearing at today's cap —
# it is a regression guard confirming log-heavy projects import cleanly,
# and it documents the real achievable ceiling for anyone tuning
# MAX_COMPRESSION_RATIO in the future (1000 has more headroom than the
# stage's own "several times higher" reasoning assumed).
# test_ratio_exemption_is_load_bearing exercises the exemption mechanism
# itself, with the cap patched below that ~200:1 ceiling.
# ===========================================================================

def _log_heavy_project_json_bytes(n_entries: int) -> bytes:
    """A project.json whose operation_log is large and highly repetitive —
    the realistic shape of a long-running project's log, not a synthetic
    zip-bomb payload."""
    from pysternblot.models import OperationLogEntry

    panel = _minimal_panel([])
    project = Project(
        project=ProjectMeta(id="p1", name="Log Heavy Project", created_utc="2024-01-01T00:00:00Z", app_version="0.1.0"),
        panel=panel,
    )
    sha = "e" * 64
    for _ in range(n_entries):
        project.operation_log.append(OperationLogEntry(
            timestamp_utc="2024-01-01T12:00:00Z",
            operation="levels_changed",
            target_type="blot",
            target_id="blot_01",
            asset_sha256=sha,
            field="display.levels_black",
            old_value=1000,
            new_value=1000,
        ))
    return project.model_dump_json(indent=2).encode("utf-8")


class TestJsonRatioExemption:

    def test_log_heavy_project_json_imports_with_production_constants(self, tmp_path):
        project_id = "p1"
        proj_bytes = _log_heavy_project_json_bytes(4000)
        proj_sha = hashlib.sha256(proj_bytes).hexdigest()

        archive_path = tmp_path / "logheavy.pbarchive"
        _write_archive(
            archive_path,
            _manifest(project_ids=[project_id], project_sha256s={project_id: proj_sha}),
            {f"pbarchive/projects/{project_id}/project.json": proj_bytes},
        )

        with zipfile.ZipFile(archive_path) as zf:
            info = zf.getinfo(f"pbarchive/projects/{project_id}/project.json")
            ratio = info.file_size / max(info.compress_size, 1)
        # Document the real, measured ceiling — see the module note above.
        assert ratio > 150, "sanity: the fixture is genuinely highly compressible"

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.integrity_errors == []
        assert result.imported_project_ids == [project_id]
        assert result.project_integrity_verified is True

    def test_ratio_exemption_is_load_bearing(self, tmp_path, monkeypatch):
        """With the cap patched below the ~200:1 a log-heavy project.json
        genuinely achieves, the same archive's asset member (same ratio,
        same cap) is rejected while the project.json member is not —
        proving check_ratio=False actually changes the outcome, not just
        that today's production cap happens not to bite."""
        monkeypatch.setattr(storage_module, "MAX_COMPRESSION_RATIO", 50)

        project_id = "p1"
        proj_bytes = _log_heavy_project_json_bytes(4000)
        proj_sha = hashlib.sha256(proj_bytes).hexdigest()

        asset_sha = "f" * 64
        asset_data = bytes(200_000)  # trivially > 50:1 too

        archive_path = tmp_path / "mixed.pbarchive"
        _write_archive(
            archive_path,
            _manifest(
                project_ids=[project_id], project_sha256s={project_id: proj_sha},
                asset_sha256s=[asset_sha],
            ),
            {
                f"pbarchive/projects/{project_id}/project.json": proj_bytes,
                f"pbarchive/assets/{asset_sha}/original.tif": asset_data,
            },
        )

        with zipfile.ZipFile(archive_path) as zf:
            proj_info = zf.getinfo(f"pbarchive/projects/{project_id}/project.json")
            proj_ratio = proj_info.file_size / max(proj_info.compress_size, 1)
        assert proj_ratio > 50, "sanity: project.json ratio exceeds the patched cap"

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.imported_project_ids == [project_id], "project.json must be exempt from the ratio cap"
        assert result.imported_asset_count == 0, "the asset must still be rejected by the same ratio cap"
        assert any("ratio" in e.lower() for e in result.integrity_errors)

    def test_project_json_still_bounded_by_absolute_size_cap(self, tmp_path, monkeypatch):
        """The ratio exemption must not become a blanket exemption: an
        oversized project.json is still rejected by MAX_MEMBER_UNCOMPRESSED_BYTES."""
        monkeypatch.setattr(storage_module, "MAX_MEMBER_UNCOMPRESSED_BYTES", 1000)

        project_id = "p1"
        # Highly compressible (so a ratio check, if mistakenly still active,
        # would also reject it) but the point here is the absolute cap alone.
        proj_bytes = b'{"padding": "' + b"z" * 5000 + b'"}'
        proj_sha = hashlib.sha256(proj_bytes).hexdigest()

        archive_path = tmp_path / "hugeproject.pbarchive"
        _write_archive(
            archive_path,
            _manifest(project_ids=[project_id], project_sha256s={project_id: proj_sha}),
            {f"pbarchive/projects/{project_id}/project.json": proj_bytes},
        )

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        result = dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert result.imported_project_ids == []
        assert any("size" in e.lower() for e in result.integrity_errors)
        assert after == before

    def test_oversized_manifest_rejected_independent_of_ratio(self, tmp_path, monkeypatch):
        """Uses near-incompressible content, so if a ratio check were
        mistakenly still applied to the manifest it would PASS — proving
        MAX_MANIFEST_BYTES alone, not the ratio cap, is what rejects it."""
        monkeypatch.setattr(storage_module, "MAX_MANIFEST_BYTES", 100)

        oversized_manifest = os.urandom(1000)  # incompressible padding
        archive_path = tmp_path / "hugemanifest_incompressible.pbarchive"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("pbarchive/manifest.json", oversized_manifest)

        with zipfile.ZipFile(archive_path) as zf:
            info = zf.getinfo("pbarchive/manifest.json")
            ratio = info.file_size / max(info.compress_size, 1)
        assert ratio < storage_module.MAX_COMPRESSION_RATIO, (
            "sanity: this payload would pass even an active ratio check"
        )

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        with pytest.raises(ValueError, match="manifest"):
            dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert after == before


# ===========================================================================
# 6. Oversized manifest rejected without reading further members
# ===========================================================================

class TestManifestSizeCap:

    def test_oversized_manifest_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_module, "MAX_MANIFEST_BYTES", 100)

        sha = "d" * 64
        archive_path = tmp_path / "hugemanifest.pbarchive"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Oversized manifest content — its own bytes don't even need to
            # be valid JSON, since the size check runs before any parsing.
            zf.writestr("pbarchive/manifest.json", b"x" * 1000)
            zf.writestr(f"pbarchive/assets/{sha}/original.tif", b"\x00" * 10)

        dst_ws = _make_workspace(tmp_path, "dest")
        before = _snapshot(dst_ws.root)
        with pytest.raises(ValueError, match="manifest"):
            dst_ws.import_archive(archive_path, "0.1.0")
        after = _snapshot(dst_ws.root)

        assert after == before


# ===========================================================================
# 7. A legitimate archive round-trips unchanged with production constants
# ===========================================================================

class TestProductionConstantsRoundTrip:

    def test_real_archive_still_imports_with_default_limits(self, tmp_path):
        # No monkeypatching here — this is the regression guard that the
        # real, shipped limits do not reject ordinary usage.
        src_ws = _make_workspace(tmp_path, "source")
        project_id, sha = _make_project_with_real_asset(src_ws, tmp_path)

        archive_path = tmp_path / "clean.pbarchive"
        src_ws.export_archive([project_id], archive_path, "0.1.0")

        dst_ws = _make_workspace(tmp_path, "dest")
        result = dst_ws.import_archive(archive_path, "0.1.0")

        assert result.integrity_errors == []
        assert result.imported_project_ids == [project_id]
        assert result.imported_asset_count == 1
        assert result.project_integrity_verified is True


# ===========================================================================
# 8. fetch_latest_release() caps the response body and never raises
# ===========================================================================

class TestUpdateCheckResponseCap:

    class _FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self, amt=None):
            return self._body if amt is None else self._body[:amt]

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def test_over_length_response_returns_none(self, monkeypatch):
        monkeypatch.setattr(update_check_module, "MAX_RESPONSE_BYTES", 50)
        # A body longer than the cap, still syntactically valid-ish JSON so a
        # failure here can only be the size guard, nothing else.
        oversized_body = json.dumps({"tag_name": "v9.9.9", "pad": "x" * 200}).encode()
        assert len(oversized_body) > 50

        monkeypatch.setattr(
            update_check_module.urllib.request, "urlopen",
            lambda *a, **k: self._FakeResponse(oversized_body),
        )
        result = update_check_module.fetch_latest_release()
        assert result is None

    def test_under_length_response_still_works(self, monkeypatch):
        monkeypatch.setattr(update_check_module, "MAX_RESPONSE_BYTES", 50)
        body = json.dumps({"tag_name": "v1.0.0"}).encode()
        assert len(body) <= 50

        monkeypatch.setattr(
            update_check_module.urllib.request, "urlopen",
            lambda *a, **k: self._FakeResponse(body),
        )
        assert update_check_module.fetch_latest_release() == "v1.0.0"


# ===========================================================================
# 9 & 10. Cache filename sanitisation
# ===========================================================================

def _minimal_panel(blots: list[Blot]) -> Panel:
    return Panel(
        lane_layout=LaneLayout(header_block=HeaderBlock(
            left_title="", groups=[Group(label="", n_lanes=1)], condition_rows=[ConditionRow(values=[""])],
        )),
        blots=blots, layout=Layout(order=[b.id for b in blots]),
    )


def _minimal_ladder() -> Ladder:
    return Ladder(
        lane_index=0, marker_set_id="ms1",
        calibration_points=[CalibrationPoint(y_px=50, kda=55), CalibrationPoint(y_px=120, kda=36)],
    )


class TestCacheFilenameSanitisation:

    def test_safe_cache_component_is_identity_for_well_formed_ids(self):
        for value in ["blot_01", "blot-02", "b.03", "BLOT_ABC123"]:
            assert _safe_cache_component(value) == value

    def test_safe_cache_component_falls_back_for_unsafe_ids(self):
        unsafe = "../../etc/passwd"
        result = _safe_cache_component(unsafe)
        assert result != unsafe
        assert "/" not in result
        assert result == hashlib.sha256(unsafe.encode("utf-8")).hexdigest()[:16]

    def test_normal_blot_id_produces_unchanged_cache_filename(self, tmp_path):
        """Regression guard: the sanitiser must be a no-op for ordinary ids,
        or every existing user's preview cache is orphaned on upgrade."""
        from pysternblot.image_utils import save_uint16_tiff
        import numpy as np

        ws = _make_workspace(tmp_path)
        arr = np.full((20, 20), 1000, dtype=np.uint16)
        src_path = tmp_path / "src.tif"
        save_uint16_tiff(arr, src_path)
        sha, dest = ws.import_asset(str(src_path))

        blot = Blot(
            id="blot_01", asset_sha256=sha, crop=Crop(x=0, y=0, w=20, h=20),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        panel = _minimal_panel([blot])

        out_path = ws.ensure_blot_crop_preview(blot, panel)
        assert out_path.name == "preview_crop_blot_01.tif", (
            "sanitiser must be transparent for a normal blot.id"
        )

    def test_path_separator_blot_id_stays_inside_assets_dir(self, tmp_path):
        from pysternblot.image_utils import save_uint16_tiff
        import numpy as np

        ws = _make_workspace(tmp_path)
        arr = np.full((20, 20), 1000, dtype=np.uint16)
        src_path = tmp_path / "src.tif"
        save_uint16_tiff(arr, src_path)
        sha, dest = ws.import_asset(str(src_path))

        malicious_id = "../../../etc/evil"
        blot = Blot(
            id=malicious_id, asset_sha256=sha, crop=Crop(x=0, y=0, w=20, h=20),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        panel = _minimal_panel([blot])

        out_path = ws.ensure_blot_crop_preview(blot, panel)

        assert out_path.resolve().is_relative_to(ws.assets_dir.resolve())
        assert out_path.exists()

        # The project as a whole must still open (save/load round trip)
        # despite the malformed blot.id — a fallback, not a rejection.
        project = Project(
            project=ProjectMeta(id="p1", name="t", created_utc="2024-01-01T00:00:00Z", app_version="0.1.0"),
            assets={sha: AssetEntry(sha256=sha, stored_original_path=str(dest))},
            panel=panel,
        )
        saved_path = ws.save_project(project)
        reloaded = ws.load_project(str(saved_path))
        assert reloaded.panel.blots[0].id == malicious_id
