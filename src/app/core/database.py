"""
src/app/core/database.py
========================
Local in-memory DuckDB demo store for ChainShield.

Responsibilities
----------------
- Create and own a single ``:memory:`` DuckDB connection.
- Define all table DDL (column names match the models in ``models.py`` and the
  preflight schema in ``scripts/preflight_demo.py`` exactly).
- Seed the connection from the synthetic dataset produced by
  ``scripts/generate_synthetic_data.py``.
- Provide a ``validate_schema()`` helper that asserts every required table and
  column exists in the live connection.

Design constraints (from AGENTS.md)
-------------------------------------
- DuckDB is always ``:memory:`` — never writes to disk.
- No network access required; runs fully offline.
- ``duckdb`` is imported lazily inside functions so that a missing optional
  dependency degrades to a clear ``ImportError``, never a hard crash.
- No FastAPI imports here.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path when this module is imported directly
# (not needed when installed as a package, but guards CI runs of scripts/).
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if TYPE_CHECKING:
    import duckdb as _duckdb_t

# ---------------------------------------------------------------------------
# DDL — one constant per table; column names mirror models.py and the
# preflight_demo.py schema exactly.
# ---------------------------------------------------------------------------

_DDL_SHIPMENTS = """
CREATE TABLE IF NOT EXISTS shipments (
    shipment_id           VARCHAR PRIMARY KEY,
    cargo_type            VARCHAR NOT NULL,
    product_class         VARCHAR NOT NULL,
    temperature_policy_id VARCHAR,
    origin_hub_id         VARCHAR NOT NULL,
    destination_hub_id    VARCHAR NOT NULL,
    current_node_id       VARCHAR NOT NULL,
    mode                  VARCHAR NOT NULL,
    carrier_id            VARCHAR NOT NULL,
    planned_departure     TIMESTAMP NOT NULL,
    planned_arrival       TIMESTAMP NOT NULL,
    delivery_deadline     TIMESTAMP NOT NULL,
    cargo_value_usd       DOUBLE NOT NULL,
    weight_kg             DOUBLE NOT NULL,
    status                VARCHAR NOT NULL
)
"""

_DDL_ASSETS = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id        VARCHAR PRIMARY KEY,
    asset_type      VARCHAR NOT NULL,
    mode            VARCHAR NOT NULL,
    current_node_id VARCHAR NOT NULL,
    available_at    TIMESTAMP NOT NULL,
    capacity_kg     DOUBLE NOT NULL,
    reefer_capable  BOOLEAN NOT NULL,
    carrier_id      VARCHAR NOT NULL,
    status          VARCHAR NOT NULL
)
"""

_DDL_SENSOR_READINGS = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    sensor_id     VARCHAR NOT NULL,
    shipment_id   VARCHAR NOT NULL,
    ts            TIMESTAMP NOT NULL,
    temperature_c DOUBLE NOT NULL,
    battery_pct   DOUBLE
)
"""

_DDL_POLICIES = """
CREATE TABLE IF NOT EXISTS policies (
    policy_id                        VARCHAR PRIMARY KEY,
    jurisdiction                     VARCHAR NOT NULL,
    product_class                    VARCHAR NOT NULL,
    min_celsius                      DOUBLE NOT NULL,
    max_celsius                      DOUBLE NOT NULL,
    max_continuous_excursion_minutes INTEGER NOT NULL,
    sample_interval_minutes          INTEGER NOT NULL,
    source_reference                 VARCHAR
)
"""

_DDL_DISRUPTIONS = """
CREATE TABLE IF NOT EXISTS disruptions (
    disruption_id   VARCHAR PRIMARY KEY,
    disruption_type VARCHAR NOT NULL,
    description     VARCHAR,
    window_start    TIMESTAMP NOT NULL,
    window_end      TIMESTAMP NOT NULL,
    severity        VARCHAR NOT NULL
)
"""

_DDL_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence_records (
    decision_id      VARCHAR PRIMARY KEY,
    timestamp        TIMESTAMP NOT NULL,
    decision_type    VARCHAR NOT NULL,
    shipment_id      VARCHAR NOT NULL,
    disruption_id    VARCHAR,
    policy_id        VARCHAR,
    reason_codes     VARCHAR NOT NULL,
    output           VARCHAR NOT NULL,
    confidence_score DOUBLE NOT NULL
)
"""

