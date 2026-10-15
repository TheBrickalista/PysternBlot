# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""
Consistent physical scale for Amersham ImageQuant 800 images.

The IQ800 always exports 2400 x 3296 px whatever "Image Area" was imaged, so
the physical pixel size varies per file (68.3 µm for 160x220 mm, 45.5 µm for
107x147 mm). With f = reference / pixel size (reference = finest), crops are
cut in native pixels (template x f, the template's physical size) and drawn
at display scale 1 / f, so every blot in the figure shows the same membrane
area at the same size. See pysternblot/physical_scale.py.

All TIFFs here are synthetic (tifffile), carrying the real IQ800 tags: Model,
MINISWHITE, ResolutionUnit CENTIMETER, XResolution 100000/683 or 100000/455
and a CRLF-separated ImageDescription. Render tests use small arrays whose
Image Area stays consistent with pixel count x pixel size; the parser tests
also use the real 2400 x 3296 grid (zlib-compressed zeros, ~20 KB).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
)

from pysternblot.integrity import build_detailed_integrity_report, write_integrity_html
from pysternblot.jsonsafe import dumps_strict
from pysternblot.logchain import verify_log_chain
from pysternblot.models import AssetEntry, Blot, CropTemplate, MarkerBand, MarkerSet, Project
from pysternblot.physical_scale import (
    BINNING_NOTE,
    blot_scale_factor,
    compute_reference_pixel_size_um,
    native_crop_size,
    reconcile_reference_pixel_size,
    scale_warnings,
    scaling_pixel_size_um,
)
from pysternblot.render import build_panel_scene, build_provenance_scene
from pysternblot.storage import Workspace, parse_iq800_metadata
from pysternblot.ui.crop_rect_item import CropRectItem
from pysternblot.ui.project_io_mixin import _ProjectIOMixin

COARSE_UM, FINE_UM = 68.3, 45.5
SMALL_W, SMALL_H = 240, 330


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# Synthetic IQ800 files
# ---------------------------------------------------------------------------

def _description(*, area: str, binning: str = "3x3", extra: list[str] | None = None) -> str:
    lines = [
        f"Binning = {binning}",
        f"Image Area = {area}",
        "Exposure time = 11.4 s",
        "Imaging mode = Chemiluminescence",
        "Instrument = Amersham ImageQuant 800",
        "Software = Amersham ImageQuant 800 Control Software V2.0.0",
        "Serial number = 36310511",
    ]
    return "\r\n".join(lines + (extra or []))


def write_iq800(path: Path, px_um: float, *, shape=(SMALL_H, SMALL_W), area: str | None = None,
                binning: str = "3x3", description: str | None = None, model: str = "Amersham ImageQuant 800",
                seed: int = 0, compress: bool = False) -> Path:
    """IQ800-format TIFF. By default Image Area is derived from shape x pixel
    size so the cross-check passes for small arrays."""
    h, w = shape
    if area is None:
        area = f"{round(w * px_um / 1000)}x{round(h * px_um / 1000)}"
    den = int(round(px_um * 10))  # 68.3 µm -> 100000/683 px/cm
    if compress:
        arr = np.zeros(shape, np.uint16)
    else:
        arr = (np.random.default_rng(seed).random(shape) * 60000).astype(np.uint16)
    extratags = [(272, "s", 0, model, True)] if model else []
    tifffile.imwrite(
        str(path), arr, photometric="miniswhite",
        resolution=((100000, den), (100000, den)), resolutionunit="CENTIMETER",
        description=description if description is not None else _description(area=area, binning=binning),
        metadata=None, extratags=extratags, compression="zlib" if compress else None,
    )
    return path


def write_plain_tiff(path: Path, *, seed: int = 0) -> Path:
    arr = (np.random.default_rng(seed).random((SMALL_H, SMALL_W)) * 60000).astype(np.uint16)
    tifffile.imwrite(str(path), arr)
    return path


