"""
src/app/api/routers/assets.py
================================
GET /api/v1/assets/idle

Returns all available (idle) assets from the demo dataset.  Each result
includes the asset detail, an estimated reposition distance based on the
route graph, and reason codes explaining why the asset is surfaced.

No live fleet-management call is made.  Data source: DEMO_DATASET["assets"].
"""
from __future__ import annotations

from typing import Annotated, Any

import networkx as nx
from fastapi import APIRouter, Depends

from src.app.api.deps import get_dataset, get_graph
from src.app.core.logging import get_logger
from src.app.core.models import Asset, AssetStatus
from src.app.core.schemas import AssetMatch, IdleAssetsResponse

router = APIRouter()
_log = get_logger(__name__)

# Reason codes per asset type that explain why the asset is surfaced.
_ASSET_REASON_CODES: dict[str, list[str]] = {
    "truck":     ["REEFER_CAPACITY_AVAILABLE"],
    "container": ["REEFER_CAPACITY_AVAILABLE"],
    "vessel":    ["SEA_CAPACITY_AVAILABLE"],
    "aircraft":  ["AIR_CAPACITY_AVAILABLE"],
    "railcar":   ["RAIL_CAPACITY_AVAILABLE"],
}

# Reference node for reposition distance (disrupted region hub).
_REFERENCE_NODE = "HUB-B"


def _reposition_distance(graph: nx.Graph, asset_node: str, ref_node: str) -> float:
    """Shortest-path distance in km from *asset_node* to *ref_node*.

    Returns 0.0 if either node is missing or no path exists.
    """
    if asset_node == ref_node:
        return 0.0
    if not graph.has_node(asset_node) or not graph.has_node(ref_node):
        return 0.0
    try:
        path = nx.shortest_path(graph, source=asset_node, target=ref_node)
        total_km = 0.0
        for i in range(len(path) - 1):
            edge_data = graph.get_edge_data(path[i], path[i + 1]) or {}
            total_km += edge_data.get("distance_km", 0.0)
        return round(total_km, 2)
    except nx.NetworkXNoPath:
        return 0.0


@router.get("/assets/idle", response_model=IdleAssetsResponse)
def get_idle_assets(
    dataset: Annotated[dict[str, Any], Depends(get_dataset)],
    graph: Annotated[nx.Graph, Depends(get_graph)],
) -> IdleAssetsResponse:
    """Return all assets whose status is 'available'.

    Each result includes:
    - Full asset detail (type, mode, capacity, reefer capability).
    - Estimated reposition distance in km from asset's current node to HUB-B
      (the reference hub adjacent to the demo disruption).
    - Reason codes: e.g. REEFER_CAPACITY_AVAILABLE for reefer-capable assets.
    """
    idle_assets: list[Asset] = [
        a for a in dataset["assets"] if a.status == AssetStatus.AVAILABLE
    ]

    matches: list[AssetMatch] = []
    for asset in idle_assets:
        base_codes = _ASSET_REASON_CODES.get(asset.asset_type.value, ["CAPACITY_AVAILABLE"])
        reason_codes = list(base_codes)
        if not asset.reefer_capable and "REEFER_CAPACITY_AVAILABLE" in reason_codes:
            reason_codes = [c for c in reason_codes if c != "REEFER_CAPACITY_AVAILABLE"]
            reason_codes.append("NON_REEFER_ASSET")

        dist = _reposition_distance(graph, asset.current_node_id, _REFERENCE_NODE)

        matches.append(
            AssetMatch(
                asset_id=asset.asset_id,
                asset=asset,
                reposition_distance_km=dist,
                available_at=asset.available_at,
                reason_codes=reason_codes,
            )
        )

    # Sort: reefer-capable first, then by distance ascending.
    matches.sort(key=lambda m: (not m.asset.reefer_capable, m.reposition_distance_km))

    reefer_count = sum(1 for m in matches if m.asset.reefer_capable)
    _log.info(
        "idle_assets_queried",
        extra={
            "idle_asset_count": len(matches),
            "reefer_capable_count": reefer_count,
            "asset_ids": [m.asset_id for m in matches],
        },
    )

    return IdleAssetsResponse(assets=matches)
