import type {
  ActionPlanResponse,
  ColdChainTimelineResponse,
  DisruptionActivateResponse,
  ExplanationResult,
  HealthResponse,
  IdleAssetsResponse,
  ShipmentDetailResponse,
} from './types';

const BASE = '/api/v1';

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch('/healthz').then(r => r.json() as Promise<HealthResponse>),

  activateDisruption: (disruption_id: string) =>
    post<DisruptionActivateResponse>('/disruptions/activate', { disruption_id }),

  getShipment: (shipment_id: string) =>
    get<ShipmentDetailResponse>(`/shipments/${shipment_id}`),

  getIdleAssets: () => get<IdleAssetsResponse>('/assets/idle'),

  getColdChainTimeline: (shipment_id: string) =>
    get<ColdChainTimelineResponse>(`/cold-chain/${shipment_id}/timeline`),

  generateExplanation: (decision_id: string) =>
    post<ExplanationResult>('/explanations/generate', { decision_id }),

  exportActionPlan: (disruption_id: string) =>
    post<ActionPlanResponse>('/action-plan/export', {
      disruption_id,
      export_format: 'json',
    }),
};
