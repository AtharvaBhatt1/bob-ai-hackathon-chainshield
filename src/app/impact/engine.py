"""
src/app/impact/engine.py
========================
Deterministic ChainShield Impact Engine.

Given a NetworkX route graph, a list of disruptions, and a list of shipments
this engine:

1. Detects whether each shipment's route intersects any active disruption
   (blocked nodes **or** blocked edges).
2. Checks that the shipment's transit window overlaps the disruption window.
3. Returns an ``ImpactResult`` for every shipment.
4. Emits SCREAMING_SNAKE_CASE reason codes consistent with the project
   documentation (PORT_NODE_BLOCKED, ROUTE_EDGE_BLOCKED, ETA_SLA_BREACH,
   TEMPERATURE_EXPOSURE_INCREASED).
5. Calculates cargo value at risk across all affected shipments.

No LLM is used.  No live routing service is called.
All branching is deterministic and idempotent — repeated calls with
identical inputs produce identical outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

import networkx as nx

from src.app.core.models import Disruption, Shipment


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShipmentImpact:
    """Impact assessment for a single shipment against a single disruption."""

    shipment_id: str
    disruption_id: str
    affected: bool
    reason_codes: list[str] = field(default_factory=list)
    cargo_value_usd: float = 0.0
    # Positive value = how many hours the planned arrival may slip.
    # Set to 0.0 for unaffected shipments.
    eta_delay_hours: float = 0.0
    evidence: dict = field(default_factory=dict)


@dataclass
class ImpactReport:
    """Aggregate report produced by ``assess_impact``."""

    disruption_id: str
    results: list[ShipmentImpact] = field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Convenience properties
    # ---------------------------------------------------------------------------

    @property
    def affected(self) -> list[ShipmentImpact]:
        return [r for r in self.results if r.affected]

    @property
    def unaffected(self) -> list[ShipmentImpact]:
        return [r for r in self.results if not r.affected]

    @property
    def total_cargo_value_at_risk_usd(self) -> float:
        return sum(r.cargo_value_usd for r in self.affected)


# ---------------------------------------------------------------------------
# Time-window helper
# ---------------------------------------------------------------------------

def _windows_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    """Return True iff time interval [a_start, a_end] overlaps [b_start, b_end].

    Uses the standard overlap test:  max(starts) <= min(ends).
    This is intentionally open-ended at both sides so a shipment arriving
    exactly as a disruption starts is considered overlapping.
    """
    return max(a_start, b_start) <= min(a_end, b_end)


# ---------------------------------------------------------------------------
# Route intersection helpers
# ---------------------------------------------------------------------------

def _route_hits_blocked_nodes(
    route: Sequence[str],
    blocked_nodes: Sequence[str],
) -> list[str]:
    """Return the subset of ``route`` nodes that are blocked."""
    blocked_set = set(blocked_nodes)
    return [n for n in route if n in blocked_set]


def _route_hits_blocked_edges(
    route: Sequence[str],
    blocked_edges: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Return the blocked edges traversed by ``route``.

    An edge (u, v) in ``blocked_edges`` is traversed by the route if there is
    any consecutive pair (route[i], route[i+1]) that equals (u, v) or (v, u)
    — edges are treated as undirected to match the NetworkX undirected default.
    """
    blocked_set = {frozenset(e) for e in blocked_edges}
    traversed = []
    for i in range(len(route) - 1):
        pair = frozenset((route[i], route[i + 1]))
        if pair in blocked_set:
            # Preserve original edge direction from blocked_edges.
            for e in blocked_edges:
                if frozenset(e) == pair:
                    traversed.append(e)
                    break
    return traversed


# ---------------------------------------------------------------------------
# SLA / deadline check
# ---------------------------------------------------------------------------

def _sla_breached(shipment: Shipment, eta_delay_hours: float) -> bool:
    """Return True if adding ``eta_delay_hours`` to the planned arrival
    would cause it to land after the delivery deadline."""
    from datetime import timedelta

    adjusted_arrival = shipment.planned_arrival + timedelta(hours=eta_delay_hours)
    return adjusted_arrival > shipment.delivery_deadline


# ---------------------------------------------------------------------------
# Core engine entry point
# ---------------------------------------------------------------------------

