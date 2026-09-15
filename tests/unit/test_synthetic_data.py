"""
tests/unit/test_synthetic_data.py
===================================
Unit tests for the synthetic demo dataset produced by
scripts/generate_synthetic_data.py.

Each test class maps to one demo scenario requirement:

  TestDisruptedShipment        – at least one disrupted shipment
  TestUnaffectedShipment       – at least one unaffected shipment
  TestIdleCompatibleAsset      – at least one idle compatible asset
  TestColdChainShipment        – at least one cold-chain shipment
  TestTemperatureExcursion     – at least one temperature excursion
  TestFeasibleReroutingOption  – at least one feasible rerouting option
  TestInfeasibleRoutingCondition – at least one infeasible routing condition
  TestDatasetIntegrity         – referential integrity and schema correctness
  TestDeterministicGeneration  – same seed produces identical data on every call
  TestClassifyExcursionIntegration – classifier on synthetic readings matches expected status
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import timezone

import pytest

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.generate_synthetic_data import (  # noqa: E402
    DEMO_DATASET,
    build_demo_dataset,
    build_route_alternatives,
    build_sensor_readings,
    build_shipments,
    build_assets,
    build_disruptions,
    build_policies,
    build_route_graph,
    build_shipment_legs,
    build_evidence_records,
)
from src.app.core.models import (  # noqa: E402
    AssetStatus,
    ShipmentStatus,
    ShipmentMode,
    DecisionType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shipment(sid: str):
    matches = [s for s in DEMO_DATASET["shipments"] if s.shipment_id == sid]
    assert matches, f"shipment {sid!r} not found in dataset"
    return matches[0]


def _asset(aid: str):
    matches = [a for a in DEMO_DATASET["assets"] if a.asset_id == aid]
    assert matches, f"asset {aid!r} not found in dataset"
    return matches[0]


def _disruption(did: str):
    matches = [d for d in DEMO_DATASET["disruptions"] if d.disruption_id == did]
    assert matches, f"disruption {did!r} not found in dataset"
    return matches[0]


def _policy(pid: str):
    matches = [p for p in DEMO_DATASET["policies"] if p.policy_id == pid]
    assert matches, f"policy {pid!r} not found in dataset"
    return matches[0]


# ===========================================================================
# Disrupted shipment
# ===========================================================================

class TestDisruptedShipment:
    """At least one shipment must be disrupted by PORT_STRIKE_01."""

    def test_disrupted_shipment_exists(self):
        """SHP-0042 is present and IN_TRANSIT."""
        shp = _shipment("SHP-0042")
        assert shp.status == ShipmentStatus.IN_TRANSIT

    def test_disrupted_shipment_route_intersects_blocked_node(self):
        """SHP-0042's legs must pass through PORT-03 (the blocked node)."""
        legs = [
            leg for leg in DEMO_DATASET["shipment_legs"]
            if leg.shipment_id == "SHP-0042"
        ]
        route_nodes = {n for leg in legs for n in (leg.origin_node_id, leg.destination_node_id)}
        disruption = _disruption("PORT_STRIKE_01")
        assert route_nodes & set(disruption.blocked_nodes), (
            f"SHP-0042 route {route_nodes} does not intersect "
            f"blocked nodes {disruption.blocked_nodes}"
        )

    def test_disrupted_shipment_is_cold_chain(self):
        """The disrupted shipment must carry cold-chain cargo."""
        shp = _shipment("SHP-0042")
        assert shp.temperature_policy_id is not None
        assert shp.cargo_type == "reefer"

    def test_disrupted_shipment_transit_window_overlaps_disruption(self):
        """SHP-0042's transit window must overlap the disruption window."""
        shp = _shipment("SHP-0042")
        dis = _disruption("PORT_STRIKE_01")
        assert shp.planned_departure <= dis.window_end
        assert dis.window_start <= shp.planned_arrival


# ===========================================================================
# Unaffected shipment
# ===========================================================================

