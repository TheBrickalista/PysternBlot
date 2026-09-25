# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Tests for importing LI-COR Image Studio float16 TIFFs (Odyssey CLx and
similar instruments): the shared reader in pysternblot/image_utils.py
(load_tiff_source, bridge_float_to_uint16, get_source_bits), LI-COR tag
parsing in pysternblot/storage.py (parse_licor_metadata), the routing and
default-display-levels wiring in pysternblot/ui/project_io_mixin.py, and
sample_format/source_bits/not-assessable-saturation reporting in
pysternblot/integrity.py.

No lab data is committed for these tests -- every fixture is built entirely
in-process via tifffile, matching the real Odyssey CLx file's shape: float16
samples, 128x128 tiles, an uncompressed 4-page pyramid (page 0 full-res,
pages 1-3 NewSubfileType=1 reduced-resolution), and the LI-COR baseline tags
(DocumentName/Make/Model/Software/Artist/DateTime/XResolution/
YResolution/ResolutionUnit).

Run from repo root:
    pytest tests/test_licor_float_import.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import tifffile
from PIL import Image, UnidentifiedImageError
from PySide6.QtWidgets import QApplication

from pysternblot.image_utils import (
    bridge_float_to_uint16,
    get_bit_depth,
    get_source_bits,
    load_tiff_source,
    save_uint16_tiff,
)
from pysternblot.integrity import (
    build_integrity_report,
    build_detailed_integrity_report,
    write_integrity_html,
)
from pysternblot.models import AssetEntry, SaturationStats
from pysternblot.storage import Workspace, parse_licor_metadata, sha256_file
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


# ---------------------------------------------------------------------------
# Fixture builders -- synthetic files only, no lab data committed
# ---------------------------------------------------------------------------

def _write_licor_float_tiff(
    path: Path,
    *,
    h: int = 256,
    w: int = 256,
    channel: int | None = 700,
    include_datetime: bool = True,
    include_artist: bool = True,
    include_docname: bool = True,
    resolution_unit: str = "CENTIMETER",
    seed: int = 42,
    known_max: float = 46.7,
) -> np.ndarray:
    """
    Build a synthetic LI-COR Odyssey CLx-style float16 TIFF: 128x128 tiled,
    uncompressed, a 4-page pyramid (page 0 full-res; pages 1-3 reduced,
    NewSubfileType=1). Returns the full-resolution float32 array that was
    written (float16 precision, promoted for easy comparison in assertions).
    """
    rng = np.random.default_rng(seed)
    full = (rng.random((h, w)) * 40.0).astype(np.float16)
    full[h // 2, w // 2] = np.float16(known_max)

    with tifffile.TiffWriter(str(path)) as tf:
        for level in range(4):
            step = 2 ** level
            data = full[::step, ::step]
            kwargs: dict = dict(
                tile=(128, 128),
                photometric="minisblack",
                subfiletype=1 if level > 0 else 0,
                resolution=(59.1, 59.1),
                resolutionunit=resolution_unit,
            )
            if level == 0:
                extratags = [(271, "s", 0, "LI-COR, Inc.", True),
                             (272, "s", 0, "Odyssey CLx 1.0.11", True)]
                if include_docname:
                    docname = (
                        f"Image ID: 0000193 Channel: {channel}"
                        if channel is not None else "Image ID: 0000193"
                    )
                    extratags.append((269, "s", 0, docname, True))
                if include_artist:
                    extratags.append((315, "s", 0, "CLX-0684", True))
                kwargs["extratags"] = extratags
                kwargs["software"] = "Image Studio 3.1.4"
                if include_datetime:
                    kwargs["datetime"] = "2026:05:07 14:26:51"
            tf.write(data, **kwargs)

    return full.astype(np.float32)


def _write_legacy_licor_uint16_tiff(path: Path, *, value: int = 5000, channel: int = 800) -> None:
    """A pre-existing Odyssey 16-bit uint TIFF style file -- Pillow-openable,
    single page, carrying the same LI-COR baseline tags."""
    arr = np.full((64, 64), value, dtype=np.uint16)
    tifffile.imwrite(
        str(path), arr, photometric="minisblack",
        resolution=(59.1, 59.1), resolutionunit="CENTIMETER",
        extratags=[
            (269, "s", 0, f"Image ID: 0000042 Channel: {channel}", True),
            (271, "s", 0, "LI-COR, Inc.", True),
            (272, "s", 0, "Odyssey CLx 1.0.11", True),
            (315, "s", 0, "CLX-0684", True),
        ],
        software="Image Studio 3.1.4",
        datetime="2020:01:01 00:00:00",
    )


def _write_non_licor_uint16_tiff(path: Path, *, value: int = 5000) -> None:
    arr = np.full((64, 64), value, dtype=np.uint16)
    save_uint16_tiff(arr, path)


def _make_workspace(tmp_path: Path) -> Workspace:
    ws = Workspace(root=tmp_path / "ws")
    ws.ensure()
    return ws


# ===========================================================================
# 1. Shared reader: routing, pyramid handling, dtype promotion
# ===========================================================================

class TestLoadTiffSourceOnLicorFixture:

    def test_pillow_cannot_open_the_tiled_float16_fixture(self, tmp_path):
        """Sanity check on the premise of the whole bug: confirms Pillow
        really does raise on this exact shape, so load_tiff_source's
        Pillow-first/tifffile-fallback routing is actually exercised."""
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path)
        with pytest.raises((UnidentifiedImageError, OSError)):
            with Image.open(str(path)) as im:
                im.load()

    def test_reads_full_resolution_page_only(self, tmp_path):
        path = tmp_path / "licor.tif"
        full = _write_licor_float_tiff(path, h=256, w=256)

        arr, source_dtype = load_tiff_source(path)

        assert source_dtype == "float16"
        assert arr.dtype == np.float32
        assert arr.shape == (256, 256)
        np.testing.assert_array_equal(arr, full)

    def test_never_reads_pyramid_levels_1_to_3(self, tmp_path):
        """A regression guard for the exact bug class this fix targets: a
        naive `pages[-1]` or `series[0].pages[k]` read would silently return
        a downsampled level. Level 0 must have a different shape from the
        other levels for this to be a meaningful assertion."""
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path, h=256, w=256)

        with tifffile.TiffFile(str(path)) as tif:
            levels = tif.series[0].levels
            assert len(levels) == 4
            assert levels[0].pages[0].shape == (256, 256)
            assert levels[1].pages[0].shape == (128, 128)
            assert levels[3].pages[0].shape == (32, 32)

        arr, _ = load_tiff_source(path)
        assert arr.shape == (256, 256)

    def test_get_bit_depth_is_32_for_float_source(self, tmp_path):
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path)
        assert get_bit_depth(path) == 32

    def test_get_source_bits_is_16_true_on_disk_width(self, tmp_path):
        """The true on-disk BitsPerSample (16 for float16), never the 32 the
        in-memory array is promoted to."""
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path)
        assert get_source_bits(path) == 16
        assert get_bit_depth(path) == 32  # confirms these are deliberately different

    def test_no_nan_or_inf_in_well_formed_fixture(self, tmp_path):
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path)
        arr, _ = load_tiff_source(path)
        assert np.isfinite(arr).all()

    def test_known_max_pixel_round_trips(self, tmp_path):
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path, known_max=46.7)
        arr, _ = load_tiff_source(path)
        # float16 cannot represent 46.7 exactly; assert close, not equal.
        assert arr.max() == pytest.approx(46.7, abs=0.05)


