# Point 36 — Optional watsonx.ai / Granite Integration

## Objective

Implement the optional IBM watsonx.ai / Granite explanation integration while preserving the deterministic operational result and ensuring the existing deterministic fallback remains available whenever watsonx.ai is unavailable.

## Files Created or Modified

- `src/app/explanation/watsonx.py`
- `src/app/api/routers/explanations.py`
- `tests/unit/test_watsonx_explanation.py`

## Major Implementation Decisions

- Added a dedicated watsonx.ai integration module under `src/app/explanation/`.
- Kept the watsonx.ai import lazy and guarded against `ImportError`.
- Generated the deterministic explanation first from the structured `DecisionRecord`.
- Passed the structured decision data and deterministic result to Granite as explanation context.
- Limited Granite to explanation/prose generation rather than operational decision-making.
- Preserved deterministic `evidence` and `uncertainties` after the model response.
- Preserved reason-code-driven operational truth.
- Added a hard 2.5-second timeout for the watsonx explanation attempt.
- Allowed timeout, network, malformed-response, missing-package, and configuration failures to propagate to the existing router fallback.
- Kept `WATSONX_ENABLED=false` as the safe offline default.
- Preserved the deterministic fallback whenever watsonx.ai is unavailable.

## Verified Requirements

- Structured deterministic input passed to explanation layer: PASS
- Reason codes preserved: PASS
- Evidence preserved: PASS
- Uncertainties preserved: PASS
- LLM does not create or change operational decisions: PASS
- Timeout/failure returns deterministic fallback: PASS
- `WATSONX_ENABLED=false` works fully offline: PASS

## Tests Run

```text
20 new watsonx integration tests
Full test suite
Preflight validation