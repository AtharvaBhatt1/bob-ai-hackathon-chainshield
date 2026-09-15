# 14_offline_hardening.md

```md
# Point 29 — Offline Hardening

## Objective

Verify and harden ChainShield for true offline demo operation using local data and deterministic logic, with no external service required for the critical demo path.

## Files Created or Modified

- `src/web/src/api/types.ts`
- `src/web/src/api/demo.ts`
- `src/web/src/components/ActionCenter.tsx`
- `src/.env.example`

## Major Implementation Decisions

- Verified the required offline configuration:
  - `DEMO_MODE=true`
  - `WATSONX_ENABLED=false`
  - `NETWORK_REQUIRED=false`
- Verified that the critical demo path uses local DuckDB, local synthetic data, local route graph data, deterministic domain logic, and deterministic fallback explanation.
- Confirmed that watsonx.ai is optional and does not block the operational result.
- Confirmed that Cloudant, live routing APIs, external datasets, and external map downloads are not required for the critical offline path.
- Verified that OR-Tools is optional and guarded through lazy import/dependency handling.
- Identified and fixed a frontend/backend `ExplanationResult` type mismatch.
- Updated the frontend explanation types to match the actual backend schema.
- Updated frontend demo explanation data to match the deterministic fallback output.
- Updated `ActionCenter` to correctly render explanation arrays and determine offline/Granite status from the actual backend response.
- Updated `src/.env.example` with explicit offline defaults and clarified unused external-service variables.

## Validation Results

```text
DEMO_MODE=true
WATSONX_ENABLED=false
NETWORK_REQUIRED=false

Preflight: 5/5 checks passed
Backend tests: 345/345 passed
TypeScript type check: PASS
Frontend build: PASS