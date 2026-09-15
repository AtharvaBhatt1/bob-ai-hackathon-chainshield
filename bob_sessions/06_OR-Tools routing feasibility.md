# Task 06 — Route Optimizer

## Objective

Implement the deterministic ChainShield route-feasibility and optimization component using the cached/local route graph and Google OR-Tools.

## Files Created or Modified

- `src/app/optimization/engine.py`
- `src/app/optimization/__init__.py`
- `tests/unit/test_optimization.py`

## Major Implementation Decisions

- Implemented deterministic route-feasibility logic with no LLM dependency and no live routing API.
- Removed edges and nodes affected by time-overlapping disruptions before route enumeration.
- Enumerated candidate paths from the local graph using NetworkX.
- Added hard-constraint validation for:
  - capacity
  - reefer capability
  - mode compatibility
  - carrier availability
  - delivery deadline
- Prevented disrupted edges and nodes from being selected as valid routes.
- Added human-readable rejection reasons and deterministic reason codes.
- Used OR-Tools CP-SAT to verify carrier assignment uniqueness for the final selection.
- Added deterministic ranking and stable tie-breaking for feasible route alternatives.
- Added handling for no-path and optimization-dependency-unavailable cases.
- Added a canonical offline fixture containing multiple carrier types and confirmed that the fixture can produce at least 3 feasible alternatives when conditions allow.
- Kept the implementation independent of the frontend and external services.

## Hard Constraints Covered

- `CAPACITY_EXCEEDED`
- `REEFER_REQUIRED`
- `MODE_INCOMPATIBLE`
- `CARRIER_UNAVAILABLE`
- `DEADLINE_BREACH`
- `DISRUPTED_EDGE`
- `DISRUPTED_NODE`

Each constraint has both positive and rejection test coverage.

## Testing and Validation

Initial test execution exposed one fixture issue in the mode-compatibility scenario. The fixture was corrected so the test exercises the intended alternative-path behavior.

## Tests Run

```text
37 route-optimization tests
251 total tests
Preflight validation

Test Results
37/37 route-optimization tests passed

251/251 total tests passed

Preflight: PASS
