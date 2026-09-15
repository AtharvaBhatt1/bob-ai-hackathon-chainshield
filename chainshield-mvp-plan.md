# ChainShield Offline MVP — Implementation Plan

## Goal

Implement the ChainShield offline MVP so that `scripts/preflight_demo.py` passes all five checks and
the end-to-end demo scenario (disruption activation → impact → alternatives → cold-chain → explanation → export)
runs fully with `DEMO_MODE=true WATSONX_ENABLED=false NETWORK_REQUIRED=false`.

## Scope

- All backend source lives under `src/app/`.
- All frontend source lives under `src/web/`.
- No new technologies beyond the declared stack.
- No watsonx.ai calls required for any test or demo run.
- Every sub-task is independently testable before the next begins.

## Sub-Task Ordering

```
ST-01 → ST-02 → ST-03 → ST-04 → ST-05 → ST-06 → ST-07 → ST-08 → ST-09 → ST-10
schemas   DB     impact  optim  cold    explain  audit   api    frontend  tests
```

---

## ST-01 — Synthetic Data, Pydantic Schemas, and Seed Fixtures

**Status:** [ ] pending

### Intent
Define the canonical data contracts for every entity the system touches.
All downstream modules import from this layer — nothing else owns schemas.
Seed fixtures provide the demo scenario used by every other sub-task.

### Expected Outcomes
- Pydantic models exist for: `Shipment`, `Asset`, `SensorReading`, `Disruption`, `PolicyProfile`, `RouteGraph`, `EvidenceRecord`, `ExplanationResult`, `ActionPlan`.
- Synthetic fixture files (Parquet or JSON) exist for the reference scenario:
  - 10+ shipments including `SHP-0042` (reefer, vaccine, route through `PORT-03`).
  - 5+ assets including `TRUCK-17` (reefer-capable, available at `HUB-B`).
  - Sensor log for `SHP-0042`: 5 readings, timestamps 08:00–08:24, spanning 2–10.4°C.
  - One disruption: `PORT_STRIKE_01` blocking `PORT-03`, window `2026-09-14` to `2026-09-17`.
  - One policy profile: `POL-CDC-01` (2–8°C, sample interval 6 min, `out_of_range → EXCURSION_REVIEW`).
  - Route graph: hubs `HUB-A`, `HUB-B`, `PORT-03`, `HUB-D` with edges matching the preflight graph.
- All fixtures validate cleanly against Pydantic models.
- A `load_fixtures()` function returns all entities in typed form.

### Todo List
- [ ] Create `src/app/schemas/` package with one file per entity type.
- [ ] Define each Pydantic model with field names matching the DuckDB column names in the preflight script (shipment_id, cargo_type, temperature_policy_id, etc.).
- [ ] Create `src/app/data/fixtures/` directory.
- [ ] Write seed data for shipments, assets, sensor readings, disruptions, policy profiles, and route graph as JSON files.
- [ ] Write `src/app/data/loader.py` with `load_fixtures() -> FixtureBundle` (typed dataclass of all entities).
- [ ] Validate fixtures against schemas in a pytest smoke test.

### Relevant Context
- DuckDB table columns: see `scripts/preflight_demo.py` lines 121–167 (CREATE TABLE statements).
- Reference scenario data: preflight lines 169–190 (INSERT statements) and cold-chain readings lines 181–189.
- Pydantic is already used for the Cold Chain Engine (see `docs/architecture.md` component table).

---

## ST-02 — DuckDB Initialization and Data Access Layer

**Status:** [ ] pending

### Intent
Create a single DuckDB connection manager that initialises the schema, seeds the demo data,
and exposes typed query helpers used by every engine. This is the only place that owns SQL.

### Expected Outcomes
- `src/app/db/connection.py` provides `get_connection()` returning a DuckDB connection.
- In `DEMO_MODE=true`, connection uses in-memory `:memory:` database (never touches disk paths that may not exist).
- `src/app/db/seed.py` seeds all fixture data on startup when `DEMO_MODE=true`.
- `src/app/db/queries.py` exposes typed query functions:
  - `get_all_shipments() -> list[Shipment]`
  - `get_shipment(shipment_id) -> Shipment`
  - `get_idle_assets() -> list[Asset]`
  - `get_sensor_readings(shipment_id) -> list[SensorReading]`
  - `get_policy(policy_id) -> PolicyProfile`
  - `get_disruption(disruption_id) -> Disruption`
  - `insert_evidence(record: EvidenceRecord)`