# Table name → minimum required columns (must all exist in the live schema).
REQUIRED_SCHEMA: dict[str, list[str]] = {
    "shipments": [
        "shipment_id", "cargo_type", "product_class", "temperature_policy_id",
        "origin_hub_id", "destination_hub_id", "current_node_id", "mode",
        "carrier_id", "planned_departure", "planned_arrival", "delivery_deadline",
        "cargo_value_usd", "weight_kg", "status",
    ],
    "assets": [
        "asset_id", "asset_type", "mode", "current_node_id", "available_at",
        "capacity_kg", "reefer_capable", "carrier_id", "status",
    ],
    "sensor_readings": [
        "sensor_id", "shipment_id", "ts", "temperature_c", "battery_pct",
    ],
    "policies": [
        "policy_id", "jurisdiction", "product_class", "min_celsius", "max_celsius",
        "max_continuous_excursion_minutes", "sample_interval_minutes", "source_reference",
    ],
    "disruptions": [
        "disruption_id", "disruption_type", "description",
        "window_start", "window_end", "severity",
    ],
    "evidence_records": [
        "decision_id", "timestamp", "decision_type", "shipment_id",
        "disruption_id", "policy_id", "reason_codes", "output", "confidence_score",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(dt: datetime) -> str:
    """Format a datetime as ``YYYY-MM-DD HH:MM:SS`` for DuckDB TIMESTAMP columns."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_connection() -> "_duckdb_t.DuckDBPyConnection":
    """Return a fresh in-memory DuckDB connection with all tables created.

    The connection is empty (no rows).  Use :func:`seed_from_demo_dataset` to
    populate it with the synthetic fixture data.

    Raises
    ------
    ImportError
        If ``duckdb`` is not installed.
    """
    try:
        import duckdb
    except ImportError as exc:
        raise ImportError(
            "duckdb is required — install with: pip install duckdb"
        ) from exc

    con = duckdb.connect(database=":memory:")
    for ddl in (
        _DDL_SHIPMENTS,
        _DDL_ASSETS,
        _DDL_SENSOR_READINGS,
        _DDL_POLICIES,
        _DDL_DISRUPTIONS,
        _DDL_EVIDENCE,
    ):
        con.execute(ddl)
    return con


def seed_from_demo_dataset(con: Any) -> None:
    """Populate *con* with every row from ``DEMO_DATASET``.

    The connection must already have the tables created (i.e. via
    :func:`create_connection`).  Calling this function on a connection that
    already has rows will raise a ``duckdb.ConstraintException`` for duplicate
    primary keys, which is intentional — this function is idempotent only when
    the tables are empty.

    Parameters
    ----------
    con:
        An open DuckDB connection (returned by :func:`create_connection`).
    """
    # Lazy import so the module can be imported even in environments without
    # the scripts/ directory on the path.
    from scripts.generate_synthetic_data import DEMO_DATASET  # noqa: PLC0415

    for shp in DEMO_DATASET["shipments"]:
        con.execute(
            "INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                shp.shipment_id,
                shp.cargo_type,
                shp.product_class,
                shp.temperature_policy_id,
                shp.origin_hub_id,
                shp.destination_hub_id,
                shp.current_node_id,
                shp.mode.value,
                shp.carrier_id,
                _ts(shp.planned_departure),
                _ts(shp.planned_arrival),
                _ts(shp.delivery_deadline),
                shp.cargo_value_usd,
                shp.weight_kg,
                shp.status.value,
            ],
        )

    for ast in DEMO_DATASET["assets"]:
        con.execute(
            "INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ast.asset_id,
                ast.asset_type.value,
                ast.mode.value,
                ast.current_node_id,
                _ts(ast.available_at),
                ast.capacity_kg,
                ast.reefer_capable,
                ast.carrier_id,
                ast.status.value,
            ],
        )

    for sr in DEMO_DATASET["sensor_readings"]:
        con.execute(
            "INSERT INTO sensor_readings VALUES (?,?,?,?,?)",
            [
                sr.sensor_id,
                sr.shipment_id,
                _ts(sr.ts),
                sr.temperature_c,
                sr.battery_pct,
            ],
        )

    for pol in DEMO_DATASET["policies"]:
        con.execute(
            "INSERT INTO policies VALUES (?,?,?,?,?,?,?,?)",
            [
                pol.policy_id,
                pol.jurisdiction,
                pol.product_class,
                pol.min_celsius,
                pol.max_celsius,
                pol.max_continuous_excursion_minutes,
                pol.sample_interval_minutes,
                pol.source_reference,
            ],
        )

    for dis in DEMO_DATASET["disruptions"]:
        con.execute(
            "INSERT INTO disruptions VALUES (?,?,?,?,?,?)",
            [
                dis.disruption_id,
                dis.disruption_type.value,
                dis.description,
                _ts(dis.window_start),
                _ts(dis.window_end),
                dis.severity,
            ],
        )

    import json as _json  # local import to avoid polluting module namespace

    for ev in DEMO_DATASET["evidence_records"]:
        con.execute(
            "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ev.decision_id,
                _ts(ev.timestamp),
                ev.decision_type.value,
                ev.shipment_id,
                ev.disruption_id,
                ev.policy_id,
                _json.dumps(ev.reason_codes),
                _json.dumps(ev.output, default=str),
                ev.confidence_score,
            ],
        )


def get_seeded_connection() -> "_duckdb_t.DuckDBPyConnection":
    """Convenience: create a connection and seed it in one call.

    Equivalent to::

        con = create_connection()
        seed_from_demo_dataset(con)

    Returns
    -------
    duckdb.DuckDBPyConnection
        An open, seeded in-memory connection.
    """
    con = create_connection()
    seed_from_demo_dataset(con)
    return con


def validate_schema(con: Any) -> list[str]:
    """Assert that every required table and column exists in *con*.

    Parameters
    ----------
    con:
        An open DuckDB connection.

    Returns
    -------
    list[str]
        A list of human-readable error strings.  An empty list means the
        schema is fully valid.
    """
    errors: list[str] = []

    # Retrieve actual schema from DuckDB's information_schema.
    rows = con.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
    ).fetchall()
    actual: dict[str, set[str]] = {}
    for table, column in rows:
        actual.setdefault(table, set()).add(column)

    for table, required_cols in REQUIRED_SCHEMA.items():
        if table not in actual:
            errors.append(f"table '{table}' is missing")
            continue
        for col in required_cols:
            if col not in actual[table]:
                errors.append(f"table '{table}' is missing column '{col}'")

    return errors