# ===========================================================================
# 2. LI-COR metadata parsing
# ===========================================================================

class TestParseLicorMetadata:

    def test_float_source_full_metadata(self, tmp_path):
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path, channel=700)

        meta = parse_licor_metadata(path)

        assert meta["channel"] == 700
        assert meta["model"] == "Odyssey CLx 1.0.11"
        assert meta["software"] == "Image Studio 3.1.4"
        assert meta["instrument_serial"] == "CLX-0684"
        assert meta["datetime"] == "2026:05:07 14:26:51"
        assert meta["pixel_size_um"] == pytest.approx(169.2, abs=0.5)

    def test_missing_tags_leave_fields_out_not_crash(self, tmp_path):
        path = tmp_path / "licor_partial.tif"
        _write_licor_float_tiff(
            path, include_datetime=False, include_artist=False, include_docname=False,
        )

        meta = parse_licor_metadata(path)

        assert "channel" not in meta
        assert "instrument_serial" not in meta
        assert "datetime" not in meta
        # Fields whose tags ARE present must still come through.
        assert meta["model"] == "Odyssey CLx 1.0.11"
        assert meta["software"] == "Image Studio 3.1.4"

    def test_inch_resolution_unit_converted_correctly(self, tmp_path):
        path = tmp_path / "licor_inch.tif"
        _write_licor_float_tiff(path, resolution_unit="INCH")
        meta = parse_licor_metadata(path)
        # 25400 / 59.1 um/px
        assert meta["pixel_size_um"] == pytest.approx(25400.0 / 59.1, abs=0.5)

    def test_non_licor_file_returns_empty_dict(self, tmp_path):
        path = tmp_path / "plain.tif"
        _write_non_licor_uint16_tiff(path)
        assert parse_licor_metadata(path) == {}

    def test_non_tiff_file_returns_empty_dict_never_raises(self, tmp_path):
        path = tmp_path / "not_a_tiff.tif"
        path.write_bytes(b"not a tiff at all")
        assert parse_licor_metadata(path) == {}

    def test_legacy_uint16_odyssey_file_also_parses(self, tmp_path):
        """The related open issue this task also closes: older Odyssey
        16-bit uint TIFFs must carry channel metadata too, not just the new
        float16 files."""
        path = tmp_path / "legacy.tif"
        _write_legacy_licor_uint16_tiff(path, channel=800)

        # Confirm this file IS Pillow-openable (the "legacy" path), then
        # confirm metadata still comes through via the same function.
        with Image.open(str(path)) as im:
            assert im.mode in ("I;16", "I;16L", "I;16B")

        meta = parse_licor_metadata(path)
        assert meta["channel"] == 800
        assert meta["instrument_serial"] == "CLX-0684"


