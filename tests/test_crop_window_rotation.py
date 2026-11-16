# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
levels_rotate_flip_crop_uint16 (crop-window rotation) is bit-identical to the
original full-image pipeline, and ensure_blot_crop_preview writes the same
pixels as before.

Each group builds the full-image reference once (the expensive part) and
checks 20 random crop windows against it: 36 groups x 20 = 720 cases.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import numpy as np
import pytest
import tifffile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pysternblot.image_utils import (
    apply_levels_uint16,
    crop_uint16,
    levels_rotate_flip_crop_uint16,
    load_image_as_uint16,
    rotate_uint16,
)
from pysternblot.models import BlotChannel, CropTemplate, DisplaySettings
from pysternblot.storage import Workspace

from test_source_export import _minimal_ladder, _minimal_project

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = [
    ROOT / "examples" / "Chemi_16.tif",
    ROOT / "tests" / "rhoa 20260220_131003_Ch_Chemi.tif",
    ROOT / "tests" / "20260507-142651-[IRlong].tif",
]
SPECIAL_ANGLES = [0.0, 90.0, 180.0, 270.0, -0.3, 179.9]
GROUPS_PER_FIXTURE = 12
CROPS_PER_GROUP = 20


# --------------------------------------------------------------------------
# Reference: the ORIGINAL full pipeline of ensure_blot_crop_preview, copied
# verbatim before the crop-window rewrite. Do not "optimise" it.
# --------------------------------------------------------------------------
def _reference(img, black, white, gamma, invert, deg, flip_h, flip_v):
    out = apply_levels_uint16(img, black, white, gamma, invert)
    out = rotate_uint16(out, deg, expand=False)
    if flip_h:
        out = np.fliplr(out)
    if flip_v:
        out = np.flipud(out)
    return out          # crop_uint16(out, x, y, w, h) is applied per case


@pytest.fixture(scope="module")
def images():
    return {p.name: load_image_as_uint16(p) for p in FIXTURES}


def _groups():
    rng = random.Random(20261116)
    groups = []
    for f_idx, path in enumerate(FIXTURES):
        for g in range(GROUPS_PER_FIXTURE):
            if g < len(SPECIAL_ANGLES):
                deg = SPECIAL_ANGLES[g]
            elif g % 2:
                deg = rng.uniform(-15.0, 15.0)
            else:
                deg = rng.uniform(-180.0, 180.0)
            black = rng.choice([0, 0, rng.randrange(0, 20000)])
            white = rng.choice([65535, rng.randrange(black + 1, 65536)])
            groups.append(dict(
                fixture=path.name,
                deg=deg,
                flip_h=bool((g + f_idx) & 1),
                flip_v=bool((g + f_idx) & 2),
                invert=bool(rng.getrandbits(1)),
                gamma=rng.choice([0.6, 1.0, 1.8]),
                black=black,
                white=white,
                seed=rng.getrandbits(32),
            ))
    return groups


GROUPS = _groups()