- Referential integrity verified on seed (no orphan sensor readings).

### Expected Outcomes — Testable
- `python -m pytest src/app/db/` passes with an in-memory DB seeded with fixtures.
- Querying `SHP-0042` returns the reference shipment with all fields populated.
- Preflight CHK-1 (`check_duckdb_schema`) passes against the seeded schema.

### Todo List
- [ ] Create `src/app/db/` package.
- [ ] Write `connection.py`: reads `DEMO_MODE` env var; returns in-memory connection when true.
- [ ] Write `schema.py`: DDL strings matching preflight CREATE TABLE statements exactly (shipments, assets, sensor_readings, plus add `disruptions`, `policy_profiles`, `evidence_records` tables).
- [ ] Write `seed.py`: calls `load_fixtures()` from ST-01 and bulk-inserts into DuckDB.
- [ ] Write `queries.py`: one function per query, returns typed Pydantic objects.
- [ ] Write unit tests for connection lifecycle, seed integrity, and each query function.

### Relevant Context
- Canonical schema: `scripts/preflight_demo.py` lines 108–167.
- Connection must never hard-crash if an optional table is missing — same "resilient" posture as preflight.
- All schema state must be fully reproducible from a cold start; no migration files needed for MVP.

---

## ST-03 — Impact Engine (NetworkX Route and Time-Window Overlap)

**Status:** [ ] pending

### Intent
Implement the deterministic disruption impact engine that decides, for each shipment,
whether its route and time window intersect a disruption. This is the core classification logic —
no heuristics, no LLM.

### Expected Outcomes
- `src/app/engines/impact.py` exposes `calculate_impact(disruption: Disruption, shipments: list[Shipment], graph: RouteGraph) -> list[ImpactResult]`.
- `ImpactResult` contains: `shipment_id`, `affected: bool`, `reason_codes: list[str]`, `cargo_value_usd`, `eta_delay_hours`.
- `SHP-0042` is classified as affected (`PORT_NODE_BLOCKED`) for `PORT_STRIKE_01`.
- `SHP-0099` (bypass route, no `PORT-03` overlap) is classified as unaffected.
- `time_overlaps(a, b)` is a standalone pure function (no side effects, easily unit-tested).
- Preflight CHK-2 (`check_networkx_impact_engine`) logic is fully reproduced.

### Todo List
- [ ] Create `src/app/engines/impact.py`.
- [ ] Port `time_overlaps()` function from preflight as a module-level pure function.
- [ ] Implement `build_route_graph(fixture) -> nx.Graph` from the fixture route data.
- [ ] Implement `calculate_impact()`: iterate shipments, check `set(route) & disruption.blocked_nodes`, check time overlap, return `ImpactResult` per shipment.
- [ ] Add `ETA_SLA_BREACH` reason code when affected shipment's deadline is within 24h of disruption end window.
- [ ] Write unit tests: reference scenario produces exactly `{SHP-0042}` as affected; bypass shipment is not affected; time-only overlap (no route hit) is not affected; route-only overlap (no time hit) is not affected.

### Relevant Context
- Preflight CHK-2: `scripts/preflight_demo.py` lines 227–294.
- Route graph structure: 4 nodes, 4 edges (including `HUB-A → HUB-D` bypass edge).
- Reason codes must be SCREAMING_SNAKE_CASE strings (see AGENTS.md).

---

## ST-04 — Optimization Engine (OR-Tools Carrier and Route Alternatives)

**Status:** [ ] pending

### Intent
Implement the constraint-satisfaction assignment engine that generates feasible carrier and
route alternatives for affected shipments. Hard constraints are never softened.

### Expected Outcomes
- `src/app/engines/optimizer.py` exposes:
  - `find_route_alternatives(shipment: Shipment, disruption: Disruption, graph: nx.Graph, assets: list[Asset]) -> list[RouteAlternative]`
  - `match_idle_assets(shipment: Shipment, assets: list[Asset]) -> list[AssetMatch]`
- `RouteAlternative` fields: `carrier_id`, `route_nodes`, `eta_delta_hours`, `additional_cost_usd`, `reason_codes`.
- `AssetMatch` fields: `asset_id`, `reposition_distance_km`, `available_at`, `reason_codes`.
- Hard constraints enforced: reefer capability, weight capacity, delivery deadline.
- `SHP-0042` (reefer, 8200 kg) is assigned only to `CARRIER-B` (reefer, 12000 kg), not `CARRIER-A` (no reefer).
- Preflight CHK-3 (`check_ortools_feasibility`) logic is fully reproduced.
- When OR-Tools is not installed, raises `OptimizationUnavailable` (not a crash).

