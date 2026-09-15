"""
src/app/api/routers/disruptions.py
====================================
POST /api/v1/disruptions/activate

Activates a disruption scenario by ID, runs the deterministic Impact Engine
against all known shipments, and returns per-shipment impact results with
reason codes and evidence.

Engine: src.app.impact.engine.assess_impact
Data:   DEMO_DATASET["disruptions"] + ["shipments"]
"""
from __future__ import annotations

from typing import Annotated, Any

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException

from src.app.api.deps import get_dataset, get_graph
from src.app.core.logging import get_logger
from src.app.core.models import Disruption, Shipment
from src.app.core.schemas import (
    DisruptionActivateRequest,
    DisruptionActivateResponse,
    ImpactResult,
)
from src.app.impact.engine import assess_impact

router = APIRouter()
_log = get_logger(__name__)

# Canonical route map for the demo dataset (shipment_id → ordered node list).
# The Impact Engine needs this to detect which nodes/edges a route traverses.
_SHIPMENT_ROUTES: dict[str, list[str]] = {
    "SHP-0042": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
    "SHP-0099": ["HUB-A", "HUB-D"],
}


def _routes_for(dataset: dict[str, Any]) -> dict[str, list[str]]:
    """Build shipment_routes from shipment_legs in the dataset, falling back
    to the hardcoded map for any shipment without leg data."""
    routes: dict[str, list[str]] = {}
    for leg in dataset.get("shipment_legs", []):
        sid = leg.shipment_id
        if sid not in routes:
            routes[sid] = [leg.origin_node_id]
        routes[sid].append(leg.destination_node_id)
    # fill gaps for shipments that have no legs
    for sid, nodes in _SHIPMENT_ROUTES.items():
        if sid not in routes:
            routes[sid] = nodes
    return routes


@router.post("/disruptions/activate", response_model=DisruptionActivateResponse)
def activate_disruption(
    body: DisruptionActivateRequest,
    dataset: Annotated[dict[str, Any], Depends(get_dataset)],
    graph: Annotated[nx.Graph, Depends(get_graph)],
) -> DisruptionActivateResponse:
    """Activate a disruption scenario and return impact results for all shipments.

    - Finds the disruption by ID in the seeded dataset.
    - Runs the deterministic Impact Engine against every known shipment.
    - Returns affected/unaffected status, reason codes, cargo value, and ETA delay.
    """
    _log.info("disruption_activation_requested", extra={"disruption_id": body.disruption_id})

    # Locate disruption
    disruption: Disruption | None = next(
        (d for d in dataset["disruptions"] if d.disruption_id == body.disruption_id),
        None,
    )
    if disruption is None:
        _log.warning(
            "disruption_not_found",
            extra={
                "disruption_id": body.disruption_id,
                "available": [d.disruption_id for d in dataset["disruptions"]],
            },
        )
        raise HTTPException(
            status_code=404,
            detail=f"Disruption '{body.disruption_id}' not found. "
                   f"Available: {[d.disruption_id for d in dataset['disruptions']]}",
        )

    shipments: list[Shipment] = dataset["shipments"]
    shipment_routes = _routes_for(dataset)

    report = assess_impact(
        graph=graph,
        disruption=disruption,
        shipments=shipments,
        shipment_routes=shipment_routes,
    )

    affected_count = len(report.affected)
    cargo_value_at_risk = report.total_cargo_value_at_risk_usd

    _log.info(
        "disruption_activated",
        extra={
            "disruption_id": disruption.disruption_id,
            "disruption_type": disruption.disruption_type,
            "affected_shipment_count": affected_count,
            "unaffected_shipment_count": len(report.unaffected),
            "cargo_value_at_risk_usd": cargo_value_at_risk,
        },
    )

    results = [
        ImpactResult(
            shipment_id=r.shipment_id,
            affected=r.affected,
            reason_codes=r.reason_codes,
            cargo_value_usd=r.cargo_value_usd,
            eta_delay_hours=r.eta_delay_hours,
        )
        for r in report.results
    ]

    return DisruptionActivateResponse(
        disruption_id=disruption.disruption_id,
        affected_shipments=results,
    )
