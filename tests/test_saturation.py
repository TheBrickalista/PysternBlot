# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for saturation detection: pysternblot/image_utils.py's
compute_saturation_stats(), its wiring into import in
pysternblot/ui/project_io_mixin.py, and its reporting in
pysternblot/integrity.py.

Run from repo root:
    pytest tests/test_saturation.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from pysternblot.image_utils import compute_saturation_stats, save_uint16_tiff
from pysternblot.logchain import verify_log_chain
from pysternblot.models import AssetEntry, SaturationStats
from pysternblot.storage import Workspace
from pysternblot.ui import project_io_mixin as project_io_mixin_module
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


# ===========================================================================
# 1-4. compute_saturation_stats: pure erosion behaviour, no Qt required
# ===========================================================================

class TestComputeSaturationStats:

    def test_no_saturated_pixels(self):
        img = np.full((50, 50), 1000, dtype=np.uint16)
        stats = compute_saturation_stats(img, bit_depth=16)
        assert stats.saturated_count == 0
        assert stats.solid_saturated_count == 0
        assert stats.max_value == 1000
        assert stats.full_scale == 65535
        assert stats.total_pixels == 2500
        assert stats.saturated_fraction == 0.0

    def test_single_isolated_pixel_is_dust_not_solid(self):
        """The dust case: one hot pixel must not produce a solid-region count."""
        img = np.zeros((50, 50), dtype=np.uint16)
        img[25, 25] = 65535
        stats = compute_saturation_stats(img, bit_depth=16)
        assert stats.saturated_count == 1
        assert stats.solid_saturated_count == 0

    def test_solid_20x20_block_erodes_to_18x18_interior(self):
        """Exact-value guard on the 3x3 erosion: an 18x18 interior survives."""
        img = np.zeros((100, 100), dtype=np.uint16)
        img[10:30, 10:30] = 65535  # 20x20 block, padded away from image edges
        stats = compute_saturation_stats(img, bit_depth=16)
        assert stats.saturated_count == 400
        assert stats.solid_saturated_count == 18 * 18 == 324

    def test_one_pixel_wide_line_has_no_solid_region(self):
        img = np.zeros((50, 50), dtype=np.uint16)
        img[25, 10:40] = 65535
        stats = compute_saturation_stats(img, bit_depth=16)
        assert stats.saturated_count > 0
        assert stats.solid_saturated_count == 0

    def test_8bit_saturates_at_255_not_65535(self):
        img = np.zeros((30, 30), dtype=np.uint16)
        img[5:25, 5:25] = 255  # a solid block, but only up to 8-bit full scale
        stats = compute_saturation_stats(img, bit_depth=8)
        assert stats.full_scale == 255
        assert stats.saturated_count == 400
        assert stats.solid_saturated_count == 18 * 18 == 324

    def test_8bit_ignores_65535_values_above_255(self):
        """Sanity: an 8-bit assessment must not treat 65535 as saturated."""
        img = np.full((10, 10), 65535, dtype=np.uint16)
        stats = compute_saturation_stats(img, bit_depth=8)
        assert stats.saturated_count == 0

    def test_border_touching_block_still_erodes_correctly(self):
        """Border pixels are treated as not-saturated: a block touching the
        image edge loses that edge's row/column too, same as an interior block."""
        img = np.zeros((20, 20), dtype=np.uint16)
        img[:, :] = 65535  # saturated block fills the entire canvas
        stats = compute_saturation_stats(img, bit_depth=16)
        assert stats.saturated_count == 400
        assert stats.solid_saturated_count == 18 * 18 == 324


# ---------------------------------------------------------------------------
# Helpers for the import-wiring / report tests
# ---------------------------------------------------------------------------

def _make_main_window(tmp_path: Path) -> MainWindow:
    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    win = MainWindow(ws)
    return win


def _write_source_tiff(path: Path, arr: np.ndarray) -> None:
    save_uint16_tiff(arr, path)