### Todo List
- [ ] Create `src/app/engines/optimizer.py`.
- [ ] Wrap `from ortools.sat.python import cp_model` in try/except; raise `OptimizationUnavailable` if missing.
- [ ] Implement `_assign_carriers(shipments, carriers) -> dict[str, str]` using CP-SAT model matching preflight CHK-3.
- [ ] Implement `find_route_alternatives()`: remove disrupted edges from graph copy, enumerate surviving paths, call `_assign_carriers()` for each candidate, rank by `(eta_delta_hours, additional_cost_usd)`.
- [ ] Implement `match_idle_assets()`: filter assets by mode, reefer, capacity, available_at; rank by reposition distance.
- [ ] Write unit tests: reefer shipment is never assigned to non-reefer carrier; overweight shipment has no feasible assignment; idle asset matching respects reefer flag.

### Relevant Context
- Preflight CHK-3: `scripts/preflight_demo.py` lines 301–373.
- CP-SAT solver timeout: `solver.parameters.max_time_in_seconds = 2.0` (match preflight).
- Asset fields: `asset_id`, `asset_type`, `mode`, `current_node_id`, `available_at`, `capacity_kg`, `reefer_capable`, `carrier_id`, `status`.

---

## ST-05 — Cold Chain Policy Engine

**Status:** [ ] pending

### Intent
Implement the configurable cold-chain excursion classifier. Every threshold, duration limit,
and severity rule comes from the policy profile dict. Nothing is hardcoded.

### Expected Outcomes
- `src/app/engines/cold_chain.py` exposes `classify_excursion(policy: PolicyProfile | None, readings: list[SensorReading]) -> ExcursionResult`.
- `ExcursionResult` fields: `status`, `max_celsius`, `min_celsius`, `duration_minutes`, `out_of_range_count`, `evidence`.
- Status values: `SAFE`, `EXCURSION_REVIEW`, `URGENT_ESCALATION`, `POLICY_REQUIRED`.
- `policy=None` → `status = "POLICY_REQUIRED"` (no exception).
- Empty readings + valid policy → `status = policy.severity_rules["missing_sensor_data"]` → `"URGENT_ESCALATION"`.
- Reference scenario (readings with max 10.4°C, 3 out-of-range readings) → `status = "EXCURSION_REVIEW"`, `duration_minutes = 18`.
- In-range reading (5.0°C) → `status = "SAFE"`.
- Preflight CHK-4 (`check_cold_chain_policy_engine`) all four assertions pass.

### Todo List
- [ ] Create `src/app/engines/cold_chain.py`.
- [ ] Port `classify_excursion()` from preflight lines 380–410, replacing raw dict with Pydantic `PolicyProfile`.
- [ ] Ensure `sample_interval_minutes` drives `duration_minutes = len(out_of_range) * sample_interval_minutes`.
- [ ] Add sensor pattern detection stubs (spike, drift, door-open, sensor failure) — return pattern label in `evidence` dict, implementation can be minimal for MVP.
- [ ] Write unit tests: all four paths (POLICY_REQUIRED, URGENT_ESCALATION, EXCURSION_REVIEW, SAFE); duration calculation; different policy dicts produce different outcomes without code change.

### Relevant Context
- Canonical implementation: `scripts/preflight_demo.py` lines 380–477.
- Policy fields: `policy_id`, `min_celsius`, `max_celsius`, `max_continuous_excursion_minutes`, `sample_interval_minutes`, `severity_rules` (dict with `out_of_range` and `missing_sensor_data` keys).
- Cold-chain is the only engine that must handle `policy=None` gracefully (product class not matched).

---

## ST-06 — Deterministic Explanation Fallback

**Status:** [ ] pending

### Intent
Implement the deterministic explanation generator that is the live path when
`WATSONX_ENABLED=false` and the fallback when watsonx.ai exceeds its 2.5s timeout.
This must never make a network call.

### Expected Outcomes
- `src/app/engines/explanation.py` exposes:
  - `generate_fallback_explanation(decision: DecisionContext) -> ExplanationResult`
  - `generate_explanation(decision: DecisionContext) -> ExplanationResult` (calls watsonx if enabled, otherwise calls fallback)