def assess_impact(
    graph: nx.Graph,
    disruption: Disruption,
    shipments: Sequence[Shipment],
    *,
    shipment_routes: dict[str, Sequence[str]],
    default_delay_hours: float = 24.0,
) -> ImpactReport:
    """Assess the impact of a single disruption on a collection of shipments.

    Parameters
    ----------
    graph:
        NetworkX graph representing the active route network.  Nodes are hub /
        port / depot identifiers (strings).  Not mutated.
    disruption:
        The active :class:`~src.app.core.models.Disruption` to evaluate.
    shipments:
        Sequence of :class:`~src.app.core.models.Shipment` objects to check.
    shipment_routes:
        Mapping of ``shipment_id`` → ordered list of node IDs representing
        that shipment's planned route through ``graph``.
    default_delay_hours:
        Estimated delay used for ETA calculations when a shipment is blocked
        but no better estimate is available.  Defaults to 24 h.

    Returns
    -------
    ImpactReport
        Contains one :class:`ShipmentImpact` per input shipment plus aggregate
        statistics.

    Notes
    -----
    * Deterministic: same inputs → same output, always.
    * No LLM, no network calls.
    * Reason code vocabulary: PORT_NODE_BLOCKED, ROUTE_EDGE_BLOCKED,
      ETA_SLA_BREACH, TEMPERATURE_EXPOSURE_INCREASED.
    """
    report = ImpactReport(disruption_id=disruption.disruption_id)

    for shipment in shipments:
        route = list(shipment_routes.get(shipment.shipment_id, []))

        # ------------------------------------------------------------------ #
        # 1. Route intersection check                                          #
        # ------------------------------------------------------------------ #
        hit_nodes = _route_hits_blocked_nodes(route, disruption.blocked_nodes)
        hit_edges = _route_hits_blocked_edges(
            route,
            [tuple(e) for e in disruption.blocked_edges],  # type: ignore[arg-type]
        )

        route_blocked = bool(hit_nodes or hit_edges)

        # ------------------------------------------------------------------ #
        # 2. Time-window overlap check                                         #
        # ------------------------------------------------------------------ #
        time_overlapping = _windows_overlap(
            shipment.planned_departure,
            shipment.planned_arrival,
            disruption.window_start,
            disruption.window_end,
        )

        affected = route_blocked and time_overlapping

        # ------------------------------------------------------------------ #
        # 3. Reason codes & delay estimate                                     #
        # ------------------------------------------------------------------ #
        reason_codes: list[str] = []
        eta_delay_hours = 0.0

        if affected:
            if hit_nodes:
                reason_codes.append("PORT_NODE_BLOCKED")
            if hit_edges:
                reason_codes.append("ROUTE_EDGE_BLOCKED")

            eta_delay_hours = default_delay_hours

            # SLA breach check
            if _sla_breached(shipment, eta_delay_hours):
                reason_codes.append("ETA_SLA_BREACH")

            # Reefer / cold-chain exposure: if cargo type requires temperature
            # control and the shipment is blocked, exposure risk increases.
            if shipment.cargo_type.lower() in ("reefer", "cold_chain", "pharmaceutical"):
                reason_codes.append("TEMPERATURE_EXPOSURE_INCREASED")

        # ------------------------------------------------------------------ #
        # 4. Evidence dict for audit trail                                     #
        # ------------------------------------------------------------------ #
        evidence: dict = {
            "route": route,
            "hit_nodes": hit_nodes,
            "hit_edges": hit_edges,
            "time_overlap": time_overlapping,
            "disruption_window": (
                disruption.window_start.isoformat(),
                disruption.window_end.isoformat(),
            ),
            "shipment_window": (
                shipment.planned_departure.isoformat(),
                shipment.planned_arrival.isoformat(),
            ),
        }

        report.results.append(
            ShipmentImpact(
                shipment_id=shipment.shipment_id,
                disruption_id=disruption.disruption_id,
                affected=affected,
                reason_codes=reason_codes,
                cargo_value_usd=shipment.cargo_value_usd if affected else 0.0,
                eta_delay_hours=eta_delay_hours,
                evidence=evidence,
            )
        )

    return report
