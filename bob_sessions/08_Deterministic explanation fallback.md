# Task 08 — Deterministic Explanation Fallback

## Objective

Implement the deterministic offline explanation fallback for ChainShield so structured operational decisions can be converted into human-readable explanations without requiring an LLM or external service.

## Files Created or Modified

- `src/app/explanation/fallback.py`
- `tests/unit/test_fallback_explanation.py`

## Major Implementation Decisions

- Added a strict `DecisionRecord` input contract using a frozen dataclass.
- The explanation layer accepts structured engine results only and does not accept arbitrary free-form operational input.
- Added `generate_fallback_explanation(decision) -> ExplanationResult` as a pure deterministic function.
- Used the supplied `reason_codes` to construct the explanation.
- Mapped known reason codes to predefined explanation phrases.
- Preserved unknown reason codes instead of inventing new operational meaning.
- Generated recommended actions only from the reason codes and predefined action hints.
- Copied the supplied reason codes into the evidence output to preserve the audit trail.
- Derived uncertainty statements only from structured engine outputs and policy availability.
- Added validation so an empty `reason_codes` list raises `ValueError`.
- Kept the fallback independent of external APIs, LLMs, and network access.
- Ensured identical structured input produces identical output.

## Tests Run

```text
29 deterministic fallback tests
300 total tests

Test Results
29/29 fallback tests passed

300/300 total tests passed