- `ExplanationResult` mandatory fields: `summary`, `why_affected`, `recommended_action`, `evidence`, `uncertainties`, `generated_by`, `model_used`.
- `generated_by = "deterministic_fallback_template"` and `model_used = None` when using fallback.
- `evidence` list is never empty for a decision with reason codes.
- `generate_explanation()` reads `WATSONX_ENABLED` env var; if false/unset, calls fallback directly without attempting a network call.
- When `WATSONX_ENABLED=true`, wraps the watsonx call in a 2.5s timeout; on timeout or exception, falls back.
- Preflight CHK-5 (`check_deterministic_fallback`) passes: all required keys present, evidence non-empty, execution under 2500ms.

### Todo List
- [ ] Create `src/app/engines/explanation.py`.
- [ ] Define `DecisionContext` dataclass: `shipment_id`, `disruption`, `reason_codes`, `recommended_route` (optional), `cold_chain` (optional).
- [ ] Port `generate_fallback_explanation()` from preflight lines 484–518, accepting `DecisionContext`.
- [ ] Implement `generate_explanation()` with env-var guard and 2.5s timeout wrapper (use `concurrent.futures.ThreadPoolExecutor` or `asyncio.wait_for`).
- [ ] Write unit tests: fallback output schema complete; evidence non-empty; cold-chain uncertainty appended when status is EXCURSION_REVIEW; no-route uncertainty appended when route is None.

### Relevant Context
- Canonical fallback: `scripts/preflight_demo.py` lines 484–569.
- Required output keys: `summary`, `why_affected`, `recommended_action`, `evidence`, `uncertainties` (asserted by preflight CHK-5).
- `WATSONX_ENABLED` env var is the gating flag — read with `os.environ.get("WATSONX_ENABLED", "false").strip().lower() == "true"`.

---

## ST-07 — Evidence and Audit Layer

**Status:** [ ] pending

### Intent
Implement the evidence recorder that every engine result passes through before reaching
the explanation layer. This creates the audit trail that judges can inspect.

### Expected Outcomes
- `src/app/audit/recorder.py` exposes `record_decision(decision: EvidenceRecord) -> str` (returns `decision_id` UUID).
- `EvidenceRecord` fields: `decision_id` (UUID, auto-generated), `timestamp` (UTC), `decision_type` (IMPACT | ROUTE | ASSET | COLD_CHAIN), `shipment_id`, `disruption_id` (optional), `policy_id` (optional), `reason_codes`, `output` (dict), `confidence_score`.
- Records are persisted to DuckDB `evidence_records` table (from ST-02).
- `get_evidence(decision_id) -> EvidenceRecord` retrieves a record by ID.
- `list_evidence(shipment_id) -> list[EvidenceRecord]` retrieves all records for a shipment.
- `confidence_score` is computed deterministically: `1.0 - (missing_fields_fraction)`; if all data present, score is `1.0`.

### Todo List
- [ ] Create `src/app/audit/recorder.py`.
- [ ] Define `EvidenceRecord` Pydantic model (or extend from ST-01 schemas).
- [ ] Implement `record_decision()`: generate UUID, add UTC timestamp, insert into DuckDB.
- [ ] Implement `get_evidence()` and `list_evidence()` using DB queries from ST-02.
- [ ] Implement deterministic `confidence_score` calculation.
- [ ] Write unit tests: round-trip record/retrieve; score is 1.0 for complete data; score decreases when optional fields are absent.

### Relevant Context
- Evidence record shape in preflight: `scripts/preflight_demo.py` lines 68–78 (`CheckResult` dataclass is the prototype).
- Evidence output written to `reports/preflight_report.json` shows the target JSON shape.
- Architecture Phase 6: `docs/architecture.md` lines 98–107.

---

## ST-08 — FastAPI Integration

**Status:** [ ] pending

### Intent
Wire all engines and the audit layer behind the eight REST endpoints described in the architecture.
The API must start, serve, and return correct responses without any network dependency.

### Expected Outcomes
- `src/app/api/main.py` is the uvicorn entry point (`src.app.api.main:app`).
- All eight endpoints implemented and returning typed responses:
  - `POST /api/v1/disruptions/activate` → `{disruption_id, affected_shipments: list[ImpactResult]}`
  - `GET /api/v1/shipments/{shipment_id}` → `Shipment` + `alternatives: list[RouteAlternative]`
  - `GET /api/v1/assets/idle` → `list[AssetMatch]`
  - `GET /api/v1/cold-chain/{shipment_id}/timeline` → sensor timeline + `ExcursionResult`
  - `POST /api/v1/explanations/generate` → `ExplanationResult`
  - `POST /api/v1/action-plan/export` → JSON or Markdown action plan
  - `GET /api/v1/evidence/{decision_id}` → `EvidenceRecord`
  - `GET /healthz` → `{status: "ok", demo_mode: bool}`
