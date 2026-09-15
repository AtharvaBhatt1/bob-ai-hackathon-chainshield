"""
src/app/api/routers/explanations.py
======================================
POST /api/v1/explanations/generate

Generates a human-readable explanation for a decision identified by its
``decision_id``.  When WATSONX_ENABLED=false (the default), the deterministic
fallback produces the explanation immediately with no network calls.

Engine:  src.app.explanation.fallback.generate_fallback_explanation
Data:    EvidenceRecord from DEMO_DATASET["evidence_records"]
"""
from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from src.app.api.deps import get_dataset
from src.app.core.logging import get_logger
from src.app.core.models import ExplanationResult
from src.app.core.schemas import ExplanationRequest
from src.app.explanation.fallback import DecisionRecord, generate_fallback_explanation

router = APIRouter()
_log = get_logger(__name__)


def _build_decision_record(ev: Any) -> DecisionRecord:
    """Convert an EvidenceRecord into a DecisionRecord for the fallback engine."""
    # Pull cold_chain_status and route_feasible out of the engine output if present.
    engine_outputs: dict[str, Any] = {}
    if ev.output:
        if "status" in ev.output:
            engine_outputs["cold_chain_status"] = ev.output["status"]
        if "affected" in ev.output:
            engine_outputs["route_feasible"] = not ev.output.get("affected", True)

    # Filter empty reason_codes — the fallback engine raises on empty lists.
    codes = [c for c in (ev.reason_codes or []) if c]

    if not codes:
        # Synthesise a minimal reason code from the decision type so the
        # fallback can produce a meaningful (if generic) explanation.
        codes = [f"{ev.decision_type.value}_DECISION"]

    return DecisionRecord(
        shipment_id=ev.shipment_id,
        disruption_id=ev.disruption_id,
        reason_codes=codes,
        engine_outputs=engine_outputs,
        policy_id=ev.policy_id,
    )


@router.post("/explanations/generate", response_model=ExplanationResult)
def generate_explanation(
    body: ExplanationRequest,
    dataset: Annotated[dict[str, Any], Depends(get_dataset)],
) -> ExplanationResult:
    """Generate a structured explanation for a decision record.

    When ``WATSONX_ENABLED=false`` (default), the deterministic fallback
    template is used.  Identical inputs always produce identical output.

    The ``decision_id`` must reference an EvidenceRecord that exists in the
    seeded dataset.
    """
    # Locate evidence record in the seeded dataset.
    ev = next(
        (r for r in dataset["evidence_records"] if r.decision_id == body.decision_id),
        None,
    )
    if ev is None:
        all_ids = [r.decision_id for r in dataset["evidence_records"]]
        _log.warning("explanation_decision_not_found", extra={"decision_id": body.decision_id})
        raise HTTPException(
            status_code=404,
            detail=f"Decision '{body.decision_id}' not found. Available: {all_ids}",
        )

    watsonx_enabled = os.getenv("WATSONX_ENABLED", "false").lower() == "true"

    if watsonx_enabled:
        # Watsonx path — attempted only when explicitly enabled.
        # Falls back to deterministic on any failure (timeout, network error, etc.).
        try:
            result = _try_watsonx(ev)
            _log.info(
                "explanation_generated",
                extra={
                    "decision_id": body.decision_id,
                    "shipment_id": ev.shipment_id,
                    "explanation_mode": "watsonx_granite",
                    "generated_by": getattr(result, "generated_by", None),
                },
            )
            return result
        except Exception as exc:
            _log.warning(
                "watsonx_explanation_failed",
                extra={
                    "decision_id": body.decision_id,
                    "error": str(exc),
                    "fallback": "deterministic_fallback_template",
                },
            )

    # Deterministic fallback — always available, no network.
    decision = _build_decision_record(ev)
    result = generate_fallback_explanation(decision)
    _log.info(
        "explanation_generated",
        extra={
            "decision_id": body.decision_id,
            "shipment_id": ev.shipment_id,
            "explanation_mode": "deterministic_fallback",
            "generated_by": result.generated_by,
        },
    )
    return result


def _try_watsonx(ev: Any) -> ExplanationResult:
    """Attempt a watsonx.ai Granite explanation call (2.5 s timeout).

    Builds a :class:`~src.app.explanation.fallback.DecisionRecord` from *ev*,
    then delegates to :func:`~src.app.explanation.watsonx.generate_granite_explanation`.
    That function produces the deterministic result first, sends it as context
    to Granite, and returns a schema-complete :class:`ExplanationResult` with
    ``generated_by`` set to the Granite model identifier.

    Evidence and uncertainties are **always** taken from the deterministic
    computation — never from the LLM output — so operational correctness is
    preserved regardless of model behaviour.

    Raises any exception on failure so the caller falls through to the
    deterministic fallback.
    """
    from src.app.explanation.watsonx import generate_granite_explanation  # noqa: PLC0415

    decision = _build_decision_record(ev)
    return generate_granite_explanation(decision)
