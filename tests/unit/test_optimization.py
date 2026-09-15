"""
tests/unit/test_optimization.py
================================
Unit tests for the ChainShield Route Feasibility Engine
(src/app/optimization/engine.py).

All tests are deterministic: they use in-memory fixtures only, make no
network calls, and import no LLM dependencies.

Hard-constraint coverage
------------------------
Each test class targets exactly one hard constraint and proves that:
  (a) a violation is detected and the route is rejected with the correct
      reason code, AND
  (b) a compliant variant is accepted as feasible.

Additional test classes cover:
  - Disrupted edges are never selected (belt-and-suspenders + subgraph)
  - Disrupted nodes are never selected
  - Deterministic ranking (transit_hours ASC, carrier_id ASC)
  - The offline demo fixture produces >= 3 feasible alternatives
  - FeasibilityReport.best returns rank-1 alternative
  - No-path case returns informative rejection
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from typing import Any

import networkx as nx

from src.app.optimization.engine import (
    RC_CAPACITY_EXCEEDED,
    RC_CARRIER_UNAVAILABLE,
    RC_DEADLINE_BREACH,
    RC_DISRUPTED_EDGE,
    RC_DISRUPTED_NODE,
    RC_MODE_INCOMPATIBLE,
    RC_NO_PATH_EXISTS,
    RC_REEFER_REQUIRED,
    RC_ROUTE_FEASIBLE,
    CarrierSpec,
    FeasibilityReport,
    OptimizationEngineUnavailable,
    RouteAlternativeResult,
    find_feasible_routes,
)
from src.app.core.models import Disruption, DisruptionType, Shipment, ShipmentMode, ShipmentStatus


# ---------------------------------------------------------------------------
# Pytest skip guard — skip entire module if ortools is absent
# ---------------------------------------------------------------------------

try:
    from ortools.sat.python import cp_model as _cp_model  # noqa: F401
    _ORTOOLS_AVAILABLE = True
except ImportError:
    _ORTOOLS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _ORTOOLS_AVAILABLE,
    reason="ortools not installed — run: pip install ortools",
)


# ---------------------------------------------------------------------------
# Shared UTC helper
# ---------------------------------------------------------------------------

def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_graph() -> nx.Graph:
    """Build a simple 6-node graph with labelled edges.

    Topology (all undirected):

        HUB-A ─[road,  8h, 400km]─ HUB-B
        HUB-A ─[sea,  24h,1200km]─ HUB-C
        HUB-B ─[road,  6h, 300km]─ HUB-D
        HUB-C ─[sea,  12h, 600km]─ HUB-D
        HUB-B ─[air,   4h, 500km]─ HUB-E
        HUB-E ─[air,   3h, 300km]─ HUB-D

    Paths from HUB-A to HUB-D:
        1. HUB-A → HUB-B → HUB-D          (road, 14 h, 700 km)
        2. HUB-A → HUB-C → HUB-D          (sea,  36 h, 1800 km)
        3. HUB-A → HUB-B → HUB-E → HUB-D  (road+air, 15 h, 1200 km)
    """
    g = nx.Graph()
    edges = [
        ("HUB-A", "HUB-B", {"mode": "road", "transit_hours": 8.0,  "distance_km": 400.0}),
        ("HUB-A", "HUB-C", {"mode": "sea",  "transit_hours": 24.0, "distance_km": 1200.0}),
        ("HUB-B", "HUB-D", {"mode": "road", "transit_hours": 6.0,  "distance_km": 300.0}),
        ("HUB-C", "HUB-D", {"mode": "sea",  "transit_hours": 12.0, "distance_km": 600.0}),
        ("HUB-B", "HUB-E", {"mode": "air",  "transit_hours": 4.0,  "distance_km": 500.0}),
        ("HUB-E", "HUB-D", {"mode": "air",  "transit_hours": 3.0,  "distance_km": 300.0}),
    ]
    for u, v, d in edges:
        g.add_edge(u, v, **d)
    return g


def _make_shipment(
    *,
    shipment_id: str = "SHP-TEST",
    cargo_type: str = "general",
    weight_kg: float = 5000.0,
    origin: str = "HUB-A",
    destination: str = "HUB-D",
    departure: str = "2025-06-01T08:00:00",
    arrival: str = "2025-06-02T08:00:00",
    deadline: str = "2025-06-04T08:00:00",
    carrier_id: str = "CARRIER-X",
    mode: ShipmentMode = ShipmentMode.ROAD,
) -> Shipment:
    return Shipment(
        shipment_id=shipment_id,
        cargo_type=cargo_type,
        product_class="general_cargo",
        origin_hub_id=origin,
        destination_hub_id=destination,
        current_node_id=origin,
        mode=mode,
        carrier_id=carrier_id,
        planned_departure=_utc(departure),
        planned_arrival=_utc(arrival),
        delivery_deadline=_utc(deadline),
        cargo_value_usd=100_000.0,
        weight_kg=weight_kg,
        status=ShipmentStatus.IN_TRANSIT,
    )


def _make_carrier(
    *,
    carrier_id: str = "CAR-1",
    mode: ShipmentMode = ShipmentMode.ROAD,
    capacity_kg: float = 10_000.0,
    reefer_capable: bool = False,
    available_at: str = "2025-06-01T00:00:00",
    cost_per_km: float = 1.0,
) -> CarrierSpec:
    return CarrierSpec(
        carrier_id=carrier_id,
        mode=mode,
        capacity_kg=capacity_kg,
        reefer_capable=reefer_capable,
        available_at=_utc(available_at),
        cost_per_km=cost_per_km,
    )


def _make_disruption(
    *,
    disruption_id: str = "DIS-01",
    blocked_nodes: list[str] | None = None,
    blocked_edges: list[tuple[str, str]] | None = None,
    window_start: str = "2025-06-01T00:00:00",
    window_end: str = "2025-06-03T00:00:00",
) -> Disruption:
    return Disruption(
        disruption_id=disruption_id,
        disruption_type=DisruptionType.PORT_CLOSURE,
        blocked_nodes=blocked_nodes or [],
        blocked_edges=blocked_edges or [],
        window_start=_utc(window_start),
        window_end=_utc(window_end),
    )


# ---------------------------------------------------------------------------
# Helper: run find_feasible_routes and extract all feasible reason-code sets
# ---------------------------------------------------------------------------

def _all_feasible_codes(report: FeasibilityReport) -> list[list[str]]:
    return [r.reason_codes for r in report.feasible]


def _all_rejected_codes(report: FeasibilityReport) -> list[list[str]]:
    return [r.reason_codes for r in report.rejected]


def _any_rejected_contains(report: FeasibilityReport, code: str) -> bool:
    return any(code in r.reason_codes for r in report.rejected)


# ===========================================================================
# 1. Capacity constraint
# ===========================================================================

class TestCapacityConstraint:
    """RC_CAPACITY_EXCEEDED must be raised when weight > capacity."""

    def test_overweight_shipment_is_rejected(self):
        g = _make_graph()
        shp = _make_shipment(weight_kg=20_000.0)
        carrier = _make_carrier(capacity_kg=10_000.0)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) == 0
        assert _any_rejected_contains(report, RC_CAPACITY_EXCEEDED)

    def test_under_capacity_shipment_is_accepted(self):
        g = _make_graph()
        shp = _make_shipment(weight_kg=5_000.0)
        carrier = _make_carrier(capacity_kg=10_000.0)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1
        assert all(RC_CAPACITY_EXCEEDED not in r.reason_codes for r in report.feasible)

    def test_capacity_exactly_equal_is_accepted(self):
        g = _make_graph()
        shp = _make_shipment(weight_kg=10_000.0)
        carrier = _make_carrier(capacity_kg=10_000.0)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1

    def test_rejected_result_has_rejection_reason_text(self):
        g = _make_graph()
        shp = _make_shipment(weight_kg=99_999.0)
        carrier = _make_carrier(capacity_kg=1_000.0)

        report = find_feasible_routes(g, shp, [carrier])

        rejected = [r for r in report.rejected if RC_CAPACITY_EXCEEDED in r.reason_codes]
        assert len(rejected) >= 1
        assert any("capacity" in rej.rejection_reasons[0].lower() for rej in rejected)


# ===========================================================================
# 2. Reefer capability constraint
# ===========================================================================

class TestReeferCapabilityConstraint:
    """Reefer shipments must never be assigned to non-reefer carriers."""

    def test_reefer_shipment_rejected_by_non_reefer_carrier(self):
        g = _make_graph()
        shp = _make_shipment(cargo_type="reefer")
        carrier = _make_carrier(reefer_capable=False)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) == 0
        assert _any_rejected_contains(report, RC_REEFER_REQUIRED)

    def test_reefer_shipment_accepted_by_reefer_carrier(self):
        g = _make_graph()
        shp = _make_shipment(cargo_type="reefer")
        carrier = _make_carrier(reefer_capable=True)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1
        assert all(RC_REEFER_REQUIRED not in r.reason_codes for r in report.feasible)

    def test_pharmaceutical_cargo_also_requires_reefer(self):
        g = _make_graph()
        shp = _make_shipment(cargo_type="pharmaceutical")
        carrier = _make_carrier(reefer_capable=False)

        report = find_feasible_routes(g, shp, [carrier])

        assert _any_rejected_contains(report, RC_REEFER_REQUIRED)

    def test_reefer_feasible_result_has_reefer_available_code(self):
        g = _make_graph()
        shp = _make_shipment(cargo_type="reefer")
        carrier = _make_carrier(reefer_capable=True)

        report = find_feasible_routes(g, shp, [carrier])

        from src.app.optimization.engine import RC_REEFER_CAPACITY_AVAILABLE
        assert any(RC_REEFER_CAPACITY_AVAILABLE in r.reason_codes for r in report.feasible)

    def test_non_reefer_cargo_accepted_by_non_reefer_carrier(self):
        g = _make_graph()
        shp = _make_shipment(cargo_type="general")
        carrier = _make_carrier(reefer_capable=False)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1


# ===========================================================================
# 3. Mode compatibility constraint
# ===========================================================================

class TestModeCompatibilityConstraint:
    """A carrier whose mode does not match the route edges must be rejected."""

    def test_sea_carrier_rejected_on_road_only_route(self):
        # Force a road-only route: HUB-A → HUB-B → HUB-D
        g = nx.Graph()
        g.add_edge("HUB-A", "HUB-B", mode="road", transit_hours=8.0, distance_km=400.0)
        g.add_edge("HUB-B", "HUB-D", mode="road", transit_hours=6.0, distance_km=300.0)

        shp = _make_shipment()
        carrier = _make_carrier(mode=ShipmentMode.SEA)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) == 0
        assert _any_rejected_contains(report, RC_MODE_INCOMPATIBLE)

    def test_road_carrier_accepted_on_road_route(self):
        g = nx.Graph()
        g.add_edge("HUB-A", "HUB-B", mode="road", transit_hours=8.0, distance_km=400.0)
        g.add_edge("HUB-B", "HUB-D", mode="road", transit_hours=6.0, distance_km=300.0)

        shp = _make_shipment()
        carrier = _make_carrier(mode=ShipmentMode.ROAD)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1

    def test_air_carrier_accepted_on_air_route(self):
        g = nx.Graph()
        g.add_edge("HUB-A", "HUB-B", mode="air", transit_hours=2.0, distance_km=600.0)
        g.add_edge("HUB-B", "HUB-D", mode="air", transit_hours=2.0, distance_km=600.0)

        shp = _make_shipment()
        carrier = _make_carrier(mode=ShipmentMode.AIR)

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1


# ===========================================================================
# 4. Carrier availability constraint
# ===========================================================================

class TestCarrierAvailabilityConstraint:
    """Carriers not available until after departure must be rejected."""

    def test_unavailable_carrier_is_rejected(self):
        g = _make_graph()
        # Carrier available one day AFTER planned departure
        shp = _make_shipment(departure="2025-06-01T08:00:00")
        carrier = _make_carrier(available_at="2025-06-02T08:00:00")

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) == 0
        assert _any_rejected_contains(report, RC_CARRIER_UNAVAILABLE)

    def test_carrier_available_before_departure_is_accepted(self):
        g = _make_graph()
        shp = _make_shipment(departure="2025-06-01T08:00:00")
        carrier = _make_carrier(available_at="2025-06-01T00:00:00")

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1

    def test_carrier_available_exactly_at_departure_is_accepted(self):
        g = _make_graph()
        shp = _make_shipment(departure="2025-06-01T08:00:00")
        carrier = _make_carrier(available_at="2025-06-01T08:00:00")

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1


# ===========================================================================
# 5. Delivery deadline constraint
# ===========================================================================

class TestDeliveryDeadlineConstraint:
    """Routes whose projected arrival exceeds the deadline must be rejected."""

    def test_slow_route_rejected_by_tight_deadline(self):
        # All routes from HUB-A→HUB-D take >= 14 h.
        # Set deadline to only 10 h after departure.
        g = _make_graph()
        departure = "2025-06-01T08:00:00"
        arrival   = "2025-06-01T18:00:00"   # 10 h — needed for Shipment validator
        deadline  = "2025-06-01T22:00:00"   # 14 h — faster than any 14 h+ route

        # The shortest path (HUB-A→HUB-B→HUB-D) takes 14 h, arrival = 22:00.
        # That equals the deadline, so it must be rejected (>).
        # Use a 13 h deadline to force rejection:
        tight_deadline = "2025-06-01T21:00:00"

        shp = Shipment(
            shipment_id="SHP-DEADLINE",
            cargo_type="general",
            product_class="general_cargo",
            origin_hub_id="HUB-A",
            destination_hub_id="HUB-D",
            current_node_id="HUB-A",
            mode=ShipmentMode.ROAD,
            carrier_id="CAR-X",
            planned_departure=_utc(departure),
            planned_arrival=_utc(arrival),
            delivery_deadline=_utc(tight_deadline),
            cargo_value_usd=50_000.0,
            weight_kg=5_000.0,
            status=ShipmentStatus.IN_TRANSIT,
        )
        carrier = _make_carrier()

        report = find_feasible_routes(g, shp, [carrier])

        # All routes take >= 14h, deadline is 13h away
        assert len(report.feasible) == 0
        assert _any_rejected_contains(report, RC_DEADLINE_BREACH)

    def test_fast_route_accepted_within_deadline(self):
        g = nx.Graph()
        g.add_edge("HUB-A", "HUB-D", mode="road", transit_hours=4.0, distance_km=200.0)

        shp = _make_shipment(
            departure="2025-06-01T08:00:00",
            arrival="2025-06-01T13:00:00",
            deadline="2025-06-02T00:00:00",
        )
        carrier = _make_carrier()

        report = find_feasible_routes(g, shp, [carrier])

        assert len(report.feasible) >= 1
        assert not _any_rejected_contains(report, RC_DEADLINE_BREACH)


# ===========================================================================
# 6. Disrupted edge hard exclusion
# ===========================================================================

class TestDisruptedEdgeExclusion:
    """A disrupted edge must NEVER appear in any feasible route."""

    def test_disrupted_edge_not_in_feasible_routes(self):
        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()
        # Block the fast path HUB-A → HUB-B
        dis = _make_disruption(blocked_edges=[("HUB-A", "HUB-B")])

        report = find_feasible_routes(g, shp, [carrier], disruptions=[dis])

        # Verify the disrupted edge never appears in any feasible route
        for alt in report.feasible:
            nodes = alt.route_nodes
            for i in range(len(nodes) - 1):
                pair = frozenset((nodes[i], nodes[i + 1]))
                assert pair != frozenset(("HUB-A", "HUB-B")), (
                    f"Disrupted edge HUB-A↔HUB-B appeared in feasible route: {nodes}"
                )

    def test_disrupted_edge_rejection_has_reason_code(self):
        """Belt-and-suspenders: if a path somehow contains a blocked edge,
        the constraint checker must emit RC_DISRUPTED_EDGE."""
        from src.app.optimization.engine import _check_hard_constraints, _route_modes
        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()
        blocked_pair = frozenset(("HUB-A", "HUB-B"))

        feasible, codes, explanations = _check_hard_constraints(
            shipment=shp,
            carrier=carrier,
            route_nodes=["HUB-A", "HUB-B", "HUB-D"],
            transit_hours=14.0,
            route_modes=_route_modes(g, ["HUB-A", "HUB-B", "HUB-D"]),
            graph=g,
            original_blocked_edge_pairs={blocked_pair},
            original_blocked_nodes=set(),
        )

        assert not feasible
        assert RC_DISRUPTED_EDGE in codes

    def test_alternative_routes_exist_when_edge_blocked(self):
        """Blocking one edge must still leave at least one feasible alternative.

        HUB-A→HUB-B is blocked.  The remaining path HUB-A→HUB-C→HUB-D is
        sea-mode, so we supply a sea carrier to confirm it is accepted.
        """
        g = _make_graph()
        shp = _make_shipment()
        # Sea carrier to match the only surviving path (HUB-A→HUB-C→HUB-D)
        sea_carrier = _make_carrier(carrier_id="CAR-SEA", mode=ShipmentMode.SEA)
        dis = _make_disruption(blocked_edges=[("HUB-A", "HUB-B")])

        report = find_feasible_routes(g, shp, [sea_carrier], disruptions=[dis])

        # HUB-A→HUB-C→HUB-D is unaffected — sea carrier must match
        assert len(report.feasible) >= 1
        for alt in report.feasible:
            nodes = alt.route_nodes
            for i in range(len(nodes) - 1):
                pair = frozenset((nodes[i], nodes[i + 1]))
                assert pair != frozenset(("HUB-A", "HUB-B")), (
                    f"Disrupted edge still appeared in alternative route: {nodes}"
                )


# ===========================================================================
# 7. Disrupted node hard exclusion
# ===========================================================================

class TestDisruptedNodeExclusion:
    """A disrupted node must NEVER appear in any feasible route."""

    def test_disrupted_node_not_in_feasible_routes(self):
        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()
        # Block HUB-B — eliminates paths through it
        dis = _make_disruption(blocked_nodes=["HUB-B"])

        report = find_feasible_routes(g, shp, [carrier], disruptions=[dis])

        for alt in report.feasible:
            assert "HUB-B" not in alt.route_nodes, (
                f"Disrupted node HUB-B appeared in feasible route: {alt.route_nodes}"
            )

    def test_belt_and_suspenders_check_for_blocked_node(self):
        from src.app.optimization.engine import _check_hard_constraints, _route_modes
        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()

        feasible, codes, _ = _check_hard_constraints(
            shipment=shp,
            carrier=carrier,
            route_nodes=["HUB-A", "HUB-B", "HUB-D"],
            transit_hours=14.0,
            route_modes=_route_modes(g, ["HUB-A", "HUB-B", "HUB-D"]),
            graph=g,
            original_blocked_edge_pairs=set(),
            original_blocked_nodes={"HUB-B"},
        )

        assert not feasible
        assert RC_DISRUPTED_NODE in codes


# ===========================================================================
# 8. Disruption time-window: past disruption does not block routes
# ===========================================================================

class TestDisruptionTimeWindow:
    """Disruptions outside the shipment window must not affect feasibility."""

    def test_past_disruption_does_not_block_route(self):
        g = _make_graph()
        shp = _make_shipment(
            departure="2025-07-01T08:00:00",
            arrival="2025-07-02T08:00:00",
            deadline="2025-07-04T08:00:00",
        )
        carrier = _make_carrier()
        # Disruption ended before the shipment departs
        dis = _make_disruption(
            blocked_edges=[("HUB-A", "HUB-B")],
            window_start="2025-06-01T00:00:00",
            window_end="2025-06-30T00:00:00",
        )

        report = find_feasible_routes(g, shp, [carrier], disruptions=[dis])

        # All routes including HUB-A→HUB-B should be available
        has_ab_route = any(
            "HUB-B" in alt.route_nodes for alt in report.feasible
        )
        assert has_ab_route, "Past disruption should not block the HUB-A→HUB-B route"


# ===========================================================================
# 9. Deterministic ranking
# ===========================================================================

class TestDeterministicRanking:
    """Results must be sorted transit_hours ASC, then carrier_id ASC."""

    def test_ranking_is_by_transit_hours_ascending(self):
        g = _make_graph()
        shp = _make_shipment()
        carriers = [
            _make_carrier(carrier_id="CAR-ROAD", mode=ShipmentMode.ROAD),
            _make_carrier(carrier_id="CAR-SEA",  mode=ShipmentMode.SEA),
        ]

        report = find_feasible_routes(g, shp, carriers, max_paths=20)

        hours = [r.transit_hours for r in report.feasible]
        assert hours == sorted(hours), f"Feasible results not sorted by transit_hours: {hours}"

    def test_same_inputs_produce_identical_output(self):
        g = _make_graph()
        shp = _make_shipment()
        carriers = [
            _make_carrier(carrier_id="CAR-ROAD", mode=ShipmentMode.ROAD),
            _make_carrier(carrier_id="CAR-SEA",  mode=ShipmentMode.SEA),
        ]

        report_a = find_feasible_routes(g, shp, carriers, max_paths=20)
        report_b = find_feasible_routes(g, shp, carriers, max_paths=20)

        routes_a = [(r.route_nodes, r.carrier_id) for r in report_a.feasible]
        routes_b = [(r.route_nodes, r.carrier_id) for r in report_b.feasible]
        assert routes_a == routes_b

    def test_rank_field_is_sequential_from_one(self):
        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()

        report = find_feasible_routes(g, shp, [carrier])

        for idx, r in enumerate(report.feasible, start=1):
            assert r.rank == idx, f"rank {r.rank} != expected {idx}"

    def test_tiebreaker_is_carrier_id_lexicographic(self):
        """Two carriers with same transit cost → sorted by carrier_id."""
        # Single-hop graph so both carriers produce the same transit_hours.
        g = nx.Graph()
        g.add_edge("HUB-A", "HUB-D", mode="road", transit_hours=5.0, distance_km=250.0)

        shp = _make_shipment()
        carriers = [
            _make_carrier(carrier_id="ZEBRA", mode=ShipmentMode.ROAD),
            _make_carrier(carrier_id="ALPHA", mode=ShipmentMode.ROAD),
        ]

        report = find_feasible_routes(g, shp, carriers)

        ids = [r.carrier_id for r in report.feasible]
        assert ids == sorted(ids), f"Carrier IDs not lexicographically sorted: {ids}"


# ===========================================================================
# 10. No-path case
# ===========================================================================

class TestNoPathCase:
    """If there is no path in the undisrupted graph, return an informative rejection."""

    def test_no_path_returns_empty_feasible(self):
        # Disconnected graph
        g = nx.Graph()
        g.add_edge("HUB-A", "HUB-B", mode="road", transit_hours=5.0, distance_km=200.0)
        # HUB-D is not connected to anything

        shp = _make_shipment()
        carrier = _make_carrier()

        report = find_feasible_routes(g, shp, [carrier])

        assert report.feasible == []
        assert len(report.rejected) >= 1
        assert _any_rejected_contains(report, RC_NO_PATH_EXISTS)

    def test_all_paths_blocked_by_disruption_returns_empty_feasible(self):
        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()
        # Block all routes by blocking HUB-A (the origin itself)
        dis = _make_disruption(blocked_nodes=["HUB-A"])

        report = find_feasible_routes(g, shp, [carrier], disruptions=[dis])

        assert report.feasible == []


# ===========================================================================
# 11. FeasibilityReport.best
# ===========================================================================

class TestFeasibilityReportBest:
    def test_best_is_rank_one(self):
        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()

        report = find_feasible_routes(g, shp, [carrier])

        if report.feasible:
            assert report.best is not None
            assert report.best.rank == 1
        else:
            assert report.best is None

    def test_best_is_none_when_no_feasible(self):
        g = _make_graph()
        # Make shipment way too heavy
        shp = _make_shipment(weight_kg=999_999.0)
        carrier = _make_carrier(capacity_kg=1.0)

        report = find_feasible_routes(g, shp, [carrier])

        assert report.best is None


# ===========================================================================
# 12. Offline demo fixture — at least 3 feasible alternatives
# ===========================================================================

class TestOfflineDemoFixture:
    """The demo fixture must produce >= 3 feasible alternatives.

    Matches the acceptance criterion in the task specification.
    Uses 3 carriers (road, sea, road-reefer) × 3 paths from the fixture graph.
    """

    def _make_demo_report(self) -> FeasibilityReport:
        g = _make_graph()
        shp = _make_shipment(
            shipment_id="SHP-DEMO",
            cargo_type="general",
            departure="2025-06-01T06:00:00",
            arrival="2025-06-02T06:00:00",
            deadline="2025-06-05T00:00:00",
        )
        carriers = [
            _make_carrier(carrier_id="CAR-ROAD-01", mode=ShipmentMode.ROAD, capacity_kg=15_000.0),
            _make_carrier(carrier_id="CAR-SEA-01",  mode=ShipmentMode.SEA,  capacity_kg=50_000.0),
            _make_carrier(carrier_id="CAR-AIR-01",  mode=ShipmentMode.AIR,  capacity_kg=8_000.0),
        ]
        # No disruptions — all paths open
        return find_feasible_routes(g, shp, carriers, max_paths=20)

    def test_at_least_three_feasible_alternatives(self):
        report = self._make_demo_report()
        assert len(report.feasible) >= 3, (
            f"Expected >= 3 feasible alternatives, got {len(report.feasible)}. "
            f"Details: {[(r.route_nodes, r.carrier_id) for r in report.feasible]}"
        )

    def test_feasible_results_have_route_feasible_code(self):
        report = self._make_demo_report()
        for r in report.feasible:
            assert RC_ROUTE_FEASIBLE in r.reason_codes, (
                f"Feasible result missing RC_ROUTE_FEASIBLE: {r}"
            )

    def test_feasible_routes_have_positive_transit_hours(self):
        report = self._make_demo_report()
        for r in report.feasible:
            assert r.transit_hours > 0, f"transit_hours must be positive: {r}"

    def test_evidence_dict_populated(self):
        report = self._make_demo_report()
        for r in report.feasible:
            assert "transit_hours" in r.evidence
            assert "distance_km" in r.evidence
            assert "projected_arrival" in r.evidence


# ===========================================================================
# 13. Multiple hard constraint violations reported correctly
# ===========================================================================

class TestMultipleConstraintViolations:
    """When several constraints fail simultaneously, all codes are present."""

    def test_overweight_and_reefer_both_reported(self):
        g = _make_graph()
        shp = _make_shipment(cargo_type="reefer", weight_kg=99_999.0)
        carrier = _make_carrier(reefer_capable=False, capacity_kg=1_000.0)

        report = find_feasible_routes(g, shp, [carrier])

        all_codes: set[str] = set()
        for r in report.rejected:
            all_codes.update(r.reason_codes)

        assert RC_CAPACITY_EXCEEDED in all_codes
        assert RC_REEFER_REQUIRED in all_codes


# ===========================================================================
# 14. OptimizationEngineUnavailable when ortools absent (import-level test)
# ===========================================================================

class TestEngineUnavailableError:
    """Monkeypatching _ORTOOLS_AVAILABLE=False must trigger the exception."""

    def test_raises_when_ortools_unavailable(self, monkeypatch):
        import src.app.optimization.engine as eng_module
        monkeypatch.setattr(eng_module, "_ORTOOLS_AVAILABLE", False)

        g = _make_graph()
        shp = _make_shipment()
        carrier = _make_carrier()

        with pytest.raises(OptimizationEngineUnavailable):
            find_feasible_routes(g, shp, [carrier])
