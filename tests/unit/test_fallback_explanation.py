"""
tests/unit/test_fallback_explanation.py
=======================================
Unit tests for src/app/explanation/fallback.py — the deterministic offline
explanation fallback.

Covered assertions
------------------
 1. Output contains all five required keys: summary, why_affected,
    recommended_action, evidence, uncertainties.
 2. generated_by == "deterministic_fallback_template" always.
 3. model_used is None always.
 4. Identical inputs produce identical output (determinism).
 5. summary contains shipment_id and disruption_id.
 6. summary uses "an unspecified disruption" when disruption_id is None.
 7. evidence equals the reason_codes supplied in the decision record.
 8. why_affected maps known reason codes to non-empty phrases.
 9. Unknown reason codes appear verbatim in why_affected ("Flagged due to …").
10. recommended_action references action hints for known codes.
11. recommended_action falls back to operator-judgment text when no hint exists.
12. cold_chain_status EXCURSION_REVIEW → uncertainty entry present.
13. cold_chain_status URGENT_ESCALATION → uncertainty entry present.
14. cold_chain_status POLICY_REQUIRED → uncertainty entry present.
15. cold_chain_status SAFE → no cold-chain uncertainty added.
16. route_feasible=False → uncertainty entry present.
17. route_feasible=True → no route uncertainty added.
18. policy_id=None + cold_chain_status set → policy uncertainty present.
19. policy_id set + cold_chain_status set → no policy uncertainty.
20. Empty engine_outputs → no uncertainties from those checks.
21. Empty reason_codes → ValueError raised.
22. Return type is ExplanationResult (Pydantic model).
23. ExplanationResult is JSON-serialisable.
24. why_affected length matches number of supplied reason_codes.
25. Multiple reason codes: each code contributes exactly one why_affected entry.
"""
from __future__ import annotations

import json

import pytest

from src.app.core.models import ExplanationResult
from src.app.explanation.fallback import DecisionRecord, generate_fallback_explanation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(
    shipment_id: str = "SHP-0042",
    disruption_id: str | None = "PORT_STRIKE_01",
    reason_codes: list[str] | None = None,
    engine_outputs: dict | None = None,
    policy_id: str | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        shipment_id=shipment_id,
        disruption_id=disruption_id,
        reason_codes=reason_codes if reason_codes is not None else ["PORT_NODE_BLOCKED"],
        engine_outputs=engine_outputs if engine_outputs is not None else {},
        policy_id=policy_id,
    )


def _explain(decision: DecisionRecord | None = None, **kwargs) -> ExplanationResult:
    if decision is None:
        decision = _make_decision(**kwargs)
    return generate_fallback_explanation(decision)


# ---------------------------------------------------------------------------
# 1–3: Schema and metadata
# ---------------------------------------------------------------------------

def test_all_required_keys_present():
    result = _explain()
    assert result.summary
    assert isinstance(result.why_affected, list)
    assert result.recommended_action
    assert isinstance(result.evidence, list)
    assert isinstance(result.uncertainties, list)


def test_generated_by_is_deterministic_fallback_template():
    assert _explain().generated_by == "deterministic_fallback_template"


def test_model_used_is_none():
    assert _explain().model_used is None


# ---------------------------------------------------------------------------
# 4: Determinism
# ---------------------------------------------------------------------------

def test_identical_inputs_produce_identical_output():
    decision = _make_decision(
        reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
        engine_outputs={"cold_chain_status": "EXCURSION_REVIEW", "route_feasible": False},
        policy_id="POL-CDC-01",
    )
    result_a = generate_fallback_explanation(decision)
    result_b = generate_fallback_explanation(decision)
    assert result_a.model_dump() == result_b.model_dump()


# ---------------------------------------------------------------------------
# 5–6: Summary content
# ---------------------------------------------------------------------------

def test_summary_contains_shipment_id():
    result = _explain(shipment_id="SHP-9999", disruption_id="WEATHER_EVENT_01")
    assert "SHP-9999" in result.summary


