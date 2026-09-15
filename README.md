# ChainShield: Explainable Supply-Chain Resilience Copilot

## 👥 Team

| Field | Value |
|---|---|
| **Team Name** | ChainShield |
| **Track** | AI |
| **Team Lead** | Devanshi Shah — 25dce107@charusat.edu.in |
| **Members** | Atharva Bhatt , Rutu Modi , Harsh Aacharya  |

## Problem Statement

Supply-chain disruptions (port closures, weather events, strikes) cascade across hundreds of shipments within minutes, but operations teams lack real-time visibility into which cargo is affected, what alternatives exist, and whether temperature-sensitive products are already at risk. Cold-chain monitoring systems detect excursions only after damage occurs, and manual rerouting decisions consume hours while cargo value and customer commitments are lost. Teams need to convert raw disruption signals and sensor anomalies into verified operational actions in under 60 seconds.

## Solution

ChainShield is an explainable crisis-response system that converts active supply-chain disruptions and cold-chain sensor anomalies into ranked, auditable actions. The system identifies affected shipments using graph-based route overlap and time-window analysis, recommends feasible rerouting and carrier alternatives constrained by capacity and deadline, identifies idle compatible assets for redeployment, and detects temperature excursions before delivery using configurable policy profiles. Every recommendation includes evidence links, reason codes, and confidence indicators; the language model explains deterministic results rather than generating operational truth.

## Key Features

- **Real-time disruption impact analysis** using graph-based route overlap and time-window matching to identify affected shipments and quantify cargo value at risk
- **Ranked route and carrier alternatives** with hard-constraint validation (capacity, delivery deadline, reefer capability) and cost/delay tradeoffs
- **Idle asset matching and redeployment** recommendations with repositioning distance and compatibility scoring
- **Deterministic cold-chain policy engine** with configurable temperature thresholds, excursion detection, and policy-driven severity classification
- **Explainable action plans** with evidence links, reason codes, and confidence indicators; language model explains structured results rather than inventing decisions

## Tech Stack

| Layer | Technology |
|-------|-----------:|
| Backend | Python 3.12 + FastAPI |
| Frontend | React + TypeScript + Vite |
| Data Processing | Polars, DuckDB, Parquet |
| Graph & Routing | NetworkX, Google OR-Tools |
| Geospatial | GeoPandas, Shapely |
| Map UI | MapLibre GL JS |
| AI Explanation | IBM watsonx.ai (Granite 3.3 8B Instruct) |
| Development Partner | IBM Bob IDE |
| Deployment | Docker Compose |

## 📁 Repository Structure

```text
bob-ai-hackathon-chainshield/
├── .bob/                         # IBM Bob project settings and rules
├── .github/                      # GitHub configuration and workflows
│   └── workflows/
│       └── validate.yml          # Official hackathon validator
├── bob_sessions/                 # Bob task/session evidence (16 sessions)
│   ├── 01_data_contracts.md
│   ├── 02_synthetic_data.md
│   ├── 03_DuckDB.md
│   ├── 04_NetworkX Impact Engine.md
│   ├── 05_Cold Chain Engine.md
│   ├── 06_OR-Tools routing feasibility.md
│   ├── 07_Evidence or Audit layer.md
│   ├── 08_Deterministic explanation fallback.md
│   ├── 09_preflight.md
│   ├── 10_FastAPI.md
│   ├── 11_frontend_control_tower.md
│   ├── 12_canonical_demo_scenario.md
│   ├── 13_end_to_end_testing.md
│   ├── 14_offline_hardening.md
│   ├── 15_application_logging.md
│   └── 16_watsonxai.md
├── demo/                         # Demo artifacts
│   ├── screenshots/              # Application screenshots (24 images)
│   ├── demo-video-link.txt       # Demo video URL
│   └── live-demo-url.txt         # Live demo URL or local-run declaration
├── docs/                         # Written documentation
│   ├── architecture.md
│   ├── problem-statement.md
│   ├── setup-guide.md
│   ├── solution-overview.md
│   └── template-guide.md
├── presentation/                 # Presentation materials
│   └── presentation-outline.md
├── reports/                      # Validation and generated reports
│   └── preflight_report.json
├── scripts/                      # Demo and data scripts
│   ├── generate_synthetic_data.py
│   ├── preflight_demo.py
│   └── seed_demo.py
├── src/                          # Application source code
│   ├── .env.example              # Environment variable template
│   ├── app/                      # FastAPI backend and deterministic engines
│   │   ├── api/                  #   REST API layer
│   │   ├── cold_chain/           #   Cold-chain policy engine
│   │   ├── core/                 #   Shared data models and config
│   │   ├── evidence/             #   Audit and evidence layer
│   │   ├── explanation/          #   watsonx.ai / fallback explanation
│   │   ├── impact/               #   Disruption impact engine
│   │   └── optimization/         #   OR-Tools route optimizer
│   └── web/                      # React + TypeScript + Vite frontend
├── tests/                        # Automated tests (365 tests, all offline)
│   ├── api/                      #   API integration tests
│   └── unit/                     #   Unit tests
├── .gitignore                    # Git ignore rules
├── AGENTS.md                     # IBM Bob project guidance
├── chainshield-mvp-plan.md       # MVP implementation plan
├── CONTRIBUTING.md               # Contribution and submission guidelines
├── docker-compose.yml            # Docker Compose orchestration
├── Dockerfile                    # Multi-stage Docker build (backend + frontend)
├── README.md                     # This file
├── requirements.txt              # Python dependencies
└── submission.yaml               # Hackathon submission metadata
```

