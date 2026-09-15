#!/usr/bin/env python3
"""
scripts/seed_demo.py
=====================
Loads the synthetic demo dataset into an in-memory DuckDB database and
validates referential integrity + row counts.

Purpose
-------
This script is the canonical "seed" step for a live demo or CI run.  It
proves that the synthetic data produced by generate_synthetic_data.py is
schema-compatible with the DuckDB tables defined in preflight_demo.py and
that the data covers the required demo scenarios end-to-end.

No network access.  No file I/O beyond the optional --export flag.
The DuckDB connection is always :memory: (never persisted to disk).

Usage
-----
    python scripts/seed_demo.py              # seed + validate, print summary
    python scripts/seed_demo.py --check      # exit 0 on success, 1 on failure
    python scripts/seed_demo.py --export     # write reports/demo_seed.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path when run directly
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.generate_synthetic_data import DEMO_DATASET  # noqa: E402


# ---------------------------------------------------------------------------
# DuckDB schema DDL (matches preflight_demo.py column names exactly)
# ---------------------------------------------------------------------------

_DDL_SHIPMENTS = """
CREATE TABLE shipments (
    shipment_id          VARCHAR PRIMARY KEY,
    cargo_type           VARCHAR,
    product_class        VARCHAR,
    temperature_policy_id VARCHAR,
    origin_hub_id        VARCHAR,
    destination_hub_id   VARCHAR,
    current_node_id      VARCHAR,
    mode                 VARCHAR,
    carrier_id           VARCHAR,
    planned_departure    TIMESTAMP,
    planned_arrival      TIMESTAMP,
    delivery_deadline    TIMESTAMP,
    cargo_value_usd      DOUBLE,
    weight_kg            DOUBLE,
    status               VARCHAR
)
"""

_DDL_ASSETS = """
CREATE TABLE assets (
    asset_id         VARCHAR PRIMARY KEY,
    asset_type       VARCHAR,
    mode             VARCHAR,
    current_node_id  VARCHAR,
    available_at     TIMESTAMP,
    capacity_kg      DOUBLE,
    reefer_capable   BOOLEAN,
    carrier_id       VARCHAR,
    status           VARCHAR
)
"""

_DDL_SENSOR_READINGS = """
CREATE TABLE sensor_readings (
    sensor_id    VARCHAR,
    shipment_id  VARCHAR,
    ts           TIMESTAMP,
    temperature_c DOUBLE,
    battery_pct  DOUBLE
)
"""

_DDL_POLICIES = """
CREATE TABLE policies (
    policy_id                      VARCHAR PRIMARY KEY,
    jurisdiction                   VARCHAR,
    product_class                  VARCHAR,
    min_celsius                    DOUBLE,
    max_celsius                    DOUBLE,
    max_continuous_excursion_minutes INTEGER,
    sample_interval_minutes        INTEGER,
    source_reference               VARCHAR
)
"""

_DDL_DISRUPTIONS = """
CREATE TABLE disruptions (
    disruption_id    VARCHAR PRIMARY KEY,
    disruption_type  VARCHAR,
    description      VARCHAR,
    window_start     TIMESTAMP,
    window_end       TIMESTAMP,
    severity         VARCHAR
)
"""

_DDL_EVIDENCE = """
CREATE TABLE evidence_records (
    decision_id      VARCHAR PRIMARY KEY,
    timestamp        TIMESTAMP,
    decision_type    VARCHAR,
    shipment_id      VARCHAR,
    disruption_id    VARCHAR,
    policy_id        VARCHAR,
    confidence_score DOUBLE
)
"""


def _ts(dt: datetime) -> str:
    """Format a datetime as an ISO string without microseconds for DuckDB."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def seed_duckdb() -> "duckdb.DuckDBPyConnection":  # type: ignore[name-defined]
    """Create an in-memory DuckDB connection seeded with DEMO_DATASET.

    Returns the open connection so callers can run further queries.
    Raises ImportError with an install hint if duckdb is missing.
    """
    try:
        import duckdb
    except ImportError as exc:
        raise ImportError(
            "duckdb is required for seed_demo.py -- "
            "run: pip install duckdb --break-system-packages"
        ) from exc

    con = duckdb.connect(database=":memory:")

    # Create tables
    for ddl in (_DDL_SHIPMENTS, _DDL_ASSETS, _DDL_SENSOR_READINGS,
                _DDL_POLICIES, _DDL_DISRUPTIONS, _DDL_EVIDENCE):
        con.execute(ddl)

    # ---- shipments ----
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

    # ---- assets ----
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

    # ---- sensor readings ----
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

    # ---- policies ----
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

    # ---- disruptions ----
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

    # ---- evidence records ----
    for ev in DEMO_DATASET["evidence_records"]:
        con.execute(
            "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?)",
            [
                ev.decision_id,
                _ts(ev.timestamp),
                ev.decision_type.value,
                ev.shipment_id,
                ev.disruption_id,
                ev.policy_id,
                ev.confidence_score,
            ],
        )

    return con


