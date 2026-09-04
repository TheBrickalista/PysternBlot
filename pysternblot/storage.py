# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
import hashlib, json, re, zipfile

try:
    from pysternblot import __version__ as _pysternblot_version
except ImportError:
    _pysternblot_version = "unknown"
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from .models import (
    BlotChannel,
    CropTemplate,
    MarkerBand,
    MarkerSet,
    MarkerSetLibrary,
    OperationLogEntry,
    Project,
)
from .logchain import append_log_entry
import datetime, uuid
from PIL import Image


@dataclass
class ImportArchiveResult:
    imported_project_ids: list[str] = field(default_factory=list)
    skipped_project_ids: list[str] = field(default_factory=list)
    imported_asset_count: int = 0
    skipped_asset_count: int = 0
    integrity_errors: list[str] = field(default_factory=list)
    project_integrity_verified: bool = False
    archive_format_version: int = 0

from .image_utils import (
    load_image_as_uint16,
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


def parse_typhoon_inf(inf_path: Path) -> dict:
    """Parse an Amersham Typhoon .inf sidecar.

    The file has an optional header block of bare values, then a
    '*** more info ***' separator, then key=value lines prefixed with
    'S,' or 'H,' (e.g. 'H,ScaleType=Linear', 'S,V=399').

    Returns a dict of selected acquisition-provenance fields, or {} if
    the file is absent, unreadable, or yields no parseable data.
    """
    try:
        if not inf_path.exists():
            return {}
        text = inf_path.read_text(encoding="utf-8", errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Only parse the structured key=value section.
        if "*** more info ***" in text:
            _, _, kv_section = text.partition("*** more info ***")
        else:
            kv_section = text

        raw: dict[str, str] = {}
        for line in kv_section.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Strip the optional 'S,' / 'H,' type prefix.
            if len(line) >= 2 and line[1] == "," and line[0].upper() in ("S", "H"):
                line = line[2:]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            raw[key.strip()] = value.strip()

        if not raw:
            return {}

        def _get(k: str):
            v = raw.get(k)
            return v if v else None

        result: dict = {}

        if _get("ScaleType"):
            result["scale_type"] = _get("ScaleType")
        if _get("ScanMode"):
            result["scan_mode"] = _get("ScanMode")
        if _get("ScanSpeed"):
            result["scan_speed"] = _get("ScanSpeed")
        if _get("LaserName"):
            result["laser_name"] = _get("LaserName")
        if _get("FilterName"):
            result["filter_name"] = _get("FilterName")
        if _get("V"):
            try:
                result["pmt_voltage"] = int(raw["V"])
            except (ValueError, TypeError):
                result["pmt_voltage"] = raw["V"]
        if _get("LaserPowerMode"):
            result["laser_power_mode"] = _get("LaserPowerMode")
        if _get("Hash"):
            result["instrument_hash"] = _get("Hash")
        if _get("Software"):
            result["software"] = _get("Software")
        if _get("SerialNumber"):
            result["serial_number"] = _get("SerialNumber")

        corrections = {
            k: v for k, v in raw.items()
            if re.match(r"Correction\d+|Shading\d*", k)
        }
        if corrections:
            result["corrections"] = corrections

        signal_process = {
            k: v for k, v in raw.items()
            if re.match(r"SignalProcess\d*$", k)
        }
        if signal_process:
            result["signal_process"] = signal_process

        return result
    except Exception:
        return {}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_component(value: str) -> bool:
    """
    True only if *value* is safe to use as a single filesystem path
    component: non-empty, at most 64 characters, drawn only from
    [A-Za-z0-9._-], and not exactly "." or "..".

    Deliberately not tied to any particular id format (e.g. the
    proj_<10 hex> generator) — a future id scheme must not break import.
    """
    if not value or len(value) > 64:
        return False
    if value in (".", ".."):
        return False
    return bool(_SAFE_COMPONENT_RE.match(value))


def _safe_member_name(name: str) -> bool:
    """
    True only if *name* is a well-formed, relative zip member path: no
    leading "/", no backslash, and no "", "." or ".." path component.
    """
    if not name or name.startswith("/") or "\\" in name:
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def _resolve_contained(base_dir: Path, *components: str) -> Path | None:
    """
    Join base_dir with components and return the resolved path only if it
    is still inside base_dir. Returns None if it would escape — defence in
    depth on top of _safe_component, not a substitute for it.
    """
    dest = base_dir.joinpath(*components).resolve()
    if not dest.is_relative_to(base_dir.resolve()):
        return None
    return dest


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

    def set_project_archived(self, project_path: str, archived: bool) -> None:
        """Flip the is_archived flag on a project and persist it to disk."""
        project = self.load_project(project_path)
        old_value = project.project.is_archived
        project.project.is_archived = archived
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        append_log_entry(
            project,
            OperationLogEntry(
                timestamp_utc=now,
                operation="archived" if archived else "unarchived",
                target_type="project",
                target_id=project.project.id,
                field="project.is_archived",
                old_value=old_value,
                new_value=archived,
            ),
        )
        self.save_project(project)

    def rename_project(self, project: Project, new_name: str) -> Path:
        old_name = project.project.name
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        project.project.name = new_name
        project.project.modified_utc = now
        append_log_entry(
            project,
            OperationLogEntry(
                timestamp_utc=now,
                operation="project_renamed",
                target_type="project",
                target_id=project.project.id,
                field="project.name",
                old_value=old_name,
                new_value=new_name,
            ),
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

    def create_new_project(self, name: str, app_version: str = _pysternblot_version) -> Path:
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

        img = load_image_as_uint16(original_path)

        x = int(round(float(crop.get("x", 0))))
        y = int(round(float(crop.get("y", 0))))
        w = int(round(float(crop.get("w", img.shape[1]))))
        h = int(round(float(crop.get("h", img.shape[0]))))

        cropped = crop_uint16(img, x, y, w, h)

        out_path = (self.assets_dir / sha256) / "preview_crop.tif"
        save_uint16_tiff(cropped, out_path)
        return out_path
    
    def ensure_blot_crop_preview(self, blot, panel, channel_index: int = -1) -> Path:
        """
        Generate/update a 16-bit crop preview TIFF from blot settings.

        channel_index == -1 (default): ECL path — uses blot.asset_sha256 and blot.display.
            Cache: assets/<blot.asset_sha256>/preview_crop_<blot.id>.tif
        channel_index >= 0: NIR path — uses blot.channels[channel_index].asset_sha256 and .display.
            Cache: assets/<channel.asset_sha256>/preview_crop_<blot.id>_ch<channel_index>.tif

        Crop position comes from blot.crop.x/y; size from panel.crop_template.
        Rotation → levels → crop, all in 16-bit.
        """
        self.ensure()

        if channel_index >= 0:
            ch = next((c for c in blot.channels if c.channel_index == channel_index), None)
            if ch is None:
                raise IndexError(
                    f"No channel with channel_index={channel_index} in blot {blot.id!r}"
                )
            sha256 = ch.asset_sha256
            display = ch.display
            cache_name = f"preview_crop_{blot.id}_ch{channel_index}.tif"
        else:
            sha256 = blot.asset_sha256
            display = getattr(blot, "display", None)
            cache_name = f"preview_crop_{blot.id}.tif"

        original_path = self.asset_original_file(sha256)
        img = load_image_as_uint16(original_path)

        black = int(getattr(display, "levels_black", 0))
        white = int(getattr(display, "levels_white", 65535))
        gamma = float(getattr(display, "levels_gamma", 1.0))
        invert = bool(getattr(display, "invert", False))

        img = apply_levels_uint16(img, black, white, gamma, invert)

        rotation_deg = float(getattr(display, "rotation_deg", 0.0) or 0.0)
        img = rotate_uint16(img, rotation_deg, expand=False)

        if bool(getattr(display, "flip_horizontal", False)):
            img = np.fliplr(img)
        if bool(getattr(display, "flip_vertical", False)):
            img = np.flipud(img)

        # w/h come from the shared crop template, not the per-blot crop
        w = int(round(float(panel.crop_template.w)))
        h = int(round(float(panel.crop_template.h)))

        if channel_index >= 0:
            c = blot.get_channel_crop(channel_index)
        else:
            c = blot.crop
        x = int(round(float(c.x)))
        y = int(round(float(c.y)))

        cropped = crop_uint16(img, x, y, w, h)

        out_path = self.assets_dir / sha256 / cache_name
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
    ) -> tuple[list[BlotChannel], dict[str, dict]]:
        """
        Import 1 or 2 Typhoon NIR channel files into the workspace and return
        a (channels, sha_to_inf_meta) tuple.

        channels           — BlotChannel objects sorted by channel_index ascending.
        sha_to_inf_meta    — {sha256: acquisition_metadata} for any channel whose
                             sibling .inf sidecar was found and parsed; empty dict
                             when no .inf is present (clean no-op).

        Each file is hashed and stored via import_asset (SHA256-deduplicated).
        Metadata is read from TIFF Tag 270 via parse_typhoon_tag270 and from the
        sibling .inf sidecar (same stem, .inf extension) via parse_typhoon_inf.
        The .inf lookup is performed here against the original source path fp,
        before the caller creates AssetEntry objects; the asset store holds only
        the .tif.
        One OperationLogEntry is appended to project.operation_log per channel.
        The caller is responsible for attaching the returned channels to a Blot,
        populating project.assets, and saving the project.
        """
        # Collect (channel_index, sha256, tag270_meta, inf_meta) per file.
        entries: list[tuple[int, str, dict, dict]] = []
        for i, fp in enumerate(file_paths):
            sha, _ = self.import_asset(str(fp))
            meta: dict = {}
            try:
                with Image.open(str(fp)) as im:
                    tag270 = im.tag_v2.get(270, "")
                meta = parse_typhoon_tag270(tag270)
            except Exception:
                pass

            # .inf sidecar: same stem, .inf extension — fp.with_suffix handles
            # the bracketed channel names (e.g. [IRlong].tif → [IRlong].inf).
            inf_meta: dict = {}
            inf_path = fp.with_suffix(".inf")
            if inf_path.exists():
                inf_meta = parse_typhoon_inf(inf_path)

            # Fall back to file order if channel_index is not in metadata.
            idx = meta.get("channel_index")
            if idx is None:
                idx = i
            entries.append((idx, sha, meta, inf_meta))

        entries.sort(key=lambda e: e[0])

        now = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
        channels: list[BlotChannel] = []
        sha_to_inf: dict[str, dict] = {}

        for channel_index, sha, meta, inf_meta in entries:
            filter_name = meta.get("filter_name") or ""
            wavelength_nm = meta.get("laser_nm")
            channel_total = meta.get("channel_total") or len(file_paths)

            note = (
                f"Typhoon: {filter_name}, {wavelength_nm}nm, "
                f"channel {channel_index + 1}/{channel_total}"
            )
            if inf_meta.get("scale_type"):
                note += f", scale={inf_meta['scale_type']}"

            append_log_entry(
                project,
                OperationLogEntry(
                    timestamp_utc=now,
                    operation="nir_channel_imported",
                    target_type="blot",
                    asset_sha256=sha,
                    note=note,
                ),
            )
            channels.append(
                BlotChannel(
                    asset_sha256=sha,
                    channel_index=channel_index,
                    wavelength_nm=wavelength_nm,
                    filter_name=filter_name or None,
                )
            )
            if inf_meta:
                sha_to_inf[sha] = inf_meta

        return channels, sha_to_inf

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

        # Serialise each project exactly once — the bytes written to the zip
        # and the bytes hashed into the manifest must be identical, or the
        # manifest hash could describe content that was never actually
        # written.
        project_json_bytes: dict[str, bytes] = {
            pid: project.model_dump_json(indent=2).encode("utf-8")
            for pid, project in projects.items()
        }
        project_sha256s = {
            pid: hashlib.sha256(data).hexdigest()
            for pid, data in project_json_bytes.items()
        }

        now = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )
        manifest = {
            "format": "pbarchive",
            "format_version": 2,
            "created_utc": now,
            "app_version": app_version,
            "project_ids": list(project_ids),
            "asset_sha256s": list(all_sha256s),
            "project_sha256s": project_sha256s,
        }

        with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("pbarchive/manifest.json", json.dumps(manifest, indent=2))

            for pid, data in project_json_bytes.items():
                zf.writestr(f"pbarchive/projects/{pid}/project.json", data)

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

            format_version = manifest.get("format_version")
            if format_version not in (1, 2):
                raise ValueError(
                    f"Unsupported archive version: {format_version}"
                )
            result.archive_format_version = format_version

            manifest_asset_shas = set(manifest.get("asset_sha256s", []))
            manifest_project_ids = set(manifest.get("project_ids", []))
            manifest_project_hashes: dict[str, str] = manifest.get("project_sha256s") or {}

            # _safe_member_name is applied to every member up front, before any
            # member is dispatched by prefix — an absolute or backslash-laced
            # name must never reach the loops below, whether or not it happens
            # to also match a "pbarchive/..." prefix.
            names: list[str] = []
            for raw_name in zf.namelist():
                if _safe_member_name(raw_name):
                    names.append(raw_name)
                else:
                    result.integrity_errors.append(
                        f"Rejected archive member with an unsafe path: {raw_name!r}"
                    )

            # ================================================================
            # PASS 1 — validate everything; nothing is written below this
            # point until every member has been checked.
            # ================================================================

            # --- Assets ---
            valid_assets: dict[str, tuple[str, bytes]] = {}  # sha256 -> (filename, data)
            archive_asset_shas: set[str] = set()

            for name in names:
                if not name.startswith("pbarchive/assets/"):
                    continue

                parts = name.split("/")
                # Expected: pbarchive / assets / <sha256> / original.<ext>
                if len(parts) != 4 or not parts[3].startswith("original."):
                    continue

                sha256_in_path, filename = parts[2], parts[3]

                if not _safe_component(sha256_in_path) or not _safe_component(filename):
                    result.integrity_errors.append(
                        f"Rejected asset member with an unsafe component: {name!r}"
                    )
                    continue

                if _resolve_contained(self.assets_dir, sha256_in_path, filename) is None:
                    result.integrity_errors.append(
                        f"Rejected asset member escaping the workspace: {name!r}"
                    )
                    continue

                archive_asset_shas.add(sha256_in_path)

                data = zf.read(name)
                computed = hashlib.sha256(data).hexdigest()

                if computed != sha256_in_path:
                    result.integrity_errors.append(
                        f"SHA256 mismatch for asset at {name}: "
                        f"path says {sha256_in_path[:12]}…, "
                        f"content hashes to {computed[:12]}…"
                    )
                    continue

                valid_assets[sha256_in_path] = (filename, data)

            # --- Projects ---
            valid_projects: dict[str, Project] = {}
            already_present_project_ids: list[str] = []
            archive_project_ids: set[str] = set()
            all_project_hashes_ok = True

            for name in names:
                if not name.startswith("pbarchive/projects/"):
                    continue

                parts = name.split("/")
                # Expected: pbarchive / projects / <project_id> / project.json
                if len(parts) != 4 or parts[3] != "project.json":
                    continue

                project_id, json_name = parts[2], parts[3]

                if not _safe_component(project_id) or not _safe_component(json_name):
                    result.integrity_errors.append(
                        f"Rejected project member with an unsafe component: {name!r}"
                    )
                    continue

                if _resolve_contained(self.projects_dir, project_id) is None:
                    result.integrity_errors.append(
                        f"Rejected project member escaping the workspace: {name!r}"
                    )
                    continue

                archive_project_ids.add(project_id)

                if (self.projects_dir / project_id).exists():
                    already_present_project_ids.append(project_id)
                    continue

                # Hash the bytes exactly as read from the zip — before
                # json.loads, before model validation, and before the
                # imported_from_archive entry is appended. The manifest hash
                # describes the archive's contents, never the imported result.
                raw_bytes = zf.read(name)

                if format_version >= 2:
                    expected_hash = manifest_project_hashes.get(project_id)
                    if expected_hash is None:
                        result.integrity_errors.append(
                            f"No manifest hash recorded for project {project_id}; skipped."
                        )
                        all_project_hashes_ok = False
                        continue
                    computed = hashlib.sha256(raw_bytes).hexdigest()
                    if computed != expected_hash:
                        result.integrity_errors.append(
                            f"SHA256 mismatch for project.json at {name}: "
                            f"manifest says {expected_hash[:12]}…, "
                            f"content hashes to {computed[:12]}…"
                        )
                        all_project_hashes_ok = False
                        continue

                try:
                    proj_data = json.loads(raw_bytes.decode("utf-8"))
                    project = Project.model_validate(proj_data)
                except Exception as exc:
                    result.integrity_errors.append(
                        f"Failed to parse project.json for {project_id}: {exc}"
                    )
                    continue

                # save_project() writes to a directory derived from
                # project.project.id, not from the (already-validated) zip
                # path — so the two must agree, or a safely-named archive
                # member could still smuggle a traversal id through the
                # JSON payload itself.
                if project.project.id != project_id:
                    result.integrity_errors.append(
                        f"Project ID mismatch for {name}: archive path says "
                        f"{project_id!r}, JSON declares {project.project.id!r}"
                    )
                    continue

                valid_projects[project_id] = project

            # --- Cross-check manifest inventory against actual archive contents ---
            for sha in sorted(manifest_asset_shas - archive_asset_shas):
                result.integrity_errors.append(
                    f"Asset {sha[:12]}… is listed in the manifest but not found in the archive."
                )
            for sha in sorted(archive_asset_shas - manifest_asset_shas):
                result.integrity_errors.append(
                    f"Asset {sha[:12]}… is present in the archive but not listed in the manifest."
                )
            for pid in sorted(manifest_project_ids - archive_project_ids):
                result.integrity_errors.append(
                    f"Project {pid} is listed in the manifest but not found in the archive."
                )
            for pid in sorted(archive_project_ids - manifest_project_ids):
                result.integrity_errors.append(
                    f"Project {pid} is present in the archive but not listed in the manifest."
                )

            result.project_integrity_verified = format_version >= 2 and all_project_hashes_ok

            # ================================================================
            # PASS 2 — write only what validated cleanly above.
            # ================================================================

            for sha, (filename, data) in valid_assets.items():
                dest_dir = self.assets_dir / sha
                if dest_dir.exists():
                    result.skipped_asset_count += 1
                else:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    (dest_dir / filename).write_bytes(data)
                    result.imported_asset_count += 1

            result.skipped_project_ids.extend(already_present_project_ids)

            for project_id, project in valid_projects.items():
                now = (
                    datetime.datetime.now(datetime.timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                )
                append_log_entry(
                    project,
                    OperationLogEntry(
                        timestamp_utc=now,
                        operation="imported_from_archive",
                        target_type="project",
                        target_id=project_id,
                        note=f"Imported from archive: {src_path.name}",
                    ),
                )

                self.save_project(project)
                result.imported_project_ids.append(project_id)

        return result
