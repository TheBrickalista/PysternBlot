# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Consistent physical scale across the blots of one panel.

Some instruments export a fixed pixel grid whatever area was imaged, so the
physical size of a pixel varies from file to file (Amersham ImageQuant 800:
always 2400 x 3296 px, 45.5 µm/px for a 107x147 mm area, 68.3 µm/px for
160x220 mm). One shared crop template in raw pixels would then cover a
different membrane area on each blot.

Model:
  - Only instruments opted in by scaling_pixel_size_um() drive scaling (today:
    ImageQuant 800, pixel size from XResolution, cross-checked against the
    recorded image area). Typhoon / LI-COR pixel sizes stay informational.
  - panel.reference_pixel_size_um = the finest scaling pixel size among ALL
    blots (included or not, so toggling inclusion never rescales anything).
  - panel.crop_template.w/h are in reference pixels, so the template covers
    a physical width of template.w x reference.
  - Per blot: f = reference / blot pixel size (<= 1 for coarser images).
    Covering that same physical width takes template x f native pixels:
    native crop = template x f (cut in native pixels, never resampled).
    It is drawn at display scale 1 / f, so every crop occupies template
    scene units (a coarser image is enlarged for display only).
  - A blot with no known scaling pixel size gets f = 1 and a warning when the
    panel also contains blots that are scaled.

Every place that converts between template and native pixels goes through
this module, so the arithmetic exists once.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from .jsonsafe import finite_or_none
from .logchain import append_log_entry
from .models import OperationLogEntry, Project

IQ800_PIXEL_SIZE_SOURCE = "iq800_xresolution"

# Relative tolerance for "same pixel size" (overlay check, reference changes).
_SAME_SIZE_RTOL = 1e-6
_OVERLAY_MISMATCH_RTOL = 0.01

DISPLAY_INTERPOLATION_SCALED = (
    "Qt SmoothTransformation (bilinear), display only; source pixels are never resampled"
)
DISPLAY_INTERPOLATION_NONE = "none (drawn 1:1)"

BINNING_NOTE = (
    "binned acquisition re-interpolated by the instrument software; effective "
    "resolution is lower than the pixel grid"
)


