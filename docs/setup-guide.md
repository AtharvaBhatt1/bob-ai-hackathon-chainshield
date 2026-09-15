# Setup Guide

> **This file is read by the automated evaluation pipeline. Be precise and complete.**

## Prerequisites

Before you begin, ensure you have the following installed:

- [ ] Python 3.12+
- [ ] Node.js 18+
- [ ] Docker Desktop (for the containerised quick-start only)

> **No IBM Cloud account is required for the offline demo.**
> `WATSONX_ENABLED=false` (the default) uses only the deterministic fallback; no
> watsonx.ai credentials are needed.

## Environment Variables

Copy `src/.env.example` to `.env` and review the values.
For the offline demo **no changes are required** — the defaults already set
`DEMO_MODE=true`, `WATSONX_ENABLED=false`, and `NETWORK_REQUIRED=false`.

```bash
cp src/.env.example .env
```

| Variable | Description | Required for demo |
|---|---|---|
| `DEMO_MODE` | `true` — use in-memory synthetic data; no DB setup needed | pre-filled `true` |
| `WATSONX_ENABLED` | `false` — use deterministic fallback only | pre-filled `false` |
| `NETWORK_REQUIRED` | `false` — all core logic runs locally | pre-filled `false` |
| `WATSONX_API_KEY` | IBM watsonx.ai API key (live explanation only) | No |
| `WATSONX_PROJECT_ID` | watsonx.ai project ID (live explanation only) | No |
| `WATSONX_URL` | watsonx.ai endpoint URL | No |
| `APP_PORT` | Backend listening port (default `8000`) | No |

> `DATABASE_URL` is **not used**. ChainShield uses DuckDB `:memory:` only —
> no PostgreSQL or external database is required.

## Quick Start (Docker — recommended)

```bash
# 1. Copy environment file (defaults are fine for offline demo)
cp src/.env.example .env

# 2. Start all services
docker compose up --build
```

Access:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs

### Offline Demo Mode (explicit flags)

```bash
DEMO_MODE=true \
WATSONX_ENABLED=false \
NETWORK_REQUIRED=false \
docker compose up --build
```

## Local Development (without Docker)

```bash
# 1. Create and activate a Python virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install backend dependencies
pip install -r requirements.txt

# 3. Start the backend
uvicorn src.app.api.main:app --reload

# 4. Install and start the frontend (separate terminal)
cd src/web && npm install && npm run dev
```

Backend: http://localhost:8000  
Frontend: http://localhost:5173

## Running Tests

```bash
python -m pytest
```

All 365 tests run offline (no network, no credentials required).

## Preflight Check (validates offline demo readiness)

```bash
python scripts/preflight_demo.py
python scripts/preflight_demo.py --strict   # treat WARN as FAIL
```

Expected output: `PREFLIGHT: OK -- safe to proceed with DEMO_MODE=true.`

Evidence record written to `reports/preflight_report.json`.

## Troubleshooting

| Issue | Solution |
|---|---|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` inside your virtual environment |
| `uvicorn: command not found` | Run `pip install uvicorn` or prefix with `python -m uvicorn` |
| Port 8000 already in use | Set `APP_PORT=8001` in `.env` and restart |
| Frontend shows blank page | Ensure `npm install` ran inside `src/web/` and Vite dev server is running |
| watsonx.ai 401 error | Check `WATSONX_API_KEY` and `WATSONX_PROJECT_ID` in `.env` — not needed for offline demo |
| Tests fail | Run `python -m pytest -v` to see which test failed; all tests pass offline |
