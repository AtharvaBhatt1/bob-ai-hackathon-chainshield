"""
src/app/core/schemas.py
=======================
Request / response payload schemas for the ChainShield API surface.

These are thin wrappers / projections over the core domain models in
``models.py``.  They are the types that FastAPI routers will eventually
use for request validation and response serialisation.  Keeping them
separate from the domain models means the API surface can evolve
independently of the storage layer.

No FastAPI imports here — schemas are plain Pydantic models so they can
be used by tests and non-API code without pulling in the web framework.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.core.models import (
    ActionPlanItem,
    Asset,
    DecisionType,
    DisruptionType,
    EvidenceRecord,
    ExcursionStatus,
    ExplanationResult,
    PolicyProfile,
    RouteGraph,
    Shipment,
    ShipmentLeg,
    ShipmentMode,
)


# ---------------------------------------------------------------------------
# Disruption schemas
# ---------------------------------------------------------------------------

class DisruptionActivateRequest(BaseModel):
    """POST /api/v1/disruptions/activate"""
    disruption_id: str = Field(..., description="ID of the disruption scenario to activate")


class ImpactResult(BaseModel):
    """Impact assessment for a single shipment."""
    shipment_id: str
    affected: bool
    reason_codes: list[str] = Field(default_factory=list)
    cargo_value_usd: float = Field(..., ge=0)
    eta_delay_hours: float = Field(0.0, description="Estimated delay in hours due to disruption")


class DisruptionActivateResponse(BaseModel):
    """Response to POST /api/v1/disruptions/activate"""
    disruption_id: str
    affected_shipments: list[ImpactResult] = Field(default_factory=list)


class DisruptionSummary(BaseModel):
    """Light summary row for the disruption scenario list."""
    disruption_id: str
    disruption_type: DisruptionType
    description: str
    window_start: datetime
    window_end: datetime
    severity: str


# ---------------------------------------------------------------------------
# Shipment schemas
# ---------------------------------------------------------------------------

class RouteAlternative(BaseModel):
    """A single feasible alternative route / carrier option for a shipment."""
    carrier_id: str
    route_nodes: list[str] = Field(default_factory=list)
    eta_delta_hours: float = Field(..., description="Hours added to arrival time vs. current plan")
    additional_cost_usd: float = Field(..., ge=0, description="Incremental cost in USD")
    reason_codes: list[str] = Field(default_factory=list)
    reefer_capable: bool = Field(False)


class ShipmentDetailResponse(BaseModel):
    """Response to GET /api/v1/shipments/{shipment_id}"""
    shipment: Shipment
    legs: list[ShipmentLeg] = Field(default_factory=list)
    alternatives: list[RouteAlternative] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Asset schemas
# ---------------------------------------------------------------------------

class AssetMatch(BaseModel):
    """An idle asset that can be repositioned to cover a disrupted shipment."""
    asset_id: str
    asset: Asset
    reposition_distance_km: float = Field(..., ge=0)
    available_at: datetime
    reason_codes: list[str] = Field(default_factory=list)


class IdleAssetsResponse(BaseModel):
    """Response to GET /api/v1/assets/idle"""
    assets: list[AssetMatch] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cold-chain schemas
# ---------------------------------------------------------------------------

class SensorReadingOut(BaseModel):
    """A single sensor reading in the cold-chain timeline response."""
    sensor_id: str
    ts: datetime
    temperature_c: float
    battery_pct: float | None = None
    in_range: bool = Field(..., description="True if temperature_c is within policy bounds")


class ExcursionEvent(BaseModel):
    """A contiguous block of out-of-range readings."""
    start_ts: datetime
    end_ts: datetime
    duration_minutes: float
    max_celsius: float
    min_celsius: float
    pattern: str = Field(
        "UNKNOWN",
        description="Detected pattern: SPIKE | DRIFT | DOOR_OPEN | SENSOR_FAILURE | UNKNOWN",
    )


class ColdChainTimelineResponse(BaseModel):
    """Response to GET /api/v1/cold-chain/{shipment_id}/timeline"""
    shipment_id: str
    policy: PolicyProfile | None
    readings: list[SensorReadingOut] = Field(default_factory=list)
    excursion_events: list[ExcursionEvent] = Field(default_factory=list)
    status: ExcursionStatus
    max_celsius: float | None = None
    min_celsius: float | None = None
    total_out_of_range_minutes: float = 0.0
    evidence: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Explanation schemas
# ---------------------------------------------------------------------------

class ExplanationRequest(BaseModel):
    """POST /api/v1/explanations/generate"""
    decision_id: str = Field(..., description="UUID of an existing EvidenceRecord")


class DecisionContext(BaseModel):
    """Structured context passed to both the deterministic fallback and Granite."""
    shipment_id: str
    disruption: str = Field(..., description="Disruption ID or display name")
    reason_codes: list[str] = Field(default_factory=list)
    recommended_route: dict[str, Any] | None = Field(
        None,
        description="Route recommendation dict: carrier, eta_delta_hours, additional_cost_usd",
    )
    cold_chain: dict[str, Any] | None = Field(
        None,
        description="Cold-chain summary dict: status, max_celsius, policy_max_celsius",
    )


# ---------------------------------------------------------------------------
# Evidence schemas
# ---------------------------------------------------------------------------

class EvidenceRecordResponse(BaseModel):
    """Response to GET /api/v1/evidence/{decision_id}"""
    record: EvidenceRecord


class EvidenceListResponse(BaseModel):
    """Response to GET /api/v1/evidence?shipment_id="""
    shipment_id: str
    records: list[EvidenceRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Action plan schemas
# ---------------------------------------------------------------------------

class ActionPlanExportRequest(BaseModel):
    """POST /api/v1/action-plan/export"""
    disruption_id: str
    export_format: str = Field("json", description="'json' or 'markdown'")


class ActionPlanResponse(BaseModel):
    """Response to POST /api/v1/action-plan/export"""
    plan_id: str
    disruption_id: str
    generated_at: datetime
    items: list[ActionPlanItem] = Field(default_factory=list)
    export_format: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Response to GET /healthz"""
    status: str = "ok"
    demo_mode: bool = False
    watsonx_enabled: bool = False
