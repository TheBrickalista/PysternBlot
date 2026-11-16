# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Original Image view: lookup-table levels and a small pixmap cache.

- apply_levels_uint16_lut equals apply_levels_uint16 on the real fixtures.
- With a cache, _load_rotated_display_pixmap returns pixel-identical pixmaps,
  and a hit skips loading the image.
- Only MainWindow's view passes a cache; it is emptied when the project
  changes. Exports never use the cache or the LUT path.
"""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem

from pysternblot import render
from pysternblot.models import LegendZone
from pysternblot.ui import export_mixin as export_mixin_module
from pysternblot.image_utils import apply_levels_uint16, apply_levels_uint16_lut, load_image_as_uint16
from pysternblot.render import ProvenancePixmapCache, _load_rotated_display_pixmap, build_provenance_scene

from test_gesture_commit import _patched_save, _window
from test_refresh_scope_staleness import ECL_A, _window as _real_tiff_window
from test_source_export import _write_asset

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = [
    ROOT / "examples" / "Chemi_16.tif",
    ROOT / "tests" / "rhoa 20260220_131003_Ch_Chemi.tif",
    ROOT / "tests" / "20260507-142651-[IRlong].tif",
]
# (black, white, gamma, invert), including the clamped edge cases.
LEVEL_SETS = [
    (0, 65535, 1.0, False),
    (0, 65535, 1.0, True),
    (500, 30000, 0.6, False),
    (1200, 20000, 1.8, True),
    (900, 50000, 2.5, False),
    (20000, 20000, 1.0, False),        # white <= black -> black + 1
    (3000, 1000, 0.0, True),           # white < black, gamma <= 0 -> 1.0
    (0, 255, 1.0, False),              # 8-bit range
]


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(scope="module")
def images():
    return [load_image_as_uint16(p) for p in FIXTURES]


@pytest.mark.parametrize("levels", LEVEL_SETS, ids=[str(s) for s in LEVEL_SETS])
def test_lut_levels_equal_apply_levels_on_real_fixtures(images, levels):
    for img in images:
        expected = apply_levels_uint16(img, *levels)
        got = apply_levels_uint16_lut(img, *levels)
        assert got.dtype == np.uint16 and got.shape == expected.shape
        assert got.flags["C_CONTIGUOUS"]
        assert np.array_equal(got, expected)


def test_lut_levels_rejects_non_uint16():
    with pytest.raises(TypeError):
        apply_levels_uint16_lut(np.zeros((2, 2), np.float32), 0, 65535, 1.0, False)


# --------------------------------------------------------------------------
# _load_rotated_display_pixmap with a cache
# --------------------------------------------------------------------------
@pytest.fixture
def ws_root(tmp_path):
    root = tmp_path / "ws"
    shas = [_write_asset(root, p.read_bytes(), ".tif") for p in FIXTURES]
    return root, shas


@contextmanager
def _count_loads():
    calls = []
    real = render.load_image_as_uint16

    def counting(path):
        calls.append(Path(path).parent.name)
        return real(path)

    with patch.object(render, "load_image_as_uint16", counting):
        yield calls


DISPLAY_SETS = [
    dict(rotation_deg=0.0),
    dict(rotation_deg=1.5, black=500, white=30000),
    dict(rotation_deg=-7.25, gamma=1.8, invert=True, flip_horizontal=True),
    dict(rotation_deg=180.0, gamma=0.6, flip_vertical=True),
    dict(rotation_deg=12.0, black=1200, white=20000, flip_horizontal=True, flip_vertical=True),
]


@pytest.mark.parametrize("settings", DISPLAY_SETS, ids=[str(d) for d in DISPLAY_SETS])
def test_cached_pixmap_is_pixel_identical_to_uncached(qapp, ws_root, settings):
    root, shas = ws_root
    cache = ProvenancePixmapCache()
    for sha in shas:
        uncached = _load_rotated_display_pixmap(root, sha, **settings)
        cached = _load_rotated_display_pixmap(root, sha, **settings, pixmap_cache=cache)
        assert not uncached.isNull() and not cached.isNull()
        assert cached.toImage() == uncached.toImage()
        hit = _load_rotated_display_pixmap(root, sha, **settings, pixmap_cache=cache)
        assert hit.toImage() == uncached.toImage()


def test_cache_hit_skips_load_and_every_setting_is_in_the_key(qapp, ws_root):
    root, shas = ws_root
    sha = shas[0]
    cache = ProvenancePixmapCache()
    base = dict(rotation_deg=1.5, black=10, white=30000, gamma=1.0,
                invert=False, flip_horizontal=False, flip_vertical=False)
    with _count_loads() as loads:
        _load_rotated_display_pixmap(root, sha, **base, pixmap_cache=cache)
        _load_rotated_display_pixmap(root, sha, **base, pixmap_cache=cache)
        assert loads == [sha]                       # second call: hit, no load
        for field, value in [("rotation_deg", 2.0), ("black", 11), ("white", 29999),
                             ("gamma", 1.2), ("invert", True),
                             ("flip_horizontal", True), ("flip_vertical", True)]:
            n = len(loads)
            cache.clear()
            _load_rotated_display_pixmap(root, sha, **base, pixmap_cache=cache)
            _load_rotated_display_pixmap(root, sha, **{**base, field: value}, pixmap_cache=cache)
            assert len(loads) == n + 2, f"{field} must be part of the cache key"
        cache.clear()
        _load_rotated_display_pixmap(root, shas[1], **base, pixmap_cache=cache)
        _load_rotated_display_pixmap(root, shas[0], **base, pixmap_cache=cache)
        assert loads[-2:] == [shas[1], shas[0]]     # sha is part of the key


def test_cache_is_lru_with_at_most_four_entries(qapp, ws_root):
    root, shas = ws_root
    sha = shas[0]
    cache = ProvenancePixmapCache()
    assert cache.maxsize == 4
    with _count_loads() as loads:
        for black in range(5):                          # 5 distinct entries
            _load_rotated_display_pixmap(root, sha, black=black, pixmap_cache=cache)
        assert len(cache) == 4 and len(loads) == 5
        _load_rotated_display_pixmap(root, sha, black=1, pixmap_cache=cache)    # hit, now newest
        assert len(loads) == 5
        _load_rotated_display_pixmap(root, sha, black=0, pixmap_cache=cache)    # evicted: reload
        assert len(loads) == 6
        _load_rotated_display_pixmap(root, sha, black=1, pixmap_cache=cache)    # still cached
        assert len(loads) == 6


def test_failed_load_is_not_cached(qapp, tmp_path):
    cache = ProvenancePixmapCache()
    assert _load_rotated_display_pixmap(tmp_path, "0" * 64, pixmap_cache=cache).isNull()
    assert len(cache) == 0


def test_uncached_path_never_uses_the_lut(qapp, ws_root):
    root, shas = ws_root
    with patch.object(render, "apply_levels_uint16_lut", side_effect=AssertionError("LUT used")):
        assert not _load_rotated_display_pixmap(root, shas[0], rotation_deg=1.5).isNull()


# --------------------------------------------------------------------------
# MainWindow: only the view uses the cache
# --------------------------------------------------------------------------
def _scene_image(scene):
    items = [i for i in scene.items() if isinstance(i, QGraphicsPixmapItem)]
    assert items
    return max(items, key=lambda i: i.pixmap().width()).pixmap().toImage()


def test_view_scene_matches_uncached_scene_and_hits_cache(qapp, tmp_path):
    win = _window(tmp_path)
    blot = win.current_project.panel.blots[0]
    blot.display.rotation_deg = 2.0
    blot.display.levels_black = 3000

    with _count_loads() as loads:
        view = _scene_image(win._build_provenance_scene_for_view())
        again = _scene_image(win._build_provenance_scene_for_view())
        assert loads.count(blot.asset_sha256) == 1      # second build: cache hit
    plain = _scene_image(build_provenance_scene(
        win.current_project, win.workspace.root, blot_id=blot.id))
    assert view == plain and again == plain

    with _count_loads() as loads:
        blot.display.levels_black = 4000                # new key -> rebuilt
        win._build_provenance_scene_for_view()
        assert loads.count(blot.asset_sha256) == 1


def test_view_cache_is_emptied_when_the_project_changes(qapp, tmp_path):
    win = _window(tmp_path)
    win._build_provenance_scene_for_view()
    assert len(win._prov_pixmap_cache) >= 1

    other = win.current_project.model_copy(deep=True)
    win.current_project = other
    with _count_loads() as loads:
        win._build_provenance_scene_for_view()
    assert loads, "a new project must not reuse the previous project's pixmaps"
    assert win._prov_pixmap_cache_project is other


def test_exports_do_not_use_the_cache_or_the_lut(qapp, tmp_path):
    win = _window(tmp_path)
    win.refresh_previews()                          # fills the view cache
    assert len(win._prov_pixmap_cache) >= 1

    seen = []
    real = render._load_rotated_display_pixmap

    def spy(*args, **kwargs):
        seen.append(kwargs.get("pixmap_cache"))
        return real(*args, **kwargs)

    out = tmp_path / "ctx.tif"
    with ExitStack() as stack:
        for p in _patched_save(out):
            stack.enter_context(p)
        stack.enter_context(patch.object(render, "_load_rotated_display_pixmap", spy))
        stack.enter_context(patch.object(
            render, "apply_levels_uint16_lut", side_effect=AssertionError("LUT used by export")))
        win._export_provenance_scene_to_tiff(win.current_project.panel.blots[0].id, str(out))
    assert out.is_file()
    assert seen and all(c is None for c in seen)


def test_legend_zone_export_does_not_use_the_cache_or_the_lut(qapp, tmp_path):
    # export_legend_zone_png calls _load_rotated_display_pixmap through the
    # name imported into export_mixin, so that is the name patched here.
    win = _real_tiff_window(tmp_path)
    blot = win._get_active_blot()
    assert blot.id == ECL_A
    blot.legend_zone = LegendZone(x=250, y=350, w=600, h=300, show_markers=False)
    win.legend_zone_cb.setChecked(True)             # also fills the view cache
    assert len(win._prov_pixmap_cache) >= 1

    calls = []
    real = export_mixin_module._load_rotated_display_pixmap

    def spy(*args, **kwargs):
        calls.append(dict(sha=args[1] if len(args) > 1 else kwargs.get("sha256"),
                          passed="pixmap_cache" in kwargs,
                          cache=kwargs.get("pixmap_cache")))
        return real(*args, **kwargs)

    out = tmp_path / "zone.png"
    with ExitStack() as stack:
        stack.enter_context(patch.object(
            export_mixin_module.QFileDialog, "getSaveFileName", return_value=(str(out), "")))
        info = stack.enter_context(patch.object(export_mixin_module.QMessageBox, "information"))
        critical = stack.enter_context(patch.object(export_mixin_module.QMessageBox, "critical"))
        stack.enter_context(patch.object(export_mixin_module, "_load_rotated_display_pixmap", spy))
        stack.enter_context(patch.object(
            render, "apply_levels_uint16_lut", side_effect=AssertionError("LUT used by export")))
        win.export_legend_zone_png()

    assert not critical.called, f"export failed: {critical.call_args}"
    assert info.call_args is not None and "Saved PNG" in info.call_args.args[2]
    assert out.is_file() and out.stat().st_size > 0
    assert win.current_project.operation_log[-1].field == "legend_zone_png"
    # The spy really sat on the export's code path ...
    assert calls and all(c["sha"] == blot.asset_sha256 for c in calls)
    # ... and no call asked for the cache.
    assert all(c["cache"] is None for c in calls)
    assert not any(c["passed"] for c in calls)