# ===========================================================================
# 3. Bridge edge cases (point 9) -- pure array tests, no file needed
# ===========================================================================

class TestBridgeFloatToUint16EdgeCases:

    def test_normal_case_scale_factor_and_values(self):
        arr = np.array([[0.0, 10.0], [20.0, 40.0]], dtype=np.float32)
        out, info = bridge_float_to_uint16(arr, "float32")

        assert info["scale_factor"] == pytest.approx(65535.0 / 40.0)
        assert out[0, 0] == 0
        assert out[1, 1] == 65535
        assert info["source_min"] == 0.0
        assert info["source_max"] == 40.0
        assert info["nonfinite_count"] == 0
        assert info["negative_clipped_count"] == 0
        assert info["method"] == "linear_scale_to_max"
        assert info["source_dtype"] == "float32"

    def test_all_zero_source_max_le_zero_no_division(self):
        arr = np.zeros((4, 4), dtype=np.float32)
        out, info = bridge_float_to_uint16(arr, "float32")
        assert info["scale_factor"] is None
        assert np.all(out == 0)

    def test_all_negative_source_max_le_zero_no_division(self):
        arr = np.full((4, 4), -5.0, dtype=np.float32)
        out, info = bridge_float_to_uint16(arr, "float32")
        assert info["scale_factor"] is None
        assert np.all(out == 0)
        # Still must disclose the clip, even though scale_factor is None.
        assert info["negative_clipped_count"] == 16
        assert info["source_min"] == -5.0

    def test_nan_and_inf_mapped_to_zero_and_counted(self):
        arr = np.array([[1.0, np.nan], [np.inf, -np.inf]], dtype=np.float32)
        out, info = bridge_float_to_uint16(arr, "float32")

        assert info["nonfinite_count"] == 3
        assert out[0, 1] == 0
        assert out[1, 0] == 0
        assert out[1, 1] == 0
        # The one finite value (1.0) is unaffected by the others being NaN/Inf.
        assert out[0, 0] == 65535  # 1.0 is also the max of the finite values

    def test_negative_values_clipped_not_silently(self):
        arr = np.array([[-10.0, 0.0], [50.0, 100.0]], dtype=np.float32)
        out, info = bridge_float_to_uint16(arr, "float32")

        assert out[0, 0] == 0  # clipped, never negative/wrapped
        assert info["negative_clipped_count"] == 1
        assert info["source_min"] == -10.0
        assert info["source_max"] == 100.0

    def test_rejects_non_float32_input(self):
        arr = np.zeros((4, 4), dtype=np.uint16)
        with pytest.raises(TypeError):
            bridge_float_to_uint16(arr, "uint16")

    def test_zero_always_maps_to_zero(self):
        arr = np.array([[0.0, 1.0], [2.0, 4.0]], dtype=np.float32)
        out, _info = bridge_float_to_uint16(arr, "float32")
        assert out[0, 0] == 0


# ===========================================================================
# 4. Saturation is not-assessable for float sources (point 2 and 3)
# ===========================================================================

