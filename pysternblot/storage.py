# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
import hashlib, json, re, zipfile
from dataclasses import dataclass, field
from pathlib import Path
from .models import (
    BlotChannel,
    CropTemplate,
    MarkerBand,
    MarkerSet,
    MarkerSetLibrary,
    OperationLogEntry,
    Project,
)
import datetime, uuid
from PIL import Image


@dataclass
class ImportArchiveResult:
    imported_project_ids: list[str] = field(default_factory=list)
    skipped_project_ids: list[str] = field(default_factory=list)
    imported_asset_count: int = 0
    skipped_asset_count: int = 0
    integrity_errors: list[str] = field(default_factory=list)

from .image_utils import (
    load_image_uint16,
    apply_levels_uint16,
    rotate_uint16,
    crop_uint16,
    save_uint16_tiff,
)

def parse_typhoon_tag270(tag_text: str) -> dict:
    """
    Parse the key=value metadata from TIFF Tag 270 produced by Cytiva Typhoon /
    Amersham TYPHOON scanners.

    Lines are delimited by CRLF, CR, or bare LF.  The string may end with a
    null terminator.  Never raises — malformed input returns whatever was
    successfully parsed, with remaining keys set to None.

    Keys returned:
        serial_number   str   e.g. "36651188"
        datetime        str   e.g. "Thu May  7 14:32:30 2026"
        laser_nm        int   e.g. 785  (from "Laser name=785 nm")
        filter_name     str   e.g. "IRlong 825BP30"  (strips "Through + " prefix)
        scan_number     str   e.g. "1/2"
        channel_index   int   0-based  (derived from scan_number numerator − 1)
        channel_total   int   e.g. 2   (denominator of scan_number)
        pixel_size_um   float e.g. 50.0
        pmt_hv_v        int   e.g. 399
        software        str   e.g. "Amersham TYPHOON Scanner Control Software 4.0.0.4"
    """
    result: dict = {
        "serial_number": None,
        "datetime": None,
        "laser_nm": None,
        "filter_name": None,
        "scan_number": None,
        "channel_index": None,
        "channel_total": None,
        "pixel_size_um": None,
        "pmt_hv_v": None,
        "software": None,
    }
    try:
        text = tag_text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\x00").strip()
        for line in text.split("\n"):
            line = line.strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            try:
                if key == "Serial number":
                    result["serial_number"] = value
                elif key == "Date time":
                    result["datetime"] = value
                elif key == "Laser name":
                    m = re.search(r"(\d+)", value)
                    if m:
                        result["laser_nm"] = int(m.group(1))
                elif key == "Filter name":
                    stripped = re.sub(r"^[Tt]hrough\s*\+\s*", "", value).strip()
                    result["filter_name"] = stripped
                elif key == "Scan number":
                    result["scan_number"] = value
                    parts = value.split("/")
                    if len(parts) == 2:
                        result["channel_index"] = int(parts[0]) - 1
                        result["channel_total"] = int(parts[1])
                elif key == "Pixel size":
                    m = re.search(r"([\d.]+)", value)
                    if m:
                        result["pixel_size_um"] = float(m.group(1))
                elif key == "PMT HV":
                    m = re.search(r"(\d+)", value)
                    if m:
                        result["pmt_hv_v"] = int(m.group(1))
                elif key == "Software":
                    result["software"] = value
            except Exception:
                pass
    except Exception:
        pass
    return result


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

    def load_antibody_name_suggestions(self) -> list[str]:
        self.ensure()
        path = self.presets_dir / "antibody_name_suggestions.json"
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

    def save_antibody_name_suggestions(self, items: list[str]) -> None:
        self.ensure()
        path = self.presets_dir / "antibody_name_suggestions.json"
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

    def import_nir_blot_typhoon(
        self,
        file_paths: list[Path],
        project: Project,
    ) -> list[BlotChannel]:
        """
        Import 1 or 2 Typhoon NIR channel files into the workspace and return
        a list of BlotChannel objects sorted by channel_index ascending.

        Each file is hashed and stored via import_asset (SHA256-deduplicated).
        Metadata is read from TIFF Tag 270 via parse_typhoon_tag270.
        One OperationLogEntry is appended to project.operation_log per channel.
        The caller is responsible for attaching the returned channels to a Blot
        and saving the project.
        """
        # Collect (channel_index, sha256, parsed_meta) for each file.
        entries: list[tuple[int, str, dict]] = []
        for i, fp in enumerate(file_paths):
            sha, _ = self.import_asset(str(fp))
            meta: dict = {}
            try:
                with Image.open(str(fp)) as im:
                    tag270 = im.tag_v2.get(270, "")
                meta = parse_typhoon_tag270(tag270)
            except Exception:
                pass
            # Fall back to file order if channel_index is not in metadata.
            idx = meta.get("channel_index")
            if idx is None:
                idx = i
            entries.append((idx, sha, meta))

        entries.sort(key=lambda e: e[0])

        now = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
        channels: list[BlotChannel] = []
        for channel_index, sha, meta in entries:
            filter_name = meta.get("filter_name") or ""
            wavelength_nm = meta.get("laser_nm")
            channel_total = meta.get("channel_total") or len(file_paths)

            note = (
                f"Typhoon: {filter_name}, {wavelength_nm}nm, "
                f"channel {channel_index + 1}/{channel_total}"
            )
            project.operation_log.append(
                OperationLogEntry(
                    timestamp_utc=now,
                    operation="nir_channel_imported",
                    target_type="blot",
                    asset_sha256=sha,
                    note=note,
                )
            )
            channels.append(
                BlotChannel(
                    asset_sha256=sha,
                    channel_index=channel_index,
                    wavelength_nm=wavelength_nm,
                    filter_name=filter_name or None,
                )
            )
        return channels

    def import_nir_blot_odyssey(
        self,
        file_path: Path,
        project: Project,
    ) -> list[BlotChannel]:
        raise NotImplementedError(
            "LI-COR Odyssey import is not yet implemented. "
            "Awaiting instrument test files. See Phase 6 in CLAUDE.md."
        )

    def export_archive(
        self,
        project_ids: list[str],
        dest_path: Path,
        app_version: str,
    ) -> None:
        self.ensure()

        for pid in project_ids:
            if not (self.projects_dir / pid / "project.json").exists():
                raise FileNotFoundError(f"Project not found in workspace: {pid}")

        # Load projects and collect every referenced asset SHA256.
        projects: dict[str, Project] = {}
        all_sha256s: set[str] = set()

        for pid in project_ids:
            project = self.load_project(str(self.projects_dir / pid / "project.json"))
            projects[pid] = project

            for sha in project.assets:
                all_sha256s.add(sha)

            for blot in project.panel.blots:
                all_sha256s.add(blot.asset_sha256)
                if blot.overlay_asset_sha256:
                    all_sha256s.add(blot.overlay_asset_sha256)

        # Verify every asset exists on disk before touching the destination file.
        asset_files: dict[str, Path] = {}
        for sha in all_sha256s:
            try:
                asset_files[sha] = self.asset_original_file(sha)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"Asset {sha} is referenced by a project but is missing from the workspace."
                )

        now = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
        manifest = {
            "format": "pbarchive",
            "format_version": 1,
            "created_utc": now,
            "app_version": app_version,
            "project_ids": list(project_ids),
            "asset_sha256s": list(all_sha256s),
        }

        with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("pbarchive/manifest.json", json.dumps(manifest, indent=2))

            for pid, project in projects.items():
                zf.writestr(
                    f"pbarchive/projects/{pid}/project.json",
                    project.model_dump_json(indent=2),
                )

            for sha, asset_path in asset_files.items():
                zf.write(str(asset_path), f"pbarchive/assets/{sha}/{asset_path.name}")

    def import_archive(
        self,
        src_path: Path,
        app_version: str,
    ) -> ImportArchiveResult:
        self.ensure()
        result = ImportArchiveResult()

        with zipfile.ZipFile(src_path, "r") as zf:
            # --- Validate manifest ---
            try:
                manifest_bytes = zf.read("pbarchive/manifest.json")
            except KeyError:
                raise ValueError(
                    "Not a valid .pbarchive file: missing pbarchive/manifest.json"
                )

            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if manifest.get("format") != "pbarchive":
                raise ValueError(
                    f"Unknown archive format: {manifest.get('format')!r}"
                )
            if manifest.get("format_version") != 1:
                raise ValueError(
                    f"Unsupported archive version: {manifest.get('format_version')}"
                )

            # --- Asset integrity check (read-only pass, nothing written yet) ---
            valid_assets: dict[str, tuple[str, bytes]] = {}  # sha256 -> (filename, data)

            for name in zf.namelist():
                if not name.startswith("pbarchive/assets/"):
                    continue
                parts = name.split("/")
                # Expected: pbarchive / assets / <sha256> / original.<ext>
                if len(parts) != 4 or not parts[3].startswith("original."):
                    continue

                sha256_in_path = parts[2]
                data = zf.read(name)

                h = hashlib.sha256()
                h.update(data)
                computed = h.hexdigest()

                if computed != sha256_in_path:
                    result.integrity_errors.append(
                        f"SHA256 mismatch for asset at {name}: "
                        f"path says {sha256_in_path[:12]}…, "
                        f"content hashes to {computed[:12]}…"
                    )
                    continue

                valid_assets[sha256_in_path] = (parts[3], data)

            # --- Write valid assets ---
            for sha, (filename, data) in valid_assets.items():
                dest_dir = self.assets_dir / sha
                if dest_dir.exists():
                    result.skipped_asset_count += 1
                else:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    (dest_dir / filename).write_bytes(data)
                    result.imported_asset_count += 1

            # --- Import projects ---
            for name in zf.namelist():
                if not name.startswith("pbarchive/projects/"):
                    continue
                parts = name.split("/")
                # Expected: pbarchive / projects / <project_id> / project.json
                if len(parts) != 4 or parts[3] != "project.json":
                    continue

                project_id = parts[2]
                proj_dir = self.projects_dir / project_id

                if proj_dir.exists():
                    result.skipped_project_ids.append(project_id)
                    continue

                proj_data = json.loads(zf.read(name).decode("utf-8"))
                project = Project.model_validate(proj_data)

                now = (
                    datetime.datetime.now(datetime.timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                )
                project.operation_log.append(
                    OperationLogEntry(
                        timestamp_utc=now,
                        operation="imported_from_archive",
                        target_type="project",
                        target_id=project_id,
                        note=f"Imported from archive: {src_path.name}",
                    )
                )

                self.save_project(project)
                result.imported_project_ids.append(project_id)

        return result
