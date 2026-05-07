# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Literal, Any

class Group(BaseModel):
    label: str
    n_lanes: int = Field(ge=1)
    underline: bool = True

class ConditionRow(BaseModel):
    values: List[str]
    unit_right: Optional[str] = None

class Span(BaseModel):
    text: str
    start_group: int = Field(ge=0)
    end_group: int = Field(ge=0)

class SpanRow(BaseModel):
    spans: List[Span]

class HeaderBlock(BaseModel):
    left_title: str
    groups: List[Group]
    condition_rows: List[ConditionRow]
    span_rows: List[SpanRow] = []

    def total_lanes(self) -> int:
        return sum(g.n_lanes for g in self.groups)

class Crop(BaseModel):
    x: float
    y: float
    w: float  # kept for backward compat; render/storage use panel.crop_template instead
    h: float  # kept for backward compat; render/storage use panel.crop_template instead
    mode: Literal["absolute", "ladder_relative"] = "absolute"
    ladder_anchor: Optional[dict] = None

class CropTemplate(BaseModel):
    """Shared crop dimensions for all blots in the panel."""
    w: float = 300.0
    h: float = 200.0

class CalibrationPoint(BaseModel):
    y_px: float
    kda: float

class LadderFit(BaseModel):
    a: float
    b: float
    model: Literal["y=a*log10(kDa)+b"] = "y=a*log10(kDa)+b"

class MarkerBand(BaseModel):
    kda: float = Field(gt=0)
    label: Optional[str] = None
    visible: bool = True
    highlight: bool = False


class MarkerSet(BaseModel):
    id: str
    name: str
    unit: str = "kDa"
    bands: List[MarkerBand] = Field(default_factory=list)


class MarkerSetLibrary(BaseModel):
    items: List[MarkerSet] = Field(default_factory=list)

class Ladder(BaseModel):
    lane_index: int = Field(ge=0)
    marker_set_id: str
    calibration_points: List[CalibrationPoint] = Field(min_length=2)
    fit: Optional[LadderFit] = None
    show_ticks: bool = True

class ProteinLabel(BaseModel):
    text: str
    align: Literal["center"] = "center"
    font_size_pt: float | None = None

class DisplaySettings(BaseModel):
    invert: bool = False
    gamma: float = 1.0
    auto_contrast: bool = True
    overlay_alpha: float = 0.35
    overlay_visible: bool = True
    rotation_deg: float = 0.0

    levels_black: int = 0      # 0..65535
    levels_white: int = 65535  # 0..65535
    levels_gamma: float = 1.0

class LegendRow(BaseModel):
    left: str = ""
    cells: List[str] = Field(default_factory=list)
    right: str = ""
    underline: bool = False   
    font_size_pt: float | None = None # <- NEW

class LegendSettings(BaseModel):
    mode: Literal["protein", "dna"] = "protein"
    upper_rows: List[LegendRow] = Field(default_factory=list)
    lower_rows: List[LegendRow] = Field(default_factory=list)

class LadderBandAssignment(BaseModel):
    y_px: float
    kda: float
    show_in_final: bool = True


class OverlayLadder(BaseModel):
    marker_set_id: str
    bands: List[LadderBandAssignment] = Field(default_factory=list)
    side: Literal["left", "right"] = "left"
    show_labels: bool = True
    show_only_highlighted: bool = False


class BlotChannel(BaseModel):
    asset_sha256: str
    channel_index: int                                          # 0-based, from Scan number tag
    wavelength_nm: Optional[int] = None                        # e.g. 685, 785
    filter_name: Optional[str] = None                          # e.g. "IRshort 720BP20"
    fluorophore: Optional[str] = None                          # user-editable, e.g. "IRDye 800CW"
    antibody_name: str = ""
    protein_label: ProteinLabel = Field(
        default_factory=lambda: ProteinLabel(text="")
    )
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    crop: Optional[Crop] = None                                 # None = use blot.crop (shared fallback)


