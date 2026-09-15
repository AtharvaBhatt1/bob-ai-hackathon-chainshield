"""
src/app/api/deps.py
===================
FastAPI dependency providers for ChainShield.

Provides:
  - A seeded DuckDB in-memory connection (singleton per process lifetime).
  - The DEMO_DATASET dict (shipments, assets, policies, disruptions, etc.).
  - A NetworkX route graph built from the demo dataset.
  - An EvidenceStore wired to the shared DuckDB connection.

Design constraints
------------------
- DuckDB is always ``:memory:``.  No disk writes.
- All seeding happens once at application startup via the lifespan hook in
  ``main.py`` — this module only provides getter functions.
- No network access.  Offline-first.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import networkx as nx

if TYPE_CHECKING:
    import duckdb as _ddb

# ---------------------------------------------------------------------------
# Module-level singletons populated by the lifespan hook.
# ---------------------------------------------------------------------------

_con: "_ddb.DuckDBPyConnection | None" = None
_dataset: "dict[str, Any] | None" = None
_graph: "nx.Graph | None" = None


def init_state(
    con: "_ddb.DuckDBPyConnection",
    dataset: "dict[str, Any]",
    graph: "nx.Graph",
) -> None:
    """Called once from the lifespan startup hook."""
    global _con, _dataset, _graph
    _con = con
    _dataset = dataset
    _graph = graph


# ---------------------------------------------------------------------------
# FastAPI dependency callables
# ---------------------------------------------------------------------------

def get_con() -> "_ddb.DuckDBPyConnection":
    """Yield the shared DuckDB connection.

    FastAPI calls this as a dependency; callers must not close the connection.
    """
    assert _con is not None, "DuckDB connection not initialised — lifespan not executed?"
    return _con


def get_dataset() -> "dict[str, Any]":
    """Return the full seeded demo dataset dict."""
    assert _dataset is not None, "Dataset not initialised — lifespan not executed?"
    return _dataset


def get_graph() -> "nx.Graph":
    """Return the route graph as a NetworkX Graph."""
    assert _graph is not None, "Graph not initialised — lifespan not executed?"
    return _graph


def build_nx_graph(route_graph: Any) -> nx.Graph:
    """Convert a :class:`~src.app.core.models.RouteGraph` to a NetworkX Graph.

    Edge attributes ``transit_hours``, ``distance_km``, and ``mode`` are
    copied from each :class:`~src.app.core.models.RouteEdge` so that the
    Optimization Engine can read them directly.
    """
    g = nx.Graph()
    for node in route_graph.nodes:
        g.add_node(node.node_id, **node.model_dump())
    for edge in route_graph.edges:
        g.add_edge(
            edge.origin_node_id,
            edge.destination_node_id,
            transit_hours=edge.transit_hours,
            distance_km=edge.distance_km,
            mode=edge.mode.value,
        )
    return g
