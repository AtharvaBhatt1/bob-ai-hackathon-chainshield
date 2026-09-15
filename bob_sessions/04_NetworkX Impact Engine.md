# Task 04 — NetworkX Impact Engine

## Objective

Implement the deterministic ChainShield Impact Engine for identifying shipments affected by active disruptions and calculating the resulting cargo value at risk and reason codes.

## Files Created or Modified

- `src/app/impact/__init__.py`
- `src/app/impact/engine.py`
- `tests/unit/test_impact_engine.py`

## Major Implementation Decisions

- Implemented the Impact Engine as deterministic logic with no randomness or time-dependent behavior.
- Added route intersection checks for blocked nodes.
- Added route intersection checks for blocked edges using consecutive route pairs.
- Treated blocked edges as undirected using `frozenset`.
- Implemented shipment/disruption time-window overlap detection.
- A shipment is classified as affected only when the route is blocked and the disruption window overlaps the shipment window.
- Calculated total cargo value at risk using affected shipments only.
- Added ETA/SLA breach detection based on planned arrival, delay, and delivery deadline.
- Added the documented reason codes:
  - `PORT_NODE_BLOCKED`
  - `ROUTE_EDGE_BLOCKED`
  - `ETA_SLA_BREACH`
  - `TEMPERATURE_EXPOSURE_INCREASED`
- Kept the engine independent of LLMs and live routing services.
- Added deterministic unit-test coverage for route impact, time overlap, SLA breach, reason codes, and edge cases.

## Tests Run

```text
26 tests


Test Results:-
26/26 passed

