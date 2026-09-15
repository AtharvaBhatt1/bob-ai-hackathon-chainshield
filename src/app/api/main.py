"""
src/app/api/main.py
===================
ChainShield FastAPI application entry point.

Entry point (uvicorn):
    uvicorn src.app.api.main:app --reload

Lifespan
--------
On startup: create in-memory DuckDB, seed with synthetic data, build NetworkX
route graph, and wire an EvidenceStore.  Everything is torn down automatically
on process exit because the connection is ``:memory:``.

Env vars
--------
DEMO_MODE          — "true" | "false" (default false)
WATSONX_ENABLED    — "true" | "false" (default false)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.app.api import deps
from src.app.api.routers import (
    action_plan,
    assets,
    cold_chain,
    disruptions,
    explanations,
    shipments,
)
from src.app.core.logging import configure_logging, get_logger
from src.app.core.schemas import HealthResponse

configure_logging()
_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: initialise all singletons once per process
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup -----------------------------------------------------------
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    watsonx_enabled = os.getenv("WATSONX_ENABLED", "false").lower() == "true"

    _log.info(
        "chainshield_startup",
        extra={
            "demo_mode": demo_mode,
            "watsonx_enabled": watsonx_enabled,
            "offline_mode": not watsonx_enabled,
        },
    )

    from scripts.generate_synthetic_data import DEMO_DATASET  # noqa: PLC0415
    from src.app.core.database import create_connection, seed_from_demo_dataset  # noqa: PLC0415

    con = create_connection()
    seed_from_demo_dataset(con)

    graph = deps.build_nx_graph(DEMO_DATASET["route_graph"])
    deps.init_state(con=con, dataset=DEMO_DATASET, graph=graph)

    _log.info(
        "chainshield_ready",
        extra={
            "shipments_loaded": len(DEMO_DATASET.get("shipments", [])),
            "disruptions_loaded": len(DEMO_DATASET.get("disruptions", [])),
            "assets_loaded": len(DEMO_DATASET.get("assets", [])),
        },
    )

    yield  # application runs

    # ---- shutdown (in-memory DB vanishes automatically) --------------------
    try:
        con.close()
    except Exception:
        pass
    _log.info("chainshield_shutdown")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ChainShield API",
    version="1.0.0",
    description=(
        "Deterministic supply-chain disruption intelligence. "
        "All decisions are produced by deterministic engines; "
        "watsonx.ai Granite is an optional explanation layer only."
    ),
    lifespan=lifespan,
)

# Allow the Vite dev-server (port 5173) and any localhost port to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(disruptions.router, prefix="/api/v1", tags=["disruptions"])
app.include_router(shipments.router,   prefix="/api/v1", tags=["shipments"])
app.include_router(assets.router,      prefix="/api/v1", tags=["assets"])
app.include_router(cold_chain.router,  prefix="/api/v1", tags=["cold-chain"])
app.include_router(explanations.router, prefix="/api/v1", tags=["explanations"])
app.include_router(action_plan.router, prefix="/api/v1", tags=["action-plan"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz", response_model=HealthResponse, tags=["health"])
def healthz() -> HealthResponse:
    """Liveness probe — no dependencies checked."""
    return HealthResponse(
        status="ok",
        demo_mode=os.getenv("DEMO_MODE", "false").lower() == "true",
        watsonx_enabled=os.getenv("WATSONX_ENABLED", "false").lower() == "true",
    )
