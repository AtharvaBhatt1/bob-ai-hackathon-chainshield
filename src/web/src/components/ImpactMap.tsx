/**
 * Impact Map
 * ──────────
 * Shows route alternatives and carrier options for the affected shipment.
 * - Shipment legs (origin → destination chain)
 * - Route alternatives with ETA delta, cost, reefer flag, reason codes
 */
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { DEMO_SHIPMENT_ID, demoShipment } from '../api/demo';
import type { ShipmentDetailResponse } from '../api/types';
import { Badge, Card, ErrorBox, KV, Spinner } from './ui';

function fmtUsd(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v);
}

export function ImpactMap() {
  const [data, setData] = useState<ShipmentDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api.getShipment(DEMO_SHIPMENT_ID)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => { setData(demoShipment); setOffline(true); setLoading(false); });
  }, []);

  if (loading) return <div style={{ padding: 20 }}><Spinner /></div>;
  if (!data) return <ErrorBox message="No shipment data" />;

  const { shipment, legs, alternatives } = data;

  return (
    <div>
      {offline && (
        <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 4, padding: '8px 14px', marginBottom: 12, fontSize: 12, color: '#92400e' }}>
          ⚡ Backend offline — showing local demo data
        </div>
      )}

      <Card title="Shipment Detail" accent="blue">
        <KV label="Shipment ID" value={shipment.shipment_id} mono />
        <KV label="Route" value={`${shipment.origin} → ${shipment.destination}`} />
        <KV label="Status" value={shipment.status} />
        <KV label="Cargo type" value={shipment.cargo_type} />
        <KV label="Carrier" value={shipment.carrier_id} mono />
        <KV label="ETA" value={shipment.eta ? new Date(shipment.eta).toLocaleString() : '—'} />
      </Card>

      <Card title="Planned Route Legs" accent="blue">
        <div style={{ overflowX: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap' }}>
            {legs.map((leg, i) => (
              <span key={leg.leg_id} style={{ display: 'flex', alignItems: 'center' }}>
                <span style={{
                  background: '#eff6ff',
                  border: '1px solid #bfdbfe',
                  borderRadius: 4,
                  padding: '4px 10px',
                  fontSize: 12,
                  fontWeight: 600,
                  fontFamily: 'monospace',
                }}>
                  {leg.origin_node_id}
                </span>
                <span style={{ color: '#6b7280', padding: '0 6px', fontSize: 11 }}>
                  ──{leg.mode}──▶
                </span>
                {i === legs.length - 1 && (
                  <span style={{
                    background: '#eff6ff',
                    border: '1px solid #bfdbfe',
                    borderRadius: 4,
                    padding: '4px 10px',
                    fontSize: 12,
                    fontWeight: 600,
                    fontFamily: 'monospace',
                  }}>
                    {leg.destination_node_id}
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Route Alternatives" accent="yellow">
        {alternatives.length === 0 ? (
          <p style={{ color: '#57606a', fontSize: 13 }}>No alternatives available.</p>
        ) : (
          alternatives.map((alt, i) => (
            <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid #f3f4f6' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>{alt.carrier_id}</span>
                <span style={{ fontSize: 12, color: alt.reefer_capable ? '#16a34a' : '#6b7280', fontWeight: 600 }}>
                  {alt.reefer_capable ? '❄ Reefer' : 'Standard'}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#374151', marginBottom: 4 }}>
                {alt.route_nodes.join(' → ')}
              </div>
              <div style={{ fontSize: 12, color: '#57606a', marginBottom: 4 }}>
                ETA delta: <strong>+{alt.eta_delta_hours}h</strong>
                {' · '}
                Extra cost: <strong>{fmtUsd(alt.additional_cost_usd)}</strong>
              </div>
              <div>
                {alt.reason_codes.map(rc => <Badge key={rc} label={rc} color="#fef9c3" />)}
              </div>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}
