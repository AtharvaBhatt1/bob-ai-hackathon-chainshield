"""
src/app/explanation/watsonx.py
===============================
Optional IBM watsonx.ai / Granite explanation integration for ChainShield.

Design constraints (from AGENTS.md)
-------------------------------------
- ``ibm_watsonx_ai`` is an optional dependency — import is guarded by
  ``try/except ImportError``.  When absent the caller falls back immediately.
- The deterministic result is **always computed first**.  This module only
  narrows that result into natural language — it never makes operational
  decisions.
- Timeout is hard-capped at **2.5 seconds**.  Any exception (timeout, network
  error, bad response, missing dep) propagates to the caller, which then uses
  :func:`~src.app.explanation.fallback.generate_fallback_explanation`.
- ``WATSONX_ENABLED=false`` is the safe offline default.  This module is
  only imported when the caller has already confirmed ``WATSONX_ENABLED=true``.
- Reason codes, evidence, and uncertainties are **copied verbatim** from the
  :class:`~src.app.explanation.fallback.DecisionRecord` into the prompt and
  into the returned :class:`~src.app.core.models.ExplanationResult`.  The LLM
  may rephrase the prose fields (``summary``, ``why_affected``,
  ``recommended_action``) but must never alter the structured fields.
- ``generated_by`` is set to ``"granite-3-3-8b-instruct"`` on success.
- ``model_used`` is set to the model identifier string on success.

Prompt design
-------------
The prompt gives Granite a structured JSON blob (the deterministic output)
and asks it to return a JSON object with the same five keys.  The structured
fields (``evidence``, ``uncertainties``) are pre-populated from the
deterministic record so they are never subject to hallucination.
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.explanation.fallback import DecisionRecord
    from src.app.core.models import ExplanationResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WATSONX_TIMEOUT = 2.5  # seconds — hard project limit
_MODEL_ID = "ibm/granite-3-3-8b-instruct"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(decision: "DecisionRecord", deterministic: "ExplanationResult") -> str:
    """Build a structured prompt for Granite.

    The deterministic result is passed as context so Granite has the full
    picture.  Reason codes and evidence are stated explicitly so the model
    cannot invent different values.  The model is instructed to return a JSON
    object containing only the five prose fields — structured fields are
    injected by the caller after parsing.
    """
    context = {
        "shipment_id": decision.shipment_id,
        "disruption_id": decision.disruption_id,
        "reason_codes": decision.reason_codes,
        "engine_outputs": decision.engine_outputs,
        "policy_id": decision.policy_id,
        "deterministic_summary": deterministic.summary,
        "deterministic_why_affected": deterministic.why_affected,
        "deterministic_recommended_action": deterministic.recommended_action,
        "deterministic_uncertainties": deterministic.uncertainties,
    }

    return (
        "You are a supply-chain operations assistant. "
        "You are given a structured decision record produced by a deterministic "
        "logistics engine. Your task is to rephrase the deterministic explanation "
        "into clear, concise, operator-facing language. "
        "You must NOT invent new reason codes, route options, temperatures, "
        "carrier names, or regulatory claims. "
        "You must NOT change any operational decision — your role is explanation only.\n\n"
        f"DECISION RECORD (JSON):\n{json.dumps(context, indent=2)}\n\n"
        "Respond ONLY with a valid JSON object containing these five keys:\n"
        '  "summary": one sentence describing the situation\n'
        '  "why_affected": array of strings — one entry per reason code, '
        "paraphrasing the deterministic_why_affected phrases\n"
        '  "recommended_action": one sentence summarising the recommended action\n'
        '  "evidence": array — MUST equal the reason_codes list above, unchanged\n'
        '  "uncertainties": array — MUST equal the deterministic_uncertainties list above, unchanged\n\n'
        "Respond with JSON only. No markdown fences, no prose outside the JSON."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_granite_explanation(decision: "DecisionRecord") -> "ExplanationResult":
    """Call watsonx.ai Granite to produce a natural-language explanation.

    Parameters
    ----------
    decision:
        Structured evidence record from the deterministic engines.

    Returns
    -------
    ExplanationResult
        Schema-complete explanation with ``generated_by="granite-3-3-8b-instruct"``.

    Raises
    ------
    ImportError
        When ``ibm_watsonx_ai`` is not installed.
    RuntimeError
        When the watsonx.ai call fails, times out, or returns invalid JSON.
    EnvironmentError
        When required environment variables are missing.
    """
    # Guard: lazy import so missing dep never crashes offline runs.
    try:
        from ibm_watsonx_ai import APIClient, Credentials  # type: ignore[import]
        from ibm_watsonx_ai.foundation_models import ModelInference  # type: ignore[import]
        from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("ibm_watsonx_ai is not installed — cannot use Granite") from exc

    api_key = os.environ.get("WATSONX_API_KEY", "")
    project_id = os.environ.get("WATSONX_PROJECT_ID", "")
    url = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

    if not api_key or not project_id:
        raise EnvironmentError(
            "WATSONX_API_KEY and WATSONX_PROJECT_ID must be set when WATSONX_ENABLED=true"
        )

    # Produce the deterministic result first — used as context in the prompt
    # and as the authoritative source for structured fields.
    from src.app.explanation.fallback import generate_fallback_explanation  # noqa: PLC0415
    from src.app.core.models import ExplanationResult  # noqa: PLC0415

    deterministic = generate_fallback_explanation(decision)
    prompt = _build_prompt(decision, deterministic)

    credentials = Credentials(url=url, api_key=api_key)
    client = APIClient(credentials)

    model = ModelInference(
        model_id=_MODEL_ID,
        api_client=client,
        project_id=project_id,
        params={
            GenParams.MAX_NEW_TOKENS: 512,
            GenParams.TEMPERATURE: 0,  # deterministic output
        },
    )

    # Hard timeout enforced here — the library itself does not guarantee it.
    import signal  # noqa: PLC0415

    def _timeout_handler(signum: int, frame: object) -> None:
        raise TimeoutError(f"watsonx.ai call exceeded {_WATSONX_TIMEOUT}s timeout")

    # signal.SIGALRM is only available on POSIX; fall back to threading on Windows.
    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, _WATSONX_TIMEOUT)
        use_signal = True
    except AttributeError:
        use_signal = False

    if not use_signal:
        import threading  # noqa: PLC0415
        timeout_event = threading.Event()

        def _run_generate(result_holder: list) -> None:
            try:
                result_holder.append(model.generate_text(prompt=prompt))
            except Exception as exc:  # noqa: BLE001
                result_holder.append(exc)

        holder: list = []
        t = threading.Thread(target=_run_generate, args=(holder,), daemon=True)
        t.start()
        t.join(timeout=_WATSONX_TIMEOUT)
        if not holder:
            raise TimeoutError(f"watsonx.ai call exceeded {_WATSONX_TIMEOUT}s timeout")
        raw_text = holder[0]
        if isinstance(raw_text, Exception):
            raise RuntimeError(f"watsonx.ai generate failed: {raw_text}") from raw_text
    else:
        try:
            raw_text = model.generate_text(prompt=prompt)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

    # Parse JSON response.
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Granite returned non-JSON response: {raw_text[:200]!r}"
        ) from exc

    # Structural fields are ALWAYS taken from the deterministic record —
    # the model output for these keys is discarded to prevent hallucination.
    return ExplanationResult(
        summary=str(parsed.get("summary") or deterministic.summary),
        why_affected=list(parsed.get("why_affected") or deterministic.why_affected),
        recommended_action=str(
            parsed.get("recommended_action") or deterministic.recommended_action
        ),
        # evidence and uncertainties: authoritative source is deterministic record only.
        evidence=list(deterministic.evidence),
        uncertainties=list(deterministic.uncertainties),
        generated_by=_MODEL_ID,
        model_used=_MODEL_ID,
    )
