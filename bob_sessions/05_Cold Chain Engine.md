# Task 05 — Cold Chain Policy Engine

## Objective

Implement the deterministic ChainShield Cold Chain Engine for monitoring temperature readings, detecting excursions, calculating excursion metrics, detecting missing sensor windows, and classifying severity using configurable policy rules.

## Files Created or Modified

- `src/app/cold_chain/engine.py`
- `tests/unit/test_cold_chain.py`

## Major Implementation Decisions

- Implemented the cold-chain classification logic as deterministic processing with no LLM dependency.
- Added a single public `classify_excursion(policy, readings)` function.
- Kept all temperature thresholds and severity rules in the supplied policy rather than hardcoding them into the engine.
- Added minimum and maximum temperature calculation.
- Added out-of-range reading count.
- Added cumulative excursion duration.
- Added maximum continuous excursion duration.
- Added missing sensor-window detection.
- Used the documented `2–8 °C` policy for the primary demo scenario while keeping the engine configurable.
- Treated return-to-normal after a confirmed excursion as not automatically SAFE.
- Checked `POLICY_REQUIRED` before normal classification when no policy profile is available.
- Preserved deterministic and reproducible results for identical policy/readings input.

## Evidence Produced

The evidence output contains the cold-chain metrics required by the implementation, including:

- `min_c`
- `max_c`
- `out_of_range_count`
- `cumulative_excursion_minutes`
- `max_continuous_excursion_minutes`
- `missing_windows`

Error cases provide an appropriate `reason` field.

## Tests Run

```text
29 tests

Test Results
29/29 passed