def _crops(seed, iw, ih):
    rng = random.Random(seed)
    for k in range(CROPS_PER_GROUP):
        if k % 4 == 0:      # small
            w, h = rng.randint(1, 40), rng.randint(1, 40)
        elif k % 4 == 1:    # large (can exceed the image)
            w, h = rng.randint(iw // 2, iw + 100), rng.randint(ih // 2, ih + 100)
        else:
            w, h = rng.randint(40, 600), rng.randint(40, 600)
        x = rng.randint(-50, iw + 20)
        y = rng.randint(-50, ih + 20)
        yield x, y, w, h


def test_groups_cover_the_required_cases():
    assert len(GROUPS) * CROPS_PER_GROUP >= 600
    degs = {g["deg"] for g in GROUPS}
    assert set(SPECIAL_ANGLES) <= degs
    assert any(abs(d) > 15 for d in degs) and any(0 < abs(d) < 15 for d in degs)
    assert {(g["flip_h"], g["flip_v"]) for g in GROUPS} == {
        (False, False), (True, False), (False, True), (True, True)}
    assert {g["invert"] for g in GROUPS} == {False, True}
    assert {g["gamma"] for g in GROUPS} == {0.6, 1.0, 1.8}
    assert {g["fixture"] for g in GROUPS} == {p.name for p in FIXTURES}


@pytest.mark.parametrize(
    "group", GROUPS,
    ids=[f"{g['fixture'][:12]}-{g['deg']:.2f}-h{int(g['flip_h'])}v{int(g['flip_v'])}" for g in GROUPS],
)
def test_crop_window_matches_full_pipeline(images, group):
    img = images[group["fixture"]]
    ih, iw = img.shape[:2]
    args = (group["black"], group["white"], group["gamma"], group["invert"],
            group["deg"], group["flip_h"], group["flip_v"])
    full = _reference(img, *args)
    for x, y, w, h in _crops(group["seed"], iw, ih):
        expected = crop_uint16(full, x, y, w, h)
        got = levels_rotate_flip_crop_uint16(img, *args, x, y, w, h)
        assert got.dtype == np.uint16
        assert got.shape == expected.shape, (x, y, w, h)
        assert np.array_equal(got, expected), (x, y, w, h)


def test_window_entirely_outside_rotated_source_is_zero(images):
    # 45 deg, top-left corner window: maps outside the source, filled with 0.
    img = images[FIXTURES[0].name]
    args = (0, 65535, 1.0, False, 45.0, False, False)
    expected = crop_uint16(_reference(img, *args), 0, 0, 30, 30)
    got = levels_rotate_flip_crop_uint16(img, *args, 0, 0, 30, 30)
    assert np.array_equal(got, expected) and not got.any()


# --------------------------------------------------------------------------
# End to end: ensure_blot_crop_preview writes the same pixels as before.
# --------------------------------------------------------------------------
def _old_preview(img, display, x, y, w, h):
    full = _reference(
        img, display.levels_black, display.levels_white, display.levels_gamma,
        display.invert, display.rotation_deg, display.flip_horizontal, display.flip_vertical,
    )
    return crop_uint16(full, x, y, w, h)


def _project_with_assets(tmp_path):
    from test_source_export import _write_asset
    from pysternblot.models import AssetEntry, Blot, Crop, ProteinLabel

    ws_dir = tmp_path / "ws"
    ecl_bytes = FIXTURES[0].read_bytes()
    nir_bytes = FIXTURES[2].read_bytes()
    ecl_sha = _write_asset(ws_dir, ecl_bytes, ".tif")
    nir_sha = _write_asset(ws_dir, nir_bytes, ".tif")
    assets = {
        sha: AssetEntry(sha256=sha, stored_original_path=str(ws_dir / "assets" / sha / "original.tif"))
        for sha in (ecl_sha, nir_sha)
    }
    ecl = Blot(
        id="blot_ecl", asset_sha256=ecl_sha, crop=Crop(x=310.0, y=455.0, w=420.0, h=180.0),
        ladder=_minimal_ladder(), protein_label=ProteinLabel(text="ECL"),
        display=DisplaySettings(levels_black=1200, levels_white=30000, levels_gamma=1.8,
                                invert=True, rotation_deg=1.5, flip_horizontal=True),
    )
    nir = Blot(
        id="blot_nir", asset_sha256=nir_sha, crop=Crop(x=0.0, y=0.0, w=420.0, h=180.0),
        ladder=_minimal_ladder(), protein_label=ProteinLabel(text="NIR"),
        modality="nir_fluorescence",
        channels=[BlotChannel(
            channel_index=0, asset_sha256=nir_sha,
            crop=Crop(x=600.0, y=1400.0, w=420.0, h=180.0),
            display=DisplaySettings(levels_black=900, levels_white=50000, levels_gamma=0.6,
                                    rotation_deg=-7.25, flip_vertical=True),
        )],
    )
    project = _minimal_project([ecl, nir], assets=assets)
    project.panel.crop_template = CropTemplate(w=420.0, h=180.0)
    ws = Workspace(root=ws_dir)
    ws.ensure()
    return ws, project, ecl, nir


def test_ensure_blot_crop_preview_pixels_unchanged_ecl_and_nir(tmp_path):
    ws, project, ecl, nir = _project_with_assets(tmp_path)
    assert nir.is_nir()

    path = ws.ensure_blot_crop_preview(ecl, project.panel, project=project)
    expected = _old_preview(load_image_as_uint16(FIXTURES[0]), ecl.display,
                            int(round(ecl.crop.x)), int(round(ecl.crop.y)), 420, 180)
    written = tifffile.imread(path)
    assert written.dtype == np.uint16 and written.shape == expected.shape
    assert written.tobytes() == expected.tobytes()

    ch = nir.channels[0]
    path = ws.ensure_blot_crop_preview(nir, project.panel, channel_index=0, project=project)
    assert path.name == "preview_crop_blot_nir_ch0.tif"
    c = nir.get_channel_crop(0)
    expected = _old_preview(load_image_as_uint16(FIXTURES[2]), ch.display,
                            int(round(c.x)), int(round(c.y)), 420, 180)
    written = tifffile.imread(path)
    assert written.dtype == np.uint16 and written.shape == expected.shape
    assert written.tobytes() == expected.tobytes()