# ---------------------------------------------------------------------------
# Project helpers
# ---------------------------------------------------------------------------

def _new_project(ws: Workspace) -> Project:
    return ws.load_project(str(ws.create_new_project("scale")))


def _add_blot(ws: Workspace, project: Project, src: Path, blot_id: str, *, metadata="parse",
              crop=(20, 30), included: bool = True, overlay_ladder=None) -> Blot:
    """Import src as an ECL blot. metadata="parse" records what import_blot
    records; None leaves the asset without metadata (a legacy project)."""
    sha, dest = ws.import_asset(str(src))
    meta = parse_iq800_metadata(dest) if metadata == "parse" else metadata
    project.assets[sha] = AssetEntry(sha256=sha, stored_original_path=str(dest), acquisition_metadata=meta or None)
    blot = Blot.model_validate({
        "id": blot_id, "asset_sha256": sha,
        "crop": {"x": crop[0], "y": crop[1], "w": 1, "h": 1},
        "ladder": {"lane_index": 0, "marker_set_id": "ms1",
                   "calibration_points": [{"y_px": 1, "kda": 55}, {"y_px": 2, "kda": 36}]},
        "protein_label": {"text": blot_id},
        "included_in_final": included,
        "overlay_ladder": overlay_ladder,
    })
    project.panel.blots.append(blot)
    project.panel.layout.order.append(blot_id)
    return blot


def _render_previews(ws: Workspace, project: Project) -> None:
    for b in project.panel.blots:
        ws.ensure_blot_crop_preview(b, project.panel, project=project)


def _two_size_panel(tmp_path, *, template=(100.0, 80.0), overlay_ladder=None):
    """blot_coarse (68.3 µm) + blot_fine (45.5 µm), template in reference px.
    The default keeps every native crop inside the small 240 x 330 test images
    (crops are clipped at the image edge, as they always have been)."""
    ws = Workspace(tmp_path)
    project = _new_project(ws)
    coarse = _add_blot(ws, project, write_iq800(tmp_path / "coarse.tif", COARSE_UM, seed=1), "blot_coarse",
                       overlay_ladder=overlay_ladder)
    fine = _add_blot(ws, project, write_iq800(tmp_path / "fine.tif", FINE_UM, seed=2), "blot_fine")
    reconcile_reference_pixel_size(project)
    project.panel.crop_template = CropTemplate(w=template[0], h=template[1])
    return ws, project, coarse, fine


def _render_png(scene: QGraphicsScene) -> QImage:
    rect = scene.itemsBoundingRect()
    img = QImage(int(rect.width()) + 4, int(rect.height()) + 4, QImage.Format_ARGB32)
    img.fill(Qt.white)
    painter = QPainter(img)
    scene.render(painter, QRectF(2, 2, rect.width(), rect.height()), rect)
    painter.end()
    return img


# ===========================================================================
# Parser
# ===========================================================================