def _import_via_ui(win: MainWindow, tmp_path: Path, src_path: Path):
    """Drive the real import_blot() UI handler headlessly.

    Bypasses new_project()'s QInputDialog.getText (a real modal prompt that
    blocks even under the offscreen QPA platform) by creating the project
    directly through the same Workspace call new_project() itself makes.
    """
    proj_path = win.workspace.create_new_project("Test Project")
    win.current_project = win.workspace.load_project(str(proj_path))

    with patch.object(
        project_io_mixin_module.QFileDialog, "getOpenFileName",
        return_value=(str(src_path), ""),
    ), patch.object(project_io_mixin_module.QMessageBox, "information"), \
       patch.object(project_io_mixin_module.QMessageBox, "critical") as mock_critical:
        win.import_blot()
    mock_critical.assert_not_called()
    return win.current_project


# ===========================================================================
# 6. Display settings never affect the stored (source-derived) stats
# ===========================================================================

class TestSourceOnlyComputation:

    def test_non_default_display_settings_do_not_change_stored_stats(self, qapp, tmp_path):
        arr = np.zeros((100, 100), dtype=np.uint16)
        arr[10:30, 10:30] = 65535  # solid 20x20 saturated block
        src_path = tmp_path / "src.tif"
        _write_source_tiff(src_path, arr)

        win = _make_main_window(tmp_path)
        project = _import_via_ui(win, tmp_path, src_path)

        blot = project.panel.blots[0]
        sha = blot.asset_sha256
        stored_before = project.assets[sha].saturation
        assert stored_before is not None
        assert stored_before.solid_saturated_count == 324

        # Mutate display settings drastically after import.
        blot.display.invert = True
        blot.display.levels_gamma = 2.7
        blot.display.gamma = 2.7
        blot.display.levels_black = 12000
        blot.display.levels_white = 40000
        blot.display.rotation_deg = 45.0

        stored_after = project.assets[sha].saturation
        assert stored_after == stored_before, (
            "changing display settings must never change the stored, "
            "source-derived saturation stats"
        )

        # And an independent recomputation on the raw stored file must
        # match exactly — the stats really do describe the source, not a
        # display-transformed view of it.
        from pysternblot.image_utils import load_image_as_uint16, get_bit_depth
        orig_path = win.workspace.asset_original_file(sha)
        recomputed = compute_saturation_stats(
            load_image_as_uint16(orig_path), get_bit_depth(orig_path)
        )
        assert recomputed == stored_after


# ===========================================================================
# 9. Import logs saturation_assessed and the chain stays "ok"
# ===========================================================================

class TestImportLogging:

    def test_saturation_assessed_logged_and_chain_ok(self, qapp, tmp_path):
        arr = np.full((40, 40), 5000, dtype=np.uint16)  # no saturation at all
        src_path = tmp_path / "clean.tif"
        _write_source_tiff(src_path, arr)

        win = _make_main_window(tmp_path)
        project = _import_via_ui(win, tmp_path, src_path)

        entries = [e for e in project.operation_log if e.operation == "saturation_assessed"]
        assert len(entries) == 1
        assert entries[0].field == "saturation"
        assert entries[0].asset_sha256 == project.panel.blots[0].asset_sha256

        chain = verify_log_chain(project)
        assert chain.status == "ok"

    def test_saturated_source_also_logs_and_chain_stays_ok(self, qapp, tmp_path):
        arr = np.zeros((60, 60), dtype=np.uint16)
        arr[5:25, 5:25] = 65535
        src_path = tmp_path / "saturated.tif"
        _write_source_tiff(src_path, arr)

        win = _make_main_window(tmp_path)
        project = _import_via_ui(win, tmp_path, src_path)

        entries = [e for e in project.operation_log if e.operation == "saturation_assessed"]
        assert len(entries) == 1
        assert entries[0].new_value["solid_saturated_count"] == 324

        assert verify_log_chain(project).status == "ok"


# ===========================================================================
# 7 & 8. Report rendering: "not assessed" wording, and crop-region
#         independence from whole-image
# ===========================================================================

