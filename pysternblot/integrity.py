# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from . import __version__
from .models import Project
from .storage import Workspace, sha256_file


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _asset_info(workspace: Workspace, project: Project, sha256: str) -> dict[str, Any]:
    path = workspace.asset_original_file(sha256)
    asset = project.assets.get(sha256)

    with Image.open(path) as im:
        mode = im.mode
        width, height = im.size

    bit_depth = 16 if mode in ("I;16", "I;16L", "I;16B") else None

    return {
        "sha256": sha256,
        "stored_original_path": str(path),
        "stored_original_sha256_check": sha256_file(str(path)),
        "original_source_path": getattr(asset, "original_source_path", None) if asset else None,
        "filename": path.name,
        "image_mode": mode,
        "bit_depth": bit_depth,
        "width_px": width,
        "height_px": height,
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

    record = {
        "blot_id": blot.id,
        "protein_label": {
            "text": blot.protein_label.text,
            "font_size_pt": blot.protein_label.font_size_pt,
        },
        "source_image": _asset_info(workspace, project, blot.asset_sha256),
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
        "schema": "pysternblot.integrity_report.v1",
        "created_utc": _utc_now(),
        "pysternblot_version": __version__,
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

        rows.append(f"""
        <tr>
          <td>{blot["blot_id"]}</td>
          <td>{blot["protein_label"]["text"]}</td>
          <td><code>{src["sha256"]}</code></td>
          <td>{src["bit_depth"]}</td>
          <td>{src["width_px"]} × {src["height_px"]}</td>
          <td>x={ops["crop"]["x"]}, y={ops["crop"]["y"]}, w={ops["crop"]["w"]}, h={ops["crop"]["h"]}</td>
          <td>{ops["rotation_deg"]}</td>
          <td>{ops["levels"]["black"]}–{ops["levels"]["white"]}, γ={ops["levels"]["gamma"]}</td>
          <td>{overlay["present"]}</td>
        </tr>
        """)

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

<h2>Machine-readable report</h2>
<p>The companion JSON file contains the complete project, panel, legend, ladder, crop, overlay and export provenance.</p>

</body>
</html>
"""

    path.write_text(html, encoding="utf-8")
    return path