class TestParseIq800Metadata:

    @pytest.mark.parametrize("px_um, area, expected_um", [
        (68.3, "160x220", 68.3),
        (45.5, "107x147", 45.5),
    ])
    def test_real_format_tags_on_real_grid(self, tmp_path, px_um, area, expected_um):
        path = write_iq800(tmp_path / "iq.tif", px_um, shape=(3296, 2400), area=area, compress=True)
        meta = parse_iq800_metadata(path)

        assert meta["instrument"] == "Amersham ImageQuant 800"
        assert meta["model"] == "Amersham ImageQuant 800"
        assert meta["software"] == "Amersham ImageQuant 800 Control Software V2.0.0"
        assert meta["serial_number"] == "36310511"
        assert meta["binning"] == "3x3"
        assert meta["image_area_mm"] == [int(n) for n in area.split("x")]
        assert meta["exposure_s"] == pytest.approx(11.4)
        assert meta["imaging_mode"] == "Chemiluminescence"
        assert meta["pixel_size_um"] == pytest.approx(expected_um)
        assert meta["pixel_size_source"] == "iq800_xresolution"
        assert meta["pixel_size_trusted"] is True
        # Real files agree within ~2.5% (2400 x 45.5 µm = 109.2 mm vs 107 nominal).
        assert meta["image_area_check"]["max_relative_difference"] < 0.025

    def test_identified_by_instrument_line_without_model_tag(self, tmp_path):
        meta = parse_iq800_metadata(write_iq800(tmp_path / "iq.tif", FINE_UM, model=""))
        assert meta["instrument"] == "Amersham ImageQuant 800"
        assert meta["pixel_size_um"] == pytest.approx(FINE_UM)

    def test_area_mismatch_marks_pixel_size_untrusted(self, tmp_path):
        # 240 px x 45.5 µm = 10.9 mm, but the description claims 107 mm.
        meta = parse_iq800_metadata(write_iq800(tmp_path / "iq.tif", FINE_UM, area="107x147"))
        assert meta["pixel_size_um"] == pytest.approx(FINE_UM)
        assert meta["pixel_size_trusted"] is False
        assert scaling_pixel_size_um(AssetEntry(sha256="x", stored_original_path="x", acquisition_metadata=meta)) is None

    def test_non_iq800_tiff_returns_empty(self, tmp_path):
        assert parse_iq800_metadata(write_plain_tiff(tmp_path / "plain.tif")) == {}

    def test_licor_tiff_returns_empty(self, tmp_path):
        path = tmp_path / "licor.tif"
        tifffile.imwrite(str(path), np.zeros((8, 8), np.float16), metadata=None,
                         extratags=[(271, "s", 0, "LI-COR", True), (269, "s", 0, "Channel: 700", True)])
        assert parse_iq800_metadata(path) == {}

    def test_png_and_non_image_return_empty(self, tmp_path):
        png = tmp_path / "x.png"
        Image.new("I;16", (8, 8)).save(str(png))
        junk = tmp_path / "junk.tif"
        junk.write_bytes(b"not a tiff at all")
        assert parse_iq800_metadata(png) == {}
        assert parse_iq800_metadata(junk) == {}
        assert parse_iq800_metadata(tmp_path / "missing.tif") == {}

    def test_malformed_description_never_raises(self, tmp_path):
        desc = "\r\n".join([
            "Instrument = Amersham ImageQuant 800",
            "garbage line without separator",
            "Image Area = abc",
            "Exposure time = soon",
            "= no key",
            "Binning =",
            "Serial number = 36310511",
        ])
        meta = parse_iq800_metadata(write_iq800(tmp_path / "iq.tif", FINE_UM, description=desc))
        assert meta["instrument"] == "Amersham ImageQuant 800"
        assert meta["serial_number"] == "36310511"
        for key in ("image_area_mm", "exposure_s", "binning", "image_area_check"):
            assert key not in meta
        # No Image Area to contradict it: the XResolution value stays trusted.
        assert meta["pixel_size_trusted"] is True


# ===========================================================================
# Reference pixel size, factors, native crop
# ===========================================================================

