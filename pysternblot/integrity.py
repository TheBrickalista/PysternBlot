# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import html
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, UnidentifiedImageError

from . import __version__
from .image_utils import (
    get_bit_depth,
    get_source_bits,
    load_image_as_uint16,
    load_tiff_source,
    crop_uint16,
    compute_saturation_stats,
)
from .jsonsafe import dumps_strict
from .logchain import verify_log_chain
from .physical_scale import blot_scale_record, native_crop_size, scale_warnings
from .models import Project, SaturationStats
from .storage import Workspace, sha256_file


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --- Saturation reporting thresholds -----------------------------------------
# A single hot pixel from dust/fibre is common and harmless; a saturated band
# is a solid, contiguous region of clipped signal. 3x3 binary erosion of the
# saturation mask removes isolated specks and one-pixel-wide structures,
# leaving only solid regions. SATURATION_SOLID_PIXEL_THRESHOLD is the minimum
# number of eroded ("solid") pixels required before a report escalates from
# an informational note to an amber warning.
#
# 1 was chosen because a pixel that survives 3x3 erosion already has all 8
# neighbours saturated too — by construction that is no longer an isolated
# speck, it is the core of a real clipped region. Raise this if erosion alone
# proves too sensitive on real acquisition noise (e.g. clustered hot pixels
# from a dirty scanner glass that are not a genuine saturated band).
SATURATION_SOLID_PIXEL_THRESHOLD = 1


def _saturation_message(sat: dict[str, Any] | None) -> tuple[str, str]:
    """
    Classify a whole-image or crop-region SaturationStats dict.

    Returns (severity, message). severity is one of:
    "not_assessed" | "not_assessable" | "clean" | "dust" | "warning".

    None means "not assessed" (an asset imported by an earlier version) —
    it must never be reported as "clean". A non-None dict with
    assessable=False means "not assessable" — a float source has no fixed
    detector ceiling to test against, a different claim from "not assessed":
    this asset WAS actively evaluated, and the answer is that the question
    does not apply.
    """
    if sat is None:
        return "not_assessed", "Not assessed (imported by an earlier version)."

    if not sat.get("assessable", True):
        return (
            "not_assessable",
            "Not assessable (float source has no fixed detector ceiling to test against).",
        )

    saturated = sat["saturated_count"]
    solid = sat["solid_saturated_count"]

    if saturated == 0:
        return "clean", "None."

    if solid < SATURATION_SOLID_PIXEL_THRESHOLD:
        return "dust", f"{saturated} isolated pixel(s) (no solid regions)."

    return "warning", f"{saturated} saturated pixel(s), {solid} in solid regions."


def _saturation_crop_message(sat: dict[str, Any] | None) -> tuple[str, str]:
    """Like _saturation_message, but a warning is worded to say the displayed
    panel itself — not just the source image — contains clipped signal."""
    severity, message = _saturation_message(sat)
    if severity == "warning":
        message = (
            f"Displayed panel contains clipped signal: {sat['saturated_count']} "
            f"saturated pixel(s) within the crop, {sat['solid_saturated_count']} "
            f"in solid regions."
        )
    return severity, message