class TestUnaffectedShipment:
    """At least one shipment must be unaffected by the disruption."""

    def test_unaffected_shipment_exists(self):
        shp = _shipment("SHP-0099")
        assert shp.status == ShipmentStatus.IN_TRANSIT

    def test_unaffected_shipment_route_avoids_blocked_nodes(self):
        """SHP-0099's legs must NOT pass through PORT-03."""
        legs = [
            leg for leg in DEMO_DATASET["shipment_legs"]
            if leg.shipment_id == "SHP-0099"
        ]
        route_nodes = {n for leg in legs for n in (leg.origin_node_id, leg.destination_node_id)}
        disruption = _disruption("PORT_STRIKE_01")
        assert not (route_nodes & set(disruption.blocked_nodes)), (
            f"SHP-0099 unexpectedly intersects blocked nodes {disruption.blocked_nodes}"
        )

    def test_unaffected_shipment_uses_bypass_mode(self):
        """The unaffected shipment uses air mode (bypass route)."""
        shp = _shipment("SHP-0099")
        assert shp.mode == ShipmentMode.AIR

    def test_unaffected_shipment_no_temperature_policy(self):
        """SHP-0099 is ambient cargo and carries no cold-chain policy."""
        shp = _shipment("SHP-0099")
        assert shp.temperature_policy_id is None


# ===========================================================================
# Idle compatible asset
# ===========================================================================

class TestIdleCompatibleAsset:
    """At least one idle, reefer-capable asset compatible with SHP-0042."""

    def test_idle_reefer_asset_exists(self):
        idle_reefer = [
            a for a in DEMO_DATASET["assets"]
            if a.status == AssetStatus.AVAILABLE and a.reefer_capable
        ]
        assert idle_reefer, "No idle reefer-capable asset found in dataset"

    def test_truck_17_is_idle_and_reefer_capable(self):
        asset = _asset("TRUCK-17")
        assert asset.status == AssetStatus.AVAILABLE
        assert asset.reefer_capable is True

    def test_truck_17_capacity_exceeds_shp_0042_weight(self):
        """TRUCK-17 must be able to carry SHP-0042's payload."""
        asset = _asset("TRUCK-17")
        shp = _shipment("SHP-0042")
        assert asset.capacity_kg >= shp.weight_kg

    def test_idle_asset_mode_compatible_with_disrupted_leg(self):
        """TRUCK-17 is ROAD -- compatible with SHP-0042's last leg (HUB-B → HUB-D)."""
        asset = _asset("TRUCK-17")
        assert asset.mode == ShipmentMode.ROAD

    def test_non_reefer_asset_also_present(self):
        """TRUCK-22 (non-reefer) must also exist to represent an infeasible option."""
        non_reefer = [
            a for a in DEMO_DATASET["assets"]
            if not a.reefer_capable and a.status == AssetStatus.AVAILABLE
        ]
        assert non_reefer, "No non-reefer available asset found"

    def test_in_use_vessel_is_not_idle(self):
        """VESSEL-04 must be IN_USE -- not a candidate for redeployment."""
        vessel = _asset("VESSEL-04")
        assert vessel.status == AssetStatus.IN_USE


# ===========================================================================
# Cold-chain shipment
# ===========================================================================

class TestColdChainShipment:
    """At least one shipment must have a cold-chain policy profile."""

    def test_cold_chain_shipment_has_policy(self):
        cold_chain_shps = [
            s for s in DEMO_DATASET["shipments"]
            if s.temperature_policy_id is not None
        ]
        assert cold_chain_shps, "No shipment with a temperature policy found"

    def test_policy_pol_cdc_01_present(self):
        pol = _policy("POL-CDC-01")
        assert pol.min_celsius == 2.0
        assert pol.max_celsius == 8.0
        assert pol.product_class == "refrigerated_vaccine"

    def test_policy_has_required_severity_rules(self):
        pol = _policy("POL-CDC-01")
        assert "out_of_range" in pol.severity_rules
        assert "missing_sensor_data" in pol.severity_rules

    def test_policy_thresholds_not_hardcoded_in_readings(self):
        """Readings themselves carry raw temperatures; the policy dict is the
        sole source of threshold knowledge."""
        pol = _policy("POL-CDC-01")
        # Ensure the policy boundary values are what we expect -- if someone
        # changes them the classifier outcome changes, not the readings.
        assert pol.min_celsius < pol.max_celsius
        assert pol.max_celsius <= 10.0  # sanity: still a cold-chain policy

    def test_sensor_readings_linked_to_cold_chain_shipment(self):
        cold_chain_ids = {
            s.shipment_id for s in DEMO_DATASET["shipments"]
            if s.temperature_policy_id is not None
        }
        reading_ids = {r.shipment_id for r in DEMO_DATASET["sensor_readings"]}
        assert cold_chain_ids & reading_ids, (
            "No sensor readings for any cold-chain shipment"
        )


