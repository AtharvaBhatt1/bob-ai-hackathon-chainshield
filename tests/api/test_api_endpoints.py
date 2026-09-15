"""
tests/api/test_api_endpoints.py
=================================
Integration tests for the ChainShield FastAPI layer.

Each test spins up the full app via FastAPI's TestClient (synchronous ASGI
transport — no network required).  The app's lifespan seeds the in-memory
DuckDB with the synthetic demo dataset before any request is processed.

Coverage
--------
POST /api/v1/disruptions/activate
GET  /api/v1/shipments/{shipment_id}
GET  /api/v1/assets/idle
GET  /api/v1/cold-chain/{shipment_id}/timeline
POST /api/v1/explanations/generate
POST /api/v1/action-plan/export  (json + markdown)
GET  /healthz
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.api.main import app


# ---------------------------------------------------------------------------
# Shared test client fixture — one client per test module (session-scoped
# would require re-seeding; module scope is the right trade-off here).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ===========================================================================
# GET /healthz
# ===========================================================================

class TestHealth:
    def test_healthz_ok(self, client: TestClient):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "demo_mode" in data
        assert "watsonx_enabled" in data


# ===========================================================================
# POST /api/v1/disruptions/activate
# ===========================================================================

class TestDisruptionsActivate:
    URL = "/api/v1/disruptions/activate"

    def test_activate_known_disruption(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["disruption_id"] == "PORT_STRIKE_01"
        assert "affected_shipments" in data
        assert len(data["affected_shipments"]) >= 1

    def test_affected_shipment_has_reason_codes(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        assert resp.status_code == 200
        affected = [s for s in resp.json()["affected_shipments"] if s["affected"]]
        assert len(affected) >= 1
        for s in affected:
            assert len(s["reason_codes"]) >= 1
            # All codes should be SCREAMING_SNAKE_CASE
            for code in s["reason_codes"]:
                assert code == code.upper(), f"Expected SCREAMING_SNAKE_CASE, got {code!r}"

    def test_shp_0042_is_affected(self, client: TestClient):
        """The demo disrupted shipment must be flagged as affected."""
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        assert resp.status_code == 200
        shp42 = next(
            (s for s in resp.json()["affected_shipments"] if s["shipment_id"] == "SHP-0042"),
            None,
        )
        assert shp42 is not None
        assert shp42["affected"] is True
        assert shp42["cargo_value_usd"] > 0
        assert shp42["eta_delay_hours"] > 0

    def test_shp_0099_is_not_affected(self, client: TestClient):
        """The bypass-route shipment must not be flagged as affected."""
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        assert resp.status_code == 200
        shp99 = next(
            (s for s in resp.json()["affected_shipments"] if s["shipment_id"] == "SHP-0099"),
            None,
        )
        assert shp99 is not None
        assert shp99["affected"] is False

    def test_unknown_disruption_returns_404(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "DOES_NOT_EXIST"})
        assert resp.status_code == 404

    def test_missing_body_returns_422(self, client: TestClient):
        resp = client.post(self.URL, json={})
        assert resp.status_code == 422


# ===========================================================================
# GET /api/v1/shipments/{shipment_id}
# ===========================================================================

class TestShipmentDetail:
    def test_get_known_shipment(self, client: TestClient):
        resp = client.get("/api/v1/shipments/SHP-0042")
        assert resp.status_code == 200
        data = resp.json()
        assert data["shipment"]["shipment_id"] == "SHP-0042"
        assert "legs" in data
        assert "alternatives" in data

    def test_legs_are_sorted_by_sequence(self, client: TestClient):
        resp = client.get("/api/v1/shipments/SHP-0042")
        legs = resp.json()["legs"]
        sequences = [lg["sequence"] for lg in legs]
        assert sequences == sorted(sequences)

    def test_alternatives_present_for_disrupted_shipment(self, client: TestClient):
        resp = client.get("/api/v1/shipments/SHP-0042")
        assert resp.status_code == 200
        alts = resp.json()["alternatives"]
        assert len(alts) >= 1

    def test_unaffected_shipment_has_no_alternatives(self, client: TestClient):
        """SHP-0099 has no alternatives in the demo dataset."""
        resp = client.get("/api/v1/shipments/SHP-0099")
        assert resp.status_code == 200
        assert resp.json()["alternatives"] == []

    def test_unknown_shipment_returns_404(self, client: TestClient):
        resp = client.get("/api/v1/shipments/SHP-XXXX")
        assert resp.status_code == 404


# ===========================================================================
# GET /api/v1/assets/idle
# ===========================================================================

class TestIdleAssets:
    URL = "/api/v1/assets/idle"

    def test_returns_only_available_assets(self, client: TestClient):
        resp = client.get(self.URL)
        assert resp.status_code == 200
        assets = resp.json()["assets"]
        for a in assets:
            assert a["asset"]["status"] == "available"

    def test_reefer_assets_come_first(self, client: TestClient):
        resp = client.get(self.URL)
        assets = resp.json()["assets"]
        if len(assets) >= 2:
            # First reefer-capable asset should appear before non-reefer
            reefer_indices = [i for i, a in enumerate(assets) if a["asset"]["reefer_capable"]]
            non_reefer_indices = [i for i, a in enumerate(assets) if not a["asset"]["reefer_capable"]]
            if reefer_indices and non_reefer_indices:
                assert min(reefer_indices) < max(non_reefer_indices)

    def test_vessel_in_use_is_excluded(self, client: TestClient):
        resp = client.get(self.URL)
        asset_ids = [a["asset_id"] for a in resp.json()["assets"]]
        assert "VESSEL-04" not in asset_ids

    def test_truck_17_is_included(self, client: TestClient):
        """TRUCK-17 is idle reefer-capable — must appear."""
        resp = client.get(self.URL)
        asset_ids = [a["asset_id"] for a in resp.json()["assets"]]
        assert "TRUCK-17" in asset_ids

    def test_reason_codes_present(self, client: TestClient):
        resp = client.get(self.URL)
        for a in resp.json()["assets"]:
            assert len(a["reason_codes"]) >= 1

    def test_reposition_distance_is_non_negative(self, client: TestClient):
        resp = client.get(self.URL)
        for a in resp.json()["assets"]:
            assert a["reposition_distance_km"] >= 0.0


# ===========================================================================
# GET /api/v1/cold-chain/{shipment_id}/timeline
# ===========================================================================

class TestColdChainTimeline:
    def test_returns_timeline_for_reefer_shipment(self, client: TestClient):
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["shipment_id"] == "SHP-0042"
        assert data["status"] in ("SAFE", "EXCURSION_REVIEW", "URGENT_ESCALATION", "POLICY_REQUIRED")

    def test_excursion_detected_for_shp_0042(self, client: TestClient):
        """The demo readings include a temperature spike → EXCURSION_REVIEW."""
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        data = resp.json()
        assert data["status"] == "EXCURSION_REVIEW"

    def test_policy_is_included(self, client: TestClient):
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        assert resp.json()["policy"] is not None

    def test_readings_are_annotated_with_in_range(self, client: TestClient):
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        readings = resp.json()["readings"]
        assert len(readings) >= 1
        for r in readings:
            assert "in_range" in r
            assert isinstance(r["in_range"], bool)

    def test_excursion_events_present(self, client: TestClient):
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        events = resp.json()["excursion_events"]
        assert len(events) >= 1
        for ev in events:
            assert ev["duration_minutes"] > 0
            assert "pattern" in ev

    def test_evidence_has_required_keys(self, client: TestClient):
        """Evidence dict must carry the five keys the cold-chain engine always emits."""
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        evidence = resp.json()["evidence"]
        for key in ("min_c", "max_c", "out_of_range_count",
                    "cumulative_excursion_minutes", "max_continuous_excursion_minutes"):
            assert key in evidence, f"Missing evidence key: {key}"

    def test_total_out_of_range_minutes_positive(self, client: TestClient):
        resp = client.get("/api/v1/cold-chain/SHP-0042/timeline")
        assert resp.json()["total_out_of_range_minutes"] > 0

    def test_unknown_shipment_returns_404(self, client: TestClient):
        resp = client.get("/api/v1/cold-chain/SHP-XXXX/timeline")
        assert resp.status_code == 404

    def test_ambient_shipment_timeline(self, client: TestClient):
        """SHP-0099 has no temperature_policy_id but its product_class resolves
        POL-AMBIENT-01.  With no sensor readings the policy's missing_sensor_data
        rule fires → EXCURSION_REVIEW (not POLICY_REQUIRED)."""
        resp = client.get("/api/v1/cold-chain/SHP-0099/timeline")
        assert resp.status_code == 200
        data = resp.json()
        # No sensor readings → missing_sensor_data severity from POL-AMBIENT-01
        assert data["status"] == "EXCURSION_REVIEW"
        assert data["readings"] == []


# ===========================================================================
# POST /api/v1/explanations/generate
# ===========================================================================

class TestExplanationsGenerate:
    URL = "/api/v1/explanations/generate"

    def test_generates_explanation_for_impact_decision(self, client: TestClient):
        resp = client.post(self.URL, json={"decision_id": "dec-impact-0042-001"})
        assert resp.status_code == 200
        data = resp.json()
        # Required ExplanationResult keys
        for key in ("summary", "why_affected", "recommended_action", "evidence", "uncertainties"):
            assert key in data, f"Missing key: {key}"

    def test_generated_by_is_fallback(self, client: TestClient):
        """With WATSONX_ENABLED unset, generated_by must be the deterministic fallback."""
        resp = client.post(self.URL, json={"decision_id": "dec-impact-0042-001"})
        assert resp.status_code == 200
        assert resp.json()["generated_by"] == "deterministic_fallback_template"

    def test_model_used_is_none(self, client: TestClient):
        resp = client.post(self.URL, json={"decision_id": "dec-impact-0042-001"})
        assert resp.json()["model_used"] is None

    def test_explanation_for_cold_chain_decision(self, client: TestClient):
        resp = client.post(self.URL, json={"decision_id": "dec-coldchain-0042-001"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["why_affected"]) >= 1

    def test_explanation_for_route_decision(self, client: TestClient):
        resp = client.post(self.URL, json={"decision_id": "dec-route-0042-001"})
        assert resp.status_code == 200

    def test_summary_mentions_shipment_id(self, client: TestClient):
        resp = client.post(self.URL, json={"decision_id": "dec-impact-0042-001"})
        assert "SHP-0042" in resp.json()["summary"]

    def test_unknown_decision_returns_404(self, client: TestClient):
        resp = client.post(self.URL, json={"decision_id": "dec-does-not-exist"})
        assert resp.status_code == 404

    def test_missing_body_returns_422(self, client: TestClient):
        resp = client.post(self.URL, json={})
        assert resp.status_code == 422

    def test_evidence_list_contains_reason_codes(self, client: TestClient):
        resp = client.post(self.URL, json={"decision_id": "dec-impact-0042-001"})
        evidence = resp.json()["evidence"]
        assert len(evidence) >= 1
        # All evidence entries should be SCREAMING_SNAKE_CASE reason codes
        for code in evidence:
            assert code == code.upper()


# ===========================================================================
# POST /api/v1/action-plan/export
# ===========================================================================

class TestActionPlanExport:
    URL = "/api/v1/action-plan/export"

    def test_json_export_for_known_disruption(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01", "export_format": "json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["disruption_id"] == "PORT_STRIKE_01"
        assert "items" in data
        assert len(data["items"]) >= 1

    def test_plan_items_have_required_fields(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        for item in resp.json()["items"]:
            for field in ("rank", "action_type", "shipment_id", "description",
                          "reason_codes", "confidence_score"):
                assert field in item, f"Missing field: {field}"

    def test_action_types_are_known_values(self, client: TestClient):
        valid = {"REROUTE", "CARRIER_SWAP", "ASSET_DEPLOY", "COLD_CHAIN_HOLD"}
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        for item in resp.json()["items"]:
            assert item["action_type"] in valid

    def test_items_are_ranked_sequentially(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        ranks = [item["rank"] for item in resp.json()["items"]]
        assert ranks == sorted(ranks)
        assert ranks[0] == 1

    def test_markdown_export_returns_text(self, client: TestClient):
        resp = client.post(
            self.URL,
            json={"disruption_id": "PORT_STRIKE_01", "export_format": "markdown"},
        )
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers.get("content-type", "")
        body = resp.text
        assert "# ChainShield Action Plan" in body
        assert "PORT_STRIKE_01" in body

    def test_unknown_disruption_returns_404(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "DOES_NOT_EXIST"})
        assert resp.status_code == 404

    def test_plan_has_cold_chain_hold_for_reefer_shipment(self, client: TestClient):
        """A reefer shipment with an excursion should trigger COLD_CHAIN_HOLD."""
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        action_types = [item["action_type"] for item in resp.json()["items"]]
        assert "COLD_CHAIN_HOLD" in action_types

    def test_plan_has_reroute_recommendation(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        action_types = [item["action_type"] for item in resp.json()["items"]]
        assert "REROUTE" in action_types

    def test_confidence_scores_in_valid_range(self, client: TestClient):
        resp = client.post(self.URL, json={"disruption_id": "PORT_STRIKE_01"})
        for item in resp.json()["items"]:
            assert 0.0 <= item["confidence_score"] <= 1.0
