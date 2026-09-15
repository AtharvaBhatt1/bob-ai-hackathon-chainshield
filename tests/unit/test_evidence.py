"""
tests/unit/test_evidence.py
===========================
Unit tests for src/app/evidence/events.py — the Evidence/Audit Layer.

Covered assertions
------------------
1.  build_record raises ValueError when reason_codes is empty.
2.  build_record raises ValueError when output is empty.
3.  Every recommendation has reason codes (non-empty list[str]).
4.  Every recommendation has evidence (non-empty output dict).
5.  Evidence records are JSON-serialisable (round-trip via json.dumps/loads).
6.  content_hash is stable for identical inputs (reproducibility).
7.  content_hash differs when any content field changes.
8.  EvidenceStore.emit persists a record; EvidenceStore.get retrieves it.
9.  Retrieved record fields match the emitted record exactly.
10. list_for_shipment returns all records for that shipment in order.
11. list_for_shipment returns empty list for unknown shipment.
12. get returns None for unknown decision_id.
13. emit → get round-trip preserves reason_codes and output faithfully.
14. Records for all four DecisionTypes are accepted.
15. EvidenceStore with auto-created connection (con=None) works.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from src.app.core.models import DecisionType, EvidenceRecord
from src.app.evidence.events import EvidenceStore, build_record, content_hash


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store():
    """Fresh in-memory EvidenceStore for each test."""
    return EvidenceStore()  # con=None → auto in-memory DuckDB


@pytest.fixture()
def impact_record():
    return build_record(
        decision_type=DecisionType.IMPACT,
        shipment_id="SHP-0042",
        reason_codes=["PORT_NODE_BLOCKED", "ETA_SLA_BREACH"],
        output={"affected_shipments": ["SHP-0042"], "max_delay_hours": 36},
        confidence_score=0.95,
        disruption_id="PORT_STRIKE_01",
    )


@pytest.fixture()
def cold_chain_record():
    return build_record(
        decision_type=DecisionType.COLD_CHAIN,
        shipment_id="SHP-0042",
        reason_codes=["TEMPERATURE_EXPOSURE_INCREASED"],
        output={"severity": "EXCURSION_REVIEW", "max_c": 10.4, "duration_minutes": 18},
        confidence_score=1.0,
        policy_id="POL-CDC-01",
    )


# ---------------------------------------------------------------------------
# 1–2. build_record validation
# ---------------------------------------------------------------------------

def test_build_record_empty_reason_codes_raises():
    with pytest.raises(ValueError, match="reason_codes must not be empty"):
        build_record(
            decision_type=DecisionType.ROUTE,
            shipment_id="SHP-0001",
            reason_codes=[],
            output={"route": "HUB-A→HUB-D"},
            confidence_score=0.8,
        )


def test_build_record_empty_output_raises():
    with pytest.raises(ValueError, match="output must not be empty"):
        build_record(
            decision_type=DecisionType.ROUTE,
            shipment_id="SHP-0001",
            reason_codes=["REEFER_CAPACITY_AVAILABLE"],
            output={},
            confidence_score=0.8,
        )


# ---------------------------------------------------------------------------
# 3–4. Every recommendation has reason codes and evidence
# ---------------------------------------------------------------------------

def test_every_recommendation_has_reason_codes(impact_record, cold_chain_record):
    """Reason codes list must be non-empty for every built record."""
    for rec in (impact_record, cold_chain_record):
        assert isinstance(rec.reason_codes, list), "reason_codes must be a list"
        assert len(rec.reason_codes) > 0, "reason_codes must not be empty"
        assert all(isinstance(c, str) for c in rec.reason_codes), (
            "each reason code must be a string"
        )


def test_every_recommendation_has_evidence(impact_record, cold_chain_record):
    """Output dict must be non-empty for every built record."""
    for rec in (impact_record, cold_chain_record):
        assert isinstance(rec.output, dict), "output must be a dict"
        assert len(rec.output) > 0, "output must not be empty"


# ---------------------------------------------------------------------------
# 5. JSON serialisability
# ---------------------------------------------------------------------------

def test_evidence_record_is_json_serialisable(impact_record):
    """model.model_dump() must round-trip through json.dumps/loads without error."""
    dumped = impact_record.model_dump()
    serialised = json.dumps(dumped, default=str)
    loaded = json.loads(serialised)
    assert loaded["shipment_id"] == impact_record.shipment_id
    assert loaded["reason_codes"] == impact_record.reason_codes
    assert loaded["output"] == impact_record.output


# ---------------------------------------------------------------------------
# 6–7. Reproducibility via content_hash
# ---------------------------------------------------------------------------

def test_content_hash_stable_for_identical_inputs():
    """Two records built from identical inputs must have the same content hash."""
    kwargs = dict(
        decision_type=DecisionType.IMPACT,
        shipment_id="SHP-0042",
        reason_codes=["PORT_NODE_BLOCKED"],
        output={"affected_shipments": ["SHP-0042"]},
        confidence_score=0.9,
        disruption_id="D-01",
    )
    rec_a = build_record(**kwargs)
    rec_b = build_record(**kwargs)
    # decision_id and timestamp differ; content hash must be the same
    assert rec_a.decision_id != rec_b.decision_id, "UUIDs must be distinct"
    assert content_hash(rec_a) == content_hash(rec_b)


def test_content_hash_differs_on_changed_reason_code():
    base = dict(
        decision_type=DecisionType.IMPACT,
        shipment_id="SHP-0042",
        reason_codes=["PORT_NODE_BLOCKED"],
        output={"detail": "x"},
        confidence_score=0.9,
    )
    rec_a = build_record(**base)
    rec_b = build_record(**{**base, "reason_codes": ["ETA_SLA_BREACH"]})
    assert content_hash(rec_a) != content_hash(rec_b)


def test_content_hash_differs_on_changed_output():
    base = dict(
        decision_type=DecisionType.COLD_CHAIN,
        shipment_id="SHP-0042",
        reason_codes=["TEMPERATURE_EXPOSURE_INCREASED"],
        output={"severity": "SAFE"},
        confidence_score=1.0,
    )
    rec_a = build_record(**base)
    rec_b = build_record(**{**base, "output": {"severity": "EXCURSION_REVIEW"}})
    assert content_hash(rec_a) != content_hash(rec_b)


def test_content_hash_differs_on_changed_confidence():
    base = dict(
        decision_type=DecisionType.ASSET,
        shipment_id="SHP-0042",
        reason_codes=["REEFER_CAPACITY_AVAILABLE"],
        output={"asset_id": "TRUCK-17"},
        confidence_score=1.0,
    )
    rec_a = build_record(**base)
    rec_b = build_record(**{**base, "confidence_score": 0.5})
    assert content_hash(rec_a) != content_hash(rec_b)


# ---------------------------------------------------------------------------
# 8–9. EvidenceStore emit/get
# ---------------------------------------------------------------------------

def test_store_emit_and_get(store, impact_record):
    returned = store.emit(impact_record)
    assert returned is impact_record, "emit must return the same record object"
    fetched = store.get(impact_record.decision_id)
    assert fetched is not None
    assert fetched.decision_id == impact_record.decision_id
    assert fetched.shipment_id == impact_record.shipment_id
    assert fetched.decision_type == impact_record.decision_type
    assert fetched.reason_codes == impact_record.reason_codes
    assert fetched.output == impact_record.output
    assert fetched.confidence_score == pytest.approx(impact_record.confidence_score)
    assert fetched.disruption_id == impact_record.disruption_id


def test_store_get_unknown_returns_none(store):
    assert store.get(str(uuid.uuid4())) is None


# ---------------------------------------------------------------------------
# 10–11. list_for_shipment
# ---------------------------------------------------------------------------

def test_list_for_shipment_returns_all_records(store, impact_record, cold_chain_record):
    store.emit(impact_record)
    store.emit(cold_chain_record)
    records = store.list_for_shipment("SHP-0042")
    ids = {r.decision_id for r in records}
    assert impact_record.decision_id in ids
    assert cold_chain_record.decision_id in ids


def test_list_for_shipment_empty_for_unknown(store):
    assert store.list_for_shipment("SHP-NONEXISTENT") == []


def test_list_for_shipment_excludes_other_shipments(store):
    rec_a = build_record(
        decision_type=DecisionType.IMPACT,
        shipment_id="SHP-AAA",
        reason_codes=["PORT_NODE_BLOCKED"],
        output={"detail": "a"},
        confidence_score=0.8,
    )
    rec_b = build_record(
        decision_type=DecisionType.IMPACT,
        shipment_id="SHP-BBB",
        reason_codes=["ETA_SLA_BREACH"],
        output={"detail": "b"},
        confidence_score=0.7,
    )
    store.emit(rec_a)
    store.emit(rec_b)
    results = store.list_for_shipment("SHP-AAA")
    assert all(r.shipment_id == "SHP-AAA" for r in results)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# 12. Round-trip fidelity: reason_codes and output
# ---------------------------------------------------------------------------

def test_round_trip_preserves_reason_codes_and_output(store):
    rec = build_record(
        decision_type=DecisionType.COLD_CHAIN,
        shipment_id="SHP-ROUNDTRIP",
        reason_codes=["TEMPERATURE_EXPOSURE_INCREASED", "ETA_SLA_BREACH"],
        output={"severity": "EXCURSION_REVIEW", "max_c": 10.4, "out_of_range_readings": 3},
        confidence_score=0.99,
        policy_id="POL-CDC-01",
    )
    store.emit(rec)
    fetched = store.get(rec.decision_id)
    assert fetched.reason_codes == rec.reason_codes
    assert fetched.output == rec.output
    assert fetched.policy_id == rec.policy_id


# ---------------------------------------------------------------------------
# 13. All four DecisionTypes are accepted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dtype", list(DecisionType))
def test_all_decision_types_accepted(store, dtype):
    rec = build_record(
        decision_type=dtype,
        shipment_id="SHP-TYPE-TEST",
        reason_codes=["TEST_REASON_CODE"],
        output={"test": True},
        confidence_score=0.5,
    )
    store.emit(rec)
    fetched = store.get(rec.decision_id)
    assert fetched is not None
    assert fetched.decision_type == dtype


# ---------------------------------------------------------------------------
# 14. Auto-created in-memory connection (con=None)
# ---------------------------------------------------------------------------

def test_store_autocreates_connection():
    """EvidenceStore() with no arguments should self-provision a DuckDB connection."""
    s = EvidenceStore()
    rec = build_record(
        decision_type=DecisionType.ROUTE,
        shipment_id="SHP-AUTO",
        reason_codes=["REEFER_CAPACITY_AVAILABLE"],
        output={"carrier": "CARRIER-B", "eta_delta_hours": 2},
        confidence_score=0.85,
    )
    s.emit(rec)
    assert s.get(rec.decision_id) is not None