class TestReferenceAndFactors:

    def test_every_crop_covers_the_same_membrane(self, qapp, tmp_path):
        """The point of the change: native px x pixel size is the same for
        every blot (= template x reference), not just the displayed size."""
        ws, project, coarse, fine = _two_size_panel(tmp_path, template=(120.0, 90.0))
        physical = {
            b.id: tuple(n * px for n in native_crop_size(project, b))
            for b, px in ((coarse, COARSE_UM), (fine, FINE_UM))
        }
        assert physical["blot_coarse"] == pytest.approx(physical["blot_fine"])
        assert physical["blot_fine"] == pytest.approx((120.0 * FINE_UM, 90.0 * FINE_UM))

        _render_previews(ws, project)
        widths_um = {
            b.id: tifffile.imread(str(ws.assets_dir / b.asset_sha256 / f"preview_crop_{b.id}.tif")).shape[1] * px
            for b, px in ((coarse, COARSE_UM), (fine, FINE_UM))
        }
        assert widths_um["blot_coarse"] == pytest.approx(widths_um["blot_fine"], abs=COARSE_UM)  # within 1 px

    def test_reference_is_finest_including_excluded_blots(self, tmp_path):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_iq800(tmp_path / "c.tif", COARSE_UM, seed=1), "b1")
        _add_blot(ws, project, write_iq800(tmp_path / "f.tif", FINE_UM, seed=2), "b2", included=False)
        assert compute_reference_pixel_size_um(project) == pytest.approx(FINE_UM)

    def test_native_crop_dims_per_blot(self, qapp, tmp_path):
        ws, project, coarse, fine = _two_size_panel(tmp_path, template=(100.0, 80.0))
        f = FINE_UM / COARSE_UM
        assert blot_scale_factor(project, fine) == 1.0
        assert blot_scale_factor(project, coarse) == pytest.approx(f)
        assert native_crop_size(project, fine) == (100.0, 80.0)
        assert native_crop_size(project, coarse) == pytest.approx((100.0 * f, 80.0 * f))

        _render_previews(ws, project)
        cached = tifffile.imread(str(ws.assets_dir / coarse.asset_sha256 / "preview_crop_blot_coarse.tif"))
        assert cached.shape == (round(80.0 * f), round(100.0 * f))  # native pixels, not resampled
        cached_fine = tifffile.imread(str(ws.assets_dir / fine.asset_sha256 / "preview_crop_blot_fine.tif"))
        assert cached_fine.shape == (80, 100)


# ===========================================================================
# Figure (build_panel_scene)
# ===========================================================================

def _image_items(scene):
    return sorted((i for i in scene.items() if isinstance(i, QGraphicsPixmapItem)),
                  key=lambda i: i.sceneBoundingRect().top())


class TestFigureScale:

    def test_equal_displayed_widths_for_683_and_455(self, qapp, tmp_path):
        ws, project, coarse, fine = _two_size_panel(tmp_path)
        _render_previews(ws, project)
        scene = build_panel_scene(project, tmp_path)

        items = _image_items(scene)
        assert len(items) == 2
        widths = [i.sceneBoundingRect().width() for i in items]
        heights = [i.sceneBoundingRect().height() for i in items]
        assert widths[0] == pytest.approx(widths[1], abs=1.0)
        assert heights[0] == pytest.approx(heights[1], abs=1.0)

        coarse_item, fine_item = items  # layout order: coarse first
        assert coarse_item.scale() == pytest.approx(COARSE_UM / FINE_UM)  # display scale 1 / f
        assert coarse_item.transformationMode() == Qt.SmoothTransformation
        assert fine_item.scale() == 1.0

    def test_mw_marker_y_uses_scale_factor(self, qapp, tmp_path):
        overlay = {"marker_set_id": "ms1", "bands": [{"y_px": 130.0, "kda": 100.0}]}
        ws, project, coarse, fine = _two_size_panel(tmp_path, overlay_ladder=overlay)
        project.marker_sets = [MarkerSet(id="ms1", name="M", bands=[MarkerBand(kda=100, label="100")])]
        _render_previews(ws, project)
        scene = build_panel_scene(project, tmp_path)

        coarse_top = _image_items(scene)[0].sceneBoundingRect().top()
        display_scale = COARSE_UM / FINE_UM  # 1 / f
        ticks = [i for i in scene.items() if isinstance(i, QGraphicsLineItem) and i.line().y1() == i.line().y2()]
        assert len(ticks) == 1
        assert ticks[0].line().y1() == pytest.approx(coarse_top + (130.0 - 30.0) * display_scale)


# ===========================================================================
# Template rescale when the reference changes
# ===========================================================================

