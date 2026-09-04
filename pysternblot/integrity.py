# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .image_utils import get_bit_depth, load_image_as_uint16, crop_uint16, compute_saturation_stats
from .logchain import verify_log_chain
from .models import Project
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
    "not_assessed" | "clean" | "dust" | "warning".

    None means "not assessed" (an asset imported by an earlier version) —
    it must never be reported as "clean".
    """
    if sat is None:
        return "not_assessed", "Not assessed (imported by an earlier version)."

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
    effective crop for the blot this asset belongs to (panel.crop_template
    supplies w/h; blot.crop supplies x/y). When present, crop-region
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

    from PIL import Image
    with Image.open(path) as im:
        mode = im.mode
        width, height = im.size

    raw_depth = get_bit_depth(path)
    bit_depth = raw_depth if raw_depth > 0 else None

    bit_depth_warning = (
        "8-bit image: limited dynamic range. Not recommended for quantification purposes. "
        "16-bit is recommended."
        if bit_depth == 8 else None
    )

    saturation = getattr(asset, "saturation", None) if asset else None

    saturation_crop_region = None
    if crop_rect is not None and bit_depth is not None:
        x, y, w, h = crop_rect
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
        "width_px": width,
        "height_px": height,
        "acquisition_metadata": getattr(asset, "acquisition_metadata", None) if asset else None,
        "saturation": saturation.model_dump() if saturation else None,
        "saturation_crop_region": (
            saturation_crop_region.model_dump() if saturation_crop_region else None
        ),
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
            crop_rect=(crop.x, crop.y, project.panel.crop_template.w, project.panel.crop_template.h),
        ),
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


def build_integrity_report(
    project: Project,
    workspace: Workspace,
    project_json_path: str | Path | None = None,
    exported_files: list[str | Path] | None = None,
) -> dict[str, Any]:
    exported_files = exported_files or []

    report = {
        "schema": "pysternblot.integrity_report.v2",
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
        },
        "blots": [
            _blot_record(workspace, project, blot)
            for blot in project.panel.blots
        ],
        "exports": [
            {
                "path": str(path),
                "sha256": sha256_file(str(path)) if Path(path).exists() else None,
            }
            for path in exported_files
        ],
    }

    return report


def write_integrity_json(report: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_integrity_html(report: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)

    rows = []
    for blot in report["blots"]:
        src = blot["source_image"]
        ops = blot["operations"]
        overlay = blot["overlay"]

        if src.get("bit_depth") == 8:
            bit_depth_cell = (
                '<td style="background:#fef3c7;color:#92400e;font-weight:bold;">'
                "8-bit ⚠ Not recommended for quantification</td>"
            )
        else:
            bit_depth_cell = f'<td>{src.get("bit_depth", "")}</td>'

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

        if sat_severity == "warning" or crop_severity == "warning":
            sat_style = "background:#fef3c7;color:#92400e;font-weight:bold;"
        elif sat_severity == "not_assessed":
            sat_style = "background:#f3f4f6;color:#4b5563;"
        else:
            sat_style = ""
        saturation_cell = f'<td style="{sat_style}">{"<br>".join(sat_lines)}</td>'

        acq = src.get("acquisition_metadata") or {}
        if acq:
            acq_parts = []
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
          <td>x={ops["crop"]["x"]}, y={ops["crop"]["y"]}, w={ops["crop"]["w"]}, h={ops["crop"]["h"]}</td>
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
<th>Crop</th>
<th>Rotation</th>
<th>Levels</th>
<th>Overlay</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>

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

    report["schema"] = "pysternblot.detailed_integrity_report.v2"
    report["operation_log"] = [
        entry.model_dump()
        for entry in getattr(project, "operation_log", [])
    ]

    return report