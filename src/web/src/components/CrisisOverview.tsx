/**
 * Crisis Overview
 * ─────────────────
 * Activates the demo disruption and shows:
 * - Active disruption ID
 * - Affected shipment count
 * - Total cargo value at risk
 * - Per-shipment impact rows with reason codes
 */
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import {
  DEMO_DISRUPTION,
  demoActivate,
} from '../api/demo';
import type { DisruptionActivateResponse } from '../api/types';
import { Badge, Card, KV, Spinner } from './ui';

function fmtUsd(v: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v);
}

export function CrisisOverview() {
  const [data, setData] = useState<DisruptionActivateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api.activateDisruption(DEMO_DISRUPTION)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => {
        setData(demoActivate);
        setOffline(true);
        setLoading(false);
      });
  }, []);

  if (loading) return <div style={{ padding: 20 }}><Spinner /></div>;
  if (!data) return null;

  const affected = data.affected_shipments.filter(s => s.affected);
  const totalValue = data.affected_shipments.reduce((sum, s) => s.affected ? sum + s.cargo_value_usd : sum, 0);

  return (
    <div>
      {offline && (
        <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 4, padding: '8px 14px', marginBottom: 12, fontSize: 12, color: '#92400e' }}>
          ⚡ Backend offline — showing local demo data
        </div>
      )}
      <Card title="Active Disruption" accent="red">
        <KV label="Disruption ID" value={data.disruption_id} mono />
        <KV label="Affected Shipments" value={`${affected.length} / ${data.affected_shipments.length}`} />
        <KV label="Cargo Value at Risk" value={fmtUsd(totalValue)} />
      </Card>

      <Card title="Affected Shipments" accent="red">
        {data.affected_shipments.map(shp => (
          <div key={shp.shipment_id} style={{
            padding: '10px 0',
            borderBottom: '1px solid #f3f4f6',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>{shp.shipment_id}</span>
              <span style={{
                fontSize: 12,
                fontWeight: 700,
                color: shp.affected ? '#dc2626' : '#16a34a',
                background: shp.affected ? '#fee2e2' : '#dcfce7',
                borderRadius: 10,
                padding: '1px 8px',
              }}>
                {shp.affected ? 'AFFECTED' : 'CLEAR'}
              </span>
            </div>
            <div style={{ fontSize: 12, color: '#57606a', marginBottom: 4 }}>
              Value: {fmtUsd(shp.cargo_value_usd)}
              {shp.eta_delay_hours > 0 && ` · ETA delay: +${shp.eta_delay_hours}h`}
            </div>
            <div>
              {shp.reason_codes.map(rc => (
                <Badge key={rc} label={rc} color="#fee2e2" />
              ))}
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}
