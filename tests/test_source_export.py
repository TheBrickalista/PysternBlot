# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for the source-file export handlers in pysternblot/ui/export_mixin.py:
export_current_source_asset() / export_all_source_assets().

These copy the stored source asset byte for byte (shutil.copyfile only) and
verify the written copy's SHA-256 before considering the export successful.
This is the regression guard for that guarantee — no library may touch the
bytes, and display settings must never leak into the exported file.

Run from repo root:
    pytest tests/test_source_export.py -v
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import zlib
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from pysternblot.logchain import verify_log_chain
from pysternblot.models import (
    AssetEntry,
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
    LaneLayout,
    Layout,
    Panel,
    Project,
    ProjectMeta,
    ProteinLabel,
)
from pysternblot.storage import Workspace
from pysternblot.ui import export_mixin as export_mixin_module
from pysternblot.ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Qt application singleton
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# Asset / project / window helpers
# ---------------------------------------------------------------------------

def _write_asset(ws_root: Path, data: bytes, ext: str) -> str:
    """Write *data* into the workspace's content-addressed asset store, as
    import_asset()/asset_original_file() expect: assets/<sha>/original.<ext>."""
    sha = hashlib.sha256(data).hexdigest()
    asset_dir = ws_root / "assets" / sha
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / f"original{ext}").write_bytes(data)
    return sha


def _encode_png_uint16(arr: np.ndarray) -> bytes:
    """Encode a 2-D uint16 array as a 16-bit grayscale PNG (no external libs) —
    a real, renderable image, needed only by the annotated-context comparison
    test, which must actually exercise build_provenance_scene()."""
    h, w = arr.shape
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)
    scanlines = bytearray()
    for row in arr:
        scanlines.append(0)
        scanlines.extend(row.astype(">u2").tobytes())
    idat = chunk(b"IDAT", zlib.compress(bytes(scanlines), 6))
    iend = chunk(b"IEND", b"")
    return sig + chunk(b"IHDR", ihdr) + idat + iend


def _minimal_ladder() -> Ladder:
    return Ladder(
        lane_index=0,
        marker_set_id="ms1",
        calibration_points=[
            CalibrationPoint(y_px=50, kda=55),
            CalibrationPoint(y_px=120, kda=36),
        ],
    )


def _minimal_project(blots: list[Blot], assets: dict[str, AssetEntry] | None = None) -> Project:
    n = len(blots) or 1
    header = HeaderBlock(
        left_title="kDa",
        groups=[Group(label="All", n_lanes=n)],
        condition_rows=[ConditionRow(values=[""] * n)],
    )
    panel = Panel(
        lane_layout=LaneLayout(header_block=header),
        blots=blots,
        layout=Layout(order=[b.id for b in blots]),
    )
    return Project(
        project=ProjectMeta(
            id="proj_test", name="Test", created_utc="2024-01-01T00:00:00Z", app_version="0.1.0",
        ),
        assets=assets or {},
        panel=panel,
    )


def _make_main_window(tmp_path: Path, project: Project) -> MainWindow:
    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    win = MainWindow(ws)
    win.current_project = project
    return win


def _patched_dialogs(save_path: str | None = None, folder: str | None = None):
    """Patch QFileDialog/QMessageBox in export_mixin so handlers run headless."""
    return (
        patch.object(
            export_mixin_module.QFileDialog, "getSaveFileName",
            return_value=(save_path or "", ""),
        ),
        patch.object(
            export_mixin_module.QFileDialog, "getExistingDirectory",
            return_value=folder or "",
        ),
        patch.object(export_mixin_module.QMessageBox, "information"),
        patch.object(export_mixin_module.QMessageBox, "critical"),
    )


# ===========================================================================
# 1 & 3. Byte-for-byte identity, including with non-default display settings
# ===========================================================================

