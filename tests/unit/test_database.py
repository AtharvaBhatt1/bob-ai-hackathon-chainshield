"""
tests/unit/test_database.py
============================
Unit tests for src/app/core/database.py — the local DuckDB demo store.

Coverage
--------
- ``create_connection``: tables are created, schema is valid, no rows yet.
- ``validate_schema``: passes on a fresh connection, catches missing tables/columns.
- ``seed_from_demo_dataset``: all six tables are seeded, row counts match the
  synthetic fixture expectations, referential integrity holds.
- ``get_seeded_connection``: convenience wrapper works end-to-end.
- Targeted queries: demo scenarios required by the preflight validator are
  reachable from the database layer (disrupted shipment, idle reefer asset,
  cold-chain policy, excursion readings, PORT_STRIKE_01 disruption).

No network access.  All data comes from DEMO_DATASET (in-memory).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so ``from src...`` and ``from scripts...``
# imports both resolve whether tests are run from the repo root or elsewhere.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Guard: skip all tests gracefully if duckdb is not installed.
# ---------------------------------------------------------------------------
duckdb = pytest.importorskip("duckdb", reason="duckdb not installed — pip install duckdb")

from src.app.core.database import (  # noqa: E402
    REQUIRED_SCHEMA,
    create_connection,
    get_seeded_connection,
    seed_from_demo_dataset,
    validate_schema,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(scope="module")
def empty_con():
    """A freshly created connection with tables but no rows."""
    con = create_connection()
    yield con
    con.close()


@pytest.fixture(scope="module")
def seeded_con():
    """A connection fully seeded with the synthetic demo dataset."""
    con = get_seeded_connection()
    yield con
    con.close()


# ===========================================================================
# create_connection — tables exist, schema is clean, no rows yet
# ===========================================================================

class TestCreateConnection:
    def test_returns_duckdb_connection(self, empty_con):
        # Should have the standard fetchone API.
        result = empty_con.execute("SELECT 1").fetchone()
        assert result == (1,)

    def test_all_required_tables_exist(self, empty_con):
        tables = {
            row[0]
            for row in empty_con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        for table in REQUIRED_SCHEMA:
            assert table in tables, f"table '{table}' not found after create_connection()"

    def test_tables_start_empty(self, empty_con):
        for table in REQUIRED_SCHEMA:
            count = empty_con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"table '{table}' should be empty, found {count} rows"

    def test_shipments_columns(self, empty_con):
        cols = {
            row[0]
            for row in empty_con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'shipments'"
            ).fetchall()
        }
        for col in REQUIRED_SCHEMA["shipments"]:
            assert col in cols

    def test_assets_columns(self, empty_con):
        cols = {
            row[0]
            for row in empty_con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'assets'"
            ).fetchall()
        }
        for col in REQUIRED_SCHEMA["assets"]:
            assert col in cols

    def test_sensor_readings_columns(self, empty_con):
        cols = {
            row[0]
            for row in empty_con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sensor_readings'"
            ).fetchall()
        }
        for col in REQUIRED_SCHEMA["sensor_readings"]:
            assert col in cols

    def test_policies_columns(self, empty_con):
        cols = {
            row[0]
            for row in empty_con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'policies'"
            ).fetchall()
        }
        for col in REQUIRED_SCHEMA["policies"]:
            assert col in cols

    def test_disruptions_columns(self, empty_con):
        cols = {
            row[0]
            for row in empty_con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'disruptions'"
            ).fetchall()
        }
        for col in REQUIRED_SCHEMA["disruptions"]:
            assert col in cols

    def test_evidence_records_columns(self, empty_con):
        cols = {
            row[0]
            for row in empty_con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'evidence_records'"
            ).fetchall()
        }
        for col in REQUIRED_SCHEMA["evidence_records"]:
            assert col in cols


# ===========================================================================
# validate_schema — pass on valid connection, catch regressions
# ===========================================================================

class TestValidateSchema:
    def test_valid_connection_returns_no_errors(self, empty_con):
        errors = validate_schema(empty_con)
        assert errors == [], f"unexpected schema errors: {errors}"

    def test_missing_table_detected(self):
        """Drop a table and verify validate_schema reports it."""
        con = create_connection()
        try:
            con.execute("DROP TABLE evidence_records")
            errors = validate_schema(con)
            assert any("evidence_records" in e for e in errors), (
                f"missing table not reported; errors: {errors}"
            )
        finally:
            con.close()

    def test_missing_column_detected(self):
        """Create a crippled version of shipments and verify the column error."""
        con = duckdb.connect(database=":memory:")
        try:
            # Create shipments WITHOUT 'status'
            con.execute(
                "CREATE TABLE shipments (shipment_id VARCHAR PRIMARY KEY, cargo_type VARCHAR)"
            )
            errors = validate_schema(con)
            assert any(
                "shipments" in e and "status" in e for e in errors
            ), f"missing column 'status' not reported; errors: {errors}"
        finally:
            con.close()

    def test_seeded_connection_passes_validation(self, seeded_con):
        errors = validate_schema(seeded_con)
        assert errors == [], f"seeded connection has schema errors: {errors}"


# ===========================================================================
# seed_from_demo_dataset — row counts and referential integrity
# ===========================================================================

class TestSeedFromDemoDataset:
    def test_shipments_row_count(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        assert count >= 2, f"expected ≥2 shipments, found {count}"

    def test_assets_row_count(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        assert count >= 4, f"expected ≥4 assets, found {count}"

    def test_sensor_readings_row_count(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
        assert count >= 5, f"expected ≥5 sensor readings, found {count}"

    def test_policies_row_count(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
        assert count >= 2, f"expected ≥2 policies, found {count}"

    def test_disruptions_row_count(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM disruptions").fetchone()[0]
        assert count >= 1, f"expected ≥1 disruption, found {count}"

    def test_evidence_records_row_count(self, seeded_con):
        count = seeded_con.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0]
        assert count >= 4, f"expected ≥4 evidence records, found {count}"

    def test_no_orphan_sensor_readings(self, seeded_con):
        orphans = seeded_con.execute(
            """
            SELECT COUNT(*) FROM sensor_readings sr
            LEFT JOIN shipments s ON sr.shipment_id = s.shipment_id
            WHERE s.shipment_id IS NULL
            """
        ).fetchone()[0]
        assert orphans == 0, f"{orphans} sensor reading(s) reference an unknown shipment_id"

    def test_no_orphan_evidence_records(self, seeded_con):
        orphans = seeded_con.execute(
            """
            SELECT COUNT(*) FROM evidence_records er
            LEFT JOIN shipments s ON er.shipment_id = s.shipment_id
            WHERE s.shipment_id IS NULL
            """
        ).fetchone()[0]
        assert orphans == 0, f"{orphans} evidence record(s) reference an unknown shipment_id"

    def test_duplicate_seed_raises(self):
        """Seeding the same data twice must fail with a primary-key violation."""
        con = create_connection()
        seed_from_demo_dataset(con)
        with pytest.raises(Exception):  # duckdb.ConstraintException or similar
            seed_from_demo_dataset(con)
        con.close()


# ===========================================================================
# get_seeded_connection — convenience wrapper
# ===========================================================================

class TestGetSeededConnection:
    def test_returns_populated_connection(self):
        con = get_seeded_connection()
        try:
            count = con.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
            assert count >= 2
        finally:
            con.close()

    def test_schema_valid_after_convenience_call(self):
        con = get_seeded_connection()
        try:
            errors = validate_schema(con)
            assert errors == []
        finally:
            con.close()


# ===========================================================================
# Demo scenario queries — mirror the assertions in scripts/seed_demo.py and
# scripts/preflight_demo.py so database.py supports the same guarantees.
# ===========================================================================

class TestDemoScenarioQueries:
    def test_disrupted_shipment_in_transit(self, seeded_con):
        """SHP-0042 must be IN_TRANSIT in the seeded database."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM shipments "
            "WHERE shipment_id = 'SHP-0042' AND status = 'IN_TRANSIT'"
        ).fetchone()[0]
        assert count == 1, "disrupted shipment SHP-0042 not found with status IN_TRANSIT"

    def test_unaffected_shipment_present(self, seeded_con):
        """SHP-0099 (bypass route) must exist."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM shipments WHERE shipment_id = 'SHP-0099'"
        ).fetchone()[0]
        assert count == 1, "unaffected shipment SHP-0099 not found"

    def test_idle_reefer_asset_truck_17(self, seeded_con):
        """TRUCK-17 must be reefer-capable and available."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM assets "
            "WHERE asset_id = 'TRUCK-17' AND reefer_capable = TRUE AND status = 'available'"
        ).fetchone()[0]
        assert count == 1, "idle reefer asset TRUCK-17 not found"

    def test_cold_chain_shipment_has_policy(self, seeded_con):
        """At least one shipment must have a temperature_policy_id."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM shipments WHERE temperature_policy_id IS NOT NULL"
        ).fetchone()[0]
        assert count >= 1, "no cold-chain shipment with temperature_policy_id found"

    def test_excursion_sensor_readings_exist(self, seeded_con):
        """At least one reading must be outside the 2–8 °C policy window."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM sensor_readings "
            "WHERE temperature_c > 8.0 OR temperature_c < 2.0"
        ).fetchone()[0]
        assert count >= 1, "no out-of-range sensor readings found"

    def test_port_strike_01_present(self, seeded_con):
        """The canonical demo disruption PORT_STRIKE_01 must be present."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM disruptions WHERE disruption_id = 'PORT_STRIKE_01'"
        ).fetchone()[0]
        assert count == 1, "disruption PORT_STRIKE_01 not found"

    def test_policy_pol_cdc_01_present(self, seeded_con):
        """The reference cold-chain policy POL-CDC-01 must be in the policies table."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM policies WHERE policy_id = 'POL-CDC-01'"
        ).fetchone()[0]
        assert count == 1, "policy POL-CDC-01 not found"

    def test_policy_temperature_range_accessible(self, seeded_con):
        """POL-CDC-01 thresholds are stored and queryable (not hardcoded in logic)."""
        row = seeded_con.execute(
            "SELECT min_celsius, max_celsius FROM policies WHERE policy_id = 'POL-CDC-01'"
        ).fetchone()
        assert row is not None, "POL-CDC-01 missing from policies"
        min_c, max_c = row
        assert min_c < max_c, "min_celsius must be less than max_celsius"

    def test_evidence_record_for_cold_chain_exists(self, seeded_con):
        """At least one COLD_CHAIN evidence record must exist."""
        count = seeded_con.execute(
            "SELECT COUNT(*) FROM evidence_records WHERE decision_type = 'COLD_CHAIN'"
        ).fetchone()[0]
        assert count >= 1, "no COLD_CHAIN evidence record found"

    def test_confidence_scores_in_range(self, seeded_con):
        """All evidence record confidence scores must be in [0.0, 1.0]."""
        out_of_range = seeded_con.execute(
            "SELECT COUNT(*) FROM evidence_records "
            "WHERE confidence_score < 0.0 OR confidence_score > 1.0"
        ).fetchone()[0]
        assert out_of_range == 0, f"{out_of_range} evidence record(s) with out-of-range confidence"

    def test_shipment_timestamps_ordered(self, seeded_con):
        """planned_departure must always precede planned_arrival."""
        bad = seeded_con.execute(
            "SELECT COUNT(*) FROM shipments WHERE planned_departure >= planned_arrival"
        ).fetchone()[0]
        assert bad == 0, f"{bad} shipment(s) with planned_departure >= planned_arrival"

    def test_disruption_window_ordered(self, seeded_con):
        """window_start must precede window_end for every disruption."""
        bad = seeded_con.execute(
            "SELECT COUNT(*) FROM disruptions WHERE window_start >= window_end"
        ).fetchone()[0]
        assert bad == 0, f"{bad} disruption(s) with window_start >= window_end"
