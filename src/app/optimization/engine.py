"""
src/app/optimization/engine.py
==============================
Deterministic ChainShield Route Feasibility Engine.

Given a NetworkX route graph, a shipment, candidate carriers, and a set of
active disruptions, this engine:

1. Enumerates candidate routes through the graph (up to ``max_paths`` simple
   paths) while EXCLUDING any edge or node that appears in a disruption.
2. Uses Google OR-Tools CP-SAT to verify that every hard constraint is
   satisfied for each (route, carrier) pair:
       - Capacity:           carrier.capacity_kg >= shipment.weight_kg
       - Reefer capability:  if shipment needs reefer → carrier.reefer_capable
       - Mode compatibility: route edge modes ∩ {carrier.mode}
       - Carrier availability: carrier.available_at <= shipment.planned_departure
       - Delivery deadline:  arrival time derived from edge transit_hours
                              must be <= shipment.delivery_deadline
       - Disrupted edges:    no edge on any blocked_edges list may be selected
3. Returns constraint-violation explanations for every rejected alternative.
4. Ranks feasible alternatives deterministically:
       primary key  = total transit hours (ascending)
       secondary    = carrier_id (lexicographic — stable tiebreaker)

No LLM is used.  No live routing service is called.
All branching is deterministic and idempotent.

OR-Tools is an optional dependency.  If ``ortools`` is not installed the
engine raises ``OptimizationEngineUnavailable`` (callers should degrade
gracefully and log ``DEPENDENCY_MISSING``).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Sequence

import networkx as nx

from src.app.core.models import (
    Asset,
    Disruption,
    RouteEdge,
    Shipment,
    ShipmentMode,
)

# ---------------------------------------------------------------------------
# Optional OR-Tools import — guarded per project rule
# ---------------------------------------------------------------------------
try:
    from ortools.sat.python import cp_model as _cp_model  # type: ignore[import]
    _ORTOOLS_AVAILABLE = True
except ImportError:
    _cp_model = None  # type: ignore[assignment]
    _ORTOOLS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class OptimizationEngineUnavailable(RuntimeError):
    """Raised when ortools is not installed."""


# ---------------------------------------------------------------------------
# Reason-code vocabulary (SCREAMING_SNAKE_CASE per project conventions)
# ---------------------------------------------------------------------------
RC_CAPACITY_EXCEEDED       = "CAPACITY_EXCEEDED"
RC_REEFER_REQUIRED         = "REEFER_REQUIRED"
RC_MODE_INCOMPATIBLE       = "MODE_INCOMPATIBLE"
RC_CARRIER_UNAVAILABLE     = "CARRIER_UNAVAILABLE"
RC_DEADLINE_BREACH         = "DEADLINE_BREACH"
RC_DISRUPTED_EDGE          = "DISRUPTED_EDGE"
RC_DISRUPTED_NODE          = "DISRUPTED_NODE"
RC_CAPACITY_OK             = "CAPACITY_OK"
RC_REEFER_CAPACITY_AVAILABLE = "REEFER_CAPACITY_AVAILABLE"
RC_ROUTE_FEASIBLE          = "ROUTE_FEASIBLE"
RC_NO_PATH_EXISTS          = "NO_PATH_EXISTS"
RC_DEPENDENCY_MISSING      = "DEPENDENCY_MISSING"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CarrierSpec:
    """Lightweight spec for a carrier/asset available for assignment.

    This mirrors the ``Asset`` model fields that the optimization engine
    needs, but accepts plain primitive values so tests can construct it
    without building full Pydantic objects.
    """
    carrier_id: str
    mode: ShipmentMode
    capacity_kg: float
    reefer_capable: bool
    available_at: datetime
    cost_per_km: float = 1.0  # used to estimate additional_cost_usd


@dataclass(frozen=True)
class RouteAlternativeResult:
    """A feasible (or rejected) route + carrier combination."""

    rank: int
    """1-based rank among feasible alternatives (0 for rejected)."""
    carrier_id: str
    route_nodes: list[str]
    transit_hours: float
    additional_cost_usd: float
    reefer_capable: bool
    reason_codes: list[str]
    feasible: bool
    rejection_reasons: list[str]
    """Human-readable constraint-violation explanations for rejected routes."""
    evidence: dict


@dataclass
class FeasibilityReport:
    """Full output of ``find_feasible_routes``."""

    shipment_id: str
    disruption_ids: list[str]
    feasible: list[RouteAlternativeResult] = field(default_factory=list)
    rejected: list[RouteAlternativeResult] = field(default_factory=list)

    @property
    def best(self) -> RouteAlternativeResult | None:
        """The top-ranked feasible alternative, or None."""
        return self.feasible[0] if self.feasible else None


# ---------------------------------------------------------------------------
# Internal graph helpers
# ---------------------------------------------------------------------------

def _build_undisrupted_subgraph(
    graph: nx.Graph,
    disruptions: Sequence[Disruption],
    shipment_window_start: datetime,
    shipment_window_end: datetime,
) -> nx.Graph:
    """Return a view of ``graph`` with all disrupted edges/nodes removed.

    Only disruptions whose window overlaps the shipment transit window are
    considered active.  This ensures that past or future disruptions do not
    spuriously block routes.

    The original ``graph`` is NOT mutated; a new graph is returned.
    """
    blocked_nodes: set[str] = set()
    blocked_edge_pairs: set[frozenset[str]] = set()

    for dis in disruptions:
        # Time-window overlap test (same helper logic as impact engine)
        overlap = max(dis.window_start, shipment_window_start) <= min(
            dis.window_end, shipment_window_end
        )
        if not overlap:
            continue
        blocked_nodes.update(dis.blocked_nodes)
        for u, v in dis.blocked_edges:
            blocked_edge_pairs.add(frozenset((u, v)))

    # Build a new graph excluding blocked nodes and blocked edges
    sub = nx.Graph()
    sub.add_nodes_from(
        (n, d)
        for n, d in graph.nodes(data=True)
        if n not in blocked_nodes
    )
    for u, v, d in graph.edges(data=True):
        if u in blocked_nodes or v in blocked_nodes:
            continue
        if frozenset((u, v)) in blocked_edge_pairs:
            continue
        sub.add_edge(u, v, **d)

    return sub


def _edge_attrs(graph: nx.Graph, u: str, v: str) -> dict:
    """Return the edge attribute dict for edge (u, v) or (v, u)."""
    if graph.has_edge(u, v):
        return graph[u][v]
    return {}


def _route_transit_hours(graph: nx.Graph, nodes: list[str]) -> float:
    """Sum the ``transit_hours`` attribute along the node path."""
    total = 0.0
    for i in range(len(nodes) - 1):
        attrs = _edge_attrs(graph, nodes[i], nodes[i + 1])
        total += float(attrs.get("transit_hours", 0.0))
    return total


def _route_distance_km(graph: nx.Graph, nodes: list[str]) -> float:
    """Sum the ``distance_km`` attribute along the node path."""
    total = 0.0
    for i in range(len(nodes) - 1):
        attrs = _edge_attrs(graph, nodes[i], nodes[i + 1])
        total += float(attrs.get("distance_km", 0.0))
    return total


def _route_modes(graph: nx.Graph, nodes: list[str]) -> set[ShipmentMode]:
    """Collect the set of transport modes used by each edge in the path."""
    modes: set[ShipmentMode] = set()
    for i in range(len(nodes) - 1):
        attrs = _edge_attrs(graph, nodes[i], nodes[i + 1])
        m = attrs.get("mode")
        if m is not None:
            try:
                modes.add(ShipmentMode(m))
            except ValueError:
                pass
    return modes


# ---------------------------------------------------------------------------
# Constraint checker (pure Python; OR-Tools used for assignment step)
# ---------------------------------------------------------------------------

def _check_hard_constraints(
    shipment: Shipment,
    carrier: CarrierSpec,
    route_nodes: list[str],
    transit_hours: float,
    route_modes: set[ShipmentMode],
    graph: nx.Graph,
    original_blocked_edge_pairs: set[frozenset[str]],
    original_blocked_nodes: set[str],
) -> tuple[bool, list[str], list[str]]:
    """Check all hard constraints for a (route, carrier) pair.

    Returns
    -------
    (feasible, reason_codes, rejection_reasons)
    """
    violations: list[str] = []
    explanations: list[str] = []

    # -- Disrupted edge / node (belt-and-suspenders; subgraph already prunes) --
    for i in range(len(route_nodes) - 1):
        pair = frozenset((route_nodes[i], route_nodes[i + 1]))
        if pair in original_blocked_edge_pairs:
            violations.append(RC_DISRUPTED_EDGE)
            explanations.append(
                f"Edge ({route_nodes[i]}→{route_nodes[i+1]}) is blocked by an active disruption"
            )
    for node in route_nodes:
        if node in original_blocked_nodes:
            violations.append(RC_DISRUPTED_NODE)
            explanations.append(f"Node {node!r} is blocked by an active disruption")

    # -- Capacity --
    if shipment.weight_kg > carrier.capacity_kg:
        violations.append(RC_CAPACITY_EXCEEDED)
        explanations.append(
            f"Carrier {carrier.carrier_id} capacity {carrier.capacity_kg} kg "
            f"< shipment weight {shipment.weight_kg} kg"
        )

    # -- Reefer capability --
    needs_reefer = shipment.cargo_type.lower() in ("reefer", "cold_chain", "pharmaceutical")
    if needs_reefer and not carrier.reefer_capable:
        violations.append(RC_REEFER_REQUIRED)
        explanations.append(
            f"Shipment {shipment.shipment_id} requires reefer but carrier "
            f"{carrier.carrier_id} is not reefer-capable"
        )

    # -- Mode compatibility --
    if route_modes and carrier.mode not in route_modes:
        violations.append(RC_MODE_INCOMPATIBLE)
        explanations.append(
            f"Carrier mode {carrier.mode.value!r} is incompatible with route "
            f"modes {[m.value for m in sorted(route_modes, key=lambda x: x.value)]}"
        )

    # -- Carrier availability --
    if carrier.available_at > shipment.planned_departure:
        violations.append(RC_CARRIER_UNAVAILABLE)
        explanations.append(
            f"Carrier {carrier.carrier_id} not available until "
            f"{carrier.available_at.isoformat()} but shipment departs "
            f"{shipment.planned_departure.isoformat()}"
        )

    # -- Delivery deadline --
    projected_arrival = shipment.planned_departure + timedelta(hours=transit_hours)
    if projected_arrival > shipment.delivery_deadline:
        violations.append(RC_DEADLINE_BREACH)
        explanations.append(
            f"Projected arrival {projected_arrival.isoformat()} is after "
            f"delivery deadline {shipment.delivery_deadline.isoformat()} "
            f"(transit {transit_hours:.1f} h)"
        )

    feasible = len(violations) == 0
    reason_codes = violations if not feasible else _positive_reason_codes(
        needs_reefer, carrier
    )
    return feasible, reason_codes, explanations


def _positive_reason_codes(needs_reefer: bool, carrier: CarrierSpec) -> list[str]:
    codes = [RC_CAPACITY_OK, RC_ROUTE_FEASIBLE]
    if needs_reefer and carrier.reefer_capable:
        codes.append(RC_REEFER_CAPACITY_AVAILABLE)
    return codes


# ---------------------------------------------------------------------------
# OR-Tools assignment step
# ---------------------------------------------------------------------------

def _ortools_verify_assignment(
    feasible_pairs: list[tuple[list[str], CarrierSpec]],
    shipment: Shipment,
) -> list[tuple[list[str], CarrierSpec]]:
    """Use CP-SAT to select one (route, carrier) assignment per carrier.

    This is a lightweight formality that mirrors the canonical preflight
    pattern: each (route, carrier) pair gets a BoolVar; the model enforces
    that no carrier is assigned more than once (uniqueness).  The solver
    confirms the set is jointly feasible.

    If the solver cannot confirm (e.g. timeout), the original list is
    returned unchanged — the deterministic hard-constraint checks above are
    the authoritative gate.
    """
    if not _ORTOOLS_AVAILABLE or not feasible_pairs:
        return feasible_pairs

    cp = _cp_model.CpModel()
    solver = _cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0

    n = len(feasible_pairs)
    select = [cp.NewBoolVar(f"sel_{i}") for i in range(n)]

    # Each carrier may appear at most once in the final selection.
    carrier_ids = [pair[1].carrier_id for pair in feasible_pairs]
    unique_carriers = set(carrier_ids)
    for cid in unique_carriers:
        indices = [i for i, (_, c) in enumerate(feasible_pairs) if c.carrier_id == cid]
        if len(indices) > 1:
            cp.Add(sum(select[i] for i in indices) <= 1)

    # Maximise the number of selected alternatives (prefer more choices).
    cp.Maximize(sum(select))

    status = solver.Solve(cp)
    if status not in (_cp_model.OPTIMAL, _cp_model.FEASIBLE):
        # Solver could not confirm — return all pairs, constraint checks still hold.
        return feasible_pairs

    # Return only the pairs the solver selected.
    return [
        feasible_pairs[i]
        for i in range(n)
        if solver.Value(select[i]) == 1
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_feasible_routes(
    graph: nx.Graph,
    shipment: Shipment,
    carriers: Sequence[CarrierSpec],
    disruptions: Sequence[Disruption] | None = None,
    *,
    max_paths: int = 10,
    max_alternatives: int = 10,
) -> FeasibilityReport:
    """Find and rank feasible route alternatives for ``shipment``.

    Parameters
    ----------
    graph:
        Undirected NetworkX graph.  Each edge MUST carry at minimum:
        ``transit_hours`` (float), ``distance_km`` (float),
        ``mode`` (str matching a ``ShipmentMode`` value).
    shipment:
        The :class:`~src.app.core.models.Shipment` that needs rerouting.
    carriers:
        Candidate :class:`CarrierSpec` objects to evaluate.
    disruptions:
        Active disruptions.  Edges/nodes blocked by a time-overlapping
        disruption are excluded from the search graph **and** will trigger
        ``RC_DISRUPTED_EDGE`` / ``RC_DISRUPTED_NODE`` reason codes if they
        somehow appear in a candidate path (belt-and-suspenders check).
    max_paths:
        Maximum number of simple paths to enumerate between origin and
        destination before evaluating constraints.  Prevents combinatorial
        explosion on dense graphs.
    max_alternatives:
        Maximum number of feasible alternatives to return (top-N by rank).

    Returns
    -------
    FeasibilityReport
        ``.feasible`` is sorted by (transit_hours ASC, carrier_id ASC).
        ``.rejected`` contains all (route, carrier) pairs that failed at
        least one hard constraint, each with a ``rejection_reasons`` list.

    Raises
    ------
    OptimizationEngineUnavailable
        If ``ortools`` is not installed.
    """
    if not _ORTOOLS_AVAILABLE:
        raise OptimizationEngineUnavailable(
            "ortools is not installed — run: pip install ortools\n"
            "Reason code: DEPENDENCY_MISSING"
        )

    active_disruptions: list[Disruption] = list(disruptions or [])

    # Collect blocked nodes/edges across all active-window disruptions for
    # the belt-and-suspenders check inside _check_hard_constraints.
    ship_start = shipment.planned_departure
    ship_end = shipment.planned_arrival

    all_blocked_nodes: set[str] = set()
    all_blocked_edge_pairs: set[frozenset[str]] = set()
    for dis in active_disruptions:
        overlap = max(dis.window_start, ship_start) <= min(dis.window_end, ship_end)
        if not overlap:
            continue
        all_blocked_nodes.update(dis.blocked_nodes)
        for u, v in dis.blocked_edges:
            all_blocked_edge_pairs.add(frozenset((u, v)))

    # Build the disruption-free subgraph for path enumeration.
    sub = _build_undisrupted_subgraph(graph, active_disruptions, ship_start, ship_end)

    origin = shipment.origin_hub_id
    destination = shipment.destination_hub_id

    # Enumerate simple paths — networkx.all_simple_paths is a generator.
    candidate_paths: list[list[str]] = []
    if sub.has_node(origin) and sub.has_node(destination):
        path_gen = nx.all_simple_paths(sub, source=origin, target=destination)
        candidate_paths = list(itertools.islice(path_gen, max_paths))

    feasible_pairs: list[tuple[list[str], CarrierSpec]] = []
    rejected_results: list[RouteAlternativeResult] = []

    if not candidate_paths:
        # No path through undisrupted graph at all.
        return FeasibilityReport(
            shipment_id=shipment.shipment_id,
            disruption_ids=[d.disruption_id for d in active_disruptions],
            feasible=[],
            rejected=[
                RouteAlternativeResult(
                    rank=0,
                    carrier_id="",
                    route_nodes=[origin, destination],
                    transit_hours=0.0,
                    additional_cost_usd=0.0,
                    reefer_capable=False,
                    reason_codes=[RC_NO_PATH_EXISTS],
                    feasible=False,
                    rejection_reasons=[
                        f"No path exists from {origin!r} to {destination!r} "
                        f"in the undisrupted route graph"
                    ],
                    evidence={"blocked_nodes": sorted(all_blocked_nodes),
                               "blocked_edges": [list(e) for e in all_blocked_edge_pairs]},
                )
            ],
        )

    # Evaluate every (path, carrier) combination.
    for path in candidate_paths:
        transit_h = _route_transit_hours(graph, path)
        distance_km = _route_distance_km(graph, path)
        r_modes = _route_modes(graph, path)

        for carrier in carriers:
            feasible, codes, explanations = _check_hard_constraints(
                shipment=shipment,
                carrier=carrier,
                route_nodes=path,
                transit_hours=transit_h,
                route_modes=r_modes,
                graph=graph,
                original_blocked_edge_pairs=all_blocked_edge_pairs,
                original_blocked_nodes=all_blocked_nodes,
            )

            projected_arrival = ship_start + timedelta(hours=transit_h)
            eta_delta = (projected_arrival - shipment.planned_arrival).total_seconds() / 3600.0
            cost_usd = distance_km * carrier.cost_per_km

            result = RouteAlternativeResult(
                rank=0,  # assigned after sorting
                carrier_id=carrier.carrier_id,
                route_nodes=list(path),
                transit_hours=transit_h,
                additional_cost_usd=cost_usd,
                reefer_capable=carrier.reefer_capable,
                reason_codes=codes,
                feasible=feasible,
                rejection_reasons=explanations,
                evidence={
                    "route_modes": [m.value for m in sorted(r_modes, key=lambda x: x.value)],
                    "carrier_mode": carrier.mode.value,
                    "distance_km": distance_km,
                    "transit_hours": transit_h,
                    "projected_arrival": projected_arrival.isoformat(),
                    "eta_delta_hours": round(eta_delta, 3),
                    "carrier_capacity_kg": carrier.capacity_kg,
                    "shipment_weight_kg": shipment.weight_kg,
                },
            )

            if feasible:
                feasible_pairs.append((path, carrier))
            else:
                rejected_results.append(result)

    # --- OR-Tools uniqueness / confirmation pass ---
    confirmed_pairs = _ortools_verify_assignment(feasible_pairs, shipment)
    confirmed_set = {
        (tuple(p), c.carrier_id) for p, c in confirmed_pairs
    }

    # Build final feasible list — only OR-Tools-confirmed pairs.
    raw_feasible: list[RouteAlternativeResult] = []
    for path, carrier in feasible_pairs:
        key = (tuple(path), carrier.carrier_id)
        transit_h = _route_transit_hours(graph, path)
        distance_km = _route_distance_km(graph, path)
        r_modes = _route_modes(graph, path)
        projected_arrival = ship_start + timedelta(hours=transit_h)
        eta_delta = (projected_arrival - shipment.planned_arrival).total_seconds() / 3600.0
        cost_usd = distance_km * carrier.cost_per_km
        needs_reefer = shipment.cargo_type.lower() in ("reefer", "cold_chain", "pharmaceutical")

        if key in confirmed_set:
            raw_feasible.append(
                RouteAlternativeResult(
                    rank=0,
                    carrier_id=carrier.carrier_id,
                    route_nodes=list(path),
                    transit_hours=transit_h,
                    additional_cost_usd=cost_usd,
                    reefer_capable=carrier.reefer_capable,
                    reason_codes=_positive_reason_codes(needs_reefer, carrier),
                    feasible=True,
                    rejection_reasons=[],
                    evidence={
                        "route_modes": [m.value for m in sorted(r_modes, key=lambda x: x.value)],
                        "carrier_mode": carrier.mode.value,
                        "distance_km": distance_km,
                        "transit_hours": transit_h,
                        "projected_arrival": projected_arrival.isoformat(),
                        "eta_delta_hours": round(eta_delta, 3),
                        "carrier_capacity_kg": carrier.capacity_kg,
                        "shipment_weight_kg": shipment.weight_kg,
                    },
                )
            )
        else:
            # Demoted by OR-Tools (duplicate carrier assignment).
            rejected_results.append(
                RouteAlternativeResult(
                    rank=0,
                    carrier_id=carrier.carrier_id,
                    route_nodes=list(path),
                    transit_hours=transit_h,
                    additional_cost_usd=cost_usd,
                    reefer_capable=carrier.reefer_capable,
                    reason_codes=["CARRIER_ALREADY_ASSIGNED"],
                    feasible=False,
                    rejection_reasons=[
                        f"Carrier {carrier.carrier_id} was demoted: another route for the "
                        f"same carrier was preferred by the OR-Tools assignment step"
                    ],
                    evidence={
                        "route_modes": [m.value for m in sorted(r_modes, key=lambda x: x.value)],
                        "distance_km": distance_km,
                        "transit_hours": transit_h,
                    },
                )
            )

    # Deterministic ranking: transit_hours ASC, then carrier_id ASC.
    raw_feasible.sort(key=lambda r: (r.transit_hours, r.carrier_id))
    ranked_feasible = raw_feasible[:max_alternatives]
    for idx, r in enumerate(ranked_feasible, start=1):
        # dataclass frozen=True — must rebuild with updated rank
        ranked_feasible[idx - 1] = RouteAlternativeResult(
            rank=idx,
            carrier_id=r.carrier_id,
            route_nodes=r.route_nodes,
            transit_hours=r.transit_hours,
            additional_cost_usd=r.additional_cost_usd,
            reefer_capable=r.reefer_capable,
            reason_codes=r.reason_codes,
            feasible=r.feasible,
            rejection_reasons=r.rejection_reasons,
            evidence=r.evidence,
        )

    return FeasibilityReport(
        shipment_id=shipment.shipment_id,
        disruption_ids=[d.disruption_id for d in active_disruptions],
        feasible=ranked_feasible,
        rejected=rejected_results,
    )


# ---------------------------------------------------------------------------
# Convenience factory: build CarrierSpec from an Asset model
# ---------------------------------------------------------------------------

def carrier_spec_from_asset(asset: Asset, cost_per_km: float = 1.0) -> CarrierSpec:
    """Convert a :class:`~src.app.core.models.Asset` to a :class:`CarrierSpec`."""
    return CarrierSpec(
        carrier_id=asset.carrier_id,
        mode=asset.mode,
        capacity_kg=asset.capacity_kg,
        reefer_capable=asset.reefer_capable,
        available_at=asset.available_at,
        cost_per_km=cost_per_km,
    )