class TestByteIdentity:

    def test_export_matches_stored_source_exactly(self, qapp, tmp_path):
        data = bytes(range(256)) * 40  # arbitrary, non-trivial binary content
        blot = Blot(
            id="blot_01", asset_sha256="", crop=Crop(x=0, y=0, w=64, h=64),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )

        ws_dir = tmp_path / "ws"
        sha = _write_asset(ws_dir, data, ".tif")
        blot.asset_sha256 = sha
        project = _minimal_project([blot], assets={
            sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.tif")),
        })

        win = _make_main_window(tmp_path, project)
        dest = tmp_path / "exported_source.tif"

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
        with p1, p2, p3, p4:
            win.export_current_source_asset()

        assert dest.exists()
        exported_bytes = dest.read_bytes()
        assert exported_bytes == data
        assert hashlib.sha256(exported_bytes).hexdigest() == sha

    def test_non_default_display_settings_do_not_affect_export(self, qapp, tmp_path):
        """Regression guard: display settings must never reach the source export."""
        data = os.urandom(4096)
        ws_dir = tmp_path / "ws"
        sha = _write_asset(ws_dir, data, ".tif")

        blot = Blot(
            id="blot_01", asset_sha256=sha, crop=Crop(x=0, y=0, w=64, h=64),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
            display=DisplaySettings(
                invert=True,
                gamma=2.2,
                levels_gamma=2.2,
                rotation_deg=90.0,
                levels_black=1000,
                levels_white=40000,
                auto_contrast=False,
            ),
        )
        project = _minimal_project([blot], assets={
            sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.tif")),
        })

        win = _make_main_window(tmp_path, project)
        dest = tmp_path / "exported_source.tif"

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
        with p1, p2, p3, p4:
            win.export_current_source_asset()

        assert dest.read_bytes() == data
        assert hashlib.sha256(dest.read_bytes()).hexdigest() == sha


# ===========================================================================
# 2. Source export must differ from the annotated-context export
# ===========================================================================

class TestDiffersFromAnnotatedContext:

    def test_source_and_annotated_context_exports_differ(self, qapp, tmp_path):
        w, h = 64, 64
        arr = np.full((h, w), 32768, dtype=np.uint16)
        png_bytes = _encode_png_uint16(arr)

        ws_dir = tmp_path / "ws"
        sha = _write_asset(ws_dir, png_bytes, ".png")

        blot = Blot(
            id="blot_01", asset_sha256=sha, crop=Crop(x=0, y=0, w=float(w), h=float(h)),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        project = _minimal_project([blot], assets={
            sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.png")),
        })
        project.panel.crop_template = CropTemplate(w=float(w), h=float(h))

        win = _make_main_window(tmp_path, project)

        source_dest = tmp_path / "source.png"
        annotated_dest = tmp_path / "annotated.tif"

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(source_dest))
        with p1, p2, p3, p4:
            win.export_current_source_asset()
        assert source_dest.exists()

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(annotated_dest))
        with p1, p2, p3, p4:
            win.export_current_original_tiff()
        assert annotated_dest.exists()

        assert source_dest.read_bytes() == png_bytes
        assert source_dest.read_bytes() != annotated_dest.read_bytes()


# ===========================================================================
# 4. 8-bit legacy source is exported unchanged (no promotion to 16-bit)
# ===========================================================================

class TestLegacy8BitSource:

    def test_8bit_source_exports_as_8bit_unchanged(self, qapp, tmp_path):
        ws_dir = tmp_path / "ws"
        src_png = tmp_path / "legacy_8bit.png"
        Image.new("L", (32, 32), color=77).save(str(src_png))
        data = src_png.read_bytes()

        assert Image.open(src_png).mode == "L"

        sha = _write_asset(ws_dir, data, ".png")
        blot = Blot(
            id="blot_01", asset_sha256=sha, crop=Crop(x=0, y=0, w=32, h=32),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        project = _minimal_project([blot], assets={
            sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.png")),
        })

        win = _make_main_window(tmp_path, project)
        dest = tmp_path / "exported_8bit.png"

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
        with p1, p2, p3, p4:
            win.export_current_source_asset()

        assert dest.read_bytes() == data
        assert Image.open(dest).mode == "L", "8-bit source must not be promoted to 16-bit"


# ===========================================================================
# 5. NIR blot: one file per channel, each matching its own channel's hash
# ===========================================================================

class TestNirPerChannelExport:

    def test_nir_blot_writes_one_verified_file_per_channel(self, qapp, tmp_path):
        ws_dir = tmp_path / "ws"
        data_685 = os.urandom(2048)
        data_785 = os.urandom(2048)
        sha_685 = _write_asset(ws_dir, data_685, ".tif")
        sha_785 = _write_asset(ws_dir, data_785, ".tif")

        blot = Blot(
            id="nir_blot", asset_sha256=sha_685, crop=Crop(x=0, y=0, w=64, h=64),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
            modality="nir_fluorescence",
            channels=[
                BlotChannel(asset_sha256=sha_685, channel_index=0, wavelength_nm=685),
                BlotChannel(asset_sha256=sha_785, channel_index=1, wavelength_nm=785),
            ],
        )
        project = _minimal_project([blot], assets={
            sha_685: AssetEntry(sha256=sha_685, stored_original_path=str(ws_dir / "assets" / sha_685 / "original.tif")),
            sha_785: AssetEntry(sha256=sha_785, stored_original_path=str(ws_dir / "assets" / sha_785 / "original.tif")),
        })

        win = _make_main_window(tmp_path, project)
        base_dest = tmp_path / "nir_blot_source.tif"

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(base_dest))
        with p1, p2, p3, p4:
            win.export_current_source_asset()

        ch0_path = tmp_path / "nir_blot_source_ch0_685nm.tif"
        ch1_path = tmp_path / "nir_blot_source_ch1_785nm.tif"

        assert ch0_path.exists()
        assert ch1_path.exists()
        assert ch0_path.read_bytes() == data_685
        assert ch1_path.read_bytes() == data_785
        assert hashlib.sha256(ch0_path.read_bytes()).hexdigest() == sha_685
        assert hashlib.sha256(ch1_path.read_bytes()).hexdigest() == sha_785


