# Project Documentation Context (Non-Obvious Only)

This file provides guidance to agents when working with code in this repository.

## Where Things Actually Live

- **`src/` is nearly empty** — only `README.md` and `.env.example` are present. All actual application code is yet to be written. The architecture described in `docs/` is the specification, not existing code.
- **`scripts/preflight_demo.py`** is the only real Python code in the repo and is the ground-truth reference for all five core engines (DuckDB schema, NetworkX impact, OR-Tools optimization, cold-chain policy, deterministic fallback).
- **`docs/architecture.md`** contains the full system diagram (Mermaid) and the 8-phase data flow walkthrough — this is the authoritative source for how components connect.
- **`submission.yaml`** is the judge-facing source of truth for the project's scope, features, and evaluation metrics. When updating docs, keep it consistent.

## Counterintuitive Structures

- There is no `requirements.txt`, `package.json`, `pyproject.toml`, or `Dockerfile` anywhere in the repo — these need to be created as part of implementation.
- The `.env.example` is in `src/`, not the repo root. The README tells users to `cp .env.example .env` from root — the actual path is `src/.env.example`.
- `docs/setup-guide.md` is listed as a required file by CI (`.github/workflows/validate.yml`) but **does not exist yet** — creating it will unblock the green CI check.

## Submission Validation

The GitHub Actions workflow at `.github/workflows/validate.yml` checks 6 things: required files exist, `submission.yaml` is valid YAML, required YAML fields are filled, `src/` has ≥1 real file, demo video link is not the placeholder, and README placeholders are replaced. Currently `[NEEDS INPUT]` placeholders remain throughout — these must be filled before submission.
