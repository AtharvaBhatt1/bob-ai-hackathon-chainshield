/**
 * Action Center
 * ─────────────
 * Shows:
 * - Idle assets (reefer-capable first)
 * - Action plan items: REROUTE, ASSET_DEPLOY, COLD_CHAIN_HOLD
 * - Per-item reason codes, confidence, ETA delta, cost
 * - Explanation panel (summary, why_affected, recommended_action, evidence,
 *   uncertainties, confidence, offline status)
 */
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import {
  DEMO_DECISION_ID,
  DEMO_DISRUPTION,
  demoActionPlan,
  demoExplanation,
  demoIdleAssets,
} from '../api/demo';
import type {
  ActionPlanResponse,
  ExplanationResult,
  IdleAssetsResponse,
} from '../api/types';
import { Badge, Card, ErrorBox, KV, Spinner } from './ui';

function fmtUsd(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v);
}

const ACTION_COLORS: Record<string, string> = {
  REROUTE: '#dbeafe',
  ASSET_DEPLOY: '#dcfce7',
  COLD_CHAIN_HOLD: '#fee2e2',
};

export function ActionCenter() {
  const [assets, setAssets] = useState<IdleAssetsResponse | null>(null);
  const [plan, setPlan] = useState<ActionPlanResponse | null>(null);
  const [explanation, setExplanation] = useState<ExplanationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [explLoading, setExplLoading] = useState(false);
  const [explError, setExplError] = useState<string | null>(null);

  useEffect(() => {
    let offlineFlag = false;
    Promise.all([
      api.getIdleAssets().catch(() => { offlineFlag = true; return demoIdleAssets; }),
      api.exportActionPlan(DEMO_DISRUPTION).catch(() => { offlineFlag = true; return demoActionPlan; }),
    ]).then(([a, p]) => {
      setAssets(a);
      setPlan(p);
      if (offlineFlag) setOffline(true);
      setLoading(false);
    });
  }, []);

  function loadExplanation() {
    setExplLoading(true);
    setExplError(null);
    api.generateExplanation(DEMO_DECISION_ID)
      .then(e => { setExplanation(e); setExplLoading(false); })
      .catch(() => { setExplanation(demoExplanation); setExplLoading(false); });
  }

  if (loading) return <div style={{ padding: 20 }}><Spinner /></div>;

  return (
    <div>
      {offline && (
        <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 4, padding: '8px 14px', marginBottom: 12, fontSize: 12, color: '#92400e' }}>
          ⚡ Backend offline — showing local demo data
        </div>
      )}

      {/* ── Idle Assets ───────────────────────────────────────────────────── */}
      <Card title="Idle Assets" accent="green">
        {assets && assets.assets.length === 0 && (
          <p style={{ color: '#57606a', fontSize: 13 }}>No idle assets found.</p>
        )}
        {assets?.assets.map(m => (
          <div key={m.asset_id} style={{ padding: '8px 0', borderBottom: '1px solid #f3f4f6' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
              <span style={{ fontWeight: 600, fontFamily: 'monospace', fontSize: 13 }}>{m.asset_id}</span>
              <span style={{ fontSize: 12, color: m.asset.reefer_capable ? '#16a34a' : '#6b7280', fontWeight: 600 }}>
                {m.asset.reefer_capable ? '❄ Reefer' : 'Standard'} · {m.asset.asset_type}
              </span>
            </div>
            <div style={{ fontSize: 12, color: '#57606a', marginBottom: 4 }}>
              Carrier: {m.asset.carrier_id} · At: {m.asset.current_node_id} · Reposition: {m.reposition_distance_km} km
            </div>
            <div>
              {m.reason_codes.map(rc => <Badge key={rc} label={rc} color="#dcfce7" />)}
            </div>
          </div>
        ))}
      </Card>

      {/* ── Action Plan ───────────────────────────────────────────────────── */}
      <Card title="Action Plan" accent="blue">
        {plan?.items.map(item => (
          <div key={item.rank} style={{
            padding: '10px 12px',
            borderRadius: 4,
            background: ACTION_COLORS[item.action_type] ?? '#f9fafb',
            marginBottom: 8,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontWeight: 700, fontSize: 12, color: '#374151' }}>
                #{item.rank} {item.action_type}
              </span>
              <span style={{ fontSize: 11, color: '#57606a', fontFamily: 'monospace' }}>{item.shipment_id}</span>
            </div>
            <p style={{ margin: '0 0 6px', fontSize: 13, color: '#1f2328' }}>{item.description}</p>
            <div style={{ fontSize: 12, color: '#57606a', marginBottom: 4 }}>
              {item.eta_delta_hours > 0 && `ETA +${item.eta_delta_hours}h · `}
              {item.additional_cost_usd > 0 && `Extra cost ${fmtUsd(item.additional_cost_usd)} · `}
              Confidence: <strong>{(item.confidence_score * 100).toFixed(0)}%</strong>
            </div>
            <div>
              {item.reason_codes.map(rc => <Badge key={rc} label={rc} />)}
            </div>
          </div>
        ))}
      </Card>

      {/* ── Explanation ───────────────────────────────────────────────────── */}
      <Card title="AI Explanation" accent="none">
        {!explanation && !explLoading && (
          <button
            onClick={loadExplanation}
            style={{
              background: '#3b82d4',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              padding: '7px 16px',
              fontSize: 13,
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Generate Explanation
          </button>
        )}
        {explLoading && <Spinner />}
        {explError && <ErrorBox message={explError} />}
        {explanation && (
          <div>
            <div style={{
              fontSize: 11,
              fontWeight: 700,
              marginBottom: 10,
              color: explanation.model_used ? '#1d4ed8' : '#92400e',
              background: explanation.model_used ? '#eff6ff' : '#fffbeb',
              padding: '4px 10px',
              borderRadius: 12,
              display: 'inline-block',
            }}>
              {explanation.model_used ? `🤖 ${explanation.model_used}` : '⚡ OFFLINE FALLBACK'}
            </div>

            <KV label="Summary" value={<span style={{ fontSize: 12 }}>{explanation.summary}</span>} />

            <KV label="Why affected" value={
              <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12 }}>
                {explanation.why_affected.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            } />

            <KV label="Recommended action" value={<span style={{ fontSize: 12 }}>{explanation.recommended_action}</span>} />

            {explanation.uncertainties.length > 0 && (
              <KV label="Uncertainties" value={
                <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12, color: '#57606a' }}>
                  {explanation.uncertainties.map((u, i) => <li key={i}>{u}</li>)}
                </ul>
              } />
            )}

            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, color: '#57606a', marginBottom: 4 }}>Evidence (reason codes)</div>
              <div>
                {explanation.evidence.map(rc => <Badge key={rc} label={rc} color="#e0e7ff" />)}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
