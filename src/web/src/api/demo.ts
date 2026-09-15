/**
 * Static demo data used as a fallback when the FastAPI backend is not running.
 * Shape matches the real API responses exactly.
 */
import type {
  ActionPlanResponse,
  ColdChainTimelineResponse,
  DisruptionActivateResponse,
  ExplanationResult,
  IdleAssetsResponse,
  ShipmentDetailResponse,
} from './types';

export const DEMO_DISRUPTION = 'DISRUPT-001';
export const DEMO_SHIPMENT_ID = 'SHP-0042';
export const DEMO_DECISION_ID = 'EV-0001';

export const demoActivate: DisruptionActivateResponse = {
  disruption_id: DEMO_DISRUPTION,
  affected_shipments: [
    {
      shipment_id: 'SHP-0042',
      affected: true,
      reason_codes: ['PORT_NODE_BLOCKED', 'ETA_SLA_BREACH'],
      cargo_value_usd: 420000,
      eta_delay_hours: 36,
    },
    {
      shipment_id: 'SHP-0099',
      affected: false,
      reason_codes: [],
      cargo_value_usd: 85000,
      eta_delay_hours: 0,
    },
  ],
};

export const demoShipment: ShipmentDetailResponse = {
  shipment: {
    shipment_id: 'SHP-0042',
    origin: 'HUB-A',
    destination: 'HUB-D',
    status: 'IN_TRANSIT',
    cargo_type: 'pharmaceutical',
    cargo_value_usd: 420000,
    carrier_id: 'CARRIER-01',
    eta: '2025-08-10T14:00:00Z',
    product_class: 'PHARMA_2C_8C',
    temperature_policy_id: 'POL-001',
  },
  legs: [
    {
      leg_id: 'LEG-001',
      shipment_id: 'SHP-0042',
      sequence: 1,
      origin_node_id: 'HUB-A',
      destination_node_id: 'PORT-03',
      mode: 'road',
      carrier_id: 'CARRIER-01',
      planned_departure: '2025-08-07T08:00:00Z',
      planned_arrival: '2025-08-07T20:00:00Z',
    },
    {
      leg_id: 'LEG-002',
      shipment_id: 'SHP-0042',
      sequence: 2,
      origin_node_id: 'PORT-03',
      destination_node_id: 'HUB-B',
      mode: 'sea',
      carrier_id: 'CARRIER-01',
      planned_departure: '2025-08-08T06:00:00Z',
      planned_arrival: '2025-08-09T06:00:00Z',
    },
  ],
  alternatives: [
    {
      carrier_id: 'CARRIER-02',
      route_nodes: ['HUB-A', 'HUB-C', 'HUB-D'],
      eta_delta_hours: 12,
      additional_cost_usd: 8500,
      reason_codes: ['REEFER_CAPABLE_ALTERNATIVE', 'PORT_BYPASS'],
      reefer_capable: true,
    },
    {
      carrier_id: 'CARRIER-03',
      route_nodes: ['HUB-A', 'HUB-E', 'HUB-D'],
      eta_delta_hours: 24,
      additional_cost_usd: 4200,
      reason_codes: ['LOWER_COST_OPTION'],
      reefer_capable: false,
    },
  ],
};

export const demoIdleAssets: IdleAssetsResponse = {
  assets: [
    {
      asset_id: 'ASSET-R01',
      asset: {
        asset_id: 'ASSET-R01',
        asset_type: 'truck',
        carrier_id: 'CARRIER-02',
        current_node_id: 'HUB-C',
        status: 'available',
        reefer_capable: true,
        capacity_teu: null,
        available_at: '2025-08-07T10:00:00Z',
      },
      reposition_distance_km: 340,
      available_at: '2025-08-07T10:00:00Z',
      reason_codes: ['REEFER_CAPACITY_AVAILABLE'],
    },
    {
      asset_id: 'ASSET-C02',
      asset: {
        asset_id: 'ASSET-C02',
        asset_type: 'container',
        carrier_id: 'CARRIER-04',
        current_node_id: 'HUB-A',
        status: 'available',
        reefer_capable: true,
        capacity_teu: 1,
        available_at: '2025-08-07T12:00:00Z',
      },
      reposition_distance_km: 0,
      available_at: '2025-08-07T12:00:00Z',
      reason_codes: ['REEFER_CAPACITY_AVAILABLE'],
    },
  ],
};

