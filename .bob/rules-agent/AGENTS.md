# Project Coding Rules (Non-Obvious Only)

This file provides guidance to agents when working with code in this repository.

## Implementation Rules

- **Cold-chain classifier signature:** `classify_excursion(policy: dict | None, readings: list[dict]) -> tuple[str, dict]`. Returns `(severity_string, evidence_dict)`. When `policy` is `None` → return `"POLICY_REQUIRED"`. When `readings` is empty → return `policy["severity_rules"]["missing_sensor_data"]`. Never hardcode threshold values inside the function.

- **Fallback explanation schema** (required keys): `summary`, `why_affected`, `recommended_action`, `evidence`, `uncertainties`. Adding Granite output must preserve all five keys — the preflight CHK-5 asserts on them.

- **OR-Tools imports are guarded:** Always wrap `from ortools.sat.python import cp_model` in `try/except ImportError` and return `(SKIP, ["DEPENDENCY_MISSING"], ...)` — never let a missing optional dep crash the whole run.

- **DuckDB usage is in-memory for tests:** Use `duckdb.connect(database=":memory:")`. Do not write to disk in test/preflight code.

- **Preflight report path** defaults to `reports/preflight_report.json`. The parent directory is auto-created via `Path.mkdir(parents=True, exist_ok=True)` — do not pre-create it manually.

- **Watsonx.ai timeout is 2.5 seconds** (hard limit). Any call to the explanation layer must have `timeout=2.5` and fall back to `generate_fallback_explanation()`.

- **Reason codes are SCREAMING_SNAKE_CASE strings** (e.g. `PORT_NODE_BLOCKED`, `ETA_SLA_BREACH`, `REEFER_CAPACITY_AVAILABLE`). Invent new ones following the same pattern; never use free-text in the `reason_codes` field.

- **API entry point:** `app.api.main:app` (uvicorn). Frontend lives in `web/`.

- **`scripts/preflight_demo.py` is the canonical reference implementation** for all five core engines. When implementing the real backend, match the logic in the corresponding `check_*` functions exactly.
