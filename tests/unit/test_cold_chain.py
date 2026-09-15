"""
Unit tests for the deterministic Cold Chain Policy Engine.

Seven cases
-----------
1. Normal shipment — all readings within policy limits → SAFE
2. Single 10.4 °C excursion reading → EXCURSION_REVIEW
3. ~18-minute excursion window → EXCURSION_REVIEW + duration ≥ 18 min
4. Return-to-normal after excursion → still EXCURSION_REVIEW (not SAFE)
5. Missing sensor reading gap detected → evidence contains missing_windows
6. No policy supplied → POLICY_REQUIRED
7. Different configurable policy (wider range, different severity rule)

Demo policy (min=2 °C, max=8 °C) — values come from the dict, not hardcoded
in the engine.
"""

import pytest

from src.app.cold_chain.engine import classify_excursion

# ---------------------------------------------------------------------------
# shared fixture — CDC refrigerated-vaccine demo profile (2–8 °C)
# ---------------------------------------------------------------------------

DEMO_POLICY = {
    "policy_id": "cdc_refrigerated_vaccine_demo",
    "min_celsius": 2.0,
    "max_celsius": 8.0,
    "max_continuous_excursion_minutes": 15,
    "sample_interval_minutes": 6,
    "severity_rules": {
        "out_of_range": "EXCURSION_REVIEW",
        "missing_sensor_data": "URGENT_ESCALATION",
    },
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ts(hhmm: str, date: str = "2026-09-14") -> str:
    """Build a bare ISO-8601 timestamp string like '2026-09-14T08:06:00'."""
    return f"{date}T{hhmm}:00"


# ---------------------------------------------------------------------------
# 1. Normal shipment — every reading in range
# ---------------------------------------------------------------------------

class TestNormalShipment:
    READINGS = [
        {"ts": _ts("08:00"), "temp_c": 4.0},
        {"ts": _ts("08:06"), "temp_c": 5.1},
        {"ts": _ts("08:12"), "temp_c": 4.8},
        {"ts": _ts("08:18"), "temp_c": 3.9},
        {"ts": _ts("08:24"), "temp_c": 5.5},
    ]

    def test_severity_is_safe(self):
        severity, _ = classify_excursion(DEMO_POLICY, self.READINGS)
        assert severity == "SAFE"

    def test_no_excursion_in_evidence(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["out_of_range_count"] == 0
        assert evidence["cumulative_excursion_minutes"] == 0.0
        assert evidence["max_continuous_excursion_minutes"] == 0.0

    def test_min_max_correct(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["min_c"] == pytest.approx(3.9)
        assert evidence["max_c"] == pytest.approx(5.5)

    def test_no_missing_windows(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["missing_windows"] == []


# ---------------------------------------------------------------------------
# 2. Single 10.4 °C excursion reading
# ---------------------------------------------------------------------------

class TestSingleExcursionReading:
    READINGS = [
        {"ts": _ts("08:00"), "temp_c": 5.0},
        {"ts": _ts("08:06"), "temp_c": 10.4},   # out of range
        {"ts": _ts("08:12"), "temp_c": 5.0},
    ]

    def test_severity_excursion_review(self):
        severity, _ = classify_excursion(DEMO_POLICY, self.READINGS)
        assert severity == "EXCURSION_REVIEW"

    def test_max_temp_captured(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["max_c"] == pytest.approx(10.4)

    def test_one_out_of_range_reading(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["out_of_range_count"] == 1

    def test_cumulative_duration_equals_one_interval(self):
        # single oor reading → span=0, +1 interval = 6 minutes
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["cumulative_excursion_minutes"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# 3. ~18-minute excursion (the reference scenario from preflight_demo.py)
# ---------------------------------------------------------------------------

class TestEighteenMinuteExcursion:
    """Readings: 6.9, 8.9, 10.4, 9.1, 6.4 — three readings outside 2–8 °C."""

    READINGS = [
        {"ts": _ts("08:00"), "temp_c": 6.9},
        {"ts": _ts("08:06"), "temp_c": 8.9},   # oor
        {"ts": _ts("08:12"), "temp_c": 10.4},  # oor
        {"ts": _ts("08:18"), "temp_c": 9.1},   # oor
        {"ts": _ts("08:24"), "temp_c": 6.4},
    ]

    def test_severity_excursion_review(self):
        severity, _ = classify_excursion(DEMO_POLICY, self.READINGS)
        assert severity == "EXCURSION_REVIEW"

    def test_max_temp_is_10_4(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["max_c"] == pytest.approx(10.4)

    def test_three_out_of_range_readings(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["out_of_range_count"] == 3

    def test_cumulative_duration_at_least_18_minutes(self):
        # span from 08:06 to 08:18 = 12 min, + 1 interval (6 min) = 18 min
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["cumulative_excursion_minutes"] >= 18.0

    def test_max_continuous_equals_cumulative(self):
        # all three oor readings are one unbroken run
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["max_continuous_excursion_minutes"] == pytest.approx(
            evidence["cumulative_excursion_minutes"]
        )


# ---------------------------------------------------------------------------
# 4. Return-to-normal after excursion — must NOT be SAFE
# ---------------------------------------------------------------------------

class TestReturnToNormalAfterExcursion:
    """Temperature goes out of range then comes back — product is NOT safe."""

    READINGS = [
        {"ts": _ts("08:00"), "temp_c": 4.0},
        {"ts": _ts("08:06"), "temp_c": 11.2},  # excursion
        {"ts": _ts("08:12"), "temp_c": 4.5},   # back in range
        {"ts": _ts("08:18"), "temp_c": 4.0},
        {"ts": _ts("08:24"), "temp_c": 3.8},
    ]

    def test_severity_is_not_safe(self):
        severity, _ = classify_excursion(DEMO_POLICY, self.READINGS)
        assert severity != "SAFE", (
            "A product must not be declared SAFE after a confirmed excursion "
            "merely because temperature returned to the normal range."
        )

    def test_severity_is_excursion_review(self):
        severity, _ = classify_excursion(DEMO_POLICY, self.READINGS)
        assert severity == "EXCURSION_REVIEW"

    def test_out_of_range_count_is_one(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["out_of_range_count"] == 1

    def test_max_temp_captured(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert evidence["max_c"] == pytest.approx(11.2)


# ---------------------------------------------------------------------------
# 5. Missing sensor reading gap detected
# ---------------------------------------------------------------------------

class TestMissingReadingGap:
    """A 30-minute gap (5× the 6-minute interval) should surface as a
    missing_window entry in the evidence."""

    READINGS = [
        {"ts": _ts("08:00"), "temp_c": 4.5},
        {"ts": _ts("08:06"), "temp_c": 4.8},
        # gap: 08:06 → 08:36 (30 minutes — 5 expected intervals)
        {"ts": _ts("08:36"), "temp_c": 5.0},
        {"ts": _ts("08:42"), "temp_c": 5.2},
    ]

    def test_missing_window_detected(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        assert len(evidence["missing_windows"]) >= 1, (
            "A 30-minute gap in a 6-minute-interval policy should register "
            "as at least one missing_windows entry."
        )

    def test_missing_window_gap_size(self):
        _, evidence = classify_excursion(DEMO_POLICY, self.READINGS)
        gap = evidence["missing_windows"][0]["gap_minutes"]
        assert gap == pytest.approx(30.0)

    def test_severity_safe_when_no_oor_readings(self):
        # No reading exceeded the range, so severity is SAFE despite the gap
        severity, _ = classify_excursion(DEMO_POLICY, self.READINGS)
        assert severity == "SAFE"

    def test_no_false_missing_windows_for_normal_interval(self):
        readings = [
            {"ts": _ts("08:00"), "temp_c": 4.0},
            {"ts": _ts("08:06"), "temp_c": 4.5},
            {"ts": _ts("08:12"), "temp_c": 5.0},
        ]
        _, evidence = classify_excursion(DEMO_POLICY, readings)
        assert evidence["missing_windows"] == []


# ---------------------------------------------------------------------------
# 6. Policy required — no policy supplied
# ---------------------------------------------------------------------------

class TestPolicyRequired:
    READINGS = [{"ts": _ts("08:00"), "temp_c": 5.0}]

    def test_severity_is_policy_required(self):
        severity, _ = classify_excursion(None, self.READINGS)
        assert severity == "POLICY_REQUIRED"

    def test_severity_is_policy_required_empty_readings(self):
        severity, _ = classify_excursion(None, [])
        assert severity == "POLICY_REQUIRED"

    def test_evidence_contains_reason(self):
        _, evidence = classify_excursion(None, self.READINGS)
        assert "reason" in evidence


# ---------------------------------------------------------------------------
# 7. Different configurable policy — ambient cargo (0–25 °C)
# ---------------------------------------------------------------------------

class TestDifferentConfigurablePolicy:
    """A wide-range ambient policy: 0–25 °C, 10-minute interval.
    The same readings that trigger EXCURSION_REVIEW under the vaccine policy
    should be SAFE under this looser policy."""

    AMBIENT_POLICY = {
        "policy_id": "ambient_cargo_demo",
        "min_celsius": 0.0,
        "max_celsius": 25.0,
        "sample_interval_minutes": 10,
        "severity_rules": {
            "out_of_range": "AMBIENT_EXCURSION",
            "missing_sensor_data": "DATA_MISSING",
        },
    }

    def test_in_range_readings_are_safe(self):
        readings = [
            {"ts": _ts("09:00"), "temp_c": 10.4},  # oor under vaccine policy
            {"ts": _ts("09:10"), "temp_c": 20.0},
            {"ts": _ts("09:20"), "temp_c": 0.5},
        ]
        severity, _ = classify_excursion(self.AMBIENT_POLICY, readings)
        assert severity == "SAFE"

    def test_above_max_triggers_ambient_excursion(self):
        readings = [
            {"ts": _ts("09:00"), "temp_c": 5.0},
            {"ts": _ts("09:10"), "temp_c": 30.0},  # oor
        ]
        severity, _ = classify_excursion(self.AMBIENT_POLICY, readings)
        assert severity == "AMBIENT_EXCURSION"

    def test_below_min_triggers_ambient_excursion(self):
        readings = [
            {"ts": _ts("09:00"), "temp_c": 12.0},
            {"ts": _ts("09:10"), "temp_c": -5.0},  # oor
        ]
        severity, _ = classify_excursion(self.AMBIENT_POLICY, readings)
        assert severity == "AMBIENT_EXCURSION"

    def test_empty_readings_use_policy_severity_rule(self):
        severity, _ = classify_excursion(self.AMBIENT_POLICY, [])
        assert severity == "DATA_MISSING"

    def test_missing_window_uses_policy_interval(self):
        # gap of 30 min in a 10-min-interval policy → 1.5× threshold = 15 min
        # 30 > 15 → should detect missing window
        readings = [
            {"ts": _ts("09:00"), "temp_c": 5.0},
            {"ts": _ts("09:30"), "temp_c": 5.0},  # 30-min gap
        ]
        _, evidence = classify_excursion(self.AMBIENT_POLICY, readings)
        assert len(evidence["missing_windows"]) == 1
        assert evidence["missing_windows"][0]["gap_minutes"] == pytest.approx(30.0)