- Every engine call records an `EvidenceRecord` before returning.
- `GET /api/v1/disruptions` returns the list of available demo disruption scenarios (for UI dropdown).
- API starts cleanly with `DEMO_MODE=true WATSONX_ENABLED=false NETWORK_REQUIRED=false`.
- `GET /docs` (Swagger UI) accessible at `http://localhost:8000/docs`.

### Todo List
- [ ] Create `src/app/api/` package with `main.py`, `routers/` sub-package.
- [ ] Create `src/app/api/routers/disruptions.py`, `shipments.py`, `assets.py`, `cold_chain.py`, `explanations.py`, `action_plan.py`, `evidence.py`.
- [ ] Implement FastAPI lifespan startup: call `seed.py` from ST-02 when `DEMO_MODE=true`.
- [ ] Wire each router to the corresponding engine function from ST-03 through ST-07.
- [ ] Ensure every engine result is passed through `record_decision()` from ST-07 before the response is returned.
- [ ] Write integration tests using `httpx.AsyncClient` and `TestClient`: activate disruption returns `SHP-0042` affected; cold-chain timeline returns `EXCURSION_REVIEW`; explanation returns all required keys; healthz returns 200.

### Relevant Context
- API surface: `docs/architecture.md` Phases 2–8.
- Entry point must be `src.app.api.main:app` (see AGENTS.md).
- `requirements.txt` must be created (or `pyproject.toml`) listing: fastapi, uvicorn, duckdb, networkx, pydantic, polars, ortools (optional), geopandas, shapely.

---

## ST-09 — Frontend Integration

**Status:** [ ] pending

### Intent
Build the React control tower UI that calls the backend API and renders the five panels:
Crisis Overview, Impact Map, Shipment Detail, Action Center, Cold-Chain Monitor, and Evidence Drawer.

### Expected Outcomes
- `src/web/` is a Vite + React + TypeScript project.
- Five screens implemented with working data from the backend API:
  1. **Crisis Overview:** active disruptions list, affected shipment count, cargo value at risk, idle asset count, open cold-chain incidents.
  2. **Impact Map:** MapLibre GL JS map with disruption zone overlay, affected routes (red), unaffected routes (green), alternative route previews (blue dashed).
  3. **Shipment Detail:** disruption cause, ETA impact, cargo value, ranked alternatives table with cost/delay/risk.
  4. **Cold-Chain Monitor:** sensor timeline chart with policy band (green), excursion spike (red), duration label, classification badge.
  5. **Evidence Drawer:** reason codes, source data, confidence score, "Why this recommendation?" expandable panel.
- Disruption activation button triggers `POST /api/v1/disruptions/activate` and refreshes the map.
- Action plan export button triggers `POST /api/v1/action-plan/export` and downloads JSON.
- All API calls use relative paths (proxied via Vite dev server to `http://localhost:8000`).
- `npm run build` succeeds cleanly.
- `npm run dev` serves at `http://localhost:5173`.

### Todo List
- [ ] Scaffold Vite + React + TypeScript project in `src/web/` (`npm create vite@latest`).
- [ ] Install dependencies: `maplibre-gl`, `react-query` (or `swr`), `recharts` (or similar for sensor chart), TypeScript types.
- [ ] Create `src/web/src/api/` with typed fetch wrappers for all eight backend endpoints.
- [ ] Build `CrisisOverviewPanel` component.
- [ ] Build `ImpactMapPanel` component using MapLibre GL JS.
- [ ] Build `ShipmentDetailPanel` component with alternatives table.
- [ ] Build `ColdChainMonitorPanel` component with sensor timeline chart.
- [ ] Build `EvidenceDrawer` component.
- [ ] Wire disruption activation control (dropdown + button).
- [ ] Wire action plan export button.
- [ ] Configure Vite proxy: `/api` → `http://localhost:8000`.
- [ ] Verify `npm run build` succeeds.

