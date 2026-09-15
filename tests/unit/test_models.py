"""
tests/unit/test_models.py
=========================
Unit tests for ChainShield Pydantic data-contract models.

Covers:
- Shipment: required fields, identifier presence, temporal ordering,
  arrival-before-deadline constraint.
- ShipmentLeg: leg departure before arrival, FK field present.
- Asset: required fields, capacity positive, reefer flag.
- SensorReading: required fields, battery bounds.
- PolicyProfile: required severity_rules keys, min < max constraint,
  configurable threshold (swapping policy dict changes outcome).
- Disruption: required fields, window_start before window_end.
- EvidenceRecord: auto-generated decision_id UUID, confidence bounds.
- ExplanationResult: all five required keys present.
- RouteGraph: node and edge composition.
- Schemas: ImpactResult, RouteAlternative, ColdChainTimelineResponse,
  DecisionContext, ActionPlanResponse, HealthResponse.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from src.app.core.models import (
    ActionPlan,
    ActionPlanItem,
    Asset,
    AssetStatus,
    AssetType,
    DecisionType,
    Disruption,
    DisruptionType,
    EvidenceRecord,
    ExcursionStatus,
    ExplanationResult,
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
from src.app.core.schemas import (
    ActionPlanResponse,
    AssetMatch,
    ColdChainTimelineResponse,
    DecisionContext,
    DisruptionActivateRequest,
    DisruptionActivateResponse,
    HealthResponse,
    ImpactResult,
    RouteAlternative,
    ShipmentDetailResponse,
    SensorReadingOut,
)


# ---------------------------------------------------------------------------
# Helpers / reference fixtures
# ---------------------------------------------------------------------------

def _dt(s: str) -> datetime:
    """Parse an ISO-8601 string to a timezone-aware datetime (UTC)."""
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _shipment(**overrides: Any) -> Shipment:
    defaults: dict[str, Any] = dict(
        shipment_id="SHP-0042",
        cargo_type="reefer",
        product_class="refrigerated_vaccine",
        temperature_policy_id="POL-CDC-01",
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-D",
        current_node_id="HUB-B",
        mode=ShipmentMode.SEA,
        carrier_id="CARRIER-A",
        planned_departure=_dt("2026-09-14T06:00:00"),
        planned_arrival=_dt("2026-09-16T14:00:00"),
        delivery_deadline=_dt("2026-09-16T18:00:00"),
        cargo_value_usd=520_000.0,
        weight_kg=8_200.0,
        status=ShipmentStatus.IN_TRANSIT,
    )
    defaults.update(overrides)
    return Shipment(**defaults)


def _policy(**overrides: Any) -> PolicyProfile:
    defaults: dict[str, Any] = dict(
        policy_id="POL-CDC-01",
        jurisdiction="US",
        product_class="refrigerated_vaccine",
        min_celsius=2.0,
        max_celsius=8.0,
        max_continuous_excursion_minutes=15,
        sample_interval_minutes=6,
        source_reference="CDC Vaccine Storage and Handling Toolkit (demo profile)",
        severity_rules={
            "out_of_range": "EXCURSION_REVIEW",
            "missing_sensor_data": "URGENT_ESCALATION",
        },
    )
    defaults.update(overrides)
    return PolicyProfile(**defaults)


def _asset(**overrides: Any) -> Asset:
    defaults: dict[str, Any] = dict(
        asset_id="TRUCK-17",
        asset_type=AssetType.TRUCK,
        mode=ShipmentMode.ROAD,
        current_node_id="HUB-B",
        available_at=_dt("2026-09-14T09:25:00"),
        capacity_kg=12_000.0,
        reefer_capable=True,
        carrier_id="CARRIER-B",
        status=AssetStatus.AVAILABLE,
    )
    defaults.update(overrides)
    return Asset(**defaults)


def _sensor_reading(**overrides: Any) -> SensorReading:
    defaults: dict[str, Any] = dict(
        sensor_id="SENSOR-9",
        shipment_id="SHP-0042",
        ts=_dt("2026-09-14T08:00:00"),
        temperature_c=6.9,
        battery_pct=91.0,
    )
    defaults.update(overrides)
    return SensorReading(**defaults)


def _disruption(**overrides: Any) -> Disruption:
    defaults: dict[str, Any] = dict(
        disruption_id="PORT_STRIKE_01",
        disruption_type=DisruptionType.STRIKE,
        description="Port strike at PORT-03",
        blocked_nodes=["PORT-03"],
        blocked_edges=[],
        window_start=_dt("2026-09-14T00:00:00"),
        window_end=_dt("2026-09-17T00:00:00"),
        severity="HIGH",
    )
    defaults.update(overrides)
    return Disruption(**defaults)


# ---------------------------------------------------------------------------
# Shipment tests
# ---------------------------------------------------------------------------

class TestShipment:
    def test_valid_reference_shipment(self):
        shp = _shipment()
        assert shp.shipment_id == "SHP-0042"
        assert shp.mode == ShipmentMode.SEA
        assert shp.cargo_value_usd == 520_000.0
        assert shp.weight_kg == 8_200.0
        assert shp.status == ShipmentStatus.IN_TRANSIT

    def test_temperature_policy_id_optional(self):
        shp = _shipment(temperature_policy_id=None)
        assert shp.temperature_policy_id is None

    def test_arrival_after_departure(self):
        """planned_departure must be strictly before planned_arrival."""
        with pytest.raises(ValidationError, match="planned_departure"):
            _shipment(
                planned_departure=_dt("2026-09-16T15:00:00"),
                planned_arrival=_dt("2026-09-14T06:00:00"),
            )

    def test_arrival_before_deadline(self):
        """planned_arrival must not be after delivery_deadline."""
        with pytest.raises(ValidationError, match="planned_arrival"):
            _shipment(
                planned_arrival=_dt("2026-09-17T00:00:00"),
                delivery_deadline=_dt("2026-09-16T18:00:00"),
            )

    def test_cargo_value_non_negative(self):
        with pytest.raises(ValidationError):
            _shipment(cargo_value_usd=-1.0)

    def test_weight_positive(self):
        with pytest.raises(ValidationError):
            _shipment(weight_kg=0.0)

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            Shipment(shipment_id="X")  # missing most required fields


# ---------------------------------------------------------------------------
# ShipmentLeg tests
# ---------------------------------------------------------------------------

class TestShipmentLeg:
    def _make_leg(self, **overrides: Any) -> ShipmentLeg:
        defaults: dict[str, Any] = dict(
            leg_id="LEG-001",
            shipment_id="SHP-0042",
            sequence=0,
            origin_node_id="HUB-A",
            destination_node_id="PORT-03",
            mode=ShipmentMode.SEA,
            carrier_id="CARRIER-A",
            planned_departure=_dt("2026-09-14T06:00:00"),
            planned_arrival=_dt("2026-09-15T12:00:00"),
        )
        defaults.update(overrides)
        return ShipmentLeg(**defaults)

    def test_valid_leg(self):
        leg = self._make_leg()
        assert leg.shipment_id == "SHP-0042"
        assert leg.sequence == 0

    def test_departure_before_arrival(self):
        with pytest.raises(ValidationError, match="planned_departure"):
            self._make_leg(
                planned_departure=_dt("2026-09-16T00:00:00"),
                planned_arrival=_dt("2026-09-14T00:00:00"),
            )

    def test_sequence_non_negative(self):
        with pytest.raises(ValidationError):
            self._make_leg(sequence=-1)


# ---------------------------------------------------------------------------
# Asset tests
# ---------------------------------------------------------------------------

class TestAsset:
    def test_valid_reference_asset(self):
        asset = _asset()
        assert asset.asset_id == "TRUCK-17"
        assert asset.reefer_capable is True
        assert asset.capacity_kg == 12_000.0

    def test_reefer_false_by_default(self):
        asset = _asset(reefer_capable=False)
        assert asset.reefer_capable is False

    def test_capacity_must_be_positive(self):
        with pytest.raises(ValidationError):
            _asset(capacity_kg=0.0)

    def test_status_enum(self):
        asset = _asset(status=AssetStatus.IN_USE)
        assert asset.status == AssetStatus.IN_USE

    def test_non_reefer_asset(self):
        """Non-reefer truck should be created without error."""
        asset = _asset(asset_id="TRUCK-99", reefer_capable=False, carrier_id="CARRIER-A")
        assert asset.reefer_capable is False


# ---------------------------------------------------------------------------
# SensorReading tests
# ---------------------------------------------------------------------------

class TestSensorReading:
    def test_valid_reading(self):
        r = _sensor_reading()
        assert r.temperature_c == 6.9
        assert r.battery_pct == 91.0

    def test_battery_optional(self):
        r = _sensor_reading(battery_pct=None)
        assert r.battery_pct is None

    def test_battery_bounds_upper(self):
        with pytest.raises(ValidationError):
            _sensor_reading(battery_pct=101.0)

    def test_battery_bounds_lower(self):
        with pytest.raises(ValidationError):
            _sensor_reading(battery_pct=-1.0)

    def test_reference_readings_all_valid(self):
        """The five preflight reference readings must all parse cleanly."""
        raw = [
            ("2026-09-14T08:00:00", 6.9),
            ("2026-09-14T08:06:00", 8.9),
            ("2026-09-14T08:12:00", 10.4),
            ("2026-09-14T08:18:00", 9.1),
            ("2026-09-14T08:24:00", 6.4),
        ]
        readings = [
            SensorReading(
                sensor_id="SENSOR-9",
                shipment_id="SHP-0042",
                ts=_dt(ts),
                temperature_c=temp,
                battery_pct=91.0,
            )
            for ts, temp in raw
        ]
        assert len(readings) == 5
        assert max(r.temperature_c for r in readings) == pytest.approx(10.4)


# ---------------------------------------------------------------------------
# PolicyProfile tests
# ---------------------------------------------------------------------------

class TestPolicyProfile:
    def test_valid_cdc_policy(self):
        p = _policy()
        assert p.min_celsius == 2.0
        assert p.max_celsius == 8.0
        assert p.severity_rules["out_of_range"] == "EXCURSION_REVIEW"
        assert p.severity_rules["missing_sensor_data"] == "URGENT_ESCALATION"

    def test_min_must_be_below_max(self):
        with pytest.raises(ValidationError, match="min_celsius"):
            _policy(min_celsius=10.0, max_celsius=5.0)

    def test_min_equal_max_rejected(self):
        with pytest.raises(ValidationError, match="min_celsius"):
            _policy(min_celsius=4.0, max_celsius=4.0)

    def test_missing_severity_key_out_of_range(self):
        with pytest.raises(ValidationError, match="severity_rules"):
            _policy(severity_rules={"missing_sensor_data": "URGENT_ESCALATION"})

    def test_missing_severity_key_missing_sensor_data(self):
        with pytest.raises(ValidationError, match="severity_rules"):
            _policy(severity_rules={"out_of_range": "EXCURSION_REVIEW"})

    def test_configurable_thresholds_different_policies_different_outcomes(self):
        """Changing only the policy dict changes which temperatures are out-of-range.
        This is the core invariant of the configurable policy design."""
        strict = _policy(min_celsius=2.0, max_celsius=5.0)   # 6.9°C is out of range
        loose = _policy(min_celsius=2.0, max_celsius=15.0)   # 6.9°C is in range

        temp = 6.9
        assert not (strict.min_celsius <= temp <= strict.max_celsius)
        assert loose.min_celsius <= temp <= loose.max_celsius

    def test_sample_interval_defaults_to_6(self):
        p = PolicyProfile(
            policy_id="P1",
            jurisdiction="US",
            product_class="food",
            min_celsius=-5.0,
            max_celsius=4.0,
            max_continuous_excursion_minutes=30,
            severity_rules={
                "out_of_range": "EXCURSION_REVIEW",
                "missing_sensor_data": "URGENT_ESCALATION",
            },
        )
        assert p.sample_interval_minutes == 6

    def test_custom_sample_interval(self):
        p = _policy(sample_interval_minutes=10)
        assert p.sample_interval_minutes == 10


# ---------------------------------------------------------------------------
# Disruption tests
# ---------------------------------------------------------------------------

class TestDisruption:
    def test_valid_port_strike(self):
        d = _disruption()
        assert d.disruption_id == "PORT_STRIKE_01"
        assert "PORT-03" in d.blocked_nodes

    def test_window_start_before_end(self):
        with pytest.raises(ValidationError, match="window_start"):
            _disruption(
                window_start=_dt("2026-09-17T00:00:00"),
                window_end=_dt("2026-09-14T00:00:00"),
            )

    def test_blocked_nodes_default_empty(self):
        d = Disruption(
            disruption_id="EVT-01",
            disruption_type=DisruptionType.WEATHER_EVENT,
            window_start=_dt("2026-09-14T00:00:00"),
            window_end=_dt("2026-09-15T00:00:00"),
        )
        assert d.blocked_nodes == []
        assert d.blocked_edges == []

    def test_disruption_type_enum(self):
        d = _disruption(disruption_type=DisruptionType.PORT_CLOSURE)
        assert d.disruption_type == DisruptionType.PORT_CLOSURE


# ---------------------------------------------------------------------------
# EvidenceRecord tests
# ---------------------------------------------------------------------------

class TestEvidenceRecord:
    def test_decision_id_auto_generated_uuid(self):
        rec = EvidenceRecord(
            decision_type=DecisionType.IMPACT,
            shipment_id="SHP-0042",
            reason_codes=["PORT_NODE_BLOCKED"],
            output={"affected": True},
            confidence_score=1.0,
        )
        # Must be parseable as UUID
        parsed = uuid.UUID(rec.decision_id)
        assert str(parsed) == rec.decision_id

    def test_two_records_have_different_ids(self):
        kwargs = dict(
            decision_type=DecisionType.IMPACT,
            shipment_id="SHP-0042",
            reason_codes=[],
            output={},
            confidence_score=1.0,
        )
        r1 = EvidenceRecord(**kwargs)
        r2 = EvidenceRecord(**kwargs)
        assert r1.decision_id != r2.decision_id

    def test_confidence_bounds_lower(self):
        with pytest.raises(ValidationError):
            EvidenceRecord(
                decision_type=DecisionType.IMPACT,
                shipment_id="SHP-0042",
                reason_codes=[],
                output={},
                confidence_score=-0.1,
            )

    def test_confidence_bounds_upper(self):
        with pytest.raises(ValidationError):
            EvidenceRecord(
                decision_type=DecisionType.IMPACT,
                shipment_id="SHP-0042",
                reason_codes=[],
                output={},
                confidence_score=1.01,
            )

    def test_optional_fields_default_none(self):
        rec = EvidenceRecord(
            decision_type=DecisionType.COLD_CHAIN,
            shipment_id="SHP-0042",
            reason_codes=["TEMPERATURE_EXPOSURE_INCREASED"],
            output={"status": "EXCURSION_REVIEW"},
            confidence_score=0.95,
        )
        assert rec.disruption_id is None
        assert rec.policy_id is None


# ---------------------------------------------------------------------------
# ExplanationResult tests
# ---------------------------------------------------------------------------

class TestExplanationResult:
    def _make_explanation(self, **overrides: Any) -> ExplanationResult:
        defaults: dict[str, Any] = dict(
            summary="SHP-0042 affected by PORT_STRIKE_01.",
            why_affected=["Flagged due to PORT_NODE_BLOCKED", "Flagged due to ETA_SLA_BREACH"],
            recommended_action="Reroute via Carrier B: +5.4h, +$1800 vs. current plan",
            evidence=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
            uncertainties=["Cold-chain status is EXCURSION_REVIEW; requires manual review."],
            generated_by="deterministic_fallback_template",
            model_used=None,
        )
        defaults.update(overrides)
        return ExplanationResult(**defaults)

    def test_all_required_keys_present(self):
        exp = self._make_explanation()
        required = {"summary", "why_affected", "recommended_action", "evidence", "uncertainties"}
        assert required.issubset(exp.model_dump().keys())

    def test_evidence_non_empty(self):
        exp = self._make_explanation()
        assert len(exp.evidence) > 0

    def test_model_used_none_for_fallback(self):
        exp = self._make_explanation()
        assert exp.model_used is None
        assert exp.generated_by == "deterministic_fallback_template"

    def test_model_used_set_for_llm(self):
        exp = self._make_explanation(
            generated_by="granite",
            model_used="ibm/granite-3-3-8b-instruct",
        )
        assert exp.model_used == "ibm/granite-3-3-8b-instruct"


# ---------------------------------------------------------------------------
# RouteGraph tests
# ---------------------------------------------------------------------------

class TestRouteGraph:
    def test_empty_graph_valid(self):
        g = RouteGraph()
        assert g.nodes == []
        assert g.edges == []

    def test_reference_graph(self):
        nodes = [
            RouteNode(node_id="HUB-A", name="Hub Alpha", node_type="hub"),
            RouteNode(node_id="HUB-B", name="Hub Beta", node_type="hub"),
            RouteNode(node_id="PORT-03", name="Port Three", node_type="port"),
            RouteNode(node_id="HUB-D", name="Hub Delta", node_type="hub"),
        ]
        edges = [
            RouteEdge(origin_node_id="HUB-A", destination_node_id="PORT-03",
                      mode=ShipmentMode.SEA, distance_km=450.0, transit_hours=12.0),
            RouteEdge(origin_node_id="PORT-03", destination_node_id="HUB-B",
                      mode=ShipmentMode.SEA, distance_km=300.0, transit_hours=8.0),
            RouteEdge(origin_node_id="HUB-B", destination_node_id="HUB-D",
                      mode=ShipmentMode.ROAD, distance_km=120.0, transit_hours=3.0),
            RouteEdge(origin_node_id="HUB-A", destination_node_id="HUB-D",
                      mode=ShipmentMode.ROAD, distance_km=550.0, transit_hours=14.0),
        ]
        g = RouteGraph(nodes=nodes, edges=edges)
        assert len(g.nodes) == 4
        assert len(g.edges) == 4

    def test_node_coordinates_bounds(self):
        with pytest.raises(ValidationError):
            RouteNode(node_id="N1", latitude=91.0, longitude=0.0)  # lat out of range

        with pytest.raises(ValidationError):
            RouteNode(node_id="N2", latitude=0.0, longitude=181.0)  # lon out of range

    def test_edge_distance_non_negative(self):
        with pytest.raises(ValidationError):
            RouteEdge(
                origin_node_id="A", destination_node_id="B",
                mode=ShipmentMode.ROAD, distance_km=-1.0, transit_hours=1.0,
            )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_impact_result(self):
        r = ImpactResult(
            shipment_id="SHP-0042",
            affected=True,
            reason_codes=["PORT_NODE_BLOCKED"],
            cargo_value_usd=520_000.0,
            eta_delay_hours=5.4,
        )
        assert r.affected is True
        assert "PORT_NODE_BLOCKED" in r.reason_codes

    def test_route_alternative(self):
        alt = RouteAlternative(
            carrier_id="CARRIER-B",
            route_nodes=["HUB-A", "HUB-D"],
            eta_delta_hours=5.4,
            additional_cost_usd=1_800.0,
            reason_codes=["REEFER_CAPACITY_AVAILABLE"],
            reefer_capable=True,
        )
        assert alt.reefer_capable is True
        assert alt.additional_cost_usd == 1_800.0

    def test_disruption_activate_request(self):
        req = DisruptionActivateRequest(disruption_id="PORT_STRIKE_01")
        assert req.disruption_id == "PORT_STRIKE_01"

    def test_disruption_activate_response(self):
        resp = DisruptionActivateResponse(
            disruption_id="PORT_STRIKE_01",
            affected_shipments=[
                ImpactResult(
                    shipment_id="SHP-0042",
                    affected=True,
                    reason_codes=["PORT_NODE_BLOCKED"],
                    cargo_value_usd=520_000.0,
                    eta_delay_hours=5.4,
                )
            ],
        )
        assert len(resp.affected_shipments) == 1
        assert resp.affected_shipments[0].shipment_id == "SHP-0042"

    def test_shipment_detail_response(self):
        resp = ShipmentDetailResponse(
            shipment=_shipment(),
            legs=[],
            alternatives=[],
        )
        assert resp.shipment.shipment_id == "SHP-0042"

    def test_asset_match(self):
        am = AssetMatch(
            asset_id="TRUCK-17",
            asset=_asset(),
            reposition_distance_km=42.0,
            available_at=_dt("2026-09-14T09:25:00"),
            reason_codes=["REEFER_CAPACITY_AVAILABLE"],
        )
        assert am.reposition_distance_km == 42.0

    def test_sensor_reading_out_in_range(self):
        r = SensorReadingOut(
            sensor_id="SENSOR-9",
            ts=_dt("2026-09-14T08:00:00"),
            temperature_c=5.0,
            battery_pct=91.0,
            in_range=True,
        )
        assert r.in_range is True

    def test_cold_chain_timeline_response(self):
        resp = ColdChainTimelineResponse(
            shipment_id="SHP-0042",
            policy=_policy(),
            readings=[
                SensorReadingOut(
                    sensor_id="SENSOR-9",
                    ts=_dt("2026-09-14T08:12:00"),
                    temperature_c=10.4,
                    in_range=False,
                )
            ],
            excursion_events=[],
            status=ExcursionStatus.EXCURSION_REVIEW,
            max_celsius=10.4,
            min_celsius=6.4,
            total_out_of_range_minutes=18.0,
        )
        assert resp.status == ExcursionStatus.EXCURSION_REVIEW
        assert resp.max_celsius == pytest.approx(10.4)

    def test_decision_context(self):
        ctx = DecisionContext(
            shipment_id="SHP-0042",
            disruption="PORT_STRIKE_01",
            reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
            recommended_route={"carrier": "Carrier B", "eta_delta_hours": 5.4, "additional_cost_usd": 1800},
            cold_chain={"status": "EXCURSION_REVIEW", "max_celsius": 10.4, "policy_max_celsius": 8.0},
        )
        assert len(ctx.reason_codes) == 2

    def test_health_response_defaults(self):
        h = HealthResponse()
        assert h.status == "ok"
        assert h.demo_mode is False
        assert h.watsonx_enabled is False

    def test_health_response_demo_mode(self):
        h = HealthResponse(demo_mode=True, watsonx_enabled=False)
        assert h.demo_mode is True


# ---------------------------------------------------------------------------
# Integration: reference scenario round-trip
# ---------------------------------------------------------------------------

class TestReferenceScenario:
    """Validate the complete reference scenario (preflight data) parses correctly."""

    def test_reference_shipment_sph_0042(self):
        shp = _shipment()
        assert shp.shipment_id == "SHP-0042"
        assert shp.temperature_policy_id == "POL-CDC-01"
        assert shp.origin_hub_id == "HUB-A"
        assert shp.destination_hub_id == "HUB-D"

    def test_reference_asset_truck_17(self):
        asset = _asset()
        assert asset.asset_id == "TRUCK-17"
        assert asset.reefer_capable is True
        assert asset.capacity_kg == 12_000.0
        assert asset.current_node_id == "HUB-B"

    def test_reference_policy_pol_cdc_01(self):
        p = _policy()
        assert p.policy_id == "POL-CDC-01"
        assert p.min_celsius == 2.0
        assert p.max_celsius == 8.0
        assert p.max_continuous_excursion_minutes == 15
        assert p.sample_interval_minutes == 6

    def test_reference_disruption_port_strike_01(self):
        d = _disruption()
        assert d.disruption_id == "PORT_STRIKE_01"
        assert "PORT-03" in d.blocked_nodes
        assert d.window_start < d.window_end

    def test_reference_sensor_readings_five_readings(self):
        readings_raw = [
            ("2026-09-14T08:00:00", 6.9),
            ("2026-09-14T08:06:00", 8.9),
            ("2026-09-14T08:12:00", 10.4),
            ("2026-09-14T08:18:00", 9.1),
            ("2026-09-14T08:24:00", 6.4),
        ]
        readings = [
            SensorReading(
                sensor_id="SENSOR-9",
                shipment_id="SHP-0042",
                ts=_dt(ts),
                temperature_c=temp,
                battery_pct=91.0,
            )
            for ts, temp in readings_raw
        ]
        policy = _policy()
        out_of_range = [
            r for r in readings
            if not (policy.min_celsius <= r.temperature_c <= policy.max_celsius)
        ]
        assert len(out_of_range) == 3  # 8.9, 10.4, 9.1 exceed 8.0°C
        duration = len(out_of_range) * policy.sample_interval_minutes
        assert duration == 18  # ~18 minutes excursion per preflight
