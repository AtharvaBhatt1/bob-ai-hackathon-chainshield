# 15_application_logging.md

```md
# Point 30 — Application Logging

## Objective

Add lightweight structured application logging to the ChainShield demo so important runtime events can be observed without changing business logic or exposing secrets.

## Files Created or Modified

- `src/app/core/logging.py`
- `src/app/api/main.py`
- `src/app/api/routers/disruptions.py`
- `src/app/api/routers/assets.py`
- `src/app/api/routers/cold_chain.py`
- `src/app/api/routers/explanations.py`
- `src/app/api/routers/action_plan.py`
- `src/app/evidence/events.py`

## Major Implementation Decisions

- Added a lightweight standard-library structured logger.
- Log records are emitted as one JSON object per line.
- Added idempotent `configure_logging()` and `get_logger(name)`.
- Added configurable `LOG_LEVEL`, defaulting to `INFO`.
- Added runtime events for:
  - startup
  - readiness
  - shutdown
  - disruption activation
  - affected shipment count
  - cargo value at risk
  - idle assets
  - cold-chain classification
  - explanation generation
  - watsonx failure/fallback
  - route alternatives
  - idle-asset matching
  - action-plan export
  - evidence creation
- Logging avoids API keys, passwords, access tokens, personal information, and confidential data.
- No business logic was changed.

## Validation

A logging smoke test confirmed that runtime records are emitted as clean JSON lines.

## Tests Run

```text
345 total tests
Preflight validation
Structured logging smoke test