class TestTemplateRescale:

    def test_finer_blot_added_rescales_template_and_logs(self, tmp_path):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_iq800(tmp_path / "c.tif", COARSE_UM, seed=1), "b1")
        reconcile_reference_pixel_size(project)
        project.panel.crop_template = CropTemplate(w=300.0, h=200.0)
        physical_w = 300.0 * COARSE_UM

        _add_blot(ws, project, write_iq800(tmp_path / "f.tif", FINE_UM, seed=2), "b2")
        assert reconcile_reference_pixel_size(project) is True

        ct = project.panel.crop_template
        assert project.panel.reference_pixel_size_um == pytest.approx(FINE_UM)
        assert ct.w * FINE_UM == pytest.approx(physical_w)
        assert ct.h == pytest.approx(200.0 * COARSE_UM / FINE_UM)
        ops = [e.operation for e in project.operation_log]
        assert ops[-2:] == ["reference_pixel_size_set", "crop_template_rescaled"]
        rescale = project.operation_log[-1]
        assert rescale.old_value == {"w": 300.0, "h": 200.0}
        assert "finer image was added" in rescale.note
        assert verify_log_chain(project).status == "ok"

    def test_finest_blot_removed_rescales_back(self, tmp_path):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_iq800(tmp_path / "c.tif", COARSE_UM, seed=1), "b1")
        _add_blot(ws, project, write_iq800(tmp_path / "f.tif", FINE_UM, seed=2), "b2")
        reconcile_reference_pixel_size(project)
        project.panel.crop_template = CropTemplate(w=450.0, h=300.0)

        project.panel.blots = [b for b in project.panel.blots if b.id != "b2"]
        project.panel.layout.order.remove("b2")
        assert reconcile_reference_pixel_size(project) is True

        assert project.panel.reference_pixel_size_um == pytest.approx(COARSE_UM)
        assert project.panel.crop_template.w == pytest.approx(450.0 * FINE_UM / COARSE_UM)
        assert "finest image was removed" in project.operation_log[-1].note

    def test_unchanged_reference_is_a_no_op(self, tmp_path):
        ws, project, _c, _f = _two_size_panel(tmp_path)
        n = len(project.operation_log)
        assert reconcile_reference_pixel_size(project) is False
        assert len(project.operation_log) == n


# ===========================================================================
# Backward compatibility (legacy projects)
# ===========================================================================

