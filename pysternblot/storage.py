# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from .models import Project
import datetime, uuid
from PySide6.QtGui import QImage, QTransform
from PySide6.QtCore import Qt

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

@dataclass
class Workspace:
    root: Path

    @property
    def assets_dir(self) -> Path: return self.root / "assets"
    @property
    def projects_dir(self) -> Path: return self.root / "projects"
    @property
    def presets_dir(self) -> Path: return self.root / "presets"

    def ensure(self) -> None:
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.presets_dir.mkdir(parents=True, exist_ok=True)

        # Legend suggestions history (editable dropdown memory)
        sugg = self.presets_dir / "legend_suggestions.json"
        if not sugg.exists():
            sugg.write_text('{"items":[]}\n', encoding="utf-8")

    def import_asset(self, src_path: str) -> tuple[str, Path]:
        self.ensure()
        src = Path(src_path)
        digest = sha256_file(str(src))
        dest_dir = self.assets_dir / digest
        dest_dir.mkdir(parents=True, exist_ok=True)
        ext = src.suffix.lower() or ".bin"
        dest_file = dest_dir / f"original{ext}"
        if not dest_file.exists():
            dest_file.write_bytes(src.read_bytes())
        return digest, dest_file

    def save_project(self, project: Project) -> Path:
        self.ensure()
        proj_dir = self.projects_dir / project.project.id
        proj_dir.mkdir(parents=True, exist_ok=True)
        path = proj_dir / "project.json"
        path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_project(self, project_json_path: str) -> Project:
        data = json.loads(Path(project_json_path).read_text(encoding="utf-8"))
        return Project.model_validate(data)
    
    def load_legend_suggestions(self) -> list[str]:
        self.ensure()
        path = self.presets_dir / "legend_suggestions.json"
        if not path.exists():
            path.write_text('{"items":[]}\n', encoding="utf-8")
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("items", [])
            # unique + stable order
            seen = set()
            out = []
            for s in items:
                s = str(s).strip()
                if s and s not in seen:
                    out.append(s)
                    seen.add(s)
            return out
        except Exception:
            return []

    def save_legend_suggestions(self, items: list[str]) -> None:
        self.ensure()
        path = self.presets_dir / "legend_suggestions.json"
        seen = set()
        out = []
        for s in items:
            s = str(s).strip()
            if s and s not in seen:
                out.append(s)
                seen.add(s)
        path.write_text(json.dumps({"items": out}, indent=2) + "\n", encoding="utf-8")
        
    def create_new_project(self, name: str, app_version: str = "0.1.0") -> Path:
        """
        Create a new project folder and a minimal project.json, return its path.
        """
        self.ensure()
        project_id = "proj_" + uuid.uuid4().hex[:10]
        now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        # Minimal but valid-ish structure for our current code paths.
        project_data = {
            "project": {
                "id": project_id,
                "name": name,
                "created_utc": now,
                "modified_utc": now,
                "app_version": app_version,
                "license": "GPL-3.0-only",
            },
            "assets": {},
            "marker_sets": [],
            "panel": {
                "style": {
                    "font_family": "Arial",
                    "font_size_pt": 10,
                    "top_header_height_px": 80,
                    "ladder_col_width_px": 60,
                    "protein_col_width_px": 120,
                    "gap_between_blots_px": 12,
                    "border_enabled": True,
                },
                "lane_layout": {
                    "mode": "manual_n_lanes",
                    "n_lanes_manual": 2,
                    "header_block": {
                        "left_title": "",
                        "groups": [{"label": "", "n_lanes": 2, "underline": True}],
                        "condition_rows": [{"values": ["", ""], "unit_right": ""}],
                        "span_rows": [],
                    },
                },
                "blots": [],
                "layout": {"stack_mode": "vertical_stack", "order": []},
                "legend": {"mode": "protein", "upper_rows": [], "lower_rows": []},
            },
        }

        proj_dir = self.projects_dir / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        path = proj_dir / "project.json"
        path.write_text(json.dumps(project_data, indent=2), encoding="utf-8")
        return path
    
    def asset_original_file(self, sha256: str) -> Path:
        """
        Return the stored original file path for an asset sha256.
        We store as assets/<sha>/original.<ext>
        """
        d = self.assets_dir / sha256
        if not d.exists():
            raise FileNotFoundError(f"Asset folder not found: {d}")
        # find original.*
        matches = list(d.glob("original.*"))
        if not matches:
            raise FileNotFoundError(f"No original.* found in {d}")
        return matches[0]

    def generate_crop_preview_png(self, sha256: str, crop: dict) -> Path:
        """
        Generate (or overwrite) a preview_crop.png for this asset sha256
        using the crop rectangle (absolute pixel coords).
        crop = {"x":..., "y":..., "w":..., "h":...}
        """
        self.ensure()
        original_path = self.asset_original_file(sha256)

        img = QImage(str(original_path))
        if img.isNull():
            raise ValueError(f"Could not load image as QImage: {original_path}")

        x = int(round(float(crop.get("x", 0))))
        y = int(round(float(crop.get("y", 0))))
        w = int(round(float(crop.get("w", img.width()))))
        h = int(round(float(crop.get("h", img.height()))))

        # clamp to bounds
        x = max(0, min(x, img.width() - 1))
        y = max(0, min(y, img.height() - 1))
        w = max(1, min(w, img.width() - x))
        h = max(1, min(h, img.height() - y))

        cropped = img.copy(x, y, w, h)

        out_path = (self.assets_dir / sha256) / "preview_crop.png"
        ok = cropped.save(str(out_path), "PNG")
        if not ok:
            raise IOError(f"Failed to save preview PNG: {out_path}")
        return out_path
    
    def ensure_blot_crop_preview(self, blot) -> Path:
        """
        Generate/update assets/<sha256>/preview_crop.png from the blot settings.
        Rotation is applied first, then crop is taken in rotated-image space.
        """
        self.ensure()

        original_path = self.asset_original_file(blot.asset_sha256)

        img = QImage(str(original_path))
        if img.isNull():
            raise ValueError(f"Could not load image as QImage: {original_path}")

        rotation_deg = float(getattr(getattr(blot, "display", None), "rotation_deg", 0.0) or 0.0)
        if abs(rotation_deg) > 1e-6:
            tr = QTransform()
            tr.rotate(rotation_deg)
            img = img.transformed(tr, Qt.SmoothTransformation)

        c = blot.crop
        x = int(round(float(c.x)))
        y = int(round(float(c.y)))
        w = int(round(float(c.w)))
        h = int(round(float(c.h)))

        if w < 1:
            w = 1
        if h < 1:
            h = 1

        # Clamp crop to rotated image bounds
        x = max(0, min(x, img.width() - 1))
        y = max(0, min(y, img.height() - 1))
        w = min(w, img.width() - x)
        h = min(h, img.height() - y)

        cropped = img.copy(x, y, w, h)

        out_path = (self.assets_dir / blot.asset_sha256) / "preview_crop.png"
        ok = cropped.save(str(out_path), "PNG")
        if not ok:
            raise IOError(f"Failed to save preview PNG: {out_path}")

        return out_path