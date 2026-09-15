"""
src/app/evidence/events.py
==========================
Evidence/Audit Layer for ChainShield.

Every operational decision produced by the deterministic engines (Impact,
Optimization, Cold-Chain) must call :func:`emit` so an immutable audit record
is persisted and available for replay or inspection.

Design constraints
------------------
- Pure deterministic logic — no LLM, no Cloudant, no network calls.
- DuckDB in-memory (``:memory:``) is the backing store for the offline MVP.
- Every :class:`~src.app.core.models.EvidenceRecord` is JSON-serialisable.
- ``reason_codes`` and ``output`` are stored as JSON text in DuckDB and
  round-tripped faithfully on retrieval.
- Identical inputs (same decision_type / shipment_id / input_ids / reason_codes
  / output / confidence) always produce records whose *content* is identical —
  only the ``decision_id`` (UUID) and ``timestamp`` differ by design, because
  every call is a new decision event. Reproducibility is verified through the
  content hash helper :func:`content_hash`.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.app.core.logging import get_logger
from src.app.core.models import DecisionType, EvidenceRecord

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# DuckDB DDL — extended schema with reason_codes and output columns
# ---------------------------------------------------------------------------

_DDL_EVIDENCE_EXTENDED = """
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts(dt: datetime) -> str:
    """Format *dt* as ``YYYY-MM-DD HH:MM:SS`` for DuckDB TIMESTAMP columns."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _row_to_record(row: tuple) -> EvidenceRecord:
    """Reconstruct an :class:`EvidenceRecord` from a DuckDB result row.

    Column order must match the SELECT in :func:`EvidenceStore.get` and
    :func:`EvidenceStore.list_for_shipment`.
    """
    (
        decision_id,
        timestamp,
        decision_type,
        shipment_id,
        disruption_id,
        policy_id,
        reason_codes_json,
        output_json,
        confidence_score,
    ) = row
    return EvidenceRecord(
        decision_id=decision_id,
        timestamp=datetime.fromisoformat(str(timestamp)).replace(tzinfo=timezone.utc)
        if isinstance(timestamp, str)
        else timestamp.replace(tzinfo=timezone.utc),
        decision_type=DecisionType(decision_type),
        shipment_id=shipment_id,
        disruption_id=disruption_id,
        policy_id=policy_id,
        reason_codes=json.loads(reason_codes_json),
        output=json.loads(output_json),
        confidence_score=confidence_score,
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def build_record(
    *,
    decision_type: DecisionType,
    shipment_id: str,
    reason_codes: list[str],
    output: dict[str, Any],
    confidence_score: float,
    disruption_id: str | None = None,
    policy_id: str | None = None,
) -> EvidenceRecord:
    """Construct an :class:`EvidenceRecord` without persisting it.

    Useful for unit-testing engine output before committing to the store.

    Parameters
    ----------
    decision_type:
        The engine that produced this decision.
    shipment_id:
        The shipment this decision relates to.
    reason_codes:
        Non-empty list of ``SCREAMING_SNAKE_CASE`` reason codes.
    output:
        Serialisable dict containing the recommendation or classification.
    confidence_score:
        Deterministic confidence in ``[0.0, 1.0]``.
    disruption_id:
        Optional disruption FK.
    policy_id:
        Optional policy profile FK.

    Returns
    -------
    EvidenceRecord
        A fully-formed, not-yet-persisted evidence record.

    Raises
    ------
    ValueError
        If *reason_codes* is empty or *output* is empty.
    """
    if not reason_codes:
        raise ValueError(
            f"reason_codes must not be empty for decision_type={decision_type.value} "
            f"shipment_id={shipment_id}"
        )
    if not output:
        raise ValueError(
            f"output must not be empty for decision_type={decision_type.value} "
            f"shipment_id={shipment_id}"
        )
    return EvidenceRecord(
        decision_id=str(uuid.uuid4()),
        timestamp=datetime.now(tz=timezone.utc),
        decision_type=decision_type,
        shipment_id=shipment_id,
        disruption_id=disruption_id,
        policy_id=policy_id,
        reason_codes=reason_codes,
        output=output,
        confidence_score=confidence_score,
    )


def content_hash(record: EvidenceRecord) -> str:
    """Return a stable hex digest of the *content* of *record*.

    The hash covers every field except ``decision_id`` and ``timestamp`` so
    that two records produced from identical inputs have the same hash,
    confirming reproducibility.

    Parameters
    ----------
    record:
        The evidence record to hash.

    Returns
    -------
    str
        SHA-256 hex digest of the canonical JSON representation.
    """
    payload = {
        "decision_type": record.decision_type.value,
        "shipment_id": record.shipment_id,
        "disruption_id": record.disruption_id,
        "policy_id": record.policy_id,
        "reason_codes": sorted(record.reason_codes),
        "output": record.output,
        "confidence_score": record.confidence_score,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# EvidenceStore
# ---------------------------------------------------------------------------

class EvidenceStore:
    """Persist and retrieve :class:`EvidenceRecord` instances in DuckDB.

    Parameters
    ----------
    con:
        An open DuckDB connection.  The ``evidence_records`` table is created
        (if absent) when the store is instantiated.  Pass ``None`` to get an
        auto-created in-memory connection (useful for tests).
    """

    def __init__(self, con: Any = None) -> None:
        if con is None:
            try:
                import duckdb
            except ImportError as exc:
                raise ImportError(
                    "duckdb is required — install with: pip install duckdb"
                ) from exc
            con = duckdb.connect(database=":memory:")
        self._con = con
        self._con.execute(_DDL_EVIDENCE_EXTENDED)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def emit(self, record: EvidenceRecord) -> EvidenceRecord:
        """Persist *record* and return it unchanged.

        Parameters
        ----------
        record:
            A fully-formed evidence record (use :func:`build_record` to
            construct one).

        Returns
        -------
        EvidenceRecord
            The same record that was passed in (for chaining convenience).
        """
        self._con.execute(
            """
            INSERT INTO evidence_records
                (decision_id, timestamp, decision_type, shipment_id,
                 disruption_id, policy_id, reason_codes, output, confidence_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record.decision_id,
                _ts(record.timestamp),
                record.decision_type.value,
                record.shipment_id,
                record.disruption_id,
                record.policy_id,
                json.dumps(record.reason_codes),
                json.dumps(record.output, default=str),
                record.confidence_score,
            ],
        )
        _log.info(
            "evidence_record_created",
            extra={
                "decision_id": record.decision_id,
                "decision_type": record.decision_type.value,
                "shipment_id": record.shipment_id,
                "disruption_id": record.disruption_id,
                "policy_id": record.policy_id,
                "reason_codes": record.reason_codes,
                "confidence_score": record.confidence_score,
            },
        )
        return record

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, decision_id: str) -> EvidenceRecord | None:
        """Retrieve one record by its ``decision_id``."""
        row = self._con.execute(
            """
            SELECT decision_id, timestamp, decision_type, shipment_id,
                   disruption_id, policy_id, reason_codes, output, confidence_score
            FROM evidence_records
            WHERE decision_id = ?
            """,
            [decision_id],
        ).fetchone()
        return _row_to_record(row) if row else None

    def list_for_shipment(self, shipment_id: str) -> list[EvidenceRecord]:
        """Return all evidence records for *shipment_id*, oldest first."""
        rows = self._con.execute(
            """
            SELECT decision_id, timestamp, decision_type, shipment_id,
                   disruption_id, policy_id, reason_codes, output, confidence_score
            FROM evidence_records
            WHERE shipment_id = ?
            ORDER BY timestamp ASC
            """,
            [shipment_id],
        ).fetchall()
        return [_row_to_record(r) for r in rows]
