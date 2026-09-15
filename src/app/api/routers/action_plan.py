"""
src/app/api/routers/action_plan.py
=====================================
POST /api/v1/action-plan/export

Generates and exports an operator action plan for an active disruption.

The plan is assembled deterministically from:
- Impact results (which shipments are affected).
- Route alternatives (feasible reroutes).
- Asset availability (idle reefer-capable assets).
- Cold-chain status (whether the shipment needs immediate quality review).

Output format: "json" (default) or "markdown" via the ``export_format`` field.

No LLM is used.  All ranking and scoring is deterministic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from src.app.api.deps import get_dataset, get_graph
from src.app.cold_chain.engine import classify_excursion
from src.app.core.logging import get_logger
from src.app.core.models import (
    ActionPlan,
    ActionPlanItem,
    AssetStatus,
    Disruption,
    Shipment,
)
from src.app.core.schemas import ActionPlanExportRequest, ActionPlanResponse
from src.app.impact.engine import assess_impact

router = APIRouter()
_log = get_logger(__name__)

# Route map for the demo (shipment_id → ordered node list).
_SHIPMENT_ROUTES: dict[str, list[str]] = {
    "SHP-0042": ["HUB-A", "PORT-03", "HUB-B", "HUB-D"],
    "SHP-0099": ["HUB-A", "HUB-D"],
}


def _routes_for(dataset: dict[str, Any]) -> dict[str, list[str]]:
    routes: dict[str, list[str]] = {}
    for leg in dataset.get("shipment_legs", []):
        sid = leg.shipment_id
        if sid not in routes:
            routes[sid] = [leg.origin_node_id]
        routes[sid].append(leg.destination_node_id)
    for sid, nodes in _SHIPMENT_ROUTES.items():
        if sid not in routes:
            routes[sid] = nodes
    return routes


def _cold_chain_status(shipment: Shipment, dataset: dict[str, Any]) -> str:
    """Run the cold-chain classifier for *shipment* and return severity string."""
    policy = None
    if shipment.temperature_policy_id:
        policy = next(
            (p for p in dataset["policies"]
             if p.policy_id == shipment.temperature_policy_id),
            None,
        )
    if policy is None:
        return "POLICY_REQUIRED"

    readings = [
        {"ts": r.ts.isoformat(), "temp_c": r.temperature_c}
        for r in dataset["sensor_readings"]
        if r.shipment_id == shipment.shipment_id
    ]
    severity, _ = classify_excursion(policy.model_dump(), readings)
    return severity


def _build_plan(
    disruption: Disruption,
    dataset: dict[str, Any],
    graph: nx.Graph,
) -> ActionPlan:
    """Build a deterministic ActionPlan for *disruption*."""
    shipments: list[Shipment] = dataset["shipments"]
    routes = _routes_for(dataset)

    report = assess_impact(
        graph=graph,
        disruption=disruption,
        shipments=shipments,
        shipment_routes=routes,
    )

    items: list[ActionPlanItem] = []
    rank = 1

    for impact in report.affected:
        shp = next(s for s in shipments if s.shipment_id == impact.shipment_id)

        # ---- REROUTE recommendation -----------------------------------------
        alts = dataset.get("route_alternatives", [])
        feasible_alts = [a for a in alts if a.reefer_capable] if alts else []

        _log.info(
            "route_alternatives_evaluated",
            extra={
                "shipment_id": shp.shipment_id,
                "disruption_id": disruption.disruption_id,
                "total_alternatives": len(alts),
                "feasible_reefer_alternatives": len(feasible_alts),
            },
        )

        if feasible_alts:
            best = min(feasible_alts, key=lambda a: a.eta_delta_hours)
            items.append(
                ActionPlanItem(
                    rank=rank,
                    action_type="REROUTE",
                    shipment_id=shp.shipment_id,
                    description=(
                        f"Reroute via {best.carrier_id} "
                        f"({' → '.join(best.route_nodes)}) "
                        f"+{best.eta_delta_hours:.1f} h, "
                        f"+${best.additional_cost_usd:,.0f}"
                    ),
                    eta_delta_hours=best.eta_delta_hours,
                    additional_cost_usd=best.additional_cost_usd,
                    reason_codes=best.reason_codes,
                    confidence_score=0.95,
                )
            )
            rank += 1

        # ---- ASSET_DEPLOY recommendation ------------------------------------
        idle_reefer = [
            a for a in dataset["assets"]
            if a.status == AssetStatus.AVAILABLE and a.reefer_capable
        ]
        if idle_reefer and shp.cargo_type.lower() in ("reefer", "cold_chain", "pharmaceutical"):
            asset = idle_reefer[0]
            _log.info(
                "idle_asset_matched",
                extra={
                    "shipment_id": shp.shipment_id,
                    "asset_id": asset.asset_id,
                    "carrier_id": asset.carrier_id,
                    "current_node": asset.current_node_id,
                    "reason_code": "REEFER_CAPACITY_AVAILABLE",
                },
            )
            items.append(
                ActionPlanItem(
                    rank=rank,
                    action_type="ASSET_DEPLOY",
                    shipment_id=shp.shipment_id,
                    description=(
                        f"Deploy idle reefer asset {asset.asset_id} "
                        f"(carrier {asset.carrier_id}) "
                        f"from {asset.current_node_id} to cover shipment."
                    ),
                    eta_delta_hours=0.0,
                    additional_cost_usd=0.0,
                    reason_codes=["REEFER_CAPACITY_AVAILABLE"],
                    confidence_score=0.90,
                )
            )
            rank += 1

        # ---- COLD_CHAIN_HOLD recommendation ---------------------------------
        cc_status = _cold_chain_status(shp, dataset)
        if cc_status in ("EXCURSION_REVIEW", "URGENT_ESCALATION"):
            items.append(
                ActionPlanItem(
                    rank=rank,
                    action_type="COLD_CHAIN_HOLD",
                    shipment_id=shp.shipment_id,
                    description=(
                        f"Cold-chain status is {cc_status}. "
                        "Place shipment on hold; initiate quality review "
                        "before releasing to next leg."
                    ),
                    eta_delta_hours=0.0,
                    additional_cost_usd=0.0,
                    reason_codes=["TEMPERATURE_EXPOSURE_INCREASED", cc_status],
                    confidence_score=1.0,
                )
            )
            rank += 1

    return ActionPlan(
        disruption_id=disruption.disruption_id,
        generated_at=datetime.now(tz=timezone.utc),
        items=items,
        export_format="json",
    )


def _plan_to_markdown(plan: ActionPlan) -> str:
    """Render an ActionPlan as a Markdown string."""
    lines = [
        f"# ChainShield Action Plan",
        f"",
        f"**Disruption:** `{plan.disruption_id}`  ",
        f"**Generated:** {plan.generated_at.isoformat()}  ",
        f"**Items:** {len(plan.items)}",
        f"",
        "---",
        "",
    ]
    for item in plan.items:
        lines += [
            f"## {item.rank}. [{item.action_type}] Shipment `{item.shipment_id}`",
            f"",
            f"{item.description}",
            f"",
            f"- ETA delta: **+{item.eta_delta_hours:.1f} h**",
            f"- Additional cost: **${item.additional_cost_usd:,.0f}**",
            f"- Confidence: **{item.confidence_score:.0%}**",
            f"- Reason codes: `{'`, `'.join(item.reason_codes)}`",
            f"",
        ]
    return "\n".join(lines)


@router.post("/action-plan/export")
def export_action_plan(
    body: ActionPlanExportRequest,
    dataset: Annotated[dict[str, Any], Depends(get_dataset)],
    graph: Annotated[nx.Graph, Depends(get_graph)],
):
    """Generate and export an operator action plan for a disruption.

    Assembles a ranked list of recommended actions (REROUTE, ASSET_DEPLOY,
    COLD_CHAIN_HOLD) entirely from deterministic engine outputs.  No LLM used.

    ``export_format``:
    - ``"json"``     — returns :class:`ActionPlanResponse` JSON.
    - ``"markdown"`` — returns plain text Markdown.
    """
    disruption: Disruption | None = next(
        (d for d in dataset["disruptions"] if d.disruption_id == body.disruption_id),
        None,
    )
    if disruption is None:
        all_ids = [d.disruption_id for d in dataset["disruptions"]]
        _log.warning("action_plan_disruption_not_found", extra={"disruption_id": body.disruption_id})
        raise HTTPException(
            status_code=404,
            detail=f"Disruption '{body.disruption_id}' not found. Available: {all_ids}",
        )

    plan = _build_plan(disruption, dataset, graph)

    action_types = [item.action_type for item in plan.items]
    _log.info(
        "action_plan_exported",
        extra={
            "disruption_id": plan.disruption_id,
            "export_format": body.export_format,
            "item_count": len(plan.items),
            "action_types": action_types,
            "reroute_count": action_types.count("REROUTE"),
            "asset_deploy_count": action_types.count("ASSET_DEPLOY"),
            "cold_chain_hold_count": action_types.count("COLD_CHAIN_HOLD"),
        },
    )

    if body.export_format == "markdown":
        return PlainTextResponse(content=_plan_to_markdown(plan), media_type="text/markdown")

    return ActionPlanResponse(
        plan_id=plan.plan_id,
        disruption_id=plan.disruption_id,
        generated_at=plan.generated_at,
        items=plan.items,
        export_format="json",
    )