# ===========================================================================
# Temperature excursion
# ===========================================================================

class TestTemperatureExcursion:
    """At least one sensor reading must be outside the policy bounds."""

    def test_excursion_readings_exist(self):
        pol = _policy("POL-CDC-01")
        out_of_range = [
            r for r in DEMO_DATASET["sensor_readings"]
            if not (pol.min_celsius <= r.temperature_c <= pol.max_celsius)
        ]
        assert out_of_range, "No out-of-range sensor readings found"

    def test_excursion_peak_temperature(self):
        """The peak reading must be 10.4 °C (reference scenario from preflight_demo.py)."""
        max_temp = max(r.temperature_c for r in DEMO_DATASET["sensor_readings"])
        assert max_temp == pytest.approx(10.4)

    def test_excursion_reading_count(self):
        """Exactly 3 of the 5 readings must be out of range for POL-CDC-01."""
        pol = _policy("POL-CDC-01")
        out_of_range = [
            r for r in DEMO_DATASET["sensor_readings"]
            if not (pol.min_celsius <= r.temperature_c <= pol.max_celsius)
        ]
        assert len(out_of_range) == 3

    def test_excursion_duration_exceeds_max_continuous(self):
        """3 readings × 6-minute interval = 18 min > max_continuous_excursion_minutes (15)."""
        pol = _policy("POL-CDC-01")
        out_of_range_count = sum(
            1 for r in DEMO_DATASET["sensor_readings"]
            if not (pol.min_celsius <= r.temperature_c <= pol.max_celsius)
        )
        duration_minutes = out_of_range_count * pol.sample_interval_minutes
        assert duration_minutes > pol.max_continuous_excursion_minutes

    def test_in_range_readings_also_present(self):
        """The first and last readings must be in-range (spike pattern)."""
        pol = _policy("POL-CDC-01")
        in_range = [
            r for r in DEMO_DATASET["sensor_readings"]
            if pol.min_celsius <= r.temperature_c <= pol.max_celsius
        ]
        assert len(in_range) >= 2

    def test_readings_are_chronologically_ordered(self):
        readings = sorted(DEMO_DATASET["sensor_readings"], key=lambda r: r.ts)
        for i in range(1, len(readings)):
            assert readings[i].ts > readings[i - 1].ts

    def test_evidence_record_captures_excursion(self):
        """An COLD_CHAIN evidence record for SHP-0042 must be present."""
        cold_chain_ev = [
            ev for ev in DEMO_DATASET["evidence_records"]
            if ev.decision_type == DecisionType.COLD_CHAIN
            and ev.shipment_id == "SHP-0042"
        ]
        assert cold_chain_ev, "No COLD_CHAIN evidence record for SHP-0042"
        assert "EXCURSION_REVIEW" in cold_chain_ev[0].reason_codes


# ===========================================================================
# Feasible rerouting option
# ===========================================================================

class TestFeasibleReroutingOption:
    """At least one route alternative must be feasible (reefer-capable, in-SLA)."""

    def test_feasible_alternative_exists(self):
        feasible = [
            alt for alt in DEMO_DATASET["route_alternatives"]
            if alt.reefer_capable and alt.eta_delta_hours < 24.0
        ]
        assert feasible, "No feasible reefer rerouting option found"

    def test_carrier_b_is_feasible(self):
        carrier_b = [
            alt for alt in DEMO_DATASET["route_alternatives"]
            if alt.carrier_id == "CARRIER-B"
        ]
        assert carrier_b, "CARRIER-B alternative not found"
        alt = carrier_b[0]
        assert alt.reefer_capable is True
        assert alt.eta_delta_hours == pytest.approx(5.4)
        assert alt.additional_cost_usd == pytest.approx(1800.0)

    def test_feasible_route_avoids_blocked_node(self):
        """The feasible reroute must not pass through PORT-03."""
        feasible = [
            alt for alt in DEMO_DATASET["route_alternatives"]
            if alt.reefer_capable and alt.eta_delta_hours < 24.0
        ]
        for alt in feasible:
            assert "PORT-03" not in alt.route_nodes, (
                f"Feasible alternative {alt.carrier_id} still routes through blocked PORT-03"
            )

    def test_feasible_route_has_reason_codes(self):
        feasible = [
            alt for alt in DEMO_DATASET["route_alternatives"]
            if alt.reefer_capable
        ]
        for alt in feasible:
            assert alt.reason_codes, "Feasible reroute must carry reason codes"

    def test_evidence_record_for_route_recommendation(self):
        """A ROUTE evidence record for SHP-0042 must be present."""
        route_ev = [
            ev for ev in DEMO_DATASET["evidence_records"]
            if ev.decision_type == DecisionType.ROUTE
            and ev.shipment_id == "SHP-0042"
        ]
        assert route_ev, "No ROUTE evidence record for SHP-0042"
        assert route_ev[0].confidence_score >= 0.9


