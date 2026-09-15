# Task 03 — DuckDB

## Objective

Implement the local DuckDB demo store for ChainShield using an in-memory database and the documented synthetic data schema.

## Files Created or Modified

- `src/app/core/database.py`
- `tests/unit/test_database.py`

## Major Implementation Decisions

- Implemented the DuckDB demo store using an in-memory `:memory:` connection.
- Added `create_connection()` to create a fresh DuckDB connection and initialize the required tables.
- Added `seed_from_demo_dataset(con)` to load the deterministic synthetic `DEMO_DATASET`.
- Added `get_seeded_connection()` as a convenience wrapper that creates and seeds a database.
- Added `validate_schema(con)` to inspect `information_schema.columns` and report missing tables or columns.
- Defined `REQUIRED_SCHEMA` as a single source of truth for the required table and column definitions.
- Used lazy DuckDB importing so the module can be imported cleanly when the dependency is unavailable.
- Kept the implementation fully offline with no FastAPI, network access, or disk I/O in the core database module.
- Matched the database column names with the existing `models.py` and `preflight_demo.py` schema.
- Added tests for schema creation, validation, seeding, referential integrity, duplicate handling, and the canonical demo scenario data.

## Tests Run

```text
36 new DuckDB/database tests
159 total tests across the suite

36/36 new tests passed

159/159 total tests passed