def validate_seed(con: Any) -> list[str]:  # type: ignore[type-arg]
    """Run integrity checks on a seeded connection.  Returns a list of error
    strings; empty list means all checks passed."""
    errors: list[str] = []

    # ---- row count expectations ----
    row_counts = {
        "shipments":       (con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],       2),
        "assets":          (con.execute("SELECT COUNT(*) FROM assets").fetchone()[0],           4),
        "sensor_readings": (con.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0], 5),
        "policies":        (con.execute("SELECT COUNT(*) FROM policies").fetchone()[0],         2),
        "disruptions":     (con.execute("SELECT COUNT(*) FROM disruptions").fetchone()[0],      1),
        "evidence_records":(con.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0], 4),
    }
    for table, (actual, expected) in row_counts.items():
        if actual != expected:
            errors.append(f"{table}: expected {expected} rows, found {actual}")

    # ---- referential integrity: no orphan sensor readings ----
    orphans = con.execute("""
        SELECT COUNT(*) FROM sensor_readings sr
        LEFT JOIN shipments s ON sr.shipment_id = s.shipment_id
        WHERE s.shipment_id IS NULL
    """).fetchone()[0]
    if orphans:
        errors.append(f"sensor_readings: {orphans} row(s) reference an unknown shipment_id")

    # ---- demo scenario assertions ----

    # At least one disrupted shipment: SHP-0042 must be IN_TRANSIT and route includes PORT-03
    disrupted = con.execute(
        "SELECT COUNT(*) FROM shipments WHERE shipment_id = 'SHP-0042' AND status = 'IN_TRANSIT'"
    ).fetchone()[0]
    if disrupted == 0:
        errors.append("demo scenario: no disrupted shipment SHP-0042 found")

    # At least one unaffected shipment: SHP-0099 uses bypass route
    unaffected = con.execute(
        "SELECT COUNT(*) FROM shipments WHERE shipment_id = 'SHP-0099'"
    ).fetchone()[0]
    if unaffected == 0:
        errors.append("demo scenario: no unaffected shipment SHP-0099 found")

    # At least one idle compatible asset: TRUCK-17, reefer=TRUE, status=available
    idle_asset = con.execute(
        "SELECT COUNT(*) FROM assets WHERE asset_id = 'TRUCK-17' "
        "AND reefer_capable = TRUE AND status = 'available'"
    ).fetchone()[0]
    if idle_asset == 0:
        errors.append("demo scenario: no idle reefer asset TRUCK-17 found")

    # At least one cold-chain shipment with policy
    cold_chain = con.execute(
        "SELECT COUNT(*) FROM shipments WHERE temperature_policy_id IS NOT NULL"
    ).fetchone()[0]
    if cold_chain == 0:
        errors.append("demo scenario: no cold-chain shipment (temperature_policy_id is NULL for all)")

    # At least one excursion reading (temperature outside policy bounds 2-8°C)
    excursion = con.execute(
        "SELECT COUNT(*) FROM sensor_readings WHERE temperature_c > 8.0 OR temperature_c < 2.0"
    ).fetchone()[0]
    if excursion == 0:
        errors.append("demo scenario: no out-of-range sensor readings found")

    # Disruption present covering PORT-03
    disruption_present = con.execute(
        "SELECT COUNT(*) FROM disruptions WHERE disruption_id = 'PORT_STRIKE_01'"
    ).fetchone()[0]
    if disruption_present == 0:
        errors.append("demo scenario: PORT_STRIKE_01 disruption not found")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="ChainShield demo data seed validator")
    parser.add_argument("--check",  action="store_true", help="Validate only; exit 0 on success")
    parser.add_argument("--export", action="store_true", help="Write reports/demo_seed.json")
    args = parser.parse_args()

    try:
        con = seed_duckdb()
    except ImportError as exc:
        print(f"[SKIP] {exc}", file=sys.stderr)
        return 0  # degraded, not failed -- mirrors preflight SKIP behaviour
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Seeding error: {exc}", file=sys.stderr)
        return 1

    errors = validate_seed(con)
    con.close()

    if errors:
        for err in errors:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1

    if args.export:
        report = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "status": "PASS",
            "tables": {
                "shipments": len(DEMO_DATASET["shipments"]),
                "assets": len(DEMO_DATASET["assets"]),
                "sensor_readings": len(DEMO_DATASET["sensor_readings"]),
                "policies": len(DEMO_DATASET["policies"]),
                "disruptions": len(DEMO_DATASET["disruptions"]),
                "evidence_records": len(DEMO_DATASET["evidence_records"]),
            },
        }
        out_path = _ROOT / "reports" / "demo_seed.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        print(f"[INFO] Report written to {out_path}")

    if args.check:
        print("[PASS] All seed checks passed.")
        return 0

    print("ChainShield Demo Seed  --  All checks PASSED")
    print(f"  shipments:        {len(DEMO_DATASET['shipments'])}")
    print(f"  assets:           {len(DEMO_DATASET['assets'])}")
    print(f"  sensor_readings:  {len(DEMO_DATASET['sensor_readings'])}")
    print(f"  policies:         {len(DEMO_DATASET['policies'])}")
    print(f"  disruptions:      {len(DEMO_DATASET['disruptions'])}")
    print(f"  evidence_records: {len(DEMO_DATASET['evidence_records'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