# ===========================================================================
# Infeasible routing condition
# ===========================================================================

class TestInfeasibleRoutingCondition:
    """At least one route alternative must be infeasible."""

    def test_infeasible_alternative_exists(self):
        """An alternative with REEFER_CAPABILITY_MISSING reason code must exist."""
        infeasible = [
            alt for alt in DEMO_DATASET["route_alternatives"]
            if "REEFER_CAPABILITY_MISSING" in alt.reason_codes
            or "ETA_SLA_BREACH" in alt.reason_codes
        ]
        assert infeasible, "No infeasible routing option found"

    def test_carrier_a_is_infeasible_for_reefer_shipment(self):
        carrier_a = [
            alt for alt in DEMO_DATASET["route_alternatives"]
            if alt.carrier_id == "CARRIER-A"
        ]
        assert carrier_a, "CARRIER-A alternative not found"
        alt = carrier_a[0]
        assert alt.reefer_capable is False
        assert "REEFER_CAPABILITY_MISSING" in alt.reason_codes

    def test_infeasible_alternative_breaches_sla(self):
        """CARRIER-A's +32h delay must breach any reasonable SLA."""
        carrier_a = [
            alt for alt in DEMO_DATASET["route_alternatives"]
            if alt.carrier_id == "CARRIER-A"
        ]
        assert carrier_a[0].eta_delta_hours > 24.0

    def test_non_reefer_asset_present_but_incompatible(self):
        """TRUCK-22 is available but non-reefer; cannot serve SHP-0042."""
        truck22 = _asset("TRUCK-22")
        shp = _shipment("SHP-0042")
        assert truck22.status == AssetStatus.AVAILABLE
        assert truck22.reefer_capable is False
        assert shp.temperature_policy_id is not None  # requires reefer


# ===========================================================================
# Dataset integrity
# ===========================================================================

