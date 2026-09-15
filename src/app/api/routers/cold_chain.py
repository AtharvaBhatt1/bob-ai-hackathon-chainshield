"""
src/app/api/routers/cold_chain.py
====================================
GET /api/v1/cold-chain/{shipment_id}/timeline

Returns the full cold-chain timeline for a shipment:
- Policy profile used for classification.
- All sensor readings annotated with in_range flag.
- Contiguous excursion events (start/end/duration/pattern).
- Overall severity classification from the deterministic engine.
- Evidence dict from the cold-chain engine.

Engine:  src.app.cold_chain.engine.classify_excursion
Data:    DEMO_DATASET["sensor_readings"] + ["policies"] + ["shipments"]
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from src.app.api.deps import get_dataset
from src.app.cold_chain.engine import classify_excursion, _parse_ts
from src.app.core.logging import get_logger
from src.app.core.models import ExcursionStatus, PolicyProfile, SensorReading
from src.app.core.schemas import (
    ColdChainTimelineResponse,
    ExcursionEvent,
    SensorReadingOut,
)

router = APIRouter()
_log = get_logger(__name__)


def _excursion_pattern(readings: list[dict[str, Any]]) -> str:
    """Heuristic pattern detector for a contiguous out-of-range block.

    Patterns:
      SPIKE    — temperature rises sharply then falls back within a short window.
      DRIFT    — temperature gradually creeps outside the boundary.
      UNKNOWN  — insufficient information.
    """
    if len(readings) <= 1:
        return "SPIKE"
    temps = [r["temp_c"] for r in readings]
    # If the mid-point is higher than both endpoints → spike
    mid = len(temps) // 2
    if temps[mid] >= temps[0] and temps[mid] >= temps[-1]:
        return "SPIKE"
    # If readings monotonically increase or decrease → drift
    if all(a <= b for a, b in zip(temps, temps[1:])) or all(
        a >= b for a, b in zip(temps, temps[1:])
    ):
        return "DRIFT"
    return "UNKNOWN"


def _build_excursion_events(
    readings: list[dict[str, Any]],
    min_c: float,
    max_c: float,
    sample_interval: float,
) -> list[ExcursionEvent]:
    """Extract contiguous blocks of out-of-range readings as ExcursionEvent objects."""
    events: list[ExcursionEvent] = []
    current_block: list[dict[str, Any]] = []

    def _flush(block: list[dict[str, Any]]) -> None:
        if not block:
            return
        start_dt = _parse_ts(block[0]["ts"])
        end_dt = _parse_ts(block[-1]["ts"])
        span_min = (end_dt.replace(tzinfo=None) - start_dt.replace(tzinfo=None)).total_seconds() / 60.0
        duration = max(span_min + sample_interval, sample_interval)
        events.append(
            ExcursionEvent(
                start_ts=start_dt,
                end_ts=end_dt,
                duration_minutes=round(duration, 2),
                max_celsius=max(r["temp_c"] for r in block),
                min_celsius=min(r["temp_c"] for r in block),
                pattern=_excursion_pattern(block),
            )
        )

    for r in readings:
        if not (min_c <= r["temp_c"] <= max_c):
            current_block.append(r)
        else:
            _flush(current_block)
            current_block = []
    _flush(current_block)
    return events


@router.get("/cold-chain/{shipment_id}/timeline", response_model=ColdChainTimelineResponse)
def cold_chain_timeline(
    shipment_id: str,
    dataset: Annotated[dict[str, Any], Depends(get_dataset)],
) -> ColdChainTimelineResponse:
    """Return the cold-chain timeline for *shipment_id*.

    Steps:
    1. Verify the shipment exists.
    2. Resolve the cold-chain policy for this shipment's product_class.
    3. Fetch all sensor readings for the shipment (sorted by ts).
    4. Run ``classify_excursion`` to get severity + evidence.
    5. Annotate each reading with ``in_range`` flag.
    6. Extract contiguous excursion events.
    """
    # ---- 1. verify shipment ------------------------------------------------
    shipment = next(
        (s for s in dataset["shipments"] if s.shipment_id == shipment_id),
        None,
    )
    if shipment is None:
        all_ids = [s.shipment_id for s in dataset["shipments"]]
        _log.warning("cold_chain_shipment_not_found", extra={"shipment_id": shipment_id})
        raise HTTPException(
            status_code=404,
            detail=f"Shipment '{shipment_id}' not found. Available: {all_ids}",
        )

    # ---- 2. resolve policy -------------------------------------------------
    policy: PolicyProfile | None = None
    if shipment.temperature_policy_id:
        policy = next(
            (p for p in dataset["policies"]
             if p.policy_id == shipment.temperature_policy_id),
            None,
        )
    if policy is None and shipment.product_class:
        policy = next(
            (p for p in dataset["policies"]
             if p.product_class == shipment.product_class),
            None,
        )

    # ---- 3. fetch + sort sensor readings -----------------------------------
    raw_readings: list[SensorReading] = [
        sr for sr in dataset["sensor_readings"] if sr.shipment_id == shipment_id
    ]
    raw_readings.sort(key=lambda r: r.ts)

    # Convert to dicts expected by classify_excursion
    engine_readings = [
        {"ts": r.ts.isoformat(), "temp_c": r.temperature_c}
        for r in raw_readings
    ]

    # ---- 4. classify -------------------------------------------------------
    policy_dict = policy.model_dump() if policy else None
    severity_str, evidence = classify_excursion(policy_dict, engine_readings)

    # Normalise severity to the enum (unknown strings → POLICY_REQUIRED as safe default)
    try:
        status = ExcursionStatus(severity_str)
    except ValueError:
        status = ExcursionStatus.EXCURSION_REVIEW

    _log.info(
        "cold_chain_classified",
        extra={
            "shipment_id": shipment_id,
            "policy_id": policy.policy_id if policy else None,
            "product_class": shipment.product_class,
            "reading_count": len(engine_readings),
            "severity": severity_str,
            "out_of_range_count": evidence.get("out_of_range_count", 0),
            "cumulative_excursion_minutes": evidence.get("cumulative_excursion_minutes", 0.0),
            "excursion_detected": severity_str not in ("SAFE", "POLICY_REQUIRED"),
        },
    )

    # ---- 5. annotate readings ----------------------------------------------
    min_c = policy.min_celsius if policy else float("-inf")
    max_c = policy.max_celsius if policy else float("inf")

    annotated: list[SensorReadingOut] = [
        SensorReadingOut(
            sensor_id=r.sensor_id,
            ts=r.ts,
            temperature_c=r.temperature_c,
            battery_pct=r.battery_pct,
            in_range=(min_c <= r.temperature_c <= max_c),
        )
        for r in raw_readings
    ]

    # ---- 6. excursion events -----------------------------------------------
    excursion_events: list[ExcursionEvent] = []
    if policy and engine_readings:
        excursion_events = _build_excursion_events(
            engine_readings, min_c, max_c,
            float(policy.sample_interval_minutes),
        )

    return ColdChainTimelineResponse(
        shipment_id=shipment_id,
        policy=policy,
        readings=annotated,
        excursion_events=excursion_events,
        status=status,
        max_celsius=evidence.get("max_c"),
        min_celsius=evidence.get("min_c"),
        total_out_of_range_minutes=evidence.get("cumulative_excursion_minutes", 0.0),
        evidence=evidence,
    )
