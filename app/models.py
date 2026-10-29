"""Clean response models. These also drive the generated openapi.json."""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    installed = "installed"
    faulty = "faulty"
    decommissioned = "decommissioned"
    unknown = "unknown"


class Phase(str, Enum):
    single = "single"
    three = "three"
    unknown = "unknown"


class InstallType(str, Enum):
    whole_current = "whole_current"
    ct_operated = "ct_operated"
    unknown = "unknown"


class Location(BaseModel):
    latitude: float
    longitude: float


class Node(BaseModel):
    """One level of the network. The portal sometimes sends a name without a code or vice versa."""
    code: str | None = None
    name: str | None = None


class Hierarchy(BaseModel):
    zone: Node
    circle: Node
    division: Node
    subdivision: Node
    substation: Node
    feeder: Node
    dt: Node


class Meter(BaseModel):
    meter_id: str
    serial_no: str
    make: str
    phase: Phase
    status: Status
    install_type: InstallType
    build: str | None = Field(None, description="Portal software generation: 'legacy' or 'v2'.")
    transformer_code: str
    location: Location | None
    hierarchy: Hierarchy
    data_quality: list[str] = Field(default_factory=list, description="Data-quality flags found on this record.")


class MeterPage(BaseModel):
    items: list[Meter]
    total: int
    limit: int
    offset: int


class NearbyMeter(BaseModel):
    meter: Meter
    distance_km: float


class Reading(BaseModel):
    timestamp: datetime
    kwh: float | None = Field(None, description="Cumulative import register (not usage in the interval).")
    kvah: float | None = Field(None, description="Cumulative apparent-energy register.")
    voltage_r: float | None = Field(None, description="R-phase voltage (V).")
    interval_kwh: float | None = Field(None, description="kWh used since the previous reading.")
    interval_kvah: float | None = None


class Anomaly(BaseModel):
    type: str
    at: datetime | None = None
    detail: str


class Consumption(BaseModel):
    meter_id: str
    timezone_assumed: str
    resolution_minutes: int | None
    count: int
    readings: list[Reading]
    anomalies: list[Anomaly]


class Transformer(BaseModel):
    code: str
    name: str
    feeder_code: str | None = None
    capacity_kva: float | None = None
    meter_count: int = 0


class QualitySummary(BaseModel):
    meters_total: int
    meters_with_issues: int
    issue_counts: dict[str, int]
    examples: dict[str, list[str]]
    notes: list[str]


class HierarchyNode(BaseModel):
    level: str
    code: str | None
    name: str | None
    meter_count: int
    children: list["HierarchyNode"] = Field(default_factory=list)


class Health(BaseModel):
    status: str
    loaded: bool
    stale: bool
    meters_cached: int
    transformers_cached: int
    data_age_seconds: float | None
    last_refresh_error: str | None


class ErrorResponse(BaseModel):
    error: str
    message: str
