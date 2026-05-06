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
from .models import Project, MarkerSet, MarkerSetLibrary, MarkerBand, CropTemplate
import datetime, uuid

from .image_utils import (
    load_image_uint16,
    apply_levels_uint16,
    rotate_uint16,
    crop_uint16,
    save_uint16_tiff,
)

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

        # Protein label suggestions history (editable dropdown memory)
        protein_sugg = self.presets_dir / "protein_label_suggestions.json"
        if not protein_sugg.exists():
            protein_sugg.write_text('{"items":[]}\n', encoding="utf-8")

        marker_sets = self.presets_dir / "protein_ladders.json"
        if not marker_sets.exists():
            default = MarkerSetLibrary(items=[
                MarkerSet(
                    id="pageruler_plus_prestained",
                    name="PageRuler Plus Prestained",
                    unit="kDa",
                    bands=[
                        MarkerBand(kda=250, label="250"),
                        MarkerBand(kda=130, label="130"),
                        MarkerBand(kda=100, label="100", highlight=True),
                        MarkerBand(kda=70, label="70"),
                        MarkerBand(kda=55, label="55", highlight=True),
                        MarkerBand(kda=35, label="35"),
                        MarkerBand(kda=25, label="25"),
                        MarkerBand(kda=15, label="15"),
                        MarkerBand(kda=10, label="10"),
                    ],
                )
            ])
            marker_sets.write_text(default.model_dump_json(indent=2) + "\n", encoding="utf-8")

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

    def rename_project(self, project: Project, new_name: str) -> Path:
        from .models import OperationLogEntry
        old_name = project.project.name
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        project.project.name = new_name
        project.project.modified_utc = now
        project.operation_log.append(
            OperationLogEntry(
                timestamp_utc=now,
                operation="project_renamed",
                target_type="project",
                target_id=project.project.id,
                field="project.name",
                old_value=old_name,
                new_value=new_name,
            )
        )
        return self.save_project(project)

    def load_project(self, project_json_path: str) -> Project:
        data = json.loads(Path(project_json_path).read_text(encoding="utf-8"))
        project = Project.model_validate(data)
        # Migrate old projects that pre-date crop_template: seed from first blot's crop w/h.
        if "crop_template" not in data.get("panel", {}) and project.panel.blots:
            first = project.panel.blots[0]
            project.panel.crop_template = CropTemplate(w=first.crop.w, h=first.crop.h)
        return project
    
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

    def load_protein_label_suggestions(self) -> list[str]:
        self.ensure()
        path = self.presets_dir / "protein_label_suggestions.json"
        if not path.exists():
            path.write_text('{"items":[]}\n', encoding="utf-8")
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("items", [])
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

    def save_protein_label_suggestions(self, items: list[str]) -> None:
        self.ensure()
        path = self.presets_dir / "protein_label_suggestions.json"
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
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

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
                    "border_width_px": 1,
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
                "crop_template": {"w": 300.0, "h": 200.0},
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

    def generate_crop_preview_tiff(self, sha256: str, crop: dict) -> Path:
        """
        Generate (or overwrite) a 16-bit preview_crop.tif for this asset sha256
        using the crop rectangle (absolute pixel coords).
        """
        self.ensure()
        original_path = self.asset_original_file(sha256)

        img = load_image_uint16(original_path)

        x = int(round(float(crop.get("x", 0))))
        y = int(round(float(crop.get("y", 0))))
        w = int(round(float(crop.get("w", img.shape[1]))))
        h = int(round(float(crop.get("h", img.shape[0]))))

        cropped = crop_uint16(img, x, y, w, h)

        out_path = (self.assets_dir / sha256) / "preview_crop.tif"
        save_uint16_tiff(cropped, out_path)
        return out_path
    
    def ensure_blot_crop_preview(self, blot, panel) -> Path:
        """
        Generate/update assets/<sha256>/preview_crop_<id>.tif from the blot settings.
        w/h come from panel.crop_template so all blots share the same crop size.
        Rotation is applied first, then crop is taken in rotated-image space.
        All processing stays in 16-bit.
        """
        self.ensure()

        original_path = self.asset_original_file(blot.asset_sha256)
        img = load_image_uint16(original_path)

        display = getattr(blot, "display", None)
        black = int(getattr(display, "levels_black", 0))
        white = int(getattr(display, "levels_white", 65535))
        gamma = float(getattr(display, "levels_gamma", 1.0))
        invert = bool(getattr(display, "invert", False))

        img = apply_levels_uint16(img, black, white, gamma, invert)

        rotation_deg = float(getattr(display, "rotation_deg", 0.0) or 0.0)
        img = rotate_uint16(img, rotation_deg, expand=False)

        c = blot.crop
        x = int(round(float(c.x)))
        y = int(round(float(c.y)))
        # w/h come from the shared crop template, not the per-blot crop
        w = int(round(float(panel.crop_template.w)))
        h = int(round(float(panel.crop_template.h)))

        cropped = crop_uint16(img, x, y, w, h)

        out_path = (self.assets_dir / blot.asset_sha256) / f"preview_crop_{blot.id}.tif"
        save_uint16_tiff(cropped, out_path)

        return out_path
    
    def marker_sets_file(self) -> Path:
        self.ensure()
        return self.presets_dir / "protein_ladders.json"

    def load_marker_sets(self) -> MarkerSetLibrary:
        self.ensure()
        path = self.presets_dir / "protein_ladders.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return MarkerSetLibrary.model_validate(data)
        except Exception:
            return MarkerSetLibrary(items=[])

    def save_marker_sets(self, library: MarkerSetLibrary) -> None:
        self.ensure()
        path = self.presets_dir / "protein_ladders.json"
        path.write_text(library.model_dump_json(indent=2) + "\n", encoding="utf-8")
    
    