def test_summary_contains_disruption_id():
    result = _explain(disruption_id="PORT_STRIKE_01")
    assert "PORT_STRIKE_01" in result.summary


def test_summary_uses_unspecified_when_disruption_id_is_none():
    result = _explain(disruption_id=None)
    assert "unspecified disruption" in result.summary


# ---------------------------------------------------------------------------
# 7: Evidence mirrors reason_codes
# ---------------------------------------------------------------------------

def test_evidence_equals_reason_codes():
    codes = ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"]
    result = _explain(reason_codes=codes)
    assert result.evidence == codes


def test_evidence_single_code():
    result = _explain(reason_codes=["CONSTRAINT_VIOLATION"])
    assert result.evidence == ["CONSTRAINT_VIOLATION"]


# ---------------------------------------------------------------------------
# 8–9: why_affected phrases
# ---------------------------------------------------------------------------

def test_known_reason_code_produces_non_empty_phrase():
    result = _explain(reason_codes=["PORT_NODE_BLOCKED"])
    assert len(result.why_affected) == 1
    assert result.why_affected[0]  # non-empty
    assert "PORT_NODE_BLOCKED" not in result.why_affected[0]  # mapped to a phrase, not verbatim code


def test_unknown_reason_code_appears_verbatim():
    result = _explain(reason_codes=["MY_CUSTOM_CODE_XYZ"])
    assert len(result.why_affected) == 1
    assert "MY_CUSTOM_CODE_XYZ" in result.why_affected[0]


def test_why_affected_length_matches_reason_codes_count():
    codes = ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH", "CONSTRAINT_VIOLATION"]
    result = _explain(reason_codes=codes)
    assert len(result.why_affected) == len(codes)


def test_each_reason_code_contributes_one_why_affected_entry():
    codes = ["PORT_NODE_BLOCKED", "ROUTE_INFEASIBLE", "EXCURSION_REVIEW"]
    result = _explain(reason_codes=codes)
    assert len(result.why_affected) == 3


# ---------------------------------------------------------------------------
# 10–11: recommended_action
# ---------------------------------------------------------------------------

def test_recommended_action_references_hint_for_known_code():
    result = _explain(reason_codes=["ETA_SLA_BREACH"])
    assert "SLA" in result.recommended_action or "escalat" in result.recommended_action.lower()


def test_recommended_action_fallback_for_unknown_codes():
    result = _explain(reason_codes=["MY_UNKNOWN_CODE_ABC"])
    assert "operator" in result.recommended_action.lower()


def test_recommended_action_is_non_empty_string():
    result = _explain(reason_codes=["PORT_NODE_BLOCKED"])
    assert isinstance(result.recommended_action, str)
    assert result.recommended_action.strip()


# ---------------------------------------------------------------------------
# 12–15: cold_chain_status → uncertainties
# ---------------------------------------------------------------------------

def test_cold_chain_excursion_review_adds_uncertainty():
    result = _explain(
        engine_outputs={"cold_chain_status": "EXCURSION_REVIEW"},
    )
    assert any("EXCURSION_REVIEW" in u for u in result.uncertainties)


def test_cold_chain_urgent_escalation_adds_uncertainty():
    result = _explain(
        engine_outputs={"cold_chain_status": "URGENT_ESCALATION"},
    )
    assert any("URGENT_ESCALATION" in u for u in result.uncertainties)


def test_cold_chain_policy_required_adds_uncertainty():
    result = _explain(
        engine_outputs={"cold_chain_status": "POLICY_REQUIRED"},
    )
    assert any("POLICY_REQUIRED" in u for u in result.uncertainties)


def test_cold_chain_safe_does_not_add_uncertainty():
    result = _explain(
        engine_outputs={"cold_chain_status": "SAFE"},
    )
    assert not any("cold-chain status" in u.lower() for u in result.uncertainties)


# ---------------------------------------------------------------------------
# 16–17: route_feasible → uncertainties
# ---------------------------------------------------------------------------

