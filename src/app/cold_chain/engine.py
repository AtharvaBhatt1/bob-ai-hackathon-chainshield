"""
Cold Chain Policy Engine — deterministic, no LLM.

Public API
----------
classify_excursion(policy, readings) -> (severity_string, evidence_dict)

``policy`` is a plain dict loaded from configuration/input — thresholds are
never hardcoded here.  Swapping the dict changes the outcome without touching
this module.

Severity strings (SCREAMING_SNAKE_CASE)
----------------------------------------
SAFE                  — every reading within policy limits
EXCURSION_REVIEW      — one or more readings outside limits (default rule)
URGENT_ESCALATION     — configured response to missing sensor data
POLICY_REQUIRED       — no policy was supplied; cannot evaluate
<any value>           — caller-supplied via severity_rules keys

Evidence dict keys
------------------
Always present:
  reason              — human-readable explanation (error/edge-case paths)
  or all five of:
  min_c               — minimum observed temperature
  max_c               — maximum observed temperature
  out_of_range_count  — number of individual out-of-range readings
  cumulative_excursion_minutes  — total minutes spent outside policy limits
  max_continuous_excursion_minutes — longest unbroken out-of-range run
  missing_windows     — list of gaps (in minutes) where sensor data is absent
                        (only populated when sample_interval_minutes is set)

A product is NEVER declared safe solely because temperature returned to the
normal range.  Any confirmed excursion produces a non-SAFE severity regardless
of the final reading.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M%z",
    "%Y-%m-%dT%H:%M",
)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to an aware or naïve datetime."""
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts!r}")


def _to_comparable(dt: datetime) -> datetime:
    """Make two datetimes comparable by stripping tz from both if mixed."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

def classify_excursion(
    policy: dict[str, Any] | None,
    readings: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Classify a shipment's temperature history against a configurable policy.

    Parameters
    ----------
    policy:
        Configuration dict that MUST contain:
          min_celsius           float  — lower acceptable bound (inclusive)
          max_celsius           float  — upper acceptable bound (inclusive)
          severity_rules        dict   — maps event names to severity strings
            out_of_range              — severity when excursion is detected
            missing_sensor_data       — severity when readings list is empty
        OPTIONAL keys:
          sample_interval_minutes  int/float — expected gap between readings;
                                               enables missing-window detection
    readings:
        List of dicts, each with:
          ts      str   — ISO-8601 timestamp
          temp_c  float — temperature in Celsius

    Returns
    -------
    (severity_string, evidence_dict)
    """
    # ---- guard: no policy -----------------------------------------------
    if policy is None:
        return (
            "POLICY_REQUIRED",
            {"reason": "no policy profile matched this shipment's product class"},
        )

    min_c: float = policy["min_celsius"]
    max_c: float = policy["max_celsius"]
    severity_rules: dict = policy.get("severity_rules", {})
    sample_interval: float | None = policy.get("sample_interval_minutes")

    # ---- guard: no readings ---------------------------------------------
    if not readings:
        severity = severity_rules.get("missing_sensor_data", "URGENT_ESCALATION")
        return severity, {"reason": "no sensor readings available for this shipment"}

    # ---- sort by timestamp ----------------------------------------------
    ordered = sorted(readings, key=lambda r: _parse_ts(r["ts"]))

    observed_min = min(r["temp_c"] for r in ordered)
    observed_max = max(r["temp_c"] for r in ordered)

    # ---- detect out-of-range readings -----------------------------------
    out_of_range = [r for r in ordered if not (min_c <= r["temp_c"] <= max_c)]

    # ---- cumulative + max-continuous excursion --------------------------
    # Strategy: walk the ordered list; for contiguous out-of-range runs
    # measure duration using actual timestamps (difference between first and
    # last reading in the run, plus one interval if available).
    cumulative_minutes = 0.0
    max_continuous_minutes = 0.0
    current_run_start: datetime | None = None
    current_run_last: datetime | None = None
    in_run = False

    for r in ordered:
        ts = _parse_ts(r["ts"])
        is_oor = not (min_c <= r["temp_c"] <= max_c)

        if is_oor:
            if not in_run:
                current_run_start = ts
                in_run = True
            current_run_last = ts
        else:
            if in_run:
                run_minutes = _run_duration(
                    current_run_start, current_run_last, sample_interval
                )
                cumulative_minutes += run_minutes
                if run_minutes > max_continuous_minutes:
                    max_continuous_minutes = run_minutes
                in_run = False

    # close an open run at the end of the sequence
    if in_run:
        run_minutes = _run_duration(
            current_run_start, current_run_last, sample_interval
        )
        cumulative_minutes += run_minutes
        if run_minutes > max_continuous_minutes:
            max_continuous_minutes = run_minutes

    # ---- missing window detection ---------------------------------------
    missing_windows: list[dict[str, Any]] = []
    if sample_interval is not None and len(ordered) >= 2:
        for i in range(1, len(ordered)):
            prev_ts = _to_comparable(_parse_ts(ordered[i - 1]["ts"]))
            curr_ts = _to_comparable(_parse_ts(ordered[i]["ts"]))
            gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0
            expected_gap = sample_interval
            # A gap more than 1.5× the expected interval implies missing data
            if gap_minutes > expected_gap * 1.5:
                missing_windows.append(
                    {
                        "after_ts": ordered[i - 1]["ts"],
                        "before_ts": ordered[i]["ts"],
                        "gap_minutes": round(gap_minutes, 2),
                        "expected_minutes": expected_gap,
                    }
                )

    # ---- build evidence dict ---------------------------------------------
    evidence: dict[str, Any] = {
        "min_c": observed_min,
        "max_c": observed_max,
        "out_of_range_count": len(out_of_range),
        "cumulative_excursion_minutes": round(cumulative_minutes, 2),
        "max_continuous_excursion_minutes": round(max_continuous_minutes, 2),
        "missing_windows": missing_windows,
    }

    # ---- classify --------------------------------------------------------
    if not out_of_range:
        # Only SAFE when there are zero excursion readings — returning to
        # normal range after an excursion still yields the excursion severity.
        return "SAFE", evidence

    severity = severity_rules.get("out_of_range", "EXCURSION_REVIEW")
    return severity, evidence


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------

def _run_duration(
    start: datetime,
    last: datetime,
    sample_interval: float | None,
) -> float:
    """Duration of a contiguous out-of-range run in minutes.

    When readings are instantaneous points we cannot know the true end of the
    excursion, so we add one sample_interval to the span if available, giving
    a conservative (worst-case) estimate.  Without an interval we use the
    span between the first and last oor timestamp, floored at 0.
    """
    start_c = _to_comparable(start)
    last_c = _to_comparable(last)
    span = (last_c - start_c).total_seconds() / 60.0
    if sample_interval is not None:
        span += sample_interval
    return max(span, 0.0)