class TestFloatSaturationNotAssessable:

    def test_assess_asset_on_import_returns_not_assessable(self, tmp_path):
        from pysternblot.ui.project_io_mixin import _assess_asset_on_import

        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path, known_max=46.7)

        saturation, float_display_scale, bridged = _assess_asset_on_import(path, bit_depth=32)

        assert saturation.assessable is False
        assert saturation.full_scale is None
        assert saturation.saturated_count is None
        assert saturation.saturated_fraction is None
        assert saturation.solid_saturated_count is None
        assert saturation.total_pixels == 256 * 256
        # The real float source max, never a placeholder zero.
        assert saturation.max_value == pytest.approx(46.7, abs=0.05)

        assert float_display_scale is not None
        assert float_display_scale["method"] == "linear_scale_to_max"
        assert bridged is not None
        assert bridged.dtype == np.uint16
        # The bridged array legitimately contains 65535 by construction --
        # this is exactly the value that must never be fed to a saturation
        # test, which is why _assess_asset_on_import computes saturation
        # from the true float array instead.
        assert bridged.max() == 65535

    def test_crop_region_saturation_via_integrity_is_not_assessable(self, tmp_path, qapp):
        """Point 2's explicit required test: a float fixture crop region
        must report not_assessable, never saturated, even though the
        bridged array has pixels at 65535 within the crop."""
        from pysternblot.integrity import _asset_info, _saturation_crop_message

        ws = _make_workspace(tmp_path)
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path, h=256, w=256, known_max=46.7)
        sha, dest = ws.import_asset(str(path))

        from pysternblot.ui.project_io_mixin import _assess_asset_on_import
        saturation, float_display_scale, _bridged = _assess_asset_on_import(dest, bit_depth=32)

        from pysternblot.models import (
            AssetEntry, Blot, Crop, CropTemplate, Ladder, CalibrationPoint,
            ProteinLabel, Panel, HeaderBlock, Group, ConditionRow, Layout,
            Project, ProjectMeta, LaneLayout,
        )
        blot = Blot(
            id="b1", asset_sha256=sha, crop=Crop(x=0, y=0, w=256, h=256),
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
            crop_template=CropTemplate(w=256, h=256),
        )
        project = Project(
            project=ProjectMeta(id="p1", name="t", created_utc="2024-01-01T00:00:00Z", app_version="0.1.0"),
            assets={sha: AssetEntry(
                sha256=sha, stored_original_path=str(dest), saturation=saturation,
                float_display_scale=float_display_scale,
            )},
            panel=panel,
        )

        info = _asset_info(ws, project, sha, crop_rect=(0, 0, 256, 256))

        assert info["saturation"]["assessable"] is False
        assert info["saturation_crop_region"]["assessable"] is False
        severity, message = _saturation_crop_message(info["saturation_crop_region"])
        assert severity == "not_assessable"
        assert "saturated" not in message.lower()

    def test_saturation_message_wording_for_not_assessable(self):
        from pysternblot.integrity import _saturation_message

        stats = SaturationStats(max_value=46.7, total_pixels=100, assessable=False)
        severity, message = _saturation_message(stats.model_dump())
        assert severity == "not_assessable"
        assert "not assessable" in message.lower()


# ===========================================================================
# 5. Both import paths load the fixture end to end
# ===========================================================================

def _import_blot_via_ui(win: MainWindow, src_path: Path):
    proj_path = win.workspace.create_new_project("LI-COR Test")
    win.current_project = win.workspace.load_project(str(proj_path))

    with patch.object(
        project_io_mixin_module.QFileDialog, "getOpenFileName",
        return_value=(str(src_path), ""),
    ), patch.object(project_io_mixin_module.QMessageBox, "information"), \
       patch.object(project_io_mixin_module.QMessageBox, "critical") as mock_critical:
        win.import_blot()
    mock_critical.assert_not_called()
    return win.current_project


class TestBothImportPathsLoadLicorFixture:

    def test_import_blot_path(self, qapp, tmp_path):
        ws = _make_workspace(tmp_path)
        win = MainWindow(ws)

        src_path = tmp_path / "licor.tif"
        _write_licor_float_tiff(src_path, channel=700, known_max=46.7)

        project = _import_blot_via_ui(win, src_path)

        blot = project.panel.blots[0]
        asset = project.assets[blot.asset_sha256]

        assert asset.acquisition_metadata is not None
        assert asset.acquisition_metadata["channel"] == 700
        assert asset.acquisition_metadata["model"] == "Odyssey CLx 1.0.11"

        assert asset.saturation is not None
        assert asset.saturation.assessable is False
        assert asset.saturation.max_value == pytest.approx(46.7, abs=0.05)

        assert asset.float_display_scale is not None
        assert asset.float_display_scale["method"] == "linear_scale_to_max"

        # Default display levels come from percentiles of the BRIDGED array,
        # not a fixed 0..65535 span with no relation to this source.
        assert 0 <= blot.display.levels_black < blot.display.levels_white <= 65535
        assert blot.display.levels_white < 65535 or blot.display.levels_black > 0

    def test_import_nir_blot_typhoon_path(self, tmp_path):
        ws = _make_workspace(tmp_path)
        proj_path = ws.create_new_project("LI-COR NIR Test")
        project = ws.load_project(str(proj_path))

        src_path = tmp_path / "licor_ch700.tif"
        _write_licor_float_tiff(src_path, channel=700, known_max=46.7)

        channels, acq_meta = ws.import_nir_blot_typhoon([src_path], project)

        assert len(channels) == 1
        sha = channels[0].asset_sha256
        assert sha in acq_meta
        assert acq_meta[sha]["channel"] == 700
        assert acq_meta[sha]["instrument_serial"] == "CLX-0684"

    def test_legacy_uint16_odyssey_channel_metadata_now_carried_over(self, tmp_path):
        """The related open issue closed by this task: an older Odyssey
        16-bit uint TIFF must have its channel metadata attached via the NIR
        import path too."""
        ws = _make_workspace(tmp_path)
        proj_path = ws.create_new_project("Legacy NIR Test")
        project = ws.load_project(str(proj_path))

        src_path = tmp_path / "legacy_ch800.tif"
        _write_legacy_licor_uint16_tiff(src_path, channel=800)

        channels, acq_meta = ws.import_nir_blot_typhoon([src_path], project)

        sha = channels[0].asset_sha256
        assert acq_meta[sha]["channel"] == 800