## How to Run

### Prerequisites

- Python 3.12+
- Node.js 18+
- Docker Desktop (for the containerised quick-start)

> **No IBM Cloud account is required for the offline demo.**

### Quick Start (Docker — recommended)

```bash
# 1. Copy environment file (defaults are fine for offline demo)
cp src/.env.example .env

# 2. Start all services
docker compose up --build
```

Access:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Offline Demo Mode

```bash
DEMO_MODE=true \
WATSONX_ENABLED=false \
NETWORK_REQUIRED=false \
docker compose up --build
```

### Local Development

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

> For the full list of environment variables and troubleshooting, see [`docs/setup-guide.md`](docs/setup-guide.md).

### Running Tests

```bash
python -m pytest
```

All 365 tests run offline — no network or credentials required.

### Preflight Check

```bash
python scripts/preflight_demo.py
python scripts/preflight_demo.py --strict   # treat WARN as FAIL
```

Expected output: `PREFLIGHT: OK -- safe to proceed with DEMO_MODE=true.`

## Demo

**Live Demo:** NOT DEPLOYED — run locally using [`docs/setup-guide.md`](docs/setup-guide.md)
**Video Demo:** See [`demo/demo-video-link.txt`](demo/demo-video-link.txt)
**Screenshots:** See [`demo/screenshots/`](demo/screenshots/) for crisis overview, impact map, rerouting, cold-chain, action center, and evidence drawer panels.

## Known Limitations

- **Regulatory scope:** The system uses configurable policy profiles for cold-chain classification. Demo profiles are based on CDC vaccine storage guidelines but are not authoritative for any specific product or jurisdiction. All excursion classifications require manual review unless an explicit policy profile permits automated disposition.
- **Offline routing:** Route alternatives are generated from a cached graph; live traffic and real-time carrier availability are not integrated.
- **Explanation latency:** Granite explanations have a 2.5-second timeout; if watsonx.ai is unavailable, the system falls back to deterministic templates.
- **Synthetic data:** All demo scenarios use synthetic shipments, assets, and sensor logs. No real customer, client, or personal data is included.
- **Deployment:** The system is designed for local deployment. Cloud services (watsonx.ai, Cloudant) are optional and not required for the core demo.

## What We're Most Proud Of

1. **Deterministic operational core:** Disruption impact, route feasibility, and cold-chain classification are calculated using verifiable logic, not LLM-generated decisions. The language model explains results, not creates them.
2. **Explainability by design:** Every recommendation includes reason codes, evidence links, and source data. Judges can audit why a shipment is affected, why a route is rejected, and why a temperature excursion is flagged.
3. **Resilience to demo failure:** The system works fully offline with cached data, precomputed scenarios, and deterministic fallbacks. External APIs, cloud services, and model inference are optional, not required.
4. **IBM Bob integration:** Bob IDE was used as the core development partner for architecture, implementation, testing, and documentation. All relevant task histories and consumption screenshots are exported to `bob_sessions/`.
5. **End-to-end crisis workflow:** A single interaction demonstrates all four required functions (disruption intelligence, shipment impact, fleet redeployment, cold-chain protection) in one connected flow, not as separate dashboards.