export const demoColdChain: ColdChainTimelineResponse = {
  shipment_id: 'SHP-0042',
  policy: {
    policy_id: 'POL-001',
    product_class: 'PHARMA_2C_8C',
    min_celsius: 2,
    max_celsius: 8,
    sample_interval_minutes: 15,
    max_excursion_minutes: 60,
    severity_rules: {
      safe: 'SAFE',
      minor_excursion: 'EXCURSION_REVIEW',
      major_excursion: 'URGENT_ESCALATION',
      missing_sensor_data: 'POLICY_REQUIRED',
    },
  },
  readings: [
    { sensor_id: 'SNS-01', ts: '2025-08-07T08:00:00Z', temperature_c: 5.1, battery_pct: 98, in_range: true },
    { sensor_id: 'SNS-01', ts: '2025-08-07T08:15:00Z', temperature_c: 5.4, battery_pct: 98, in_range: true },
    { sensor_id: 'SNS-01', ts: '2025-08-07T08:30:00Z', temperature_c: 6.2, battery_pct: 97, in_range: true },
    { sensor_id: 'SNS-01', ts: '2025-08-07T08:45:00Z', temperature_c: 8.8, battery_pct: 97, in_range: false },
    { sensor_id: 'SNS-01', ts: '2025-08-07T09:00:00Z', temperature_c: 9.5, battery_pct: 96, in_range: false },
    { sensor_id: 'SNS-01', ts: '2025-08-07T09:15:00Z', temperature_c: 7.9, battery_pct: 96, in_range: true },
    { sensor_id: 'SNS-01', ts: '2025-08-07T09:30:00Z', temperature_c: 6.1, battery_pct: 95, in_range: true },
    { sensor_id: 'SNS-01', ts: '2025-08-07T09:45:00Z', temperature_c: 5.8, battery_pct: 95, in_range: true },
    { sensor_id: 'SNS-01', ts: '2025-08-07T10:00:00Z', temperature_c: 5.3, battery_pct: 94, in_range: true },
    { sensor_id: 'SNS-01', ts: '2025-08-07T10:15:00Z', temperature_c: 4.9, battery_pct: 94, in_range: true },
  ],
  excursion_events: [
    {
      start_ts: '2025-08-07T08:45:00Z',
      end_ts: '2025-08-07T09:00:00Z',
      duration_minutes: 30,
      max_celsius: 9.5,
      min_celsius: 8.8,
      pattern: 'SPIKE',
    },
  ],
  status: 'EXCURSION_REVIEW',
  max_celsius: 9.5,
  min_celsius: 4.9,
  total_out_of_range_minutes: 30,
  evidence: {
    out_of_range_count: 2,
    total_readings: 10,
    cumulative_excursion_minutes: 30,
    max_c: 9.5,
    min_c: 4.9,
  },
};

export const demoExplanation: ExplanationResult = {
  summary: 'Shipment SHP-0042 has been flagged due to DISRUPT-001.',
  why_affected: [
    'The shipment\'s current route passes through a node that is blocked.',
    'The estimated arrival is projected to breach the contracted SLA deadline.',
    'Sensor data indicates the shipment has been exposed to temperatures outside the acceptable range defined by its policy profile.',
  ],
  recommended_action: 'Operator should: review alternative routing that avoids the blocked node; escalate to logistics operations to assess SLA impact; review sensor log and assess product viability with quality assurance.',
  evidence: ['PORT_NODE_BLOCKED', 'ETA_SLA_BREACH', 'TEMPERATURE_EXPOSURE_INCREASED'],
  uncertainties: [
    'Cold-chain status is EXCURSION_REVIEW; requires manual review before disposition.',
    'No feasible route alternative was found within hard constraints; operator judgment is required.',
  ],
  generated_by: 'deterministic_fallback_template',
  model_used: null,
};

export const demoActionPlan: ActionPlanResponse = {
  plan_id: 'PLAN-001',
  disruption_id: 'DISRUPT-001',
  generated_at: '2025-08-07T10:30:00Z',
  export_format: 'json',
  items: [
    {
      rank: 1,
      action_type: 'REROUTE',
      shipment_id: 'SHP-0042',
      description: 'Reroute via CARRIER-02 (HUB-A → HUB-C → HUB-D) +12.0 h, +$8,500',
      eta_delta_hours: 12,
      additional_cost_usd: 8500,
      reason_codes: ['PORT_NODE_BLOCKED', 'REEFER_CAPABLE_ALTERNATIVE'],
      confidence_score: 0.95,
    },
    {
      rank: 2,
      action_type: 'ASSET_DEPLOY',
      shipment_id: 'SHP-0042',
      description: 'Deploy idle reefer asset ASSET-R01 (carrier CARRIER-02) from HUB-C to cover shipment.',
      eta_delta_hours: 0,
      additional_cost_usd: 0,
      reason_codes: ['REEFER_CAPACITY_AVAILABLE'],
      confidence_score: 0.9,
    },
    {
      rank: 3,
      action_type: 'COLD_CHAIN_HOLD',
      shipment_id: 'SHP-0042',
      description: 'Cold-chain status is EXCURSION_REVIEW. Place shipment on hold; initiate quality review before releasing to next leg.',
      eta_delta_hours: 0,
      additional_cost_usd: 0,
      reason_codes: ['TEMPERATURE_EXPOSURE_INCREASED', 'EXCURSION_REVIEW'],
      confidence_score: 1.0,
    },
  ],
};