# ===========================================================================
# 6. Source hash is always the original file's raw bytes
# ===========================================================================

class TestSourceHashIsRawBytes:

    def test_import_asset_digest_matches_raw_file_bytes(self, tmp_path):
        ws = _make_workspace(tmp_path)
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path)

        raw_bytes = path.read_bytes()
        expected = hashlib.sha256(raw_bytes).hexdigest()

        digest, dest = ws.import_asset(str(path))

        assert digest == expected
        assert sha256_file(str(dest)) == expected
        # The stored copy's bytes are identical to the source's, not a
        # re-encoded/decoded version of the same pixel data.
        assert dest.read_bytes() == raw_bytes


# ===========================================================================
# 7. Integrity report: sample_format, source_bits, and not-assessable wiring
# ===========================================================================

class TestIntegrityReportFloatFields:

    def _project_with_licor_asset(self, tmp_path, ws):
        from pysternblot.models import (
            AssetEntry, Blot, Crop, CropTemplate, Ladder, CalibrationPoint,
            ProteinLabel, Panel, HeaderBlock, Group, ConditionRow, Layout,
            Project, ProjectMeta, LaneLayout,
        )
        from pysternblot.ui.project_io_mixin import _assess_asset_on_import

        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path, h=256, w=256, known_max=46.7)
        sha, dest = ws.import_asset(str(path))

        saturation, float_display_scale, _bridged = _assess_asset_on_import(dest, bit_depth=32)

        blot = Blot(
            id="b1", asset_sha256=sha, crop=Crop(x=0, y=0, w=256, h=256),
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
            crop_template=CropTemplate(w=256, h=256),
        )
        project = Project(
            project=ProjectMeta(id="p1", name="t", created_utc="2024-01-01T00:00:00Z", app_version="0.1.0"),
            assets={sha: AssetEntry(
                sha256=sha, stored_original_path=str(dest), saturation=saturation,
                float_display_scale=float_display_scale,
                acquisition_metadata=parse_licor_metadata(dest) or None,
            )},
            panel=panel,
        )
        return project

    def test_report_includes_sample_format_and_true_source_bits(self, tmp_path):
        ws = _make_workspace(tmp_path)
        project = self._project_with_licor_asset(tmp_path, ws)

        report = build_integrity_report(project, ws)
        src = report["blots"][0]["source_image"]

        assert src["sample_format"] == "float"
        assert src["source_bits"] == 16       # true on-disk width, never 32
        assert src["bit_depth"] == 32          # promoted in-memory depth

    def test_html_renders_not_assessable_with_no_placeholder_zeros(self, tmp_path):
        ws = _make_workspace(tmp_path)
        project = self._project_with_licor_asset(tmp_path, ws)

        detailed = build_detailed_integrity_report(project, ws)
        html_path = write_integrity_html(detailed, tmp_path / "report.html")
        html = html_path.read_text()

        assert "not assessable" in html.lower()
        assert "float" in html.lower()

    def test_negative_clip_warning_surfaces_in_report(self, tmp_path):
        """Point 9: negative-value clipping must be flagged in the
        integrity report, not just recorded silently in float_display_scale."""
        from pysternblot.models import (
            AssetEntry, Blot, Crop, CropTemplate, Ladder, CalibrationPoint,
            ProteinLabel, Panel, HeaderBlock, Group, ConditionRow, Layout,
            Project, ProjectMeta, LaneLayout,
        )

        ws = _make_workspace(tmp_path)
        path = tmp_path / "licor.tif"
        _write_licor_float_tiff(path, h=64, w=64)
        sha, dest = ws.import_asset(str(path))

        arr, source_dtype = load_tiff_source(dest)
        arr = arr.copy()
        arr[0, 0] = -3.0  # inject a negative value to trigger the clip path
        _bridged, scale_info = bridge_float_to_uint16(arr, source_dtype)
        assert scale_info["negative_clipped_count"] == 1

        saturation = SaturationStats(max_value=float(arr.max()), total_pixels=int(arr.size), assessable=False)

        blot = Blot(
            id="b1", asset_sha256=sha, crop=Crop(x=0, y=0, w=64, h=64),
            ladder=Ladder(
                lane_index=0, marker_set_id="ms1",
                calibration_points=[CalibrationPoint(y_px=10, kda=55), CalibrationPoint(y_px=20, kda=36)],
            ),
            protein_label=ProteinLabel(text=""),
        )
        panel = Panel(
            lane_layout=LaneLayout(header_block=HeaderBlock(
                left_title="", groups=[Group(label="", n_lanes=1)], condition_rows=[ConditionRow(values=[""])],
            )),
            blots=[blot], layout=Layout(order=["b1"]),
            crop_template=CropTemplate(w=64, h=64),
        )
        project = Project(
            project=ProjectMeta(id="p1", name="t", created_utc="2024-01-01T00:00:00Z", app_version="0.1.0"),
            assets={sha: AssetEntry(
                sha256=sha, stored_original_path=str(dest), saturation=saturation,
                float_display_scale=scale_info,
            )},
            panel=panel,
        )

        report = build_integrity_report(project, ws)
        src = report["blots"][0]["source_image"]
        assert src["float_scale_warning"] is not None
        assert "1" in src["float_scale_warning"]

        detailed = build_detailed_integrity_report(project, ws)
        html_path = write_integrity_html(detailed, tmp_path / "report2.html")
        html = html_path.read_text()
        assert "clipped" in html.lower()