# ===========================================================================
# 6. Operation log entry per written file; chain stays "ok"
# ===========================================================================

class TestOperationLogAndChain:

    def test_source_asset_exported_entry_logged_and_chain_ok(self, qapp, tmp_path):
        data = os.urandom(1024)
        ws_dir = tmp_path / "ws"
        sha = _write_asset(ws_dir, data, ".tif")

        blot = Blot(
            id="blot_01", asset_sha256=sha, crop=Crop(x=0, y=0, w=64, h=64),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        project = _minimal_project([blot], assets={
            sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.tif")),
        })

        win = _make_main_window(tmp_path, project)
        dest = tmp_path / "exported.tif"

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
        with p1, p2, p3, p4:
            win.export_current_source_asset()

        entries = [
            e for e in win.current_project.operation_log
            if e.operation == "source_asset_exported"
        ]
        assert len(entries) == 1
        assert entries[0].target_id == "blot_01"
        assert entries[0].asset_sha256 == sha
        assert entries[0].field == "source_asset"

        chain = verify_log_chain(win.current_project)
        assert chain.status == "ok"

    def test_export_all_source_assets_logs_one_entry_per_blot(self, qapp, tmp_path):
        ws_dir = tmp_path / "ws"
        data1, data2 = os.urandom(512), os.urandom(512)
        sha1 = _write_asset(ws_dir, data1, ".tif")
        sha2 = _write_asset(ws_dir, data2, ".tif")

        blot1 = Blot(
            id="blot_01", asset_sha256=sha1, crop=Crop(x=0, y=0, w=64, h=64),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        blot2 = Blot(
            id="blot_02", asset_sha256=sha2, crop=Crop(x=0, y=0, w=64, h=64),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        project = _minimal_project([blot1, blot2], assets={
            sha1: AssetEntry(sha256=sha1, stored_original_path=str(ws_dir / "assets" / sha1 / "original.tif")),
            sha2: AssetEntry(sha256=sha2, stored_original_path=str(ws_dir / "assets" / sha2 / "original.tif")),
        })

        win = _make_main_window(tmp_path, project)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        p1, p2, p3, p4 = _patched_dialogs(folder=str(out_dir))
        with p1, p2, p3, p4:
            win.export_all_source_assets()

        entries = [
            e for e in win.current_project.operation_log
            if e.operation == "source_asset_exported"
        ]
        assert len(entries) == 2
        assert {e.target_id for e in entries} == {"blot_01", "blot_02"}
        assert verify_log_chain(win.current_project).status == "ok"


# ===========================================================================
# 7. A corrupted copy is caught, deleted, and reported — never accepted
# ===========================================================================

class TestCorruptionIsCaught:

    def test_corrupted_copy_is_deleted_and_handler_raises(self, qapp, tmp_path):
        data = os.urandom(1024)
        ws_dir = tmp_path / "ws"
        sha = _write_asset(ws_dir, data, ".tif")

        blot = Blot(
            id="blot_01", asset_sha256=sha, crop=Crop(x=0, y=0, w=64, h=64),
            ladder=_minimal_ladder(), protein_label=ProteinLabel(text=""),
        )
        project = _minimal_project([blot], assets={
            sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.tif")),
        })

        win = _make_main_window(tmp_path, project)
        dest = tmp_path / "corrupted_export.tif"

        def _corrupt_copy(src, dst):
            Path(dst).write_bytes(b"this is not the original file content at all")

        p1, p2, p3, p4 = _patched_dialogs(save_path=str(dest))
        with p1, p2, p3, p4 as mock_critical, \
             patch.object(export_mixin_module.shutil, "copyfile", side_effect=_corrupt_copy):
            win.export_current_source_asset()

        mock_critical.assert_called_once()
        assert not dest.exists(), "a failed verification must leave no file behind"

        entries = [
            e for e in win.current_project.operation_log
            if e.operation == "source_asset_exported"
        ]
        assert entries == [], "a rejected export must not be logged"
