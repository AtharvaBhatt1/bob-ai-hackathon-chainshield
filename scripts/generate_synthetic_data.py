#!/usr/bin/env python3
"""
scripts/generate_synthetic_data.py
====================================
Canonical ChainShield offline demonstration scenario — synthetic data only.

This module produces a deterministic ``DEMO_DATASET`` dict (and exposes all
sub-builder functions) that satisfies every requirement of the canonical demo:

    1. Identify shipments affected by an active disruption         (SHP-0042)
    2. Recommend rerouting options                                 (CARRIER-B)
    3. Recommend carrier alternatives                              (CARRIER-B / CARRIER-A)
    4. Identify idle fleet assets for redeployment                 (TRUCK-17)
    5. Monitor cold-chain sensor logs                              (SENSOR-9 readings)
    6. Detect temperature excursions before delivery               (8.9 / 10.4 / 9.1 °C)
    7. Classify excursion severity using a configurable policy     (POL-CDC-01 → EXCURSION_REVIEW)

Determinism guarantees
----------------------
- All IDs are literal strings — no UUIDs generated at call time.
- All timestamps are timezone-aware UTC.
- build_demo_dataset() called N times always returns structurally identical data.
- DEMO_DATASET is built once at module import so that every import in the same
  process sees exactly the same constant.

Design constraints (AGENTS.md)
--------------------------------
- This module contains **only data** — no business logic.
- Thresholds live in policy dicts, never in the data itself.
- No network access, no disk I/O.
- DuckDB / FastAPI are NOT imported here.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path when this module is imported directly
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.core.models import (  # noqa: E402
    Asset,
    AssetStatus,
    AssetType,
    DecisionType,
    Disruption,
    DisruptionType,
    EvidenceRecord,
    PolicyProfile,
    RouteEdge,
    RouteGraph,
    RouteNode,
    Shipment,
    ShipmentLeg,
    ShipmentMode,
    ShipmentStatus,
    SensorReading,
)
from src.app.core.schemas import RouteAlternative  # noqa: E402


# ---------------------------------------------------------------------------
# Timestamp helpers (all UTC-aware)
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int,
         hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# ===========================================================================
# 1. Route graph  (nodes + edges)
# ===========================================================================

def build_route_graph() -> RouteGraph:
    """Return the canonical 4-node route graph.

    Nodes: HUB-A, PORT-03, HUB-B, HUB-D
    Edges:
      HUB-A  ─sea──►  PORT-03  ─sea──►  HUB-B  ─road──►  HUB-D
      HUB-A  ─air──►  HUB-D              (bypass — never passes PORT-03)
      HUB-B  ─road──► HUB-D              (last leg continuation)
    """
    nodes = [
        RouteNode(node_id="HUB-A",   name="Origin Hub A",        latitude=51.5074,  longitude=-0.1278,  node_type="hub"),
        RouteNode(node_id="PORT-03", name="Port 03 (disrupted)", latitude=51.9000,  longitude=4.4800,   node_type="port"),
        RouteNode(node_id="HUB-B",   name="Transit Hub B",        latitude=53.3498,  longitude=-6.2603,  node_type="hub"),
        RouteNode(node_id="HUB-D",   name="Destination Hub D",    latitude=48.8566,  longitude=2.3522,   node_type="hub"),
    ]
    edges = [
        RouteEdge(origin_node_id="HUB-A",   destination_node_id="PORT-03", mode=ShipmentMode.SEA,  distance_km=520.0,  transit_hours=12.0),
        RouteEdge(origin_node_id="PORT-03", destination_node_id="HUB-B",   mode=ShipmentMode.SEA,  distance_km=840.0,  transit_hours=18.0),
        RouteEdge(origin_node_id="HUB-B",   destination_node_id="HUB-D",   mode=ShipmentMode.ROAD, distance_km=180.0,  transit_hours=4.0),
        RouteEdge(origin_node_id="HUB-A",   destination_node_id="HUB-D",   mode=ShipmentMode.AIR,  distance_km=1100.0, transit_hours=8.0),
    ]
    return RouteGraph(nodes=nodes, edges=edges)


# ===========================================================================
# 2. Policies
# ===========================================================================

def build_policies() -> list[PolicyProfile]:
    """Return the two canonical policy profiles.

    POL-CDC-01:      Refrigerated vaccine — 2–8 °C, strict.
    POL-AMBIENT-01:  Ambient cargo — 5–30 °C, lenient.
                     ``missing_sensor_data`` → EXCURSION_REVIEW so that
                     SHP-0099 (no readings) produces EXCURSION_REVIEW not
                     POLICY_REQUIRED in the cold-chain timeline endpoint.
    """
    return [
        PolicyProfile(
            policy_id="POL-CDC-01",
            jurisdiction="US",
            product_class="refrigerated_vaccine",
            min_celsius=2.0,
            max_celsius=8.0,
            max_continuous_excursion_minutes=15,
            sample_interval_minutes=6,
            source_reference="CDC Vaccine Storage and Handling Toolkit (demo profile, not authoritative)",
            severity_rules={
                "out_of_range": "EXCURSION_REVIEW",
                "missing_sensor_data": "URGENT_ESCALATION",
            },
        ),
        PolicyProfile(
            policy_id="POL-AMBIENT-01",
            jurisdiction="GLOBAL",
            product_class="ambient_general",
            min_celsius=5.0,
            max_celsius=30.0,
            max_continuous_excursion_minutes=60,
            sample_interval_minutes=30,
            source_reference="ChainShield internal ambient cargo baseline (demo)",
            severity_rules={
                "out_of_range": "EXCURSION_REVIEW",
                "missing_sensor_data": "EXCURSION_REVIEW",
            },
        ),
    ]


# ===========================================================================
# 3. Disruptions
# ===========================================================================

def build_disruptions() -> list[Disruption]:
    """Return one active disruption: PORT_STRIKE_01 blocking PORT-03."""
    return [
        Disruption(
            disruption_id="PORT_STRIKE_01",
            disruption_type=DisruptionType.STRIKE,
            description="Industrial action at Port 03 — all inbound/outbound vessel movements suspended.",
            blocked_nodes=["PORT-03"],
            blocked_edges=[],
            window_start=_utc(2026, 9, 14, 0, 0, 0),
            window_end=_utc(2026, 9, 17, 0, 0, 0),
            severity="HIGH",
        ),
    ]


# ===========================================================================
# 4. Shipments
# ===========================================================================

def build_shipments() -> list[Shipment]:
    """Return the two canonical shipments.

    SHP-0042  Refrigerated vaccine, IN_TRANSIT via PORT-03 → affected.
    SHP-0099  Ambient electronics, IN_TRANSIT via HUB-A→HUB-D bypass → unaffected.
    """
    return [
        Shipment(
            shipment_id="SHP-0042",
            cargo_type="reefer",
            product_class="refrigerated_vaccine",
            temperature_policy_id="POL-CDC-01",
            origin_hub_id="HUB-A",
            destination_hub_id="HUB-D",
            current_node_id="HUB-B",
            mode=ShipmentMode.SEA,
            carrier_id="CARRIER-A",
            planned_departure=_utc(2026, 9, 14, 6, 0, 0),
            planned_arrival=_utc(2026, 9, 16, 14, 0, 0),
            delivery_deadline=_utc(2026, 9, 16, 18, 0, 0),
            cargo_value_usd=520_000.0,
            weight_kg=8_200.0,
            status=ShipmentStatus.IN_TRANSIT,
        ),
        Shipment(
            shipment_id="SHP-0099",
            cargo_type="ambient",
            product_class="ambient_general",
            temperature_policy_id=None,
            origin_hub_id="HUB-A",
            destination_hub_id="HUB-D",
            current_node_id="HUB-A",
            mode=ShipmentMode.AIR,
            carrier_id="CARRIER-C",
            planned_departure=_utc(2026, 9, 14, 6, 0, 0),
            planned_arrival=_utc(2026, 9, 15, 2, 0, 0),
            delivery_deadline=_utc(2026, 9, 15, 12, 0, 0),
            cargo_value_usd=95_000.0,
            weight_kg=1_800.0,
            status=ShipmentStatus.IN_TRANSIT,
        ),
    ]


# ===========================================================================
# 5. Shipment legs
# ===========================================================================

def build_shipment_legs() -> list[ShipmentLeg]:
    """Return the planned legs for both shipments.

    SHP-0042 (sea): HUB-A→PORT-03→HUB-B→HUB-D  (PORT-03 is blocked)
    SHP-0099 (air): HUB-A→HUB-D                  (direct bypass)
    """
    return [
        # SHP-0042 leg 0: HUB-A → PORT-03
        ShipmentLeg(
            leg_id="LEG-0042-0",
            shipment_id="SHP-0042",
            sequence=0,
            origin_node_id="HUB-A",
            destination_node_id="PORT-03",
            mode=ShipmentMode.SEA,
            carrier_id="CARRIER-A",
            planned_departure=_utc(2026, 9, 14, 6, 0, 0),
            planned_arrival=_utc(2026, 9, 14, 18, 0, 0),
        ),
        # SHP-0042 leg 1: PORT-03 → HUB-B
        ShipmentLeg(
            leg_id="LEG-0042-1",
            shipment_id="SHP-0042",
            sequence=1,
            origin_node_id="PORT-03",
            destination_node_id="HUB-B",
            mode=ShipmentMode.SEA,
            carrier_id="CARRIER-A",
            planned_departure=_utc(2026, 9, 14, 20, 0, 0),
            planned_arrival=_utc(2026, 9, 15, 14, 0, 0),
        ),
        # SHP-0042 leg 2: HUB-B → HUB-D
        ShipmentLeg(
            leg_id="LEG-0042-2",
            shipment_id="SHP-0042",
            sequence=2,
            origin_node_id="HUB-B",
            destination_node_id="HUB-D",
            mode=ShipmentMode.ROAD,
            carrier_id="CARRIER-B",
            planned_departure=_utc(2026, 9, 16, 6, 0, 0),
            planned_arrival=_utc(2026, 9, 16, 14, 0, 0),
        ),
        # SHP-0099 leg 0: HUB-A → HUB-D  (direct air bypass)
        ShipmentLeg(
            leg_id="LEG-0099-0",
            shipment_id="SHP-0099",
            sequence=0,
            origin_node_id="HUB-A",
            destination_node_id="HUB-D",
            mode=ShipmentMode.AIR,
            carrier_id="CARRIER-C",
            planned_departure=_utc(2026, 9, 14, 6, 0, 0),
            planned_arrival=_utc(2026, 9, 15, 2, 0, 0),
        ),
    ]


# ===========================================================================
# 6. Assets
# ===========================================================================

def build_assets() -> list[Asset]:
    """Return the fleet assets for the demo scenario.

    TRUCK-17  (CARRIER-B) — available, reefer-capable, HUB-B.  Compatible idle asset.
    TRUCK-22  (CARRIER-C) — available, NON-reefer.             Incompatible (no cold-chain).
    VESSEL-04 (CARRIER-A) — IN_USE.                            Not a redeployment candidate.
    """
    return [
        Asset(
            asset_id="TRUCK-17",
            asset_type=AssetType.TRUCK,
            mode=ShipmentMode.ROAD,
            current_node_id="HUB-B",
            available_at=_utc(2026, 9, 14, 9, 25, 0),
            capacity_kg=12_000.0,
            reefer_capable=True,
            carrier_id="CARRIER-B",
            status=AssetStatus.AVAILABLE,
        ),
        Asset(
            asset_id="TRUCK-22",
            asset_type=AssetType.TRUCK,
            mode=ShipmentMode.ROAD,
            current_node_id="HUB-D",
            available_at=_utc(2026, 9, 14, 10, 0, 0),
            capacity_kg=9_000.0,
            reefer_capable=False,
            carrier_id="CARRIER-C",
            status=AssetStatus.AVAILABLE,
        ),
        Asset(
            asset_id="VESSEL-04",
            asset_type=AssetType.VESSEL,
            mode=ShipmentMode.SEA,
            current_node_id="PORT-03",
            available_at=_utc(2026, 9, 18, 0, 0, 0),
            capacity_kg=250_000.0,
            reefer_capable=True,
            carrier_id="CARRIER-A",
            status=AssetStatus.IN_USE,
        ),
        Asset(
            asset_id="AIRCRAFT-11",
            asset_type=AssetType.AIRCRAFT,
            mode=ShipmentMode.AIR,
            current_node_id="HUB-A",
            available_at=_utc(2026, 9, 14, 7, 0, 0),
            capacity_kg=50_000.0,
            reefer_capable=False,
            carrier_id="CARRIER-C",
            status=AssetStatus.AVAILABLE,
        ),
    ]


# ===========================================================================
# 7. Sensor readings
# ===========================================================================

def build_sensor_readings() -> list[SensorReading]:
    """Return 5 sensor readings for SHP-0042 / SENSOR-9.

    Timestamps at 6-minute intervals.  Three readings are outside the
    2–8 °C policy window (8.9, 10.4, 9.1 °C), matching the reference
    scenario in scripts/preflight_demo.py.

    Reading pattern (SPIKE):
      08:00 →  6.9 °C  (in-range)
      08:06 →  8.9 °C  (OUT — start of excursion)
      08:12 → 10.4 °C  (OUT — peak)
      08:18 →  9.1 °C  (OUT — still out)
      08:24 →  6.4 °C  (in-range — return to normal)

    3 out-of-range readings × 6 min interval = 18 min > policy limit of 15 min
    → classified as EXCURSION_REVIEW by classify_excursion(POL-CDC-01, ...).
    """
    _READINGS = [
        ("2026-09-14T08:00:00", 6.9),
        ("2026-09-14T08:06:00", 8.9),
        ("2026-09-14T08:12:00", 10.4),
        ("2026-09-14T08:18:00", 9.1),
        ("2026-09-14T08:24:00", 6.4),
    ]
    return [
        SensorReading(
            sensor_id="SENSOR-9",
            shipment_id="SHP-0042",
            ts=datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc),
            temperature_c=temp,
            battery_pct=91.0,
        )
        for ts_str, temp in _READINGS
    ]


# ===========================================================================
# 8. Route alternatives  (for SHP-0042 after PORT_STRIKE_01)
# ===========================================================================

def build_route_alternatives() -> list[RouteAlternative]:
    """Return two pre-computed route alternatives for SHP-0042.

    CARRIER-B  — feasible: reefer-capable, avoids PORT-03, +5.4h, +$1 800.
    CARRIER-A  — infeasible: no reefer capability, +32h SLA breach.

    The reason_codes and reefer_capable fields encode constraint verdicts so
    that the Optimization Engine's output is visible without re-running it.
    """
    return [
        RouteAlternative(
            carrier_id="CARRIER-B",
            route_nodes=["HUB-A", "HUB-B", "HUB-D"],
            eta_delta_hours=5.4,
            additional_cost_usd=1_800.0,
            reason_codes=["CAPACITY_OK", "REEFER_CAPACITY_AVAILABLE", "ROUTE_FEASIBLE"],
            reefer_capable=True,
        ),
        RouteAlternative(
            carrier_id="CARRIER-A",
            route_nodes=["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
            eta_delta_hours=32.0,
            additional_cost_usd=0.0,
            reason_codes=["REEFER_CAPABILITY_MISSING", "ETA_SLA_BREACH"],
            reefer_capable=False,
        ),
    ]


# ===========================================================================
# 9. Evidence records  (deterministic IDs)
# ===========================================================================

def build_evidence_records() -> list[EvidenceRecord]:
    """Return three pre-computed evidence records with stable decision_id values.

    dec-impact-0042-001    IMPACT decision: SHP-0042 affected by PORT_STRIKE_01.
    dec-coldchain-0042-001 COLD_CHAIN decision: EXCURSION_REVIEW for SHP-0042.
    dec-route-0042-001     ROUTE decision: CARRIER-B recommended for SHP-0042.

    These IDs are referenced by the API endpoint tests (test_api_endpoints.py).
    """
    _TS = _utc(2026, 9, 14, 8, 30, 0)
    return [
        EvidenceRecord(
            decision_id="dec-impact-0042-001",
            timestamp=_TS,
            decision_type=DecisionType.IMPACT,
            shipment_id="SHP-0042",
            disruption_id="PORT_STRIKE_01",
            policy_id=None,
            reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH", "TEMPERATURE_EXPOSURE_INCREASED"],
            output={
                "affected": True,
                "eta_delay_hours": 24.0,
                "cargo_value_usd": 520_000.0,
                "hit_nodes": ["PORT-03"],
            },
            confidence_score=1.0,
        ),
        EvidenceRecord(
            decision_id="dec-coldchain-0042-001",
            timestamp=_TS,
            decision_type=DecisionType.COLD_CHAIN,
            shipment_id="SHP-0042",
            disruption_id="PORT_STRIKE_01",
            policy_id="POL-CDC-01",
            reason_codes=["EXCURSION_REVIEW", "TEMPERATURE_EXPOSURE_INCREASED"],
            output={
                "status": "EXCURSION_REVIEW",
                "max_c": 10.4,
                "min_c": 6.4,
                "out_of_range_count": 3,
                "cumulative_excursion_minutes": 18.0,
                "max_continuous_excursion_minutes": 18.0,
            },
            confidence_score=1.0,
        ),
        EvidenceRecord(
            decision_id="dec-route-0042-001",
            timestamp=_TS,
            decision_type=DecisionType.ROUTE,
            shipment_id="SHP-0042",
            disruption_id="PORT_STRIKE_01",
            policy_id=None,
            reason_codes=["CAPACITY_OK", "REEFER_CAPACITY_AVAILABLE", "ROUTE_FEASIBLE"],
            output={
                "carrier_id": "CARRIER-B",
                "route_nodes": ["HUB-A", "HUB-B", "HUB-D"],
                "eta_delta_hours": 5.4,
                "additional_cost_usd": 1_800.0,
                "feasible": True,
            },
            confidence_score=0.95,
        ),
        EvidenceRecord(
            decision_id="dec-impact-0099-001",
            timestamp=_TS,
            decision_type=DecisionType.IMPACT,
            shipment_id="SHP-0099",
            disruption_id="PORT_STRIKE_01",
            policy_id=None,
            reason_codes=["ROUTE_UNAFFECTED"],
            output={"affected": False, "eta_delay_hours": 0.0, "cargo_value_usd": 0.0},
            confidence_score=1.0,
        ),
    ]


# ===========================================================================
# Master builder
# ===========================================================================

def build_demo_dataset() -> dict[str, Any]:
    """Build and return the complete canonical demo dataset.

    Returns a dict with the following keys:

        route_graph          RouteGraph
        policies             list[PolicyProfile]
        disruptions          list[Disruption]
        shipments            list[Shipment]
        shipment_legs        list[ShipmentLeg]
        assets               list[Asset]
        sensor_readings      list[SensorReading]
        route_alternatives   list[RouteAlternative]
        evidence_records     list[EvidenceRecord]

    This function is **pure and deterministic**: calling it N times always
    produces structurally identical data.  No random values, no UUIDs
    generated at call time (all IDs are literal strings).
    """
    return {
        "route_graph": build_route_graph(),
        "policies": build_policies(),
        "disruptions": build_disruptions(),
        "shipments": build_shipments(),
        "shipment_legs": build_shipment_legs(),
        "assets": build_assets(),
        "sensor_readings": build_sensor_readings(),
        "route_alternatives": build_route_alternatives(),
        "evidence_records": build_evidence_records(),
    }


# ---------------------------------------------------------------------------
# Module-level constant  (imported by database.py, main.py, and tests)
# ---------------------------------------------------------------------------

DEMO_DATASET: dict[str, Any] = build_demo_dataset()