# ===========================================================================
# 8. Regression: existing uint16/uint8 imports are unaffected (point 8)
# ===========================================================================

class TestUint16ImportUnaffected:

    def test_uint16_import_default_levels_are_full_scale_not_percentile(self, qapp, tmp_path):
        ws = _make_workspace(tmp_path)
        win = MainWindow(ws)

        src_path = tmp_path / "plain16.tif"
        arr = np.full((64, 64), 5000, dtype=np.uint16)
        save_uint16_tiff(arr, src_path)

        project = _import_blot_via_ui(win, src_path)
        blot = project.panel.blots[0]

        assert blot.display.levels_black == 0
        assert blot.display.levels_white == 65535

    def test_uint16_saturation_still_fully_assessable(self, qapp, tmp_path):
        ws = _make_workspace(tmp_path)
        win = MainWindow(ws)

        src_path = tmp_path / "plain16.tif"
        arr = np.zeros((64, 64), dtype=np.uint16)
        arr[10:30, 10:30] = 65535
        save_uint16_tiff(arr, src_path)

        project = _import_blot_via_ui(win, src_path)
        blot = project.panel.blots[0]
        asset = project.assets[blot.asset_sha256]

        assert asset.saturation.assessable is True
        assert asset.saturation.full_scale == 65535
        assert asset.saturation.solid_saturated_count == 18 * 18
        assert asset.float_display_scale is None


# ===========================================================================
# 9. main_window saturation badge is None/not-assessable safe
# ===========================================================================

class TestSaturationBadgeNoneSafe:

    def test_badge_hidden_for_not_assessable_float_source(self, qapp, tmp_path):
        ws = _make_workspace(tmp_path)
        win = MainWindow(ws)

        src_path = tmp_path / "licor.tif"
        _write_licor_float_tiff(src_path, known_max=46.7)

        project = _import_blot_via_ui(win, src_path)
        blot = project.panel.blots[0]

        win.active_blot_id = blot.id
        win._update_prov_label()  # must not raise on None solid_saturated_count

        assert win.prov_saturation_badge.isVisible() is False


# ===========================================================================
# 10. v1.2.0-format project: hashed content must be unchanged by the model
#     changes (SaturationStats.max_value type, new optional fields)
# ===========================================================================