class TestReportRendering:

    def _minimal_project_with_asset(self, tmp_path, ws, arr, crop_xywh, saturation):
        from pysternblot.models import (
            Blot, Crop, CropTemplate, Ladder, CalibrationPoint, ProteinLabel,
            Panel, HeaderBlock, Group, ConditionRow, Layout, Project, ProjectMeta,
            LaneLayout,
        )
        src_path = tmp_path / "src.tif"
        _write_source_tiff(src_path, arr)
        sha, dest = ws.import_asset(str(src_path))

        cx, cy, cw, ch = crop_xywh
        blot = Blot(
            id="b1", asset_sha256=sha, crop=Crop(x=cx, y=cy, w=cw, h=ch),
            ladder=Ladder(
                lane_index=0, marker_set_id="ms1",
                calibration_points=[CalibrationPoint(y_px=50, kda=55), CalibrationPoint(y_px=120, kda=36)],
            ),
            protein_label=ProteinLabel(text=""),
        )
        panel = Panel(
            lane_layout=LaneLayout(header_block=HeaderBlock(
                left_title="", groups=[Group(label="", n_lanes=1)], condition_rows=[ConditionRow(values=[""])],
            )),
            blots=[blot], layout=Layout(order=["b1"]),
            crop_template=CropTemplate(w=cw, h=ch),
        )
        project = Project(
            project=ProjectMeta(id="p1", name="t", created_utc="2024-01-01T00:00:00Z", app_version="0.1.0"),
            assets={sha: AssetEntry(sha256=sha, stored_original_path=str(dest), saturation=saturation)},
            panel=panel,
        )
        return project, sha

    def test_none_saturation_renders_not_assessed_never_none(self, tmp_path):
        from pysternblot.integrity import (
            build_integrity_report, build_detailed_integrity_report, write_integrity_html,
        )
        ws = Workspace(root=tmp_path / "ws")
        ws.ensure()

        arr = np.full((40, 40), 1000, dtype=np.uint16)
        project, sha = self._minimal_project_with_asset(
            tmp_path, ws, arr, crop_xywh=(0, 0, 40, 40), saturation=None,
        )

        report = build_integrity_report(project, ws)
        assert report["blots"][0]["source_image"]["saturation"] is None

        detailed = build_detailed_integrity_report(project, ws)
        html_path = write_integrity_html(detailed, tmp_path / "report.html")
        html = html_path.read_text()

        assert "Not assessed (imported by an earlier version)" in html
        # The word "none" must never stand in for an unassessed asset.
        assert "Whole image: None." not in html

    def test_crop_region_independent_of_whole_image(self, tmp_path):
        """A solid saturated region entirely outside the crop must report a
        whole-image warning but a clean crop region."""
        from pysternblot.integrity import build_integrity_report

        ws = Workspace(root=tmp_path / "ws")
        ws.ensure()

        arr = np.zeros((100, 100), dtype=np.uint16)
        arr[10:30, 10:30] = 65535  # solid block near the top-left corner

        whole_stats = compute_saturation_stats(arr, bit_depth=16)
        assert whole_stats.solid_saturated_count == 324

        # Crop far away from the saturated block.
        project, sha = self._minimal_project_with_asset(
            tmp_path, ws, arr, crop_xywh=(60, 60, 20, 20), saturation=whole_stats,
        )

        report = build_integrity_report(project, ws)
        src = report["blots"][0]["source_image"]

        assert src["saturation"]["solid_saturated_count"] == 324
        assert src["saturation_crop_region"]["saturated_count"] == 0
        assert src["saturation_crop_region"]["solid_saturated_count"] == 0

    def test_crop_region_warning_when_saturation_is_inside_crop(self, tmp_path):
        from pysternblot.integrity import build_integrity_report

        ws = Workspace(root=tmp_path / "ws")
        ws.ensure()

        arr = np.zeros((100, 100), dtype=np.uint16)
        arr[10:30, 10:30] = 65535

        whole_stats = compute_saturation_stats(arr, bit_depth=16)

        # Crop that fully contains the saturated block.
        project, sha = self._minimal_project_with_asset(
            tmp_path, ws, arr, crop_xywh=(0, 0, 100, 100), saturation=whole_stats,
        )

        report = build_integrity_report(project, ws)
        src = report["blots"][0]["source_image"]
        assert src["saturation_crop_region"]["solid_saturated_count"] == 324