class TestLegacyProjects:

    def _legacy_single_size_project(self, tmp_path):
        """Saved by the previous version: IQ800 assets without metadata, no
        reference field, a chained log, one shared pixel size."""
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        overlay = {"marker_set_id": "ms1", "bands": [{"y_px": 90.0, "kda": 100.0}]}
        for i in (1, 2):
            _add_blot(ws, project, write_iq800(tmp_path / f"s{i}.tif", COARSE_UM, seed=i), f"b{i}",
                      metadata=None, overlay_ladder=overlay)
        project.marker_sets = [MarkerSet(id="ms1", name="M", bands=[MarkerBand(kda=100, label="100")])]
        project.panel.crop_template = CropTemplate(w=150.0, h=120.0)
        host = _ProjectIOMixin()
        host.current_project = project
        host.log_operation("display_changed", field="levels_gamma", old_value=1.0, new_value=1.2)
        data = project.model_dump(mode="json")
        data["panel"].pop("reference_pixel_size_um")  # field did not exist yet
        path = ws.projects_dir / project.project.id / "project.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps_strict(data, indent=2), encoding="utf-8")
        return ws, path

    def test_single_pixel_size_figure_is_pixel_identical(self, qapp, tmp_path):
        ws, path = self._legacy_single_size_project(tmp_path)

        # As the previous version saw it: no metadata, hence no scaling at all.
        before = Project.model_validate_json(path.read_text(encoding="utf-8"))
        for b in before.panel.blots:
            ws.ensure_blot_crop_preview(b, before.panel)
        img_before = _render_png(build_panel_scene(before, tmp_path))

        after = ws.load_project(str(path))  # backfill + reference
        assert after.panel.reference_pixel_size_um == pytest.approx(COARSE_UM)
        assert all(blot_scale_factor(after, b) == 1.0 for b in after.panel.blots)
        _render_previews(ws, after)
        img_after = _render_png(build_panel_scene(after, tmp_path))

        assert img_before.size() == img_after.size()
        assert img_before == img_after

    def test_single_pixel_size_chain_still_verifies_and_only_log_entries_appear(self, tmp_path):
        ws, path = self._legacy_single_size_project(tmp_path)
        before = Project.model_validate_json(path.read_text(encoding="utf-8"))
        after = ws.load_project(str(path))

        assert verify_log_chain(after).status == "ok"
        new_ops = [e.operation for e in after.operation_log[len(before.operation_log):]]
        assert new_ops == ["iq800_metadata_backfilled", "iq800_metadata_backfilled", "reference_pixel_size_set"]
        assert after.panel.crop_template == before.panel.crop_template

        reloaded = ws.load_project(str(ws.save_project(after)))
        assert verify_log_chain(reloaded).status == "ok"
        assert len(reloaded.operation_log) == len(after.operation_log)  # backfill happens once

    def test_legacy_mixed_sizes_logs_interpretation_warning(self, tmp_path):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_iq800(tmp_path / "c.tif", COARSE_UM, seed=1), "b1", metadata=None)
        _add_blot(ws, project, write_iq800(tmp_path / "f.tif", FINE_UM, seed=2), "b2", metadata=None)
        project.panel.crop_template = CropTemplate(w=150.0, h=100.0)
        path = ws.save_project(project)

        loaded = ws.load_project(str(path))
        assert loaded.panel.crop_template == CropTemplate(w=150.0, h=100.0)  # read as reference px
        assert loaded.operation_log[-1].operation == "crop_template_legacy_interpretation"
        assert "Warning" in loaded.operation_log[-1].note
        assert verify_log_chain(loaded).status == "ok"

    def test_non_iq800_project_gets_no_new_entries(self, tmp_path):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_plain_tiff(tmp_path / "p.tif"), "b1", metadata=None)
        path = ws.save_project(project)
        loaded = ws.load_project(str(path))
        assert loaded.panel.reference_pixel_size_um is None
        assert len(loaded.operation_log) == len(project.operation_log)


# ===========================================================================
# Unknown / informational pixel sizes, warnings, overlay
# ===========================================================================

class TestUnknownAndInformational:

    def test_unknown_pixel_size_gets_f1_and_warning(self, tmp_path):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_iq800(tmp_path / "f.tif", FINE_UM), "iq")
        plain = _add_blot(ws, project, write_plain_tiff(tmp_path / "p.tif"), "plain")
        reconcile_reference_pixel_size(project)

        assert blot_scale_factor(project, plain) == 1.0
        warnings = scale_warnings(project)
        assert len(warnings) == 1 and "plain" in warnings[0] and "f = 1" in warnings[0]

    @pytest.mark.parametrize("meta", [
        {"pixel_size_um": 100.0, "laser_nm": 685, "filter_name": "IRshort"},          # Typhoon
        {"pixel_size_um": 84.67, "channel": 700, "model": "Odyssey CLx 1.0.11"},      # LI-COR
    ])
    def test_typhoon_and_licor_pixel_size_do_not_affect_rendering(self, qapp, tmp_path, meta):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        other = _add_blot(ws, project, write_plain_tiff(tmp_path / "p.tif"), "other", metadata=meta)
        reconcile_reference_pixel_size(project)
        assert project.panel.reference_pixel_size_um is None
        assert blot_scale_factor(project, other) == 1.0

        _add_blot(ws, project, write_iq800(tmp_path / "f.tif", FINE_UM), "iq")
        reconcile_reference_pixel_size(project)
        assert blot_scale_factor(project, other) == 1.0
        _render_previews(ws, project)
        scene = build_panel_scene(project, tmp_path)
        assert all(item.scale() == 1.0 for item in _image_items(scene))

    def test_overlay_pixel_size_mismatch_warns(self, tmp_path):
        ws, project, coarse, _fine = _two_size_panel(tmp_path)
        sha, dest = ws.import_asset(str(write_iq800(tmp_path / "ov.tif", FINE_UM, seed=9)))
        project.assets[sha] = AssetEntry(sha256=sha, stored_original_path=str(dest),
                                         acquisition_metadata=parse_iq800_metadata(dest))
        coarse.overlay_asset_sha256 = sha
        warnings = scale_warnings(project)
        assert any("blot_coarse" in w and "overlay" in w for w in warnings)