### Relevant Context
- UI panels described in `docs/solution-overview.md` lines 73–127.
- MapLibre GL JS (not Mapbox) — open-source, no API key required for offline use.
- Map data (hub locations, route geometry) comes from the backend API, not a tile server — use GeoJSON layers.
- All UI must function with no network access beyond `localhost` (no CDN imports).

---

## ST-10 — Tests and Docker Compose

**Status:** [ ] pending

### Intent
Assemble the full test suite and Docker Compose configuration so the complete offline demo
passes preflight and starts from a cold clone with a single command.

### Expected Outcomes
- `python -m pytest` passes all unit and integration tests from ST-01 through ST-08.
- `python scripts/preflight_demo.py` exits 0 with all five checks PASS or SKIP.
- `python scripts/preflight_demo.py --strict` exits 0 (no WARNs).
- `docker compose up --build` starts backend (`8000`) and frontend (`5173`).
- `DEMO_MODE=true WATSONX_ENABLED=false NETWORK_REQUIRED=false docker compose up --build` starts fully offline.
- `docker compose run --rm backend python scripts/preflight_demo.py` exits 0 inside the container.
- CI GitHub Actions `validate.yml` passes: `src/` has ≥1 real file, `submission.yaml` fields filled, `docs/setup-guide.md` exists.

### Todo List
- [ ] Create `requirements.txt` at repo root listing all Python dependencies.
- [ ] Create `src/web/package.json` (from ST-09 scaffold).
- [ ] Create `Dockerfile` for backend (Python 3.12 slim, copies `src/app/`, installs requirements, exposes 8000).
- [ ] Create `Dockerfile` for frontend (Node 20 slim, copies `src/web/`, runs `npm ci && npm run build`, serves via nginx or `serve`).
- [ ] Create `docker-compose.yml` at repo root with `backend` and `frontend` services, env var passthrough for `DEMO_MODE`, `WATSONX_ENABLED`, `NETWORK_REQUIRED`.
- [ ] Create `src/.env.example` → already exists; verify all new env vars are listed.
- [ ] Create `docs/setup-guide.md` (required by CI — currently missing).
- [ ] Add `conftest.py` at `src/app/` level with a shared in-memory DuckDB fixture.
- [ ] Run `python scripts/preflight_demo.py --strict` locally; fix any WARN or FAIL.
- [ ] Verify GitHub Actions `validate.yml` passes on push.

### Relevant Context
- `docs/setup-guide.md` is a required file per `.github/workflows/validate.yml` line 35 — currently missing and will fail CI.
- `src/` must contain ≥1 non-README, non-`.env.example` file (CI check, line 100).
- Preflight exit codes: 0 = all PASS/SKIP; 1 = any FAIL (or WARN with `--strict`).
- Docker Compose service names expected by README: `backend`, implicit `frontend`.

---

## Architecture Reference

```
src/
  app/
    schemas/          # ST-01: Pydantic models for all entities
    data/
      fixtures/       # ST-01: JSON seed files for demo scenario
      loader.py       # ST-01: load_fixtures() -> FixtureBundle
    db/
      connection.py   # ST-02: get_connection(), DEMO_MODE guard
      schema.py       # ST-02: DDL strings
      seed.py         # ST-02: seed fixtures into DuckDB
      queries.py      # ST-02: typed query functions
    engines/
      impact.py       # ST-03: NetworkX impact engine
      optimizer.py    # ST-04: OR-Tools carrier/asset assignment
      cold_chain.py   # ST-05: configurable excursion classifier
      explanation.py  # ST-06: deterministic fallback + watsonx wrapper
    audit/
      recorder.py     # ST-07: evidence record persistence
    api/
      main.py         # ST-08: FastAPI app entry point
      routers/        # ST-08: one file per resource
  web/                # ST-09: Vite + React + TypeScript frontend
scripts/
  preflight_demo.py   # Existing — must pass after ST-10
docs/
  setup-guide.md      # ST-10: must be created for CI
requirements.txt      # ST-10: Python deps
docker-compose.yml    # ST-10: backend + frontend services
```

## Non-Negotiable Rules (from AGENTS.md)

- LLM never makes a decision — it only explains structured results.
- Cold-chain thresholds always come from policy dicts, never from code.
- OR-Tools imports are always guarded with try/except ImportError.
- Every engine result passes through the Evidence/Audit Layer before the response is returned.
- `WATSONX_ENABLED=false` must result in zero network calls — no timeout wait, no fallback-after-attempt.
- All application code lives under `src/` — no root-level `app/` or `web/` directories.
