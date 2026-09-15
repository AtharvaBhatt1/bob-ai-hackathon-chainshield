# Task 02 — Synthetic Demo Data

## Objective

Implement the ChainShield synthetic demo data layer so the offline MVP has deterministic local data covering all required demonstration scenarios.

## Files Created or Modified

- `scripts/generate_synthetic_data.py`
- `scripts/seed_demo.py`
- `tests/unit/test_synthetic_data.py`

## Major Implementation Decisions

- `scripts/generate_synthetic_data.py` is the single source of truth for the synthetic demo dataset.
- Added a validated `DEMO_DATASET` containing the required shipment, asset, disruption, cold-chain, sensor, routing, carrier, policy, and supporting entities.
- Added deterministic `build_*()` functions for individual data types.
- Used deterministic synthetic data and UTC-aware timestamps.
- Kept cold-chain thresholds configurable through `PolicyProfile` data rather than hardcoding them into the engine.
- Added CLI validation/output support through `--check` and `--json`.
- `scripts/seed_demo.py` loads the synthetic dataset into an in-memory DuckDB database.
- The seeder validates row counts, referential integrity, and the required seven demo scenario conditions.
- Optional DuckDB absence is handled with `[SKIP]` and exit code `0`, following the existing graceful-degradation pattern.
- `tests/unit/test_synthetic_data.py` adds coverage for the required demo scenarios, integrity, determinism, and integration with the existing excursion-classification logic.

## Canonical Demo Scenario Entities

- Disrupted shipment: `SHP-0042` — route passes through blocked `PORT-03`
- Unaffected shipment: `SHP-0099` — bypasses `PORT-03`
- Idle compatible asset: `TRUCK-17`
- Cold-chain shipment: `SHP-0042` — `refrigerated_vaccine`, `POL-CDC-01`
- Temperature excursion: `SENSOR-9` — 10.4 °C spike, 18 minutes outside the 2–8 °C range, classified as `EXCURSION_REVIEW`
- Feasible rerouting: `CARRIER-B`
- Infeasible routing: `CARRIER-A` — rejected because of reefer incompatibility / `ETA_SLA_BREACH`

## Tests Run

```text
62/62 synthetic data tests passed
123/123 total tests passed

Generator checks: PASS

Seeder:
[SKIP] when DuckDB is unavailable
Exit code: 0

Full test suite:
123/123 passed