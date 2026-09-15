"""
src/app/explanation/fallback.py
================================
Deterministic offline explanation fallback for ChainShield.

Used when ``WATSONX_ENABLED=false`` or when the watsonx.ai call exceeds its
2.5 s timeout.  Pure string templating over already-computed, already-authorised
structured facts — **no model call, no network, no invented data**.

Design rules
------------
- Input is a *structured* :class:`DecisionRecord` dataclass, not free-form text.
- Output is an :class:`~src.app.core.models.ExplanationResult` Pydantic model.
- Identical inputs **always** produce identical outputs (deterministic).
- Only reason codes and evidence drawn from the supplied decision record appear
  in the output — nothing is invented: no routes, no temperatures, no regulatory
  claims, no carrier availability, no confidence values.
- Works with ``WATSONX_ENABLED=false``; never calls any external API.
- ``generated_by`` is always ``"deterministic_fallback_template"``.
- ``model_used`` is always ``None``.

Reason-code catalogue (SCREAMING_SNAKE_CASE)
--------------------------------------------
The ``_WHY_AFFECTED_PHRASES`` dict maps known reason codes to human-readable
impact sentences.  Unknown codes are surfaced verbatim as
``"Flagged due to <CODE>"`` — no invented explanation is ever added.

The ``_ACTION_HINTS`` dict maps reason codes to short action hints that are
concatenated into ``recommended_action`` only when those codes appear in the
decision record.  When no matching code is present the output says so plainly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.app.core.models import ExplanationResult


# ---------------------------------------------------------------------------
# Reason-code → human phrase mappings
# (only codes the project already defines; no invented information)
# ---------------------------------------------------------------------------

_WHY_AFFECTED_PHRASES: dict[str, str] = {
    "PORT_NODE_BLOCKED": (
        "The shipment's current route passes through a node that is blocked."
    ),
    "ETA_SLA_BREACH": (
        "The estimated arrival is projected to breach the contracted SLA deadline."
    ),
    "REEFER_CAPACITY_AVAILABLE": (
        "A reefer-capable alternative capacity slot has been identified."
    ),
    "ROUTE_INFEASIBLE": (
        "No feasible route could be found that satisfies all hard constraints."
    ),
    "CAPACITY_OK": (
        "Current capacity constraints are satisfied under the assessed scenario."
    ),
    "CONSTRAINT_VIOLATION": (
        "A required constraint (e.g. reefer capability, weight limit) would be "
        "violated under the current assignment."
    ),
    "TEMPERATURE_EXPOSURE_INCREASED": (
        "Sensor data indicates the shipment has been exposed to temperatures "
        "outside the acceptable range defined by its policy profile."
    ),
    "EXCURSION_REVIEW": (
        "A temperature excursion has been detected; the shipment requires "
        "manual review before final disposition."
    ),
    "URGENT_ESCALATION": (
        "Sensor data is absent or the excursion severity requires immediate "
        "operator escalation."
    ),
    "POLICY_REQUIRED": (
        "No cold-chain policy profile matched this shipment's product class; "
        "classification cannot proceed without a policy."
    ),
    "COLD_CHAIN_CLASSIFICATION_MISMATCH": (
        "The cold-chain classifier returned an unexpected severity for the "
        "reference scenario — manual review is required."
    ),
    "MISSING_EVIDENCE_LINK": (
        "The explanation layer produced no evidence codes; the decision record "
        "must be reviewed for completeness."
    ),
    "DEPENDENCY_MISSING": (
        "An optional dependency required for this check was not installed; "
        "the check was skipped."
    ),
}

_ACTION_HINTS: dict[str, str] = {
    "PORT_NODE_BLOCKED": "review alternative routing that avoids the blocked node",
    "ETA_SLA_BREACH": "escalate to logistics operations to assess SLA impact",
    "CONSTRAINT_VIOLATION": "reassign shipment to a constraint-compliant carrier or asset",
    "ROUTE_INFEASIBLE": "engage logistics operations — no automated re-route is available",
    "EXCURSION_REVIEW": "initiate manual cold-chain review before releasing shipment",
    "URGENT_ESCALATION": "immediately escalate to quality assurance and cold-chain team",
    "POLICY_REQUIRED": "assign a matching cold-chain policy profile to this shipment",
    "TEMPERATURE_EXPOSURE_INCREASED": (
        "review sensor log and assess product viability with quality assurance"
    ),
}


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionRecord:
    """Structured evidence record passed into :func:`generate_fallback_explanation`.

    All fields are drawn from already-computed engine outputs.  No field is
    optional in the sense that the caller must have explicit knowledge of its
    value; ``None`` / empty collections are legal and handled gracefully.

    Parameters
    ----------
    shipment_id:
        The shipment this decision relates to, e.g. ``"SHP-0042"``.
    disruption_id:
        Identifier of the disruption event, e.g. ``"PORT_STRIKE_01"``.
        ``None`` if the decision was not triggered by a named disruption.
    reason_codes:
        Non-empty list of ``SCREAMING_SNAKE_CASE`` reason codes produced by
        the deterministic engines.
    engine_outputs:
        Dict of raw engine output fields (e.g. ``cold_chain_status``,
        ``route_feasible``).  Only keys explicitly listed in this module are
        referenced; unknown keys are ignored.
    policy_id:
        Cold-chain policy profile ID, if one was evaluated.  ``None`` otherwise.
    """

    shipment_id: str
    disruption_id: str | None
    reason_codes: list[str]
    engine_outputs: dict[str, Any] = field(default_factory=dict)
    policy_id: str | None = None


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def generate_fallback_explanation(decision: DecisionRecord) -> ExplanationResult:
    """Produce a deterministic, schema-complete explanation from *decision*.

    This function performs **no network calls**, **no model inference**, and
    **invents nothing**.  Every sentence in the output traces back to a field
    in *decision*.

    The function is pure: calling it twice with the same :class:`DecisionRecord`
    instance always produces structurally and textually identical output.

    Parameters
    ----------
    decision:
        Structured evidence from the deterministic engines.

    Returns
    -------
    ExplanationResult
        A fully-populated :class:`~src.app.core.models.ExplanationResult` with
        ``generated_by="deterministic_fallback_template"`` and
        ``model_used=None``.

    Raises
    ------
    ValueError
        If ``decision.reason_codes`` is empty — a decision with no reason codes
        cannot produce a meaningful explanation.
    """
    if not decision.reason_codes:
        raise ValueError(
            f"reason_codes must not be empty for shipment_id={decision.shipment_id!r}"
        )

    # -- summary -------------------------------------------------------------
    disruption_label = decision.disruption_id or "an unspecified disruption"
    summary = (
        f"Shipment {decision.shipment_id} has been flagged due to "
        f"{disruption_label}."
    )

    # -- why_affected --------------------------------------------------------
    # Deterministic: iterate reason_codes in the order supplied; map known
    # codes to their phrases, surface unknown codes verbatim.
    why_affected: list[str] = []
    for code in decision.reason_codes:
        phrase = _WHY_AFFECTED_PHRASES.get(code)
        if phrase:
            why_affected.append(phrase)
        else:
            why_affected.append(f"Flagged due to {code}.")

    # -- recommended_action --------------------------------------------------
    # Collect action hints only for reason codes present in the record.
    action_parts: list[str] = []
    for code in decision.reason_codes:
        hint = _ACTION_HINTS.get(code)
        if hint and hint not in action_parts:
            action_parts.append(hint)

    if action_parts:
        recommended_action = "Operator should: " + "; ".join(action_parts) + "."
    else:
        recommended_action = (
            "No automated action recommendation is available for the supplied "
            "reason codes; operator judgment is required."
        )

    # -- evidence ------------------------------------------------------------
    # Reproduce the reason codes as the audit-trail link — no fabrication.
    evidence: list[str] = list(decision.reason_codes)

    # -- uncertainties -------------------------------------------------------
    uncertainties: list[str] = []

    cold_chain_status = decision.engine_outputs.get("cold_chain_status")
    if cold_chain_status in {"EXCURSION_REVIEW", "URGENT_ESCALATION", "POLICY_REQUIRED"}:
        uncertainties.append(
            f"Cold-chain status is {cold_chain_status}; requires manual review "
            "before disposition."
        )

    if decision.engine_outputs.get("route_feasible") is False:
        uncertainties.append(
            "No feasible route alternative was found within hard constraints; "
            "operator judgment is required."
        )

    if decision.policy_id is None and cold_chain_status is not None:
        uncertainties.append(
            "No cold-chain policy profile was referenced; classification "
            "completeness cannot be confirmed."
        )

    return ExplanationResult(
        summary=summary,
        why_affected=why_affected,
        recommended_action=recommended_action,
        evidence=evidence,
        uncertainties=uncertainties,
        generated_by="deterministic_fallback_template",
        model_used=None,
    )
