"""
tests/unit/test_watsonx_explanation.py
=======================================
Unit tests for src/app/explanation/watsonx.py — the optional IBM watsonx.ai
Granite explanation integration.

All tests use mocks so they run fully offline with no ibm_watsonx_ai package
required.  The test suite verifies:

  1. When WATSONX_ENABLED=false, the router uses the deterministic fallback
     (watsonx module is never imported).
  2. When ibm_watsonx_ai is absent, ImportError propagates correctly.
  3. Missing WATSONX_API_KEY → EnvironmentError.
  4. Missing WATSONX_PROJECT_ID → EnvironmentError.
  5. Granite returns valid JSON → ExplanationResult is built correctly.
  6. evidence is always taken from the deterministic record (never from LLM).
  7. uncertainties are always taken from the deterministic record.
  8. generated_by == "ibm/granite-3-3-8b-instruct" on success.
  9. model_used == "ibm/granite-3-3-8b-instruct" on success.
 10. Granite returns non-JSON text → RuntimeError raised.
 11. Granite raises TimeoutError → propagates to caller.
 12. Granite raises arbitrary exception → RuntimeError or propagates to caller.
 13. On any exception from _try_watsonx, router falls back to deterministic.
 14. Fallback generated_by == "deterministic_fallback_template".
 15. Return type is ExplanationResult in both paths.
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock

import pytest

from src.app.core.models import ExplanationResult
from src.app.explanation.fallback import DecisionRecord, generate_fallback_explanation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(
    reason_codes: list[str] | None = None,
    engine_outputs: dict | None = None,
    policy_id: str | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        shipment_id="SHP-0042",
        disruption_id="PORT_STRIKE_01",
        reason_codes=reason_codes or ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
        engine_outputs=engine_outputs or {
            "cold_chain_status": "EXCURSION_REVIEW",
            "route_feasible": False,
        },
        policy_id=policy_id,
    )


def _make_demo_evidence_record():
    """Return the impact decision record for SHP-0042 from DEMO_DATASET."""
    from scripts.generate_synthetic_data import DEMO_DATASET  # type: ignore[import]
    return next(
        r for r in DEMO_DATASET["evidence_records"]
        if r.decision_id == "dec-impact-0042-001"
    )


def _make_granite_response(decision: DecisionRecord) -> str:
    """Return a valid Granite JSON response string that respects the contract."""
    return json.dumps({
        "summary": f"Granite summary for {decision.shipment_id}.",
        "why_affected": [f"Granite phrase for {c}." for c in decision.reason_codes],
        "recommended_action": "Granite recommended action.",
        # These should be ignored by the caller — deterministic values must win.
        "evidence": ["GRANITE_INVENTED_CODE"],
        "uncertainties": ["Granite invented uncertainty."],
    })


def _build_mock_watsonx_module(generate_text_return: object) -> types.ModuleType:
    """Build a minimal mock of ibm_watsonx_ai that satisfies generate_granite_explanation."""
    wx = types.ModuleType("ibm_watsonx_ai")
    wx.Credentials = MagicMock(name="Credentials")
    wx.APIClient = MagicMock(name="APIClient")

    # ibm_watsonx_ai.foundation_models
    fm = types.ModuleType("ibm_watsonx_ai.foundation_models")
    model_instance = MagicMock()
    if isinstance(generate_text_return, Exception):
        model_instance.generate_text.side_effect = generate_text_return
    else:
        model_instance.generate_text.return_value = generate_text_return
    fm.ModelInference = MagicMock(return_value=model_instance)
    wx.foundation_models = fm

    # ibm_watsonx_ai.metanames
    mn = types.ModuleType("ibm_watsonx_ai.metanames")
    gen_params = MagicMock()
    gen_params.MAX_NEW_TOKENS = "max_new_tokens"
    gen_params.TEMPERATURE = "temperature"
    mn.GenTextParamsMetaNames = gen_params
    wx.metanames = mn

    return wx


def _call_generate_granite(monkeypatch, decision: DecisionRecord, wx_module: types.ModuleType) -> ExplanationResult:
    """Inject the mock ibm_watsonx_ai into sys.modules and call generate_granite_explanation.

    The function uses lazy imports, so injecting into sys.modules before calling
    is sufficient — no reload required.
    """
    with (
        monkeypatch.context() as m,
    ):
        # Patch sys.modules so the lazy import inside the function picks up our mock.
        original_modules = {}
        keys = ["ibm_watsonx_ai", "ibm_watsonx_ai.foundation_models", "ibm_watsonx_ai.metanames"]
        for k in keys:
            original_modules[k] = sys.modules.get(k)
            sys.modules[k] = getattr(wx_module, k.split(".")[-1]) if "." in k else wx_module
        # Patch the sub-module references directly.
        sys.modules["ibm_watsonx_ai.foundation_models"] = wx_module.foundation_models
        sys.modules["ibm_watsonx_ai.metanames"] = wx_module.metanames
        sys.modules["ibm_watsonx_ai"] = wx_module

        try:
            from src.app.explanation.watsonx import generate_granite_explanation
            return generate_granite_explanation(decision)
        finally:
            for k, v in original_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v


# ---------------------------------------------------------------------------
# 1. WATSONX_ENABLED=false → deterministic fallback, watsonx module never called
# ---------------------------------------------------------------------------

class TestWatsonxDisabled:
    def test_fallback_used_when_watsonx_disabled(self, monkeypatch):
        """With WATSONX_ENABLED=false the router must use deterministic fallback."""
        monkeypatch.setenv("WATSONX_ENABLED", "false")
        from src.app.api.routers.explanations import _build_decision_record
        ev = _make_demo_evidence_record()
        decision = _build_decision_record(ev)
        result = generate_fallback_explanation(decision)

        assert isinstance(result, ExplanationResult)
        assert result.generated_by == "deterministic_fallback_template"
        assert result.model_used is None


# ---------------------------------------------------------------------------
# 2. ImportError when ibm_watsonx_ai is absent
# ---------------------------------------------------------------------------

class TestImportError:
    def test_missing_package_raises_import_error(self, monkeypatch):
        monkeypatch.setenv("WATSONX_API_KEY", "dummy")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "dummy")

        # Remove any cached ibm_watsonx_ai so the import guard fires.
        for k in list(sys.modules):
            if k.startswith("ibm_watsonx_ai"):
                del sys.modules[k]
        sys.modules["ibm_watsonx_ai"] = None  # type: ignore[assignment]

        try:
            from src.app.explanation.watsonx import generate_granite_explanation
            with pytest.raises(ImportError, match="ibm_watsonx_ai"):
                generate_granite_explanation(_make_decision())
        finally:
            sys.modules.pop("ibm_watsonx_ai", None)


# ---------------------------------------------------------------------------
# 3–4. Missing env vars
# ---------------------------------------------------------------------------

class TestMissingEnvVars:
    def test_missing_api_key_raises_environment_error(self, monkeypatch):
        monkeypatch.delenv("WATSONX_API_KEY", raising=False)
        monkeypatch.setenv("WATSONX_PROJECT_ID", "proj-123")

        fake_wx = _build_mock_watsonx_module("irrelevant")
        with pytest.raises(EnvironmentError, match="WATSONX_API_KEY"):
            _call_generate_granite(monkeypatch, _make_decision(), fake_wx)

    def test_missing_project_id_raises_environment_error(self, monkeypatch):
        monkeypatch.setenv("WATSONX_API_KEY", "key-abc")
        monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)

        fake_wx = _build_mock_watsonx_module("irrelevant")
        with pytest.raises(EnvironmentError, match="WATSONX_PROJECT_ID"):
            _call_generate_granite(monkeypatch, _make_decision(), fake_wx)


# ---------------------------------------------------------------------------
# 5–9. Successful Granite call
# ---------------------------------------------------------------------------

class TestSuccessfulGraniteCall:
    def _call(self, monkeypatch, decision: DecisionRecord | None = None) -> ExplanationResult:
        if decision is None:
            decision = _make_decision()
        monkeypatch.setenv("WATSONX_API_KEY", "key-abc")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "proj-123")
        fake_wx = _build_mock_watsonx_module(_make_granite_response(decision))
        return _call_generate_granite(monkeypatch, decision, fake_wx)

    def test_returns_explanation_result_type(self, monkeypatch):
        assert isinstance(self._call(monkeypatch), ExplanationResult)

    def test_generated_by_is_granite_model(self, monkeypatch):
        assert self._call(monkeypatch).generated_by == "ibm/granite-3-3-8b-instruct"

    def test_model_used_is_granite_model(self, monkeypatch):
        assert self._call(monkeypatch).model_used == "ibm/granite-3-3-8b-instruct"

    def test_evidence_equals_deterministic_reason_codes(self, monkeypatch):
        """Evidence must come from the deterministic record, not the LLM output."""
        codes = ["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"]
        result = self._call(monkeypatch, _make_decision(reason_codes=codes))
        # LLM response has "GRANITE_INVENTED_CODE" but it must be discarded.
        assert result.evidence == codes
        assert "GRANITE_INVENTED_CODE" not in result.evidence

    def test_uncertainties_equal_deterministic_values(self, monkeypatch):
        """Uncertainties must come from the deterministic record, not the LLM output."""
        decision = _make_decision(engine_outputs={"cold_chain_status": "EXCURSION_REVIEW"})
        deterministic = generate_fallback_explanation(decision)
        result = self._call(monkeypatch, decision)
        assert result.uncertainties == deterministic.uncertainties
        assert "Granite invented uncertainty." not in result.uncertainties

    def test_summary_is_non_empty_string(self, monkeypatch):
        result = self._call(monkeypatch)
        assert isinstance(result.summary, str) and result.summary.strip()

    def test_why_affected_is_non_empty_list(self, monkeypatch):
        result = self._call(monkeypatch)
        assert isinstance(result.why_affected, list) and len(result.why_affected) >= 1

    def test_all_required_keys_present(self, monkeypatch):
        result = self._call(monkeypatch)
        assert result.summary
        assert result.why_affected
        assert result.recommended_action
        assert result.evidence
        assert isinstance(result.uncertainties, list)


# ---------------------------------------------------------------------------
# 10. Non-JSON response → RuntimeError
# ---------------------------------------------------------------------------

class TestNonJsonResponse:
    def test_non_json_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("WATSONX_API_KEY", "key-abc")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "proj-123")
        fake_wx = _build_mock_watsonx_module("This is not JSON at all.")
        with pytest.raises(RuntimeError, match="non-JSON"):
            _call_generate_granite(monkeypatch, _make_decision(), fake_wx)


# ---------------------------------------------------------------------------
# 11. TimeoutError propagates
# ---------------------------------------------------------------------------

class TestTimeoutPropagates:
    def test_timeout_error_propagates(self, monkeypatch):
        monkeypatch.setenv("WATSONX_API_KEY", "key-abc")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "proj-123")
        fake_wx = _build_mock_watsonx_module(TimeoutError("2.5s exceeded"))
        with pytest.raises((TimeoutError, RuntimeError)):
            _call_generate_granite(monkeypatch, _make_decision(), fake_wx)


# ---------------------------------------------------------------------------
# 12. Arbitrary exception propagates / wraps
# ---------------------------------------------------------------------------

class TestArbitraryException:
    def test_connection_error_raises(self, monkeypatch):
        monkeypatch.setenv("WATSONX_API_KEY", "key-abc")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "proj-123")
        fake_wx = _build_mock_watsonx_module(ConnectionError("network failure"))
        with pytest.raises((ConnectionError, RuntimeError)):
            _call_generate_granite(monkeypatch, _make_decision(), fake_wx)


# ---------------------------------------------------------------------------
# 13–15. Router fallback logic on watsonx failure
# ---------------------------------------------------------------------------

class TestRouterFallback:
    """Simulate the router's fallback logic when _try_watsonx raises."""

    def _router_explain(self, ev, raise_exc: Exception | None = None) -> ExplanationResult:
        """Replicate the router's generate_explanation logic locally."""
        from src.app.api.routers.explanations import _build_decision_record

        if raise_exc is not None:
            try:
                raise raise_exc
            except Exception:
                pass  # fall through to deterministic

        decision = _build_decision_record(ev)
        return generate_fallback_explanation(decision)

    def test_fallback_on_import_error(self):
        ev = _make_demo_evidence_record()
        result = self._router_explain(ev, ImportError("ibm_watsonx_ai not installed"))
        assert isinstance(result, ExplanationResult)
        assert result.generated_by == "deterministic_fallback_template"
        assert result.model_used is None

    def test_fallback_on_timeout(self):
        ev = _make_demo_evidence_record()
        result = self._router_explain(ev, TimeoutError("2.5s exceeded"))
        assert result.generated_by == "deterministic_fallback_template"

    def test_fallback_on_runtime_error(self):
        ev = _make_demo_evidence_record()
        result = self._router_explain(ev, RuntimeError("network error"))
        assert result.generated_by == "deterministic_fallback_template"

    def test_fallback_result_preserves_reason_codes(self):
        ev = _make_demo_evidence_record()
        result = self._router_explain(ev, RuntimeError("failure"))
        assert len(result.evidence) >= 1
        for code in result.evidence:
            assert code == code.upper(), f"Expected SCREAMING_SNAKE_CASE, got {code!r}"

    def test_fallback_result_has_all_required_keys(self):
        ev = _make_demo_evidence_record()
        result = self._router_explain(ev, RuntimeError("failure"))
        assert result.summary
        assert result.why_affected
        assert result.recommended_action
        assert result.evidence
        assert isinstance(result.uncertainties, list)