def _independent_entry_hash(entry: dict) -> str:
    """Re-implements logchain's canonical hashing from first principles, so
    the fixture's hashes do not depend on the code under test."""
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestV120ProjectStillVerifies:

    def _write_v120_project(self, ws: Workspace, tmp_path: Path):
        from pysternblot.logchain import GENESIS_HASH

        proj_path = ws.create_new_project("v1.2.0 fixture", app_version="1.2.0")
        data = json.loads(Path(proj_path).read_text(encoding="utf-8"))

        sha = "a" * 64
        # Exactly what v1.2.0 wrote: int max_value, no `assessable`, no
        # `float_display_scale` keys.
        old_saturation = {
            "max_value": 65535, "full_scale": 65535, "saturated_count": 400,
            "total_pixels": 10000, "saturated_fraction": 0.04,
            "solid_saturated_count": 324,
        }
        data["assets"] = {sha: {
            "sha256": sha, "stored_original_path": "x", "original_source_path": None,
            "stored_preview_path": None, "acquisition_metadata": None,
            "saturation": old_saturation,
        }}

        log = []
        prev = GENESIS_HASH
        for i, (op, new_value) in enumerate([
            ("saturation_assessed", old_saturation),
            ("blot_imported", {"blot_id": "blot_01"}),
        ]):
            entry = {
                "timestamp_utc": f"2026-01-0{i + 1}T00:00:00+00:00", "operation": op,
                "target_type": "asset", "target_id": sha, "asset_sha256": sha,
                "field": "saturation", "old_value": None, "new_value": new_value,
                "note": None, "prev_hash": prev,
            }
            entry["entry_hash"] = _independent_entry_hash(entry)
            prev = entry["entry_hash"]
            log.append(entry)
        data["operation_log"] = log
        Path(proj_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return proj_path

    def test_loads_verifies_saves_reloads_and_stays_ok(self, tmp_path):
        from pysternblot.logchain import verify_log_chain

        ws = _make_workspace(tmp_path)
        proj_path = self._write_v120_project(ws, tmp_path)

        project = ws.load_project(str(proj_path))
        assert verify_log_chain(project).status == "ok"
        assert verify_log_chain(project).n_chained == 2

        ws.save_project(project)
        reloaded = ws.load_project(str(proj_path))
        assert verify_log_chain(reloaded).status == "ok"

    def test_uint_max_value_still_serializes_as_int(self, tmp_path):
        ws = _make_workspace(tmp_path)
        proj_path = self._write_v120_project(ws, tmp_path)

        project = ws.load_project(str(proj_path))
        ws.save_project(project)

        saved_text = Path(proj_path).read_text(encoding="utf-8")
        saved = json.loads(saved_text)
        sat = saved["assets"]["a" * 64]["saturation"]
        assert sat["max_value"] == 65535
        assert isinstance(sat["max_value"], int)
        assert '"max_value": 65535,' in saved_text or '"max_value": 65535\n' in saved_text

    def test_new_uint_import_log_entry_serializes_int_max_value(self):
        from pysternblot.image_utils import compute_saturation_stats
        stats = compute_saturation_stats(np.full((4, 4), 1000, dtype=np.uint16), 16)
        assert isinstance(stats.model_dump()["max_value"], int)
        assert '"max_value":1000,' in stats.model_dump_json()

    def test_float_max_value_still_serializes_as_float(self):
        stats = SaturationStats(max_value=46.7, total_pixels=4, assessable=False)
        assert stats.model_dump()["max_value"] == 46.7


class TestBridgeIsScaleOnly:

    def test_no_min_subtraction_when_min_is_positive(self):
        arr = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)
        out, info = bridge_float_to_uint16(arr, "float32")
        # uint16 = round(v * 65535 / max): the source minimum (10) must NOT
        # map to 0, or proportionality (and any ratio between pixels) is lost.
        assert out.tolist() == [[16384, 32768], [49151, 65535]]
        assert out[0, 0] != 0
        assert info["scale_factor"] == pytest.approx(65535.0 / 40.0)


# ===========================================================================
# 11. LI-COR channel label (NIR radio) and integrity HTML acquisition cell
# ===========================================================================

TESTS_DIR = Path(__file__).parent


def _radio_labels(win: MainWindow, blot) -> list[str]:
    from PySide6.QtWidgets import QRadioButton
    win._rebuild_nir_channel_selector(blot)
    return [
        win._nir_ch_layout.itemAt(i).widget().text()
        for i in range(win._nir_ch_layout.count())
        if isinstance(win._nir_ch_layout.itemAt(i).widget(), QRadioButton)
    ]


def _nir_blot(channels):
    from pysternblot.models import Blot
    return Blot.model_validate({
        "id": "b1", "asset_sha256": channels[0].asset_sha256, "modality": "nir_fluorescence",
        "channels": [c.model_dump() for c in channels],
        "crop": {"x": 0, "y": 0, "w": 10, "h": 10},
        "ladder": {"lane_index": 0, "marker_set_id": "ms1", "calibration_points": [
            {"y_px": 1, "kda": 55}, {"y_px": 2, "kda": 36}]},
        "protein_label": {"text": ""},
    })