def test_route_infeasible_adds_uncertainty():
    result = _explain(
        reason_codes=["ROUTE_INFEASIBLE"],
        engine_outputs={"route_feasible": False},
    )
    assert any("feasible route" in u.lower() or "no feasible" in u.lower() for u in result.uncertainties)


def test_route_feasible_true_does_not_add_uncertainty():
    result = _explain(engine_outputs={"route_feasible": True})
    assert not any("feasible route" in u.lower() for u in result.uncertainties)


# ---------------------------------------------------------------------------
# 18–19: policy_id + cold_chain_status → policy uncertainty
# ---------------------------------------------------------------------------

def test_no_policy_id_and_cold_chain_status_set_adds_policy_uncertainty():
    result = _explain(
        engine_outputs={"cold_chain_status": "EXCURSION_REVIEW"},
        policy_id=None,
    )
    assert any("policy" in u.lower() for u in result.uncertainties)


def test_policy_id_set_suppresses_policy_uncertainty():
    result = _explain(
        engine_outputs={"cold_chain_status": "EXCURSION_REVIEW"},
        policy_id="POL-CDC-01",
    )
    # should have EXCURSION_REVIEW uncertainty, but NOT the "no policy" uncertainty
    assert not any(
        "no cold-chain policy profile was referenced" in u.lower()
        for u in result.uncertainties
    )


# ---------------------------------------------------------------------------
# 20: Empty engine_outputs → no uncertainties from those checks
# ---------------------------------------------------------------------------

def test_empty_engine_outputs_produces_no_uncertainties():
    result = _explain(engine_outputs={})
    assert result.uncertainties == []


# ---------------------------------------------------------------------------
# 21: Empty reason_codes raises ValueError
# ---------------------------------------------------------------------------

def test_empty_reason_codes_raises_value_error():
    with pytest.raises(ValueError, match="reason_codes must not be empty"):
        generate_fallback_explanation(
            DecisionRecord(
                shipment_id="SHP-0001",
                disruption_id=None,
                reason_codes=[],
            )
        )


# ---------------------------------------------------------------------------
# 22–23: Return type and JSON serialisability
# ---------------------------------------------------------------------------

def test_return_type_is_explanation_result():
    result = _explain()
    assert isinstance(result, ExplanationResult)


def test_result_is_json_serialisable():
    result = _explain(
        reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
        engine_outputs={"cold_chain_status": "EXCURSION_REVIEW", "route_feasible": False},
        policy_id=None,
    )
    serialised = json.dumps(result.model_dump())
    recovered = json.loads(serialised)
    assert recovered["summary"]
    assert recovered["evidence"] == ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"]


# ---------------------------------------------------------------------------
# Integration-style: canonical preflight scenario
# ---------------------------------------------------------------------------

def test_canonical_preflight_scenario():
    """Mirrors the decision fixture in scripts/preflight_demo.py check_deterministic_fallback."""
    decision = DecisionRecord(
        shipment_id="SHP-0042",
        disruption_id="PORT_STRIKE_01",
        reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
        engine_outputs={
            "cold_chain_status": "EXCURSION_REVIEW",
            "cold_chain_max_celsius": 10.4,
            "cold_chain_policy_max_celsius": 8.0,
            "cold_chain_duration_minutes": 18,
        },
        policy_id=None,
    )
    result = generate_fallback_explanation(decision)

    # schema completeness (preflight CHK-5 assertion)
    assert result.summary
    assert result.why_affected
    assert result.recommended_action
    assert result.evidence
    # uncertainties may be empty only if no cold-chain or route signals; here both present
    assert result.uncertainties

    # evidence == supplied reason codes (no fabrication)
    assert result.evidence == ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"]

    # determinism
    assert generate_fallback_explanation(decision).model_dump() == result.model_dump()

    # no invented values
    assert result.model_used is None
    assert result.generated_by == "deterministic_fallback_template"