class Blot(BaseModel):
    id: str
    asset_sha256: str
    overlay_asset_sha256: Optional[str] = None
    crop: Crop
    ladder: Ladder
    protein_label: ProteinLabel
    display: DisplaySettings = DisplaySettings()
    overlay_ladder: Optional[OverlayLadder] = None
    included_in_final: bool = True
    antibody_name: str = ""
    modality: Literal["ecl", "nir_fluorescence"] = "ecl"
    channels: List[BlotChannel] = Field(default_factory=list)

    def is_nir(self) -> bool:
        return self.modality == "nir_fluorescence"

    def get_channel_crop(self, channel_index: int) -> Crop:
        """Return crop for the given NIR channel; falls back to blot.crop if not set.
        For ECL blots, channel_index is ignored and blot.crop is always returned."""
        if not self.is_nir():
            return self.crop
        ch = next((c for c in self.channels if c.channel_index == channel_index), None)
        if ch is None or ch.crop is None:
            return self.crop
        return ch.crop

    def set_channel_crop(self, channel_index: int, crop: Optional[Crop]) -> None:
        """Set the crop for the given NIR channel. For ECL blots, sets blot.crop."""
        if not self.is_nir():
            self.crop = crop
            return
        ch = next((c for c in self.channels if c.channel_index == channel_index), None)
        if ch is not None:
            ch.crop = crop

    def get_display_channel(self, channel_index: int = 0) -> tuple[str, DisplaySettings]:
        """Return (asset_sha256, display) for the given channel.

        For ECL blots (modality == 'ecl'), channel_index is ignored and the
        blot's own asset_sha256 and display are returned.
        For NIR blots, returns the matching BlotChannel's fields.
        """
        if not self.is_nir():
            return self.asset_sha256, self.display
        ch = next((c for c in self.channels if c.channel_index == channel_index), None)
        if ch is None:
            raise IndexError(f"No channel {channel_index} in NIR blot {self.id}")
        return ch.asset_sha256, ch.display

class Style(BaseModel):
    font_family: str = "Arial"
    font_size_pt: float = 9
    top_header_height_px: int = 70
    ladder_col_width_px: int = 60
    protein_col_width_px: int = 90
    gap_between_blots_px: int = 10
    border_enabled: bool = True
    border_width_px: int = 1
    kda_label_font_size_pt: float = 24.0

class Layout(BaseModel):
    stack_mode: Literal["vertical_stack"] = "vertical_stack"
    order: List[str]

class LaneLayout(BaseModel):
    mode: Literal["derived_from_groups", "manual_n_lanes"] = "derived_from_groups"
    n_lanes_manual: Optional[int] = None
    header_block: HeaderBlock

class Panel(BaseModel):
    style: Style = Style()
    lane_layout: LaneLayout
    blots: List[Blot]
    layout: Layout
    legend: LegendSettings = Field(default_factory=LegendSettings)
    crop_template: CropTemplate = Field(default_factory=CropTemplate)

class AssetEntry(BaseModel):
    sha256: str
    stored_original_path: str
    original_source_path: Optional[str] = None
    stored_preview_path: Optional[str] = None

class ProjectMeta(BaseModel):
    id: str
    name: str
    created_utc: str
    modified_utc: Optional[str] = None
    app_version: str
    license: Literal["GPL-3.0-only", "GPL-3.0-or-later"] = "GPL-3.0-only"

class OperationLogEntry(BaseModel):
    timestamp_utc: str
    operation: str

    target_type: Optional[str] = None   # "project", "blot", "asset", "export"
    target_id: Optional[str] = None     # blot.id, project.id, etc.
    asset_sha256: Optional[str] = None

    field: Optional[str] = None         # e.g. "display.rotation_deg"
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None

    note: Optional[str] = None

class Project(BaseModel):
    project: ProjectMeta
    assets: Dict[str, AssetEntry] = {}
    marker_sets: List[MarkerSet] = Field(default_factory=list)
    panel: Panel
    operation_log: List[OperationLogEntry] = Field(default_factory=list)

