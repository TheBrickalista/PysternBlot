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

    def ensure(self) -> None:
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

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
            },
        }

        proj_dir = self.projects_dir / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        path = proj_dir / "project.json"
        path.write_text(json.dumps(project_data, indent=2), encoding="utf-8")
        return path
