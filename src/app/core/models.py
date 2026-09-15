"""
src/app/core/models.py
======================
Canonical Pydantic data-contract models for ChainShield.

Field names mirror the DuckDB column names in scripts/preflight_demo.py so
that ORM-style mapping from query results is a direct attribute assignment.

All threshold and severity values are stored in policy dicts (PolicyProfile),
never hardcoded in logic.  The cold-chain classifier receives a PolicyProfile
instance and reads every threshold from it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ShipmentMode(str, Enum):
    """Transport mode for a shipment or asset."""
    SEA = "sea"
    AIR = "air"
    ROAD = "road"
    RAIL = "rail"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AssetStatus(str, Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class AssetType(str, Enum):
    TRUCK = "truck"
    CONTAINER = "container"
    VESSEL = "vessel"
    AIRCRAFT = "aircraft"
    RAILCAR = "railcar"


class DisruptionType(str, Enum):
    PORT_CLOSURE = "PORT_CLOSURE"
    WEATHER_EVENT = "WEATHER_EVENT"
    STRIKE = "STRIKE"
    ROAD_CLOSURE = "ROAD_CLOSURE"
    RAIL_DISRUPTION = "RAIL_DISRUPTION"


class ExcursionStatus(str, Enum):
    SAFE = "SAFE"
    EXCURSION_REVIEW = "EXCURSION_REVIEW"
    URGENT_ESCALATION = "URGENT_ESCALATION"
    POLICY_REQUIRED = "POLICY_REQUIRED"


class DecisionType(str, Enum):
    IMPACT = "IMPACT"
    ROUTE = "ROUTE"
    ASSET = "ASSET"
    COLD_CHAIN = "COLD_CHAIN"


# ---------------------------------------------------------------------------
# Shipment
# ---------------------------------------------------------------------------

class Shipment(BaseModel):
    """A physical shipment tracked through the supply chain.

    Field names match the DuckDB ``shipments`` table columns exactly.
    """
    shipment_id: str = Field(..., description="Unique shipment identifier, e.g. 'SHP-0042'")
    cargo_type: str = Field(..., description="General cargo category, e.g. 'reefer'")
    product_class: str = Field(..., description="Product class driving the cold-chain policy, e.g. 'refrigerated_vaccine'")
    temperature_policy_id: str | None = Field(None, description="FK to PolicyProfile.policy_id")
    origin_hub_id: str = Field(..., description="Origin node identifier")
    destination_hub_id: str = Field(..., description="Destination node identifier")
    current_node_id: str = Field(..., description="Node where the shipment is currently located")
    mode: ShipmentMode = Field(..., description="Primary transport mode")
    carrier_id: str = Field(..., description="Assigned carrier identifier")
    planned_departure: datetime = Field(..., description="Planned departure timestamp (UTC)")
    planned_arrival: datetime = Field(..., description="Planned arrival timestamp (UTC)")
    delivery_deadline: datetime = Field(..., description="Hard delivery deadline (UTC)")
    cargo_value_usd: float = Field(..., ge=0, description="Declared cargo value in USD")
    weight_kg: float = Field(..., gt=0, description="Shipment weight in kilograms")
    status: ShipmentStatus = Field(ShipmentStatus.PENDING, description="Lifecycle status")

    @model_validator(mode="after")
    def _arrival_before_deadline(self) -> "Shipment":
        if self.planned_arrival > self.delivery_deadline:
            raise ValueError(
                f"planned_arrival ({self.planned_arrival}) is after delivery_deadline "
                f"({self.delivery_deadline}) for shipment {self.shipment_id}"
            )
        return self

    @model_validator(mode="after")
    def _departure_before_arrival(self) -> "Shipment":
        if self.planned_departure >= self.planned_arrival:
            raise ValueError(
                f"planned_departure ({self.planned_departure}) must be before "
                f"planned_arrival ({self.planned_arrival}) for shipment {self.shipment_id}"
            )
        return self


# ---------------------------------------------------------------------------
# Shipment Leg
# ---------------------------------------------------------------------------

class ShipmentLeg(BaseModel):
    """One segment of a multi-leg shipment route."""
    leg_id: str = Field(..., description="Unique leg identifier")
    shipment_id: str = Field(..., description="Parent shipment FK")
    sequence: int = Field(..., ge=0, description="0-based position within the route")
    origin_node_id: str = Field(..., description="Starting node for this leg")
    destination_node_id: str = Field(..., description="Ending node for this leg")
    mode: ShipmentMode = Field(..., description="Transport mode for this leg")
    carrier_id: str = Field(..., description="Carrier assigned to this leg")
    planned_departure: datetime = Field(..., description="Planned leg departure (UTC)")
    planned_arrival: datetime = Field(..., description="Planned leg arrival (UTC)")

    @model_validator(mode="after")
    def _leg_departure_before_arrival(self) -> "ShipmentLeg":
        if self.planned_departure >= self.planned_arrival:
            raise ValueError(
                f"planned_departure must be before planned_arrival on leg {self.leg_id}"
            )
        return self


# ---------------------------------------------------------------------------
# Asset (fleet resource)
# ---------------------------------------------------------------------------

class Asset(BaseModel):
    """A physical transport asset (truck, container, vessel, etc.).

    Field names match the DuckDB ``assets`` table columns exactly.
    """
    asset_id: str = Field(..., description="Unique asset identifier, e.g. 'TRUCK-17'")
    asset_type: AssetType = Field(..., description="Physical asset type")
    mode: ShipmentMode = Field(..., description="Supported transport mode")
    current_node_id: str = Field(..., description="Node where the asset is currently located")
    available_at: datetime = Field(..., description="Earliest time this asset is available (UTC)")
    capacity_kg: float = Field(..., gt=0, description="Maximum payload in kilograms")
    reefer_capable: bool = Field(False, description="Whether this asset can maintain cold-chain temperature control")
    carrier_id: str = Field(..., description="Owning carrier identifier")
    status: AssetStatus = Field(AssetStatus.AVAILABLE, description="Current operational status")


# ---------------------------------------------------------------------------
# Sensor Reading
# ---------------------------------------------------------------------------

class SensorReading(BaseModel):
    """A single IoT sensor measurement.

    Field names match the DuckDB ``sensor_readings`` table columns exactly.
    The field ``ts`` and ``temperature_c`` mirror the preflight schema.
    """
    sensor_id: str = Field(..., description="Sensor device identifier")
    shipment_id: str = Field(..., description="Shipment this reading belongs to")
    ts: datetime = Field(..., description="Measurement timestamp (UTC)")
    temperature_c: float = Field(..., description="Recorded temperature in Celsius")
    battery_pct: float | None = Field(None, ge=0, le=100, description="Sensor battery level 0–100 %")


# ---------------------------------------------------------------------------
# Temperature / Cold-Chain Policy
# ---------------------------------------------------------------------------

class PolicyProfile(BaseModel):
    """Configurable cold-chain policy profile.

    Every threshold, duration limit, and severity classification lives here.
    The classifier reads all values from this model — nothing is hardcoded in
    the engine logic.
    """
    policy_id: str = Field(..., description="Unique policy identifier, e.g. 'POL-CDC-01'")
    jurisdiction: str = Field(..., description="Regulatory jurisdiction, e.g. 'US'")
    product_class: str = Field(..., description="Product class this policy applies to")
    min_celsius: float = Field(..., description="Minimum acceptable temperature (°C)")
    max_celsius: float = Field(..., description="Maximum acceptable temperature (°C)")
    max_continuous_excursion_minutes: int = Field(
        ..., gt=0,
        description="Maximum cumulative out-of-range duration before escalation",
    )
    sample_interval_minutes: int = Field(
        6, gt=0,
        description="Expected interval between sensor readings in minutes",
    )
    source_reference: str = Field(
        "", description="Regulatory or manufacturer reference document"
    )
    severity_rules: dict[str, str] = Field(
        ...,
        description=(
            "Maps excursion event types to severity strings. "
            "Required keys: 'out_of_range', 'missing_sensor_data'."
        ),
    )

    @field_validator("severity_rules")
    @classmethod
    def _required_severity_keys(cls, v: dict[str, str]) -> dict[str, str]:
        required = {"out_of_range", "missing_sensor_data"}
        missing = required - v.keys()
        if missing:
            raise ValueError(f"severity_rules is missing required keys: {sorted(missing)}")
        return v

    @model_validator(mode="after")
    def _min_below_max(self) -> "PolicyProfile":
        if self.min_celsius >= self.max_celsius:
            raise ValueError(
                f"min_celsius ({self.min_celsius}) must be less than "
                f"max_celsius ({self.max_celsius})"
            )
        return self


# ---------------------------------------------------------------------------
# Disruption
# ---------------------------------------------------------------------------

class Disruption(BaseModel):
    """A supply-chain disruption event (port closure, weather, strike, etc.)."""
    disruption_id: str = Field(..., description="Unique disruption identifier, e.g. 'PORT_STRIKE_01'")
    disruption_type: DisruptionType = Field(..., description="Disruption category")
    description: str = Field("", description="Human-readable event description")
    blocked_nodes: list[str] = Field(
        default_factory=list,
        description="Route graph node IDs directly blocked by this disruption",
    )
    blocked_edges: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Route graph edges (origin, destination) blocked by this disruption",
    )
    window_start: datetime = Field(..., description="Disruption start time (UTC)")
    window_end: datetime = Field(..., description="Disruption end time (UTC)")
    severity: str = Field("MEDIUM", description="Operator-assigned severity label")

    @model_validator(mode="after")
    def _start_before_end(self) -> "Disruption":
        if self.window_start >= self.window_end:
            raise ValueError(
                f"window_start ({self.window_start}) must be before "
                f"window_end ({self.window_end}) for disruption {self.disruption_id}"
            )
        return self


# ---------------------------------------------------------------------------
# Evidence / Audit Record
# ---------------------------------------------------------------------------

class EvidenceRecord(BaseModel):
    """Audit record produced by every engine decision."""
    decision_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID uniquely identifying this decision event",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now().astimezone(),
        description="UTC timestamp of when the decision was recorded",
    )
    decision_type: DecisionType = Field(..., description="Engine that produced this decision")
    shipment_id: str = Field(..., description="Shipment this decision relates to")
    disruption_id: str | None = Field(None, description="Disruption referenced (if any)")
    policy_id: str | None = Field(None, description="Policy profile referenced (if any)")
    reason_codes: list[str] = Field(
        default_factory=list,
        description="SCREAMING_SNAKE_CASE reason codes, e.g. ['PORT_NODE_BLOCKED']",
    )
    output: dict[str, Any] = Field(
        default_factory=dict,
        description="Serialised engine output (recommendation, classification, etc.)",
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Deterministic confidence 0–1; 1.0 = all data present",
    )


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------

class ExplanationResult(BaseModel):
    """Structured explanation produced by the deterministic fallback or Granite."""
    summary: str = Field(..., description="One-sentence summary of the situation")
    why_affected: list[str] = Field(..., description="Human-readable reasons why the shipment is affected")
    recommended_action: str = Field(..., description="Primary recommended operator action")
    evidence: list[str] = Field(..., description="Reason codes that back this explanation")
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Known unknowns or caveats the operator should be aware of",
    )
    generated_by: str = Field(..., description="Producer identifier, e.g. 'deterministic_fallback_template'")
    model_used: str | None = Field(None, description="Model identifier if an LLM was used; None for fallback")


# ---------------------------------------------------------------------------
# Route Graph
# ---------------------------------------------------------------------------

class RouteNode(BaseModel):
    """A single node (hub, port, depot) in the route graph."""
    node_id: str = Field(..., description="Unique node identifier, e.g. 'HUB-A'")
    name: str = Field("", description="Human-readable name")
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    node_type: str = Field("hub", description="Node category: hub, port, depot, airport")


class RouteEdge(BaseModel):
    """A directed or undirected edge connecting two route nodes."""
    origin_node_id: str
    destination_node_id: str
    mode: ShipmentMode
    distance_km: float = Field(..., ge=0)
    transit_hours: float = Field(..., ge=0)


class RouteGraph(BaseModel):
    """Complete route graph used by the Impact and Optimization Engines."""
    nodes: list[RouteNode] = Field(default_factory=list)
    edges: list[RouteEdge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Action Plan
# ---------------------------------------------------------------------------

class ActionPlanItem(BaseModel):
    """A single ranked recommendation in the action plan."""
    rank: int = Field(..., ge=1)
    action_type: str = Field(..., description="REROUTE | CARRIER_SWAP | ASSET_DEPLOY | COLD_CHAIN_HOLD")
    shipment_id: str
    description: str
    eta_delta_hours: float = Field(0.0, description="Estimated arrival change in hours (positive = later)")
    additional_cost_usd: float = Field(0.0, description="Estimated additional cost in USD")
    reason_codes: list[str] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0.0, le=1.0)


class ActionPlan(BaseModel):
    """Complete operator action plan for an active disruption."""
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    disruption_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    items: list[ActionPlanItem] = Field(default_factory=list)
    export_format: str = Field("json", description="'json' or 'markdown'")