def _positive_finite(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def scaling_pixel_size_um(asset) -> Optional[float]:
    """Pixel size (µm) that drives display scaling for this asset, or None.

    Opt-in per instrument: today only ImageQuant 800 metadata whose
    XResolution passed the image-area cross-check. Pixel sizes recorded for
    other instruments (Typhoon, LI-COR) are informational and return None.
    """
    meta = getattr(asset, "acquisition_metadata", None) if asset is not None else None
    if not isinstance(meta, dict):
        return None
    if meta.get("pixel_size_source") != IQ800_PIXEL_SIZE_SOURCE:
        return None
    if meta.get("pixel_size_trusted") is not True:
        return None
    return _positive_finite(meta.get("pixel_size_um"))


def blot_pixel_size_um(project: Project, blot) -> Optional[float]:
    return scaling_pixel_size_um(project.assets.get(blot.asset_sha256))


def overlay_pixel_size_um(project: Project, blot) -> Optional[float]:
    sha = getattr(blot, "overlay_asset_sha256", None)
    return scaling_pixel_size_um(project.assets.get(sha)) if sha else None


def compute_reference_pixel_size_um(project: Project) -> Optional[float]:
    """Finest scaling pixel size among all blots (included or not)."""
    sizes = [s for s in (blot_pixel_size_um(project, b) for b in project.panel.blots) if s]
    return min(sizes) if sizes else None


def blot_scale_factor(project: Project, blot) -> float:
    """f = reference / blot pixel size; 1.0 when either is unknown."""
    ref = _positive_finite(project.panel.reference_pixel_size_um)
    px = blot_pixel_size_um(project, blot)
    if ref is None or px is None:
        return 1.0
    return ref / px


def blot_display_scale(project: Project, blot) -> float:
    """Scale at which this blot's native crop is drawn in the figure: 1 / f.
    1.0 for the reference resolution, > 1 for coarser images."""
    return 1.0 / blot_scale_factor(project, blot)


def native_crop_size(project: Project, blot) -> tuple[float, float]:
    """Crop size of this blot in its own native pixels: template x f, i.e.
    the same physical size as the template (template x reference µm).

    Not rounded here: code that cuts pixels rounds, exactly as it always has
    for the template (so f == 1 is identical to the pre-scaling behaviour).
    """
    f = blot_scale_factor(project, blot)
    ct = project.panel.crop_template
    return float(ct.w) * f, float(ct.h) * f


def template_size_from_native(project: Project, blot, w: float, h: float) -> tuple[float, float]:
    """Inverse of native_crop_size: native pixels of this blot -> template."""
    f = blot_scale_factor(project, blot)
    return float(w) / f, float(h) / f


def _same(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=_SAME_SIZE_RTOL)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log(project: Project, operation: str, *, field: str, old, new, note: str) -> None:
    append_log_entry(
        project,
        OperationLogEntry(
            timestamp_utc=_now(),
            operation=operation,
            target_type="project",
            target_id=project.project.id,
            field=field,
            old_value=finite_or_none(old),
            new_value=finite_or_none(new),
            note=note,
        ),
    )


def reconcile_reference_pixel_size(project: Project) -> bool:
    """Bring panel.reference_pixel_size_um in line with the blots.

    When the reference changes between two known values (a finer image was
    added, or the finest one removed), crop_template is rescaled by
    old / new so its physical size is preserved. When a project that had no
    reference yet already mixes pixel sizes (a legacy project), the existing
    template is interpreted as reference pixels and a warning entry is logged.
    Every change is logged. Returns True if anything changed.
    """
    panel = project.panel
    old = _positive_finite(panel.reference_pixel_size_um)
    new = compute_reference_pixel_size_um(project)
    if _same(old, new):
        return False

    panel.reference_pixel_size_um = new
    _log(
        project, "reference_pixel_size_set",
        field="panel.reference_pixel_size_um", old=old, new=new,
        note="Finest scaling pixel size among all blots; crop_template is expressed in this unit.",
    )

    ct = panel.crop_template
    if old is not None and new is not None:
        before = {"w": ct.w, "h": ct.h}
        ratio = old / new
        ct.w = float(ct.w) * ratio
        ct.h = float(ct.h) * ratio
        reason = "a finer image was added" if new < old else "the finest image was removed"
        _log(
            project, "crop_template_rescaled",
            field="panel.crop_template", old=before, new={"w": ct.w, "h": ct.h},
            note=(
                f"Reference pixel size changed from {old:.4g} to {new:.4g} µm because {reason}; "
                f"crop template rescaled by {ratio:.6g} to keep its physical size."
            ),
        )
    elif old is None and new is not None:
        known = {round(s, 9) for s in (blot_pixel_size_um(project, b) for b in panel.blots) if s}
        if len(known) > 1:
            _log(
                project, "crop_template_legacy_interpretation",
                field="panel.crop_template", old=None, new={"w": ct.w, "h": ct.h},
                note=(
                    "Warning: this project already mixes pixel sizes "
                    f"({', '.join(f'{s:.4g}' for s in sorted(known))} µm). The existing crop "
                    f"template is interpreted as reference pixels ({new:.4g} µm); blots with "
                    "coarser pixels are now cropped to the same physical size and scaled for display."
                ),
            )
    return True


def scale_warnings(project: Project) -> list[str]:
    """Non-blocking warnings for the Figure tab and the integrity report."""
    warnings: list[str] = []
    blots = project.panel.blots
    known = [b.id for b in blots if blot_pixel_size_um(project, b) is not None]
    unknown = [b.id for b in blots if blot_pixel_size_um(project, b) is None]
    if known and unknown:
        warnings.append(
            "Mixed physical scale: "
            f"{', '.join(unknown)} {'has' if len(unknown) == 1 else 'have'} no known pixel size "
            "and {} drawn 1:1 (f = 1), while {} {} scaled to the reference pixel size "
            "({:.4g} µm). Membrane widths may not match.".format(
                "is" if len(unknown) == 1 else "are",
                ", ".join(known),
                "is" if len(known) == 1 else "are",
                project.panel.reference_pixel_size_um or 0.0,
            )
        )
    for b in blots:
        bp, op = blot_pixel_size_um(project, b), overlay_pixel_size_um(project, b)
        if bp is not None and op is not None and not math.isclose(bp, op, rel_tol=_OVERLAY_MISMATCH_RTOL):
            warnings.append(
                f"{b.id}: membrane overlay pixel size ({op:.4g} µm) differs from the blot's "
                f"({bp:.4g} µm). The overlay is drawn unscaled and may not align."
            )
    return warnings


def blot_scale_record(project: Project, blot) -> dict[str, Any]:
    """Per-blot physical-scale provenance for the integrity reports."""
    asset = project.assets.get(blot.asset_sha256)
    meta = getattr(asset, "acquisition_metadata", None) if asset is not None else None
    meta = meta if isinstance(meta, dict) else {}
    px = scaling_pixel_size_um(asset)
    f = blot_scale_factor(project, blot)
    display_scale = 1.0 / f
    nw, nh = native_crop_size(project, blot)

    notes: list[str] = []
    binning = meta.get("binning") if meta.get("pixel_size_source") == IQ800_PIXEL_SIZE_SOURCE else None
    if binning and str(binning).replace(" ", "").lower() != "1x1":
        notes.append(BINNING_NOTE)
    if meta.get("pixel_size_source") == IQ800_PIXEL_SIZE_SOURCE and px is None:
        notes.append(
            "Recorded pixel size not used for scaling: it disagrees with the recorded "
            "image area by more than 10%."
        )

    blot_warnings = [w for w in scale_warnings(project) if w.startswith(f"{blot.id}:")]
    if px is None and any(blot_pixel_size_um(project, b) is not None for b in project.panel.blots):
        blot_warnings.append(
            f"{blot.id}: no known pixel size; drawn 1:1 (f = 1) in a panel that is otherwise scaled."
        )

    return {
        "pixel_size_um": px,
        "pixel_size_source": IQ800_PIXEL_SIZE_SOURCE if px is not None else None,
        "binning": binning,
        "image_area_mm": meta.get("image_area_mm") if meta.get("pixel_size_source") == IQ800_PIXEL_SIZE_SOURCE else None,
        "reference_pixel_size_um": project.panel.reference_pixel_size_um,
        # f = reference / pixel size; the native crop (template x f) is drawn
        # at display_scale = 1 / f.
        "scale_factor_f": f,
        "display_scale": display_scale,
        "native_crop_px": {"w": int(round(nw)), "h": int(round(nh))},
        "display_interpolation": DISPLAY_INTERPOLATION_NONE if f == 1.0 else DISPLAY_INTERPOLATION_SCALED,
        "notes": notes,
        "warnings": blot_warnings,
    }