# ===========================================================================
# Original Image tab (build_provenance_scene + CropRectItem)
# ===========================================================================

def _crop_rect_item(scene) -> CropRectItem:
    items = [i for i in scene.items() if isinstance(i, CropRectItem)]
    assert len(items) == 1
    return items[0]


class TestOriginalImageCropRect:

    def test_crop_rect_reports_rect_without_pen_padding(self, qapp):
        got = []
        item = CropRectItem(QRectF(100, 50, 300, 200), on_change=got.append)
        scene = QGraphicsScene()
        scene.addItem(item)
        item.setPos(10, 0)
        assert (got[-1].x(), got[-1].y(), got[-1].width(), got[-1].height()) == (110, 50, 300, 200)

    def test_rect_shows_native_size(self, qapp, tmp_path):
        ws, project, coarse, fine = _two_size_panel(tmp_path)
        scene_coarse = build_provenance_scene(project, tmp_path, blot_id="blot_coarse")
        scene_fine = build_provenance_scene(project, tmp_path, blot_id="blot_fine")
        rect_coarse = _crop_rect_item(scene_coarse).rect()
        rect_fine = _crop_rect_item(scene_fine).rect()
        assert rect_fine.width() == pytest.approx(100.0)
        assert rect_coarse.width() == pytest.approx(100.0 * FINE_UM / COARSE_UM)
        # The finer image's rectangle is ~1.5x larger: it needs more of its
        # (smaller) pixels to cover the same membrane.
        assert rect_fine.width() / rect_coarse.width() == pytest.approx(COARSE_UM / FINE_UM)

    def test_move_commit_does_not_alter_template(self, qapp, tmp_path):
        ws, project, coarse, _fine = _two_size_panel(tmp_path)
        before = project.panel.crop_template.model_copy()
        commits = []
        scene = build_provenance_scene(project, tmp_path, blot_id="blot_coarse",
                                       on_crop_commit=commits.append)
        item = _crop_rect_item(scene)
        item.moveBy(7.0, 5.0)                      # live on_change via itemChange
        item._on_move_commit(item.crop_scene_rect())

        assert commits == [coarse]
        assert project.panel.crop_template == before
        assert (coarse.crop.x, coarse.crop.y) == (27.0, 35.0)

    def test_resize_commit_writes_template_in_reference_pixels(self, qapp, tmp_path):
        ws, project, coarse, _fine = _two_size_panel(tmp_path)
        scene = build_provenance_scene(project, tmp_path, blot_id="blot_coarse")
        item = _crop_rect_item(scene)
        r = item.rect()
        item.setRect(QRectF(r.x(), r.y(), 180.0, 120.0))   # native px of the coarse image
        item._on_resize_commit(item.crop_scene_rect())

        f = FINE_UM / COARSE_UM
        assert project.panel.crop_template.w == pytest.approx(180.0 / f)
        assert project.panel.crop_template.h == pytest.approx(120.0 / f)
        # and back: the coarse image now shows exactly what was drawn
        assert native_crop_size(project, coarse) == pytest.approx((180.0, 120.0))


# ===========================================================================
# Integrity reports
# ===========================================================================