class TestLicorChannelLabel:

    def test_licor_import_sets_channel_label_not_wavelength(self, tmp_path):
        ws = _make_workspace(tmp_path)
        project = ws.load_project(str(ws.create_new_project("p")))
        f700, f800 = tmp_path / "a.tif", tmp_path / "b.tif"
        _write_licor_float_tiff(f700, channel=700, seed=1)
        _write_licor_float_tiff(f800, channel=800, seed=2)

        channels, _ = ws.import_nir_blot_typhoon([f700, f800], project)

        assert [c.channel_label for c in channels] == ["700", "800"]
        assert all(c.wavelength_nm is None for c in channels)

    def test_licor_radio_labels_show_channel(self, qapp, tmp_path):
        ws = _make_workspace(tmp_path)
        project = ws.load_project(str(ws.create_new_project("p")))
        f700, f800 = tmp_path / "a.tif", tmp_path / "b.tif"
        _write_licor_float_tiff(f700, channel=700, seed=1)
        _write_licor_float_tiff(f800, channel=800, seed=2)
        channels, _ = ws.import_nir_blot_typhoon([f700, f800], project)

        labels = _radio_labels(MainWindow(ws), _nir_blot(channels))
        assert labels == ["Ch1 — 700 channel", "Ch2 — 800 channel"]
        assert not any("nm" in lbl for lbl in labels)

    def test_licor_file_without_channel_tag_has_no_label(self, tmp_path):
        ws = _make_workspace(tmp_path)
        project = ws.load_project(str(ws.create_new_project("p")))
        f = tmp_path / "a.tif"
        _write_licor_float_tiff(f, include_docname=False)
        channels, _ = ws.import_nir_blot_typhoon([f], project)
        assert channels[0].channel_label is None

    def test_typhoon_labels_unchanged(self, qapp, tmp_path):
        ch_short = TESTS_DIR / "20260507-142651-[IRshort].tif"
        ch_long = TESTS_DIR / "20260507-142651-[IRlong].tif"
        if not ch_short.exists() or not ch_long.exists():
            pytest.skip("Typhoon test files not found in tests/")
        ws = _make_workspace(tmp_path)
        project = ws.load_project(str(ws.create_new_project("p")))

        channels, _ = ws.import_nir_blot_typhoon([ch_short, ch_long], project)

        assert all(c.channel_label is None for c in channels)
        assert [c.wavelength_nm for c in channels] == [785, 685]
        labels = _radio_labels(MainWindow(ws), _nir_blot(channels))
        assert labels == ["Ch1 — 785nm IRlong 825BP30", "Ch2 — 685nm IRshort 720BP20"]
        notes = [e.note for e in project.operation_log if e.operation == "nir_channel_imported"]
        assert all(n.startswith("Typhoon: ") for n in notes)

    def test_old_project_json_without_channel_label_loads(self):
        from pysternblot.models import BlotChannel
        ch = BlotChannel.model_validate({"asset_sha256": "a" * 64, "channel_index": 0, "wavelength_nm": 785})
        assert ch.channel_label is None


class TestIntegrityHtmlAcquisition:

    def _html(self, tmp_path, acq):
        report = {
            "blots": [{
                "blot_id": "b1", "protein_label": {"text": "P"}, "gamma_warning": None,
                "source_image": {
                    "sha256": "x", "bit_depth": 16, "bit_depth_warning": None,
                    "saturation": None, "saturation_crop_region": None,
                    "acquisition_metadata": acq, "width_px": 1, "height_px": 1,
                },
                "operations": {
                    "crop": {"x": 0, "y": 0, "w": 1, "h": 1}, "rotation_deg": 0,
                    "levels": {"black": 0, "white": 1, "gamma": 1.0},
                },
                "overlay": {"present": False},
            }],
            "project": {"name": "n", "id": "i"}, "created_utc": "t",
            "pysternblot_version": "v", "schema": "s",
        }
        return write_integrity_html(report, tmp_path / "r.html").read_text(encoding="utf-8")

    def test_licor_keys_rendered(self, tmp_path):
        html = self._html(tmp_path, {
            "channel": 700, "model": "Odyssey CLx 1.0.11", "software": "Image Studio 3.1.4",
            "instrument_serial": "CLX-0684", "datetime": "2026:05:07 14:26:51",
            "pixel_size_um": 169.19,
        })
        assert "Channel: 700" in html
        assert "Instrument: Odyssey CLx 1.0.11" in html
        assert "Serial: CLX-0684" in html
        assert "Software: Image Studio 3.1.4" in html
        assert "Acquired: 2026:05:07 14:26:51" in html
        assert "Pixel size: 169.2 µm" in html

    def test_partial_licor_metadata_renders_only_present_keys(self, tmp_path):
        html = self._html(tmp_path, {"model": "Odyssey CLx 1.0.11"})
        assert "Instrument: Odyssey CLx 1.0.11" in html
        assert "Channel:" not in html and "Serial:" not in html

    def test_typhoon_rendering_unchanged(self, tmp_path):
        html = self._html(tmp_path, {"scale_type": "Linear", "scan_mode": "Fast", "pmt_voltage": 399})
        assert "<b>Scale: Linear</b>" in html
        assert "Mode: Fast" in html and "PMT: 399 V" in html
        assert "Channel:" not in html and "Instrument:" not in html
