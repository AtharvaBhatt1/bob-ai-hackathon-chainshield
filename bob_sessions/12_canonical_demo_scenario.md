# 12_canonical_demo_scenario.md

```md
# Point 27 — Canonical Demo Scenario

## Objective

Create and verify one reproducible ChainShield offline demonstration scenario that exercises all seven required functions in one connected workflow.

## Files Created or Modified

- `scripts/__init__.py`
- `scripts/generate_synthetic_data.py`
- Additional files modified as required by the existing tests and demo integration
- Temporary smoke-test files were removed after validation

## Major Implementation Decisions

- Created a deterministic synthetic dataset as the source of truth for the canonical demo scenario.
- Used deterministic IDs and fixed decision IDs so repeated runs are reproducible.
- Added the required dataset components:
  - route graph
  - policies
  - disruptions
  - shipments
  - shipment legs
  - assets
  - sensor readings
  - route alternatives
  - evidence records
- The canonical scenario includes:
  - disrupted shipment `SHP-0042`
  - unaffected shipment `SHP-0099`
  - active disruption `PORT_STRIKE_01`
  - compatible idle asset `TRUCK-17`
  - cold-chain policy `POL-CDC-01`
  - ambient policy `POL-AMBIENT-01`
  - temperature excursion sensor data
  - feasible and infeasible routing alternatives
  - evidence records with deterministic decision IDs
- Added additional dataset records required by existing database tests.
- Preserved configurable cold-chain policy behavior.
- Kept the scenario fully local and deterministic.
- Did not introduce live external services.

## Seven Required Functions Demonstrated

1. Identify shipments affected by an active disruption
2. Recommend rerouting options
3. Recommend carrier alternatives
4. Identify idle fleet assets for redeployment
5. Monitor cold-chain sensor logs
6. Detect temperature excursions before delivery
7. Classify excursion severity using a configurable policy

## Tests Run

```text
Full test suite
Preflight validation
API end-to-end smoke test