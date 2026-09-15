"""
src/app/api/routers/shipments.py
==================================
GET /api/v1/shipments/{shipment_id}

Returns shipment detail, its planned legs, and pre-computed route alternatives
(from the demo dataset — no live routing call is made).
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from src.app.api.deps import get_dataset
from src.app.core.schemas import RouteAlternative, ShipmentDetailResponse

router = APIRouter()


@router.get("/shipments/{shipment_id}", response_model=ShipmentDetailResponse)
def get_shipment(
    shipment_id: str,
    dataset: Annotated[dict[str, Any], Depends(get_dataset)],
) -> ShipmentDetailResponse:
    """Return detail for a single shipment including legs and route alternatives.

    - ``shipment``      — full Shipment model with all fields.
    - ``legs``          — ordered ShipmentLeg list for the shipment.
    - ``alternatives``  — pre-computed feasible/infeasible route alternatives.
    """
    shipment = next(
        (s for s in dataset["shipments"] if s.shipment_id == shipment_id),
        None,
    )
    if shipment is None:
        all_ids = [s.shipment_id for s in dataset["shipments"]]
        raise HTTPException(
            status_code=404,
            detail=f"Shipment '{shipment_id}' not found. Available: {all_ids}",
        )

    legs = [lg for lg in dataset.get("shipment_legs", []) if lg.shipment_id == shipment_id]
    legs.sort(key=lambda lg: lg.sequence)

    # Route alternatives are stored per-shipment in the dataset; they are only
    # available for the disrupted shipment (SHP-0042) in the demo.
    raw_alts: list[RouteAlternative] = dataset.get("route_alternatives", [])
    # All alternatives in the demo belong to the disrupted shipment.
    alternatives: list[RouteAlternative] = (
        raw_alts if shipment_id == "SHP-0042" else []
    )

    return ShipmentDetailResponse(
        shipment=shipment,
        legs=legs,
        alternatives=alternatives,
    )
