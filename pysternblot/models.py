# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

from __future__ import annotations
from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, Field

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
    w: float
    h: float
    mode: Literal["absolute", "ladder_relative"] = "absolute"
    ladder_anchor: Optional[dict] = None

class CalibrationPoint(BaseModel):
    y_px: float
    kda: float

class LadderFit(BaseModel):
    a: float
    b: float
    model: Literal["y=a*log10(kDa)+b"] = "y=a*log10(kDa)+b"

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

class Blot(BaseModel):
    id: str
    asset_sha256: str
    overlay_asset_sha256: Optional[str] = None
    crop: Crop
    ladder: Ladder
    protein_label: ProteinLabel
    display: DisplaySettings = DisplaySettings()

class Style(BaseModel):
    font_family: str = "Arial"
    font_size_pt: float = 9
    top_header_height_px: int = 70
    ladder_col_width_px: int = 60
    protein_col_width_px: int = 90
    gap_between_blots_px: int = 10
    border_enabled: bool = True
    border_width_px: int = 1

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

class Project(BaseModel):
    project: ProjectMeta
    assets: Dict[str, AssetEntry] = {}
    marker_sets: List[dict] = []
    panel: Panel


