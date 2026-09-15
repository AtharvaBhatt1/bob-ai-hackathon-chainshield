// API types mirroring src/app/core/schemas.py + models.py

export interface HealthResponse {
  status: string;
  demo_mode: boolean;
  watsonx_enabled: boolean;
}

// ── Disruptions ──────────────────────────────────────────────────────────────

export interface ImpactResult {
  shipment_id: string;
  affected: boolean;
  reason_codes: string[];
  cargo_value_usd: number;
  eta_delay_hours: number;
}

export interface DisruptionActivateResponse {
  disruption_id: string;
  affected_shipments: ImpactResult[];
}

// ── Shipments ─────────────────────────────────────────────────────────────────

export interface RouteAlternative {
  carrier_id: string;
  route_nodes: string[];
  eta_delta_hours: number;
  additional_cost_usd: number;
  reason_codes: string[];
  reefer_capable: boolean;
}

export interface Shipment {
  shipment_id: string;
  origin: string;
  destination: string;
  status: string;
  cargo_type: string;
  cargo_value_usd: number;
  carrier_id: string;
  eta: string | null;
  product_class: string | null;
  temperature_policy_id: string | null;
}

export interface ShipmentLeg {
  leg_id: string;
  shipment_id: string;
  sequence: number;
  origin_node_id: string;
  destination_node_id: string;
  mode: string;
  carrier_id: string;
  planned_departure: string;
  planned_arrival: string;
}

export interface ShipmentDetailResponse {
  shipment: Shipment;
  legs: ShipmentLeg[];
  alternatives: RouteAlternative[];
}

// ── Assets ────────────────────────────────────────────────────────────────────

export interface Asset {
  asset_id: string;
  asset_type: string;
  carrier_id: string;
  current_node_id: string;
  status: string;
  reefer_capable: boolean;
  capacity_teu: number | null;
  available_at: string;
}

export interface AssetMatch {
  asset_id: string;
  asset: Asset;
  reposition_distance_km: number;
  available_at: string;
  reason_codes: string[];
}

export interface IdleAssetsResponse {
  assets: AssetMatch[];
}

// ── Cold-chain ────────────────────────────────────────────────────────────────

export interface SensorReadingOut {
  sensor_id: string;
  ts: string;
  temperature_c: number;
  battery_pct: number | null;
  in_range: boolean;
}

export interface ExcursionEvent {
  start_ts: string;
  end_ts: string;
  duration_minutes: number;
  max_celsius: number;
  min_celsius: number;
  pattern: string;
}

export interface PolicyProfile {
  policy_id: string;
  product_class: string;
  min_celsius: number;
  max_celsius: number;
  sample_interval_minutes: number;
  max_excursion_minutes: number;
  severity_rules: Record<string, string>;
}

export interface ColdChainTimelineResponse {
  shipment_id: string;
  policy: PolicyProfile | null;
  readings: SensorReadingOut[];
  excursion_events: ExcursionEvent[];
  status: string;
  max_celsius: number | null;
  min_celsius: number | null;
  total_out_of_range_minutes: number;
  evidence: Record<string, unknown>;
}

// ── Explanations ──────────────────────────────────────────────────────────────

export interface ExplanationResult {
  summary: string;
  why_affected: string[];
  recommended_action: string;
  evidence: string[];
  uncertainties: string[];
  generated_by: string;
  model_used: string | null;
}

// ── Action plan ───────────────────────────────────────────────────────────────

export interface ActionPlanItem {
  rank: number;
  action_type: string;
  shipment_id: string;
  description: string;
  eta_delta_hours: number;
  additional_cost_usd: number;
  reason_codes: string[];
  confidence_score: number;
}

export interface ActionPlanResponse {
  plan_id: string;
  disruption_id: string;
  generated_at: string;
  items: ActionPlanItem[];
  export_format: string;
}
