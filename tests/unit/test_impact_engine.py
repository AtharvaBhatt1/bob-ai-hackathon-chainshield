"""
tests/unit/test_impact_engine.py
=================================
Unit tests for the deterministic ChainShield Impact Engine.

Test matrix
-----------
1. route_affected_time_overlap       – affected + time overlap → PORT_NODE_BLOCKED
2. route_affected_no_time_overlap    – route hits blocked node but windows do not
                                       overlap → unaffected
3. route_unaffected                  – shipment bypasses all blocked nodes/edges
4. multiple_affected_shipments       – 3 shipments, 2 affected, check aggregates
5. deterministic_repeated_execution  – calling assess_impact twice with identical
                                       inputs produces byte-for-byte identical output
"""
from __future__ import annotations

from datetime import datetime, timezone

import networkx as nx
import pytest

from src.app.core.models import Disruption, DisruptionType, Shipment, ShipmentMode, ShipmentStatus
from src.app.impact.engine import (
    ImpactReport,
    ShipmentImpact,
    _windows_overlap,
    assess_impact,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _dt(iso: str) -> datetime:
    """Parse an ISO-8601 string to a timezone-aware UTC datetime."""
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def _make_graph() -> nx.Graph:
    """
    HUB-A ── PORT-03 ── HUB-B ── HUB-D
      └───────────────────────────┘   (bypass, never touches PORT-03)
    """
    g = nx.Graph()
    g.add_nodes_from(["HUB-A", "PORT-03", "HUB-B", "HUB-D"])
    g.add_edges_from(
        [
            ("HUB-A", "PORT-03"),
            ("PORT-03", "HUB-B"),
            ("HUB-B", "HUB-D"),
            ("HUB-A", "HUB-D"),
        ]
    )
    return g


def _make_disruption(
    *,
    window_start: str = "2026-09-14T00:00:00",
    window_end: str = "2026-09-17T00:00:00",
    blocked_nodes: list[str] | None = None,
    blocked_edges: list[tuple[str, str]] | None = None,
) -> Disruption:
    return Disruption(
        disruption_id="PORT_STRIKE_01",
        disruption_type=DisruptionType.PORT_CLOSURE,
        description="Strike at PORT-03",
        blocked_nodes=blocked_nodes or ["PORT-03"],
        blocked_edges=blocked_edges or [],
        window_start=_dt(window_start),
        window_end=_dt(window_end),
        severity="HIGH",
    )


def _make_shipment(
    shipment_id: str,
    *,
    departure: str,
    arrival: str,
    deadline: str | None = None,
    cargo_type: str = "general",
    cargo_value_usd: float = 100_000.0,
) -> Shipment:
    dep = _dt(departure)
    arr = _dt(arrival)
    dl = _dt(deadline) if deadline else _dt("2026-12-31T23:59:59")
    return Shipment(
        shipment_id=shipment_id,
        cargo_type=cargo_type,
        product_class="standard",
        origin_hub_id="HUB-A",
        destination_hub_id="HUB-D",
        current_node_id="HUB-A",
        mode=ShipmentMode.SEA,
        carrier_id="CARRIER-01",
        planned_departure=dep,
        planned_arrival=arr,
        delivery_deadline=dl,
        cargo_value_usd=cargo_value_usd,
        weight_kg=10_000.0,
        status=ShipmentStatus.IN_TRANSIT,
    )


# ---------------------------------------------------------------------------
# 1. route_affected_time_overlap
# ---------------------------------------------------------------------------

class TestRouteAffectedTimeOverlap:
    """Shipment route passes through PORT-03 and transit window overlaps."""

    def setup_method(self):
        self.graph = _make_graph()
        self.disruption = _make_disruption()
        self.shipment = _make_shipment(
            "SHP-0042",
            departure="2026-09-14T06:00:00",
            arrival="2026-09-16T14:00:00",
        )
        self.routes = {"SHP-0042": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"]}

    def test_shipment_is_affected(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert len(report.affected) == 1
        result = report.affected[0]
        assert result.shipment_id == "SHP-0042"
        assert result.affected is True

    def test_reason_code_port_node_blocked(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert "PORT_NODE_BLOCKED" in report.affected[0].reason_codes

    def test_cargo_value_at_risk(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert report.total_cargo_value_at_risk_usd == pytest.approx(100_000.0)

    def test_eta_delay_is_positive(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert report.affected[0].eta_delay_hours > 0

    def test_evidence_contains_hit_nodes(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert "PORT-03" in report.affected[0].evidence["hit_nodes"]


# ---------------------------------------------------------------------------
# 2. route_affected_no_time_overlap
# ---------------------------------------------------------------------------

class TestRouteAffectedNoTimeOverlap:
    """Route passes through PORT-03 but the shipment runs after the disruption."""

    def setup_method(self):
        self.graph = _make_graph()
        # Disruption ends 2026-09-17; shipment departs 2026-09-18.
        self.disruption = _make_disruption()
        self.shipment = _make_shipment(
            "SHP-0101",
            departure="2026-09-18T00:00:00",
            arrival="2026-09-20T00:00:00",
        )
        self.routes = {"SHP-0101": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"]}

    def test_shipment_is_not_affected(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert len(report.affected) == 0
        assert len(report.unaffected) == 1

    def test_no_reason_codes(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert report.unaffected[0].reason_codes == []

    def test_cargo_value_at_risk_is_zero(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert report.total_cargo_value_at_risk_usd == 0.0


# ---------------------------------------------------------------------------
# 3. route_unaffected
# ---------------------------------------------------------------------------

class TestRouteUnaffected:
    """Shipment uses the bypass edge (HUB-A → HUB-D) and never enters PORT-03."""

    def setup_method(self):
        self.graph = _make_graph()
        self.disruption = _make_disruption()
        self.shipment = _make_shipment(
            "SHP-0099",
            departure="2026-09-14T06:00:00",
            arrival="2026-09-15T02:00:00",
        )
        # Bypass route — never visits PORT-03
        self.routes = {"SHP-0099": ["HUB-A", "HUB-D"]}

    def test_shipment_is_not_affected(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert len(report.affected) == 0
        assert report.unaffected[0].shipment_id == "SHP-0099"

    def test_no_reason_codes(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert report.unaffected[0].reason_codes == []

    def test_cargo_value_at_risk_is_zero(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert report.total_cargo_value_at_risk_usd == 0.0


# ---------------------------------------------------------------------------
# 4. multiple_affected_shipments
# ---------------------------------------------------------------------------

class TestMultipleAffectedShipments:
    """
    3 shipments:
      - SHP-A: route via PORT-03 + time overlap → AFFECTED
      - SHP-B: bypass route → UNAFFECTED
      - SHP-C: route via PORT-03 + time overlap, reefer → AFFECTED + TEMPERATURE_EXPOSURE_INCREASED
    """

    def setup_method(self):
        self.graph = _make_graph()
        self.disruption = _make_disruption()

        self.shp_a = _make_shipment(
            "SHP-A",
            departure="2026-09-14T08:00:00",
            arrival="2026-09-16T08:00:00",
            cargo_value_usd=50_000.0,
        )
        self.shp_b = _make_shipment(
            "SHP-B",
            departure="2026-09-14T08:00:00",
            arrival="2026-09-15T08:00:00",
            cargo_value_usd=30_000.0,
        )
        self.shp_c = _make_shipment(
            "SHP-C",
            departure="2026-09-15T00:00:00",
            arrival="2026-09-17T00:00:00",
            cargo_type="reefer",
            cargo_value_usd=80_000.0,
        )

        self.routes = {
            "SHP-A": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
            "SHP-B": ["HUB-A", "HUB-D"],  # bypass
            "SHP-C": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
        }

    def test_two_affected_one_unaffected(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shp_a, self.shp_b, self.shp_c],
            shipment_routes=self.routes,
        )
        affected_ids = {r.shipment_id for r in report.affected}
        assert affected_ids == {"SHP-A", "SHP-C"}
        assert {r.shipment_id for r in report.unaffected} == {"SHP-B"}

    def test_total_cargo_value_at_risk(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shp_a, self.shp_b, self.shp_c],
            shipment_routes=self.routes,
        )
        assert report.total_cargo_value_at_risk_usd == pytest.approx(130_000.0)

    def test_reefer_shipment_has_temperature_code(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shp_a, self.shp_b, self.shp_c],
            shipment_routes=self.routes,
        )
        shp_c_result = next(r for r in report.affected if r.shipment_id == "SHP-C")
        assert "TEMPERATURE_EXPOSURE_INCREASED" in shp_c_result.reason_codes

    def test_non_reefer_does_not_have_temperature_code(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shp_a, self.shp_b, self.shp_c],
            shipment_routes=self.routes,
        )
        shp_a_result = next(r for r in report.affected if r.shipment_id == "SHP-A")
        assert "TEMPERATURE_EXPOSURE_INCREASED" not in shp_a_result.reason_codes

    def test_all_affected_have_port_node_blocked(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shp_a, self.shp_b, self.shp_c],
            shipment_routes=self.routes,
        )
        for r in report.affected:
            assert "PORT_NODE_BLOCKED" in r.reason_codes


# ---------------------------------------------------------------------------
# 5. deterministic_repeated_execution
# ---------------------------------------------------------------------------

class TestDeterministicRepeatedExecution:
    """assess_impact must produce identical results on repeated calls."""

    def setup_method(self):
        self.graph = _make_graph()
        self.disruption = _make_disruption()
        self.shipments = [
            _make_shipment(
                "SHP-0042",
                departure="2026-09-14T06:00:00",
                arrival="2026-09-16T14:00:00",
                cargo_value_usd=100_000.0,
            ),
            _make_shipment(
                "SHP-0099",
                departure="2026-09-14T06:00:00",
                arrival="2026-09-15T02:00:00",
                cargo_value_usd=55_000.0,
            ),
        ]
        self.routes = {
            "SHP-0042": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
            "SHP-0099": ["HUB-A", "HUB-D"],
        }

    def _run(self) -> ImpactReport:
        return assess_impact(
            self.graph,
            self.disruption,
            self.shipments,
            shipment_routes=self.routes,
        )

    def test_affected_sets_are_identical(self):
        r1 = self._run()
        r2 = self._run()
        assert [s.shipment_id for s in r1.affected] == [s.shipment_id for s in r2.affected]
        assert [s.shipment_id for s in r1.unaffected] == [s.shipment_id for s in r2.unaffected]

    def test_reason_codes_are_identical(self):
        r1 = self._run()
        r2 = self._run()
        for res1, res2 in zip(r1.results, r2.results):
            assert res1.reason_codes == res2.reason_codes

    def test_cargo_value_at_risk_is_identical(self):
        r1 = self._run()
        r2 = self._run()
        assert r1.total_cargo_value_at_risk_usd == r2.total_cargo_value_at_risk_usd

    def test_eta_delay_is_identical(self):
        r1 = self._run()
        r2 = self._run()
        for res1, res2 in zip(r1.results, r2.results):
            assert res1.eta_delay_hours == res2.eta_delay_hours


# ---------------------------------------------------------------------------
# Edge-case: blocked edge (ROUTE_EDGE_BLOCKED)
# ---------------------------------------------------------------------------

class TestBlockedEdge:
    """Disruption blocks an edge (HUB-A, PORT-03) rather than a node."""

    def setup_method(self):
        self.graph = _make_graph()
        self.disruption = Disruption(
            disruption_id="EDGE_BLOCK_01",
            disruption_type=DisruptionType.ROAD_CLOSURE,
            description="Edge closure HUB-A–PORT-03",
            blocked_nodes=[],
            blocked_edges=[("HUB-A", "PORT-03")],
            window_start=_dt("2026-09-14T00:00:00"),
            window_end=_dt("2026-09-17T00:00:00"),
            severity="MEDIUM",
        )
        self.shipment = _make_shipment(
            "SHP-EDGE",
            departure="2026-09-14T06:00:00",
            arrival="2026-09-16T14:00:00",
        )
        self.routes = {"SHP-EDGE": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"]}

    def test_route_edge_blocked_code(self):
        report = assess_impact(
            self.graph,
            self.disruption,
            [self.shipment],
            shipment_routes=self.routes,
        )
        assert report.affected[0].reason_codes == ["ROUTE_EDGE_BLOCKED"]

    def test_bypass_route_not_affected(self):
        bypass_shipment = _make_shipment(
            "SHP-BYPASS",
            departure="2026-09-14T06:00:00",
            arrival="2026-09-15T02:00:00",
        )
        report = assess_impact(
            self.graph,
            self.disruption,
            [bypass_shipment],
            shipment_routes={"SHP-BYPASS": ["HUB-A", "HUB-D"]},
        )
        assert len(report.affected) == 0


# ---------------------------------------------------------------------------
# Edge-case: ETA_SLA_BREACH
# ---------------------------------------------------------------------------

class TestEtaSlaBreach:
    """Shipment with a tight deadline should receive ETA_SLA_BREACH code."""

    def test_sla_breach_code_when_delay_exceeds_deadline(self):
        graph = _make_graph()
        disruption = _make_disruption()
        # Deadline is only 12 hours after planned arrival; default delay is 24 h.
        shipment = _make_shipment(
            "SHP-TIGHT",
            departure="2026-09-14T06:00:00",
            arrival="2026-09-16T00:00:00",
            deadline="2026-09-16T12:00:00",
        )
        routes = {"SHP-TIGHT": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"]}
        report = assess_impact(
            graph,
            disruption,
            [shipment],
            shipment_routes=routes,
            default_delay_hours=24.0,
        )
        assert "ETA_SLA_BREACH" in report.affected[0].reason_codes


# ---------------------------------------------------------------------------
# Unit test for _windows_overlap helper
# ---------------------------------------------------------------------------

class TestWindowsOverlap:
    def test_exact_overlap(self):
        a = (_dt("2026-09-14T00:00:00"), _dt("2026-09-15T00:00:00"))
        b = (_dt("2026-09-14T12:00:00"), _dt("2026-09-16T00:00:00"))
        assert _windows_overlap(*a, *b) is True

    def test_adjacent_windows_overlap(self):
        # Touching at a single point counts as overlapping.
        a = (_dt("2026-09-14T00:00:00"), _dt("2026-09-15T00:00:00"))
        b = (_dt("2026-09-15T00:00:00"), _dt("2026-09-16T00:00:00"))
        assert _windows_overlap(*a, *b) is True

    def test_non_overlapping_windows(self):
        a = (_dt("2026-09-14T00:00:00"), _dt("2026-09-15T00:00:00"))
        b = (_dt("2026-09-16T00:00:00"), _dt("2026-09-17T00:00:00"))
        assert _windows_overlap(*a, *b) is False
