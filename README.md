# ChainShield: Explainable Supply-Chain Resilience Copilot

## 👥 Team

| Field | Value |
|---|---|
| **Team Name** | ChainShield |
| **Track** | AI |
| **Team Lead** | Devanshi Shah — 25dce107@charusat.edu.in |
| **Members** | Atharva Bhatt , Rutu Modi , Harsh AAcharya  |

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
|-------|-----------|
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
├── .pytest_cache/                # Pytest cache
├── bob_sessions/                 # Bob task/session evidence
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
│   ├── screenshots/              # Application screenshots
│   ├── demo-video-link.txt       # Demo video URL
│   └── live-demo-url.txt         # Live demo URL or local-run declaration
├── docs/                         # Written documentation
│   ├── architecture.md
│   ├── problem-statement.md
│   ├── setup-guide.md
│   ├── solution-overview.md
│   └── template-guide.md
├── presentation/                 # Presentation materials
│   ├── presentation-outline.md
│   └── slides.pdf
├── reports/                      # Validation and generated reports
│   └── preflight_report.json
├── scripts/                      # Demo and data scripts
│   ├── generate_synthetic_data.py
│   ├── preflight_demo.py
│   └── seed_demo.py
├── src/                          # Application source code
│   ├── app/                      # FastAPI backend and deterministic engines
│   └── web/                      # React + TypeScript + Vite frontend
├── tests/                        # Automated tests
├── .gitignore                    # Git ignore rules
├── AGENTS.md                     # IBM Bob project guidance
├── CONTRIBUTING.md               # Contribution guidelines
├── README.md                     # Project documentation
├── requirements.txt              # Python dependencies
└── submission.yaml               # Hackathon submission metadata

## How to Run

### Quick Start (Docker)

```bash
cp .env.example .env
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
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
uvicorn src.app.api.main:app --reload
cd src/web && npm install && npm run dev
```

### Preflight Check

```bash
docker compose run --rm backend python scripts/preflight_demo.py
```

## Demo

**Live Demo:** [NEEDS INPUT: Demo URL or deployment link]  
**Video Demo:** [NEEDS INPUT: YouTube or video link]  
**Screenshots:** See `screenshots/` folder for crisis overview, rerouting, and cold-chain panels.

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