class TestIntegrityReports:

    def test_physical_scale_recorded_per_blot(self, qapp, tmp_path):
        ws, project, coarse, fine = _two_size_panel(tmp_path)
        report = build_detailed_integrity_report(project, ws)
        records = {b["blot_id"]: b["physical_scale"] for b in report["blots"]}

        c = records["blot_coarse"]
        assert c["pixel_size_um"] == pytest.approx(COARSE_UM)
        assert c["pixel_size_source"] == "iq800_xresolution"
        assert c["binning"] == "3x3"
        assert c["image_area_mm"] == [16, 23]
        assert c["scale_factor_f"] == pytest.approx(FINE_UM / COARSE_UM)
        assert c["display_scale"] == pytest.approx(COARSE_UM / FINE_UM)
        assert c["native_crop_px"] == {"w": round(100 * FINE_UM / COARSE_UM), "h": round(80 * FINE_UM / COARSE_UM)}
        assert c["reference_pixel_size_um"] == pytest.approx(FINE_UM)
        assert "SmoothTransformation" in c["display_interpolation"]
        assert BINNING_NOTE in c["notes"]
        assert records["blot_fine"]["scale_factor_f"] == 1.0
        assert records["blot_fine"]["display_interpolation"] == "none (drawn 1:1)"
        assert report["panel"]["reference_pixel_size_um"] == pytest.approx(FINE_UM)

        html = write_integrity_html(report, tmp_path / "r.html").read_text(encoding="utf-8")
        assert "Physical scale" in html and "Binning: 3x3" in html and BINNING_NOTE in html


# ===========================================================================
# Import helper and Figure tab (main window)
# ===========================================================================

class TestImportAndFigureTab:

    def test_attach_new_blot_reconciles_and_records_native_crop(self, tmp_path):
        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_iq800(tmp_path / "c.tif", COARSE_UM, seed=1), "b1")
        reconcile_reference_pixel_size(project)
        project.panel.crop_template = CropTemplate(w=100.0, h=80.0)

        sha, dest = ws.import_asset(str(write_iq800(tmp_path / "f.tif", FINE_UM, seed=2)))
        project.assets[sha] = AssetEntry(sha256=sha, stored_original_path=str(dest),
                                         acquisition_metadata=parse_iq800_metadata(dest))
        new = Blot.model_validate({
            "id": "b2", "asset_sha256": sha, "crop": {"x": 0, "y": 0, "w": 1, "h": 1},
            "ladder": {"lane_index": 0, "marker_set_id": "ms1",
                       "calibration_points": [{"y_px": 1, "kda": 55}, {"y_px": 2, "kda": 36}]},
            "protein_label": {"text": "b2"},
        })
        host = _ProjectIOMixin()
        host.current_project = project
        host._attach_new_blot(new)

        assert project.panel.layout.order[-1] == "b2"
        assert project.panel.reference_pixel_size_um == pytest.approx(FINE_UM)
        ratio = COARSE_UM / FINE_UM
        assert project.panel.crop_template.w == pytest.approx(100.0 * ratio)   # physical size kept
        assert (new.crop.w, new.crop.h) == pytest.approx((100.0 * ratio, 80.0 * ratio))  # f = 1

    def test_figure_tab_shows_mixed_scale_warning(self, qapp, tmp_path):
        from pysternblot.ui.main_window import MainWindow

        ws = Workspace(tmp_path)
        project = _new_project(ws)
        _add_blot(ws, project, write_iq800(tmp_path / "f.tif", FINE_UM), "iq")
        _add_blot(ws, project, write_plain_tiff(tmp_path / "p.tif"), "plain")
        reconcile_reference_pixel_size(project)

        mw = MainWindow(ws)
        mw.current_project = project
        mw._regenerate_crop_previews(project.panel.blots)
        mw._refresh_final_only(fit=False)

        assert not mw.scale_warning_label.isHidden()
        assert "plain" in mw.scale_warning_label.text()
        assert (ws.assets_dir / project.panel.blots[0].asset_sha256 / "preview_crop_iq.tif").exists()
