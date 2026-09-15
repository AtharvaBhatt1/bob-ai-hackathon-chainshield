# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Summary

ChainShield is a **hackathon submission** (IBM Bob AI Hackathon). The full implementation lives under `src/app/` (FastAPI backend) and `src/web/` (React + TypeScript frontend). All seven required functions are implemented; 365 tests pass; the offline demo runs with `DEMO_MODE=true WATSONX_ENABLED=false NETWORK_REQUIRED=false`.

## Stack

- **Backend:** Python 3.12 + FastAPI (entry point: `src.app.api.main:app`, source under `src/app/`)
- **Frontend:** React + TypeScript + Vite (source under `src/web/`)
- **Data:** DuckDB (in-memory `:memory:` for tests), Parquet cache files
- **Graph:** NetworkX (route overlap), Google OR-Tools (CP-SAT constraint solver)
- **AI:** IBM watsonx.ai Granite 3.3 8B (optional; 2.5s timeout, deterministic fallback always present)

## Commands

```bash
# Backend dev server
uvicorn src.app.api.main:app --reload

# Frontend dev server (from src/web/)
cd src/web && npm install && npm run dev

# Run all tests
python -m pytest

# Run a single test file
python -m pytest path/to/test_file.py

# Preflight validator (no network needed)
python scripts/preflight_demo.py
python scripts/preflight_demo.py --strict          # treat WARN as FAIL

# Full offline demo via Docker
DEMO_MODE=true WATSONX_ENABLED=false NETWORK_REQUIRED=false docker compose up --build

# Validate submission YAML
yq '.' submission.yaml
```

## Critical Architecture Constraints

- **Deterministic core is non-negotiable:** Disruption impact, route feasibility, and cold-chain classification MUST be computed by deterministic logic. The LLM (Granite) only explains results — it never makes operational decisions.
- **Cold-chain thresholds must come from policy dicts**, never hardcoded. The `classify_excursion(policy, readings)` pattern in [`scripts/preflight_demo.py`](scripts/preflight_demo.py:380) is the canonical example — swapping the `policy` dict changes outcome without touching logic.
- **Every external API call (watsonx.ai, Cloudant) must have a timeout and a deterministic fallback.** The fallback in `generate_fallback_explanation()` is the live path when `WATSONX_ENABLED=false`.
- **Offline-first:** All core logic must work with `DEMO_MODE=true`, `WATSONX_ENABLED=false`, `NETWORK_REQUIRED=false`. This is tested by `scripts/preflight_demo.py`.

## Evidence/Audit Pattern

Every recommendation MUST include: reason codes (e.g. `PORT_NODE_BLOCKED`, `ETA_SLA_BREACH`), source data links, and a confidence score. The `CheckResult` dataclass in the preflight script shows the canonical shape: `{check_id, reason_codes, detail, evidence}`.

## Env Variables

Copy `src/.env.example` → `.env`. Required for watsonx.ai: `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`. Never commit `.env`.

## Submission Validation

GitHub Actions runs `.github/workflows/validate.yml` on every push. `team.track` must be exactly one of: `AI | DevOps | Sustainability | Open`. The `src/` directory must contain at least one non-README, non-`.env.example` file or CI fails.

## Repository Layout

All application implementation must live under `src/`. Do not create root-level `app/` or `web/` directories.

| Path | Purpose |
|---|---|
| `src/app/` | Backend (FastAPI) |
| `src/web/` | Frontend (React + TypeScript + Vite) |
| `README.md` | Project overview |
| `submission.yaml` | Hackathon submission metadata |
| `docs/problem-statement.md` | Problem statement |
| `docs/solution-overview.md` | Solution overview |
| `docs/architecture.md` | Architecture diagram and data flow |
| `presentation/presentation-outline.md` | Presentation notes |
| `scripts/preflight_demo.py` | Offline preflight validator |

## OR-Tools Usage Note

OR-Tools is an optional dependency (lazy import). When absent, the check degrades to `SKIP` — not `FAIL`. Use `from ortools.sat.python import cp_model` inside a try/except, mirroring the preflight pattern.