def _asset_info(
    workspace: Workspace,
    project: Project,
    sha256: str,
    crop_rect: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """
    crop_rect, if given, is (x, y, w, h) in source-image pixel space — the
    effective crop for the blot this asset belongs to (panel.crop_template,
    converted to the blot's native pixels, supplies w/h; blot.crop supplies
    x/y). When present, crop-region
    saturation is additionally computed at report time from the current
    crop, since only whole-image saturation is a fixed fact recorded at
    import — crop-region saturation changes as the user re-crops.
    """
    path = workspace.asset_original_file(sha256)
    asset = project.assets.get(sha256)

    # Guard: bit depth must always be read from the original asset, never a preview
    if "preview" in path.name:
        raise RuntimeError(
            f"Source bit depth must be read from the original asset, not a preview: {path}"
        )

    # Pillow's im.mode/im.size is the exact, unchanged path for every source
    # that already worked (uint8/uint16/etc.) — it is only bypassed when
    # Pillow cannot open the file at all (e.g. a tiled float16 TIFF), in
    # which case the same shared reader the loader uses supplies width/height.
    try:
        with Image.open(path) as im:
            mode = im.mode
            width, height = im.size
    except (UnidentifiedImageError, OSError):
        arr_for_shape, source_dtype = load_tiff_source(path)
        height, width = arr_for_shape.shape[:2]
        mode = source_dtype

    raw_depth = get_bit_depth(path)
    bit_depth = raw_depth if raw_depth > 0 else None
    sample_format = "float" if bit_depth == 32 else ("uint" if bit_depth else None)
    source_bits = get_source_bits(path)

    bit_depth_warning = (
        "8-bit image: limited dynamic range. Not recommended for quantification purposes. "
        "16-bit is recommended."
        if bit_depth == 8 else None
    )

    saturation = getattr(asset, "saturation", None) if asset else None
    float_display_scale = getattr(asset, "float_display_scale", None) if asset else None

    float_scale_warning = None
    if float_display_scale and float_display_scale.get("negative_clipped_count"):
        float_scale_warning = (
            f"{float_display_scale['negative_clipped_count']} negative pixel(s) clipped to 0 "
            f"when building the display representation (source min: "
            f"{float_display_scale.get('source_min')})."
        )

    saturation_crop_region = None
    if crop_rect is not None and bit_depth is not None:
        x, y, w, h = crop_rect
        if bit_depth == 32:
            # Float source: the bridged (display-only) uint16 array has a
            # pixel at 65535 by construction and must never be tested for
            # saturation. Compute from the true float array instead, and
            # the result is always not-assessable, same as the whole-image
            # record — this is a property of the source, not of the crop.
            arr, _source_dtype = load_tiff_source(path)
            cropped = crop_uint16(arr, int(round(x)), int(round(y)), int(round(w)), int(round(h)))
            finite = cropped[np.isfinite(cropped)]
            crop_max = float(finite.max()) if finite.size else 0.0
            saturation_crop_region = SaturationStats(
                max_value=crop_max,
                total_pixels=int(cropped.size),
                assessable=False,
            )
        else:
            arr = load_image_as_uint16(path)
            cropped = crop_uint16(arr, int(round(x)), int(round(y)), int(round(w)), int(round(h)))
            saturation_crop_region = compute_saturation_stats(cropped, bit_depth)

    return {
        "sha256": sha256,
        "stored_original_path": str(path),
        "stored_original_sha256_check": sha256_file(str(path)),
        "original_source_path": getattr(asset, "original_source_path", None) if asset else None,
        "filename": path.name,
        "image_mode": mode,
        "bit_depth": bit_depth,
        "bit_depth_warning": bit_depth_warning,
        "sample_format": sample_format,          # "uint" | "float" | None
        "source_bits": source_bits,               # true on-disk BitsPerSample; 16 for a float16 source
        "width_px": width,
        "height_px": height,
        "acquisition_metadata": getattr(asset, "acquisition_metadata", None) if asset else None,
        "saturation": saturation.model_dump() if saturation else None,
        "saturation_crop_region": (
            saturation_crop_region.model_dump() if saturation_crop_region else None
        ),
        "float_display_scale": float_display_scale,
        "float_scale_warning": float_scale_warning,
    }


def _marker_set_name(project: Project, marker_set_id: str | None) -> str | None:
    if not marker_set_id:
        return None
    for ms in project.marker_sets:
        if ms.id == marker_set_id:
            return ms.name
    return None


def _blot_record(workspace: Workspace, project: Project, blot) -> dict[str, Any]:
    display = blot.display
    crop = blot.crop
    native_w, native_h = native_crop_size(project, blot)

    _gamma = float(display.levels_gamma)
    gamma_warning = (
        f"Nonlinear gamma adjustment applied (γ = {_gamma:.2f}). "
        f"This is a permitted display adjustment but MUST be disclosed in the figure "
        f"legend or Methods per journal image-integrity guidelines (e.g. Nature, JCB). "
        f"Not suitable for densitometric quantification."
        if abs(_gamma - 1.0) > 1e-3 else None
    )

    # For NIR blots, rendering uses per-channel display, not blot.display.
    # Inspect each channel's gamma independently so non-default channel gammas
    # are not silently missed.
    if getattr(blot, "is_nir", lambda: False)() and getattr(blot, "channels", None):
        nir_flagged = [
            f"ch{ch.channel_index} (γ={float(ch.display.levels_gamma):.2f})"
            for ch in blot.channels
            if abs(float(ch.display.levels_gamma) - 1.0) > 1e-3
        ]
        if nir_flagged:
            nir_msg = (
                f"Nonlinear gamma on NIR channel(s): {', '.join(nir_flagged)}. "
                f"Permitted but must be declared in figure legend/Methods "
                f"(Nature, JCB image-integrity guidelines)."
            )
            gamma_warning = f"{gamma_warning} {nir_msg}" if gamma_warning else nir_msg

    record = {
        "blot_id": blot.id,
        "protein_label": {
            "text": blot.protein_label.text,
            "font_size_pt": blot.protein_label.font_size_pt,
        },
        "gamma_warning": gamma_warning,
        "source_image": _asset_info(
            workspace, project, blot.asset_sha256,
            crop_rect=(crop.x, crop.y, native_w, native_h),
        ),
        "physical_scale": blot_scale_record(project, blot),
        "operations": {
            "crop": {
                "x": crop.x,
                "y": crop.y,
                "w": crop.w,
                "h": crop.h,
                "mode": crop.mode,
                "ladder_anchor": crop.ladder_anchor,
            },
            "rotation_deg": display.rotation_deg,
            "levels": {
                "black": display.levels_black,
                "white": display.levels_white,
                "gamma": display.levels_gamma,
            },
            "invert": display.invert,
            "auto_contrast": display.auto_contrast,
        },
        "overlay": {
            "present": blot.overlay_asset_sha256 is not None,
            "asset": (
                _asset_info(workspace, project, blot.overlay_asset_sha256)
                if blot.overlay_asset_sha256
                else None
            ),
            "visible": display.overlay_visible,
            "alpha": display.overlay_alpha,
        },
        "ladder": {
            "lane_index": blot.ladder.lane_index,
            "marker_set_id": blot.ladder.marker_set_id,
            "marker_set_name": _marker_set_name(project, blot.ladder.marker_set_id),
            "show_ticks": blot.ladder.show_ticks,
            "calibration_points": [
                {"y_px": p.y_px, "kda": p.kda}
                for p in blot.ladder.calibration_points
            ],
            "fit": blot.ladder.fit.model_dump() if blot.ladder.fit else None,
        },
        "overlay_ladder": (
            blot.overlay_ladder.model_dump()
            if getattr(blot, "overlay_ladder", None) is not None
            else None
        ),
    }

    return record


# Operations that record a file written by Pystern Blot, and the format to
# assume for entries logged before export_generated carried {"format": ...}.
_EXPORT_OPERATIONS = ("export_generated", "source_asset_exported")
_LEGACY_EXPORT_FORMATS = {
    "final_png": "png",
    "legend_zone_png": "png",
    "final_pdf": "pdf",
    "final_svg": "svg",
    "original_annotated_tiff": "tiff",
    "source_asset": "source",
}
EXPORT_STATUSES = ("ok", "changed", "missing", "unreadable", "not_recorded", "superseded", "listed")


def _resolved_path_key(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return str(path)


def _current_file_hash(path: str, cache: dict) -> tuple[Optional[str], str]:
    """(sha256 or None, "present" | "missing" | "unreadable"); each distinct
    resolved path is hashed at most once per report."""
    key = _resolved_path_key(path)
    if key not in cache:
        p = Path(path).expanduser()
        if not p.is_file():
            cache[key] = (None, "missing")
        else:
            try:
                cache[key] = (sha256_file(str(p)), "present")
            except OSError:
                cache[key] = (None, "unreadable")
    return cache[key]


def collect_exports(project: Project) -> list[dict[str, Any]]:
    """One record per export_generated / source_asset_exported log entry, in
    log order, each re-verified against the file currently at its path.

    status:
      - "superseded": a later entry wrote the same (resolved) path; only the
        latest entry for a path is checked against the disk.
      - "not_recorded": no hash was recorded (exported by an earlier
        version); current_sha256 is still reported if the file exists.
      - "missing" / "unreadable": the file is not at the path / cannot be read.
      - "ok" / "changed": the file's current hash matches / differs.

    Malformed entries are skipped; this never raises.
    """
    candidates: list[dict[str, Any]] = []
    for index, entry in enumerate(getattr(project, "operation_log", []) or []):
        if entry.operation not in _EXPORT_OPERATIONS:
            continue
        value = entry.new_value
        if isinstance(value, dict):
            path = value.get("path")
            if not isinstance(path, str) or not path:
                continue
            fmt = value.get("format") if isinstance(value.get("format"), str) else None
            recorded = value.get("sha256") if isinstance(value.get("sha256"), str) else None
        elif isinstance(value, str) and value:
            path, fmt, recorded = value, None, None
        else:
            continue
        if fmt is None:
            fmt = _LEGACY_EXPORT_FORMATS.get(entry.field or "")
        if entry.operation == "source_asset_exported":
            # The source export copies the asset byte for byte and verifies
            # the copy, so the asset hash is the hash of the written file.
            recorded = entry.asset_sha256 if isinstance(entry.asset_sha256, str) else None
        candidates.append({
            "log_index": index,
            "operation": entry.operation,
            "field": entry.field,
            "format": fmt,
            "path": path,
            "timestamp_utc": entry.timestamp_utc,
            "target_id": entry.target_id,
            "asset_sha256": entry.asset_sha256,
            "recorded_sha256": recorded,
            "current_sha256": None,
            "status": None,
        })

    latest_for_path: dict[str, int] = {}
    for i, rec in enumerate(candidates):
        latest_for_path[_resolved_path_key(rec["path"])] = i

    cache: dict = {}
    for i, rec in enumerate(candidates):
        if latest_for_path[_resolved_path_key(rec["path"])] != i:
            rec["status"] = "superseded"
            continue
        current, state = _current_file_hash(rec["path"], cache)
        rec["current_sha256"] = current
        if rec["recorded_sha256"] is None:
            rec["status"] = "not_recorded"
        elif state != "present":
            rec["status"] = state
        else:
            rec["status"] = "ok" if current == rec["recorded_sha256"] else "changed"
    return candidates


def _listed_export(path: str | Path, cache: dict) -> dict[str, Any]:
    """A row for a path passed via exported_files (kept for API
    compatibility): no log entry and no recorded hash."""
    current, state = _current_file_hash(str(path), cache)
    return {
        "log_index": None,
        "operation": None,
        "field": None,
        "format": None,
        "path": str(path),
        "timestamp_utc": None,
        "target_id": None,
        "asset_sha256": None,
        "recorded_sha256": None,
        "current_sha256": current,
        "status": "listed" if state == "present" else state,
    }


def build_integrity_report(
    project: Project,
    workspace: Workspace,
    project_json_path: str | Path | None = None,
    exported_files: list[str | Path] | None = None,
) -> dict[str, Any]:
    exported_files = exported_files or []

    report = {
        "schema": "pysternblot.integrity_report.v3",
        "created_utc": _utc_now(),
        "pysternblot_version": __version__,
        "operation_log_chain": verify_log_chain(project).model_dump(),
        "system": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "project": {
            "id": project.project.id,
            "name": project.project.name,
            "created_utc": project.project.created_utc,
            "modified_utc": project.project.modified_utc,
            "app_version": project.project.app_version,
            "license": project.project.license,
            "project_json_path": str(project_json_path) if project_json_path else None,
            "project_json_sha256": (
                sha256_file(str(project_json_path))
                if project_json_path and Path(project_json_path).exists()
                else None
            ),
        },
        "panel": {
            "layout_order": list(project.panel.layout.order),
            "style": project.panel.style.model_dump(),
            "lane_layout": project.panel.lane_layout.model_dump(),
            "legend": project.panel.legend.model_dump(),
            "crop_template": project.panel.crop_template.model_dump(),
            "reference_pixel_size_um": project.panel.reference_pixel_size_um,
            "physical_scale_warnings": scale_warnings(project),
        },
        "blots": [
            _blot_record(workspace, project, blot)
            for blot in project.panel.blots
        ],
    }

    # Exports are derived from the operation log (each export_generated /
    # source_asset_exported entry, re-verified against the file on disk),
    # plus any paths passed explicitly via exported_files.
    listed_cache: dict = {}
    exports = collect_exports(project) + [_listed_export(path, listed_cache) for path in exported_files]
    report["exports"] = exports
    summary = {status: 0 for status in EXPORT_STATUSES}
    for rec in exports:
        summary[rec["status"]] = summary.get(rec["status"], 0) + 1
    summary["total"] = len(exports)
    report["exports_summary"] = summary

    return report


def write_integrity_json(report: dict[str, Any], path: str | Path) -> Path:
    """Write the report as strict RFC 8259 JSON: a non-finite float (e.g. one
    loaded from a project.json carrying NaN/Infinity tokens) is written as
    null, never as a NaN/Infinity token."""
    path = Path(path)
    path.write_text(dumps_strict(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


_EXPORT_STATUS_STYLE = {
    "ok": "background:#dcfce7;color:#166534;font-weight:bold;",
    "changed": "background:#fee2e2;color:#991b1b;font-weight:bold;",
    "unreadable": "background:#fef3c7;color:#92400e;font-weight:bold;",
    "missing": "background:#f3f4f6;color:#4b5563;",
    "not_recorded": "background:#f3f4f6;color:#4b5563;",
    "superseded": "background:#f3f4f6;color:#4b5563;",
    "listed": "background:#f3f4f6;color:#4b5563;",
}
_EXPORT_STATUS_TEXT = {
    "ok": "Matches the file on disk.",
    "changed": (
        "File at this path differs from the exported bytes (expected if edited in "
        "another application after export)."
    ),
    "missing": (
        "Not found at the recorded path (moved, renamed, or report generated on "
        "another machine). Verify by hash."
    ),
    "unreadable": "The file exists but could not be read.",
    "not_recorded": "Hash not recorded (exported by an earlier version).",
    "superseded": "Overwritten by a later export to the same path.",
    "listed": "Listed for this report; no hash recorded at export time.",
}


def _exports_html(exports: list[dict[str, Any]]) -> str:
    """The "Exported files" table. Every interpolated value is escaped:
    paths are chosen by the user."""
    esc = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
    intro = (
        "<p>The recorded SHA-256 identifies each file as written by Pystern Blot. "
        "Files re-encoded downstream (e.g. by a journal's submission system) will not match.</p>"
    )
    if not exports:
        return (
            "<h2>Exported files</h2>\n" + intro +
            "\n<p>No exports recorded in this project's operation log.</p>"
        )
    rows = []
    for rec in exports:
        status = rec.get("status") or ""
        kind = " / ".join(esc(v) for v in (rec.get("format"), rec.get("field")) if v)
        status_html = f"<b>{esc(status)}</b><br>{esc(_EXPORT_STATUS_TEXT.get(status, ''))}"
        if status == "changed" and rec.get("current_sha256"):
            status_html += f"<br>Current: <code>{esc(rec['current_sha256'])}</code>"
        rows.append(
            "<tr>"
            f"<td>{esc(rec.get('timestamp_utc'))}</td>"
            f"<td>{kind}</td>"
            f"<td>{esc(rec.get('target_id'))}</td>"
            f"<td><code>{esc(rec.get('path'))}</code></td>"
            f"<td><code>{esc(rec.get('recorded_sha256'))}</code></td>"
            f'<td style="{_EXPORT_STATUS_STYLE.get(status, "")}">{status_html}</td>'
            "</tr>"
        )
    return (
        "<h2>Exported files</h2>\n" + intro + "\n<table>\n<thead>\n<tr>"
        "<th>Time UTC</th><th>Kind</th><th>Target</th><th>Path</th>"
        "<th>Recorded SHA-256</th><th>Status</th>"
        "</tr>\n</thead>\n<tbody>\n" + "\n".join(rows) + "\n</tbody>\n</table>"
    )


def write_integrity_html(report: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)

    rows = []
    for blot in report["blots"]:
        src = blot["source_image"]
        ops = blot["operations"]
        overlay = blot["overlay"]

        sample_format_val = src.get("sample_format")
        source_bits_val = src.get("source_bits")
        depth_suffix = ""
        if sample_format_val == "float":
            depth_suffix = (
                f" (float32 in memory; {source_bits_val}-bit float source)"
                if source_bits_val else " (float32 in memory)"
            )
        elif source_bits_val and source_bits_val != src.get("bit_depth"):
            depth_suffix = f" ({source_bits_val}-bit source)"

        if src.get("bit_depth") == 8:
            bit_depth_cell = (
                '<td style="background:#fef3c7;color:#92400e;font-weight:bold;">'
                f"8-bit ⚠ Not recommended for quantification{depth_suffix}</td>"
            )
        else:
            bit_depth_cell = f'<td>{src.get("bit_depth", "")}{depth_suffix}</td>'

        warning_text = src.get("bit_depth_warning") or ""

        gamma_warning_val = blot.get("gamma_warning") or ""
        if gamma_warning_val:
            gamma_cell = (
                '<td style="background:#fef3c7;color:#92400e;font-weight:bold;">'
                f"{gamma_warning_val}</td>"
            )
        else:
            gamma_cell = "<td></td>"

        sat_severity, sat_message = _saturation_message(src.get("saturation"))
        crop_severity, crop_message = _saturation_crop_message(src.get("saturation_crop_region"))

        sat_lines = [f"Whole image: {sat_message}"]
        if src.get("saturation_crop_region") is not None or crop_severity != "not_assessed":
            sat_lines.append(f"Crop region: {crop_message}")

        float_scale_warning_val = src.get("float_scale_warning") or ""
        if float_scale_warning_val:
            sat_lines.append(f"⚠ {float_scale_warning_val}")

        if sat_severity == "warning" or crop_severity == "warning" or float_scale_warning_val:
            sat_style = "background:#fef3c7;color:#92400e;font-weight:bold;"
        elif sat_severity == "not_assessed" or sat_severity == "not_assessable":
            sat_style = "background:#f3f4f6;color:#4b5563;"
        else:
            sat_style = ""
        saturation_cell = f'<td style="{sat_style}">{"<br>".join(sat_lines)}</td>'

        acq = src.get("acquisition_metadata") or {}
        if acq:
            acq_parts = []
            if acq.get("channel") is not None:
                acq_parts.append(f"<b>Channel: {acq['channel']}</b>")
            if acq.get("model"):
                acq_parts.append(f"Instrument: {acq['model']}")
            if acq.get("instrument_serial"):
                acq_parts.append(f"Serial: {acq['instrument_serial']}")
            if acq.get("serial_number"):
                acq_parts.append(f"Serial: {acq['serial_number']}")
            if acq.get("imaging_mode"):
                acq_parts.append(f"Mode: {acq['imaging_mode']}")
            if acq.get("exposure_s") is not None:
                acq_parts.append(f"Exposure: {acq['exposure_s']:g} s")
            if acq.get("binning"):
                acq_parts.append(f"Binning: {acq['binning']}")
            if acq.get("image_area_mm"):
                area = acq["image_area_mm"]
                acq_parts.append(f"Image area: {area[0]} × {area[1]} mm")
            if acq.get("software"):
                acq_parts.append(f"Software: {acq['software']}")
            if acq.get("datetime"):
                acq_parts.append(f"Acquired: {acq['datetime']}")
            if acq.get("pixel_size_um") is not None:
                acq_parts.append(f"Pixel size: {float(acq['pixel_size_um']):.1f} µm")
            if acq.get("scale_type"):
                acq_parts.append(f"<b>Scale: {acq['scale_type']}</b>")
            if acq.get("scan_mode"):
                acq_parts.append(f"Mode: {acq['scan_mode']}")
            if acq.get("scan_speed"):
                acq_parts.append(f"Speed: {acq['scan_speed']}")
            if acq.get("laser_name"):
                acq_parts.append(f"Laser: {acq['laser_name']}")
            if acq.get("pmt_voltage") is not None:
                acq_parts.append(f"PMT: {acq['pmt_voltage']} V")
            if acq.get("laser_power_mode"):
                acq_parts.append(f"Laser power: {acq['laser_power_mode']}")
            if acq.get("corrections"):
                corr_str = ", ".join(f"{k}={v}" for k, v in acq["corrections"].items())
                acq_parts.append(f"Corrections: {corr_str}")
            if acq.get("signal_process"):
                sp_str = ", ".join(f"{k}={v}" for k, v in acq["signal_process"].items())
                acq_parts.append(f"Signal: {sp_str}")
            acq_cell = f'<td style="font-size:11px;">{"<br>".join(acq_parts)}</td>'
        else:
            acq_cell = "<td></td>"

        scale = blot.get("physical_scale") or {}
        scale_parts = []
        if scale.get("pixel_size_um") is not None:
            scale_parts.append(
                f"Pixel size: {float(scale['pixel_size_um']):.1f} µm ({scale.get('pixel_size_source')})"
            )
        else:
            scale_parts.append("Pixel size: unknown (not scaled)")
        if scale.get("reference_pixel_size_um") is not None:
            scale_parts.append(f"Reference: {float(scale['reference_pixel_size_um']):.1f} µm")
        if scale:
            scale_parts.append(
                f"f = {float(scale.get('scale_factor_f', 1.0)):.4f} "
                f"(display scale {float(scale.get('display_scale', 1.0)):.4f})"
            )
            scale_parts.append(f"Interpolation: {scale.get('display_interpolation', '')}")
        for note in scale.get("notes") or []:
            scale_parts.append(f"Note: {note}")
        for warning in scale.get("warnings") or []:
            scale_parts.append(f"⚠ {warning}")
        scale_style = (
            "background:#fef3c7;color:#92400e;font-weight:bold;" if scale.get("warnings") else ""
        )
        scale_cell = f'<td style="font-size:11px;{scale_style}">{"<br>".join(scale_parts)}</td>'
        native = scale.get("native_crop_px") or {}
        crop_size = (
            f'w={native["w"]}, h={native["h"]}' if native
            else f'w={ops["crop"]["w"]}, h={ops["crop"]["h"]}'
        )

        rows.append(f"""
        <tr>
          <td>{blot["blot_id"]}</td>
          <td>{blot["protein_label"]["text"]}</td>
          <td><code>{src["sha256"]}</code></td>
          {bit_depth_cell}
          <td>{warning_text}</td>
          {gamma_cell}
          {saturation_cell}
          {acq_cell}
          <td>{src["width_px"]} × {src["height_px"]}</td>
          {scale_cell}
          <td>x={ops["crop"]["x"]}, y={ops["crop"]["y"]}, {crop_size}</td>
          <td>{ops["rotation_deg"]}</td>
          <td>{ops["levels"]["black"]}–{ops["levels"]["white"]}, γ={ops["levels"]["gamma"]}</td>
          <td>{overlay["present"]}</td>
        </tr>
        """)

    operation_rows = []
    for entry in report.get("operation_log", []):
        operation_rows.append(f"""
        <tr>
          <td>{entry.get("timestamp_utc", "")}</td>
          <td>{entry.get("operation", "")}</td>
          <td>{entry.get("target_type", "") or ""}</td>
          <td>{entry.get("target_id", "") or ""}</td>
          <td>{entry.get("field", "") or ""}</td>
          <td><code>{json.dumps(entry.get("old_value", None), ensure_ascii=False)}</code></td>
          <td><code>{json.dumps(entry.get("new_value", None), ensure_ascii=False)}</code></td>
          <td>{entry.get("note", "") or ""}</td>
        </tr>
        """)

    chain = report.get("operation_log_chain") or {}
    chain_status = chain.get("status")
    chain_message = chain.get("message", "")
    chain_style = {
        "ok": "background:#dcfce7;color:#166534;font-weight:bold;",
        "not_chained": "background:#f3f4f6;color:#4b5563;",
        "partial": "background:#fef3c7;color:#92400e;font-weight:bold;",
        "broken": "background:#fee2e2;color:#991b1b;font-weight:bold;",
    }.get(chain_status, "")
    chain_line = (
        f'<p style="{chain_style}padding:6px;">{chain_message}</p>' if chain_message else ""
    )

    operation_section = ""
    if operation_rows:
        operation_section = f"""
<h2>Chronological operation log</h2>
{chain_line}
<table>
<thead>
<tr>
<th>Time UTC</th>
<th>Operation</th>
<th>Target type</th>
<th>Target ID</th>
<th>Field</th>
<th>Old value</th>
<th>New value</th>
<th>Note</th>
</tr>
</thead>
<tbody>
{''.join(operation_rows)}
</tbody>
</table>
"""

    exports_section = _exports_html(report.get("exports") or [])

    panel_scale_warnings = (report.get("panel") or {}).get("physical_scale_warnings") or []
    scale_warnings_html = "".join(
        f'<p style="background:#fef3c7;color:#92400e;font-weight:bold;padding:6px;">⚠ {w}</p>'
        for w in panel_scale_warnings
    )

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Pystern Blot integrity report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #222; }}
h1, h2 {{ margin-bottom: 0.3em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ccc; padding: 6px; vertical-align: top; }}
th {{ background: #eee; }}
code {{ font-size: 11px; word-break: break-all; }}
.summary {{ background: #f7f7f7; padding: 12px; border: 1px solid #ddd; }}
</style>
</head>
<body>
<h1>Pystern Blot integrity report</h1>

<div class="summary">
<p><strong>Project:</strong> {report["project"]["name"]}</p>
<p><strong>Project ID:</strong> {report["project"]["id"]}</p>
<p><strong>Created UTC:</strong> {report["created_utc"]}</p>
<p><strong>Pystern Blot version:</strong> {report["pysternblot_version"]}</p>
<p><strong>Schema:</strong> {report["schema"]}</p>
</div>
{scale_warnings_html}

<h2>Blot provenance</h2>
<table>
<thead>
<tr>
<th>Blot</th>
<th>Protein</th>
<th>Source SHA256</th>
<th>Bit depth</th>
<th>Bit depth warning</th>
<th>Gamma warning</th>
<th>Saturation</th>
<th>Acquisition</th>
<th>Source size</th>
<th>Physical scale</th>
<th>Crop (native px)</th>
<th>Rotation</th>
<th>Levels</th>
<th>Overlay</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>

{exports_section}

{operation_section}

<h2>Machine-readable report</h2>
<p>The companion JSON file contains the complete project, panel, legend, ladder, crop, overlay and export provenance{" including the chronological operation log" if operation_rows else ""}.</p>

</body>
</html>
"""

    path.write_text(html, encoding="utf-8")
    return path


def build_detailed_integrity_report(
    project: Project,
    workspace: Workspace,
    project_json_path: str | Path | None = None,
    exported_files: list[str | Path] | None = None,
) -> dict[str, Any]:
    report = build_integrity_report(
        project=project,
        workspace=workspace,
        project_json_path=project_json_path,
        exported_files=exported_files,
    )

    report["schema"] = "pysternblot.detailed_integrity_report.v3"
    report["operation_log"] = [
        entry.model_dump()
        for entry in getattr(project, "operation_log", [])
    ]

    return report