class TestDatasetIntegrity:
    """Referential integrity and schema completeness checks."""

    def test_all_sensor_readings_reference_known_shipment(self):
        shipment_ids = {s.shipment_id for s in DEMO_DATASET["shipments"]}
        for reading in DEMO_DATASET["sensor_readings"]:
            assert reading.shipment_id in shipment_ids, (
                f"Sensor reading {reading.sensor_id} references unknown shipment "
                f"{reading.shipment_id!r}"
            )

    def test_all_legs_reference_known_shipment(self):
        shipment_ids = {s.shipment_id for s in DEMO_DATASET["shipments"]}
        for leg in DEMO_DATASET["shipment_legs"]:
            assert leg.shipment_id in shipment_ids, (
                f"Leg {leg.leg_id} references unknown shipment {leg.shipment_id!r}"
            )

    def test_all_shipments_have_valid_nodes(self):
        node_ids = {n.node_id for n in DEMO_DATASET["route_graph"].nodes}
        for shp in DEMO_DATASET["shipments"]:
            assert shp.origin_hub_id in node_ids, f"{shp.shipment_id}: origin not in graph"
            assert shp.destination_hub_id in node_ids, f"{shp.shipment_id}: destination not in graph"

    def test_evidence_records_reference_known_shipments(self):
        shipment_ids = {s.shipment_id for s in DEMO_DATASET["shipments"]}
        for ev in DEMO_DATASET["evidence_records"]:
            assert ev.shipment_id in shipment_ids, (
                f"Evidence record {ev.decision_id} references unknown shipment {ev.shipment_id!r}"
            )

    def test_evidence_records_reference_known_disruptions(self):
        disruption_ids = {d.disruption_id for d in DEMO_DATASET["disruptions"]}
        for ev in DEMO_DATASET["evidence_records"]:
            if ev.disruption_id is not None:
                assert ev.disruption_id in disruption_ids, (
                    f"Evidence record {ev.decision_id} references unknown disruption "
                    f"{ev.disruption_id!r}"
                )

    def test_cold_chain_shipments_have_matching_policy(self):
        policy_ids = {p.policy_id for p in DEMO_DATASET["policies"]}
        for shp in DEMO_DATASET["shipments"]:
            if shp.temperature_policy_id is not None:
                assert shp.temperature_policy_id in policy_ids, (
                    f"Shipment {shp.shipment_id} references unknown policy "
                    f"{shp.temperature_policy_id!r}"
                )

    def test_all_shipments_pass_pydantic_validation(self):
        """Pydantic models validate at construction; this test just asserts they
        are all proper model instances."""
        from src.app.core.models import Shipment
        for shp in DEMO_DATASET["shipments"]:
            assert isinstance(shp, Shipment)

    def test_all_assets_pass_pydantic_validation(self):
        from src.app.core.models import Asset
        for ast in DEMO_DATASET["assets"]:
            assert isinstance(ast, Asset)

    def test_all_sensor_readings_pass_pydantic_validation(self):
        from src.app.core.models import SensorReading
        for sr in DEMO_DATASET["sensor_readings"]:
            assert isinstance(sr, SensorReading)

    def test_all_legs_ordered_correctly(self):
        """For each shipment, leg sequences must form a contiguous 0-based range."""
        from itertools import groupby
        legs_by_shipment: dict[str, list] = {}
        for leg in DEMO_DATASET["shipment_legs"]:
            legs_by_shipment.setdefault(leg.shipment_id, []).append(leg)
        for sid, legs in legs_by_shipment.items():
            seqs = sorted(leg.sequence for leg in legs)
            assert seqs == list(range(len(seqs))), (
                f"Shipment {sid} has non-contiguous leg sequences: {seqs}"
            )

    def test_disruption_window_valid(self):
        for dis in DEMO_DATASET["disruptions"]:
            assert dis.window_start < dis.window_end

    def test_shipment_timestamps_valid(self):
        for shp in DEMO_DATASET["shipments"]:
            assert shp.planned_departure < shp.planned_arrival
            assert shp.planned_arrival <= shp.delivery_deadline

    def test_policy_thresholds_valid(self):
        for pol in DEMO_DATASET["policies"]:
            assert pol.min_celsius < pol.max_celsius

    def test_route_graph_nodes_and_edges_consistent(self):
        graph = DEMO_DATASET["route_graph"]
        node_ids = {n.node_id for n in graph.nodes}
        for edge in graph.edges:
            assert edge.origin_node_id in node_ids, f"Edge origin {edge.origin_node_id!r} not in nodes"
            assert edge.destination_node_id in node_ids, f"Edge dest {edge.destination_node_id!r} not in nodes"

    def test_dataset_has_all_required_keys(self):
        required = {
            "route_graph", "policies", "disruptions", "shipments",
            "shipment_legs", "assets", "sensor_readings",
            "route_alternatives", "evidence_records",
        }
        assert required <= DEMO_DATASET.keys()

    def test_confidence_scores_in_bounds(self):
        for ev in DEMO_DATASET["evidence_records"]:
            assert 0.0 <= ev.confidence_score <= 1.0

    def test_timestamps_are_timezone_aware(self):
        """All datetime fields in the dataset must carry timezone info."""
        for shp in DEMO_DATASET["shipments"]:
            assert shp.planned_departure.tzinfo is not None
            assert shp.planned_arrival.tzinfo is not None
            assert shp.delivery_deadline.tzinfo is not None
        for sr in DEMO_DATASET["sensor_readings"]:
            assert sr.ts.tzinfo is not None
        for dis in DEMO_DATASET["disruptions"]:
            assert dis.window_start.tzinfo is not None
            assert dis.window_end.tzinfo is not None


# ===========================================================================
# Deterministic generation
# ===========================================================================

class TestDeterministicGeneration:
    """build_demo_dataset() must return identical data on every call."""

    def test_multiple_calls_produce_identical_shipments(self):
        ds1 = build_demo_dataset()
        ds2 = build_demo_dataset()
        for s1, s2 in zip(ds1["shipments"], ds2["shipments"]):
            assert s1.shipment_id == s2.shipment_id
            assert s1.cargo_value_usd == s2.cargo_value_usd
            assert s1.weight_kg == s2.weight_kg

    def test_multiple_calls_produce_identical_sensor_readings(self):
        ds1 = build_demo_dataset()
        ds2 = build_demo_dataset()
        for r1, r2 in zip(ds1["sensor_readings"], ds2["sensor_readings"]):
            assert r1.sensor_id == r2.sensor_id
            assert r1.temperature_c == r2.temperature_c
            assert r1.ts == r2.ts

    def test_multiple_calls_produce_identical_assets(self):
        ds1 = build_demo_dataset()
        ds2 = build_demo_dataset()
        ids1 = [a.asset_id for a in ds1["assets"]]
        ids2 = [a.asset_id for a in ds2["assets"]]
        assert ids1 == ids2

    def test_demo_dataset_module_constant_matches_fresh_build(self):
        """The module-level DEMO_DATASET must be equivalent to a fresh call."""
        fresh = build_demo_dataset()
        assert len(fresh["shipments"]) == len(DEMO_DATASET["shipments"])
        assert len(fresh["assets"]) == len(DEMO_DATASET["assets"])
        assert len(fresh["sensor_readings"]) == len(DEMO_DATASET["sensor_readings"])


# ===========================================================================
# Classifier integration on synthetic readings
# ===========================================================================

class TestClassifyExcursionIntegration:
    """Run classify_excursion (from preflight_demo.py) on the synthetic readings
    and assert the outcomes match the documented reference scenario."""

    @pytest.fixture
    def classify(self):
        from scripts.preflight_demo import classify_excursion
        return classify_excursion

    def _readings_as_dicts(self):
        return [
            {"ts": r.ts.isoformat(), "temp_c": r.temperature_c}
            for r in DEMO_DATASET["sensor_readings"]
        ]

    def _policy_as_dict(self):
        pol = _policy("POL-CDC-01")
        return {
            "policy_id": pol.policy_id,
            "jurisdiction": pol.jurisdiction,
            "product_class": pol.product_class,
            "min_celsius": pol.min_celsius,
            "max_celsius": pol.max_celsius,
            "max_continuous_excursion_minutes": pol.max_continuous_excursion_minutes,
            "sample_interval_minutes": pol.sample_interval_minutes,
            "severity_rules": dict(pol.severity_rules),
        }

    def test_synthetic_readings_produce_excursion_review(self, classify):
        status, evidence = classify(self._policy_as_dict(), self._readings_as_dicts())
        assert status == "EXCURSION_REVIEW", (
            f"Expected EXCURSION_REVIEW for reference excursion scenario, got {status}"
        )

    def test_no_policy_returns_policy_required(self, classify):
        status, _ = classify(None, self._readings_as_dicts())
        assert status == "POLICY_REQUIRED"

    def test_empty_readings_return_urgent_escalation(self, classify):
        status, _ = classify(self._policy_as_dict(), [])
        assert status == "URGENT_ESCALATION"

    def test_in_range_reading_returns_safe(self, classify):
        in_range_reading = [{"ts": "2026-09-14T08:00:00+00:00", "temp_c": 5.0}]
        status, _ = classify(self._policy_as_dict(), in_range_reading)
        assert status == "SAFE"

    def test_evidence_contains_max_temperature(self, classify):
        status, evidence = classify(self._policy_as_dict(), self._readings_as_dicts())
        assert "max_c" in evidence
        assert evidence["max_c"] == pytest.approx(10.4)

    def test_evidence_duration_matches_expected(self, classify):
        """3 out-of-range readings × 6-minute interval = 18 minutes."""
        _, evidence = classify(self._policy_as_dict(), self._readings_as_dicts())
        assert evidence.get("duration_minutes") == pytest.approx(18.0)
