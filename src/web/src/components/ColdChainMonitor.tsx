/**
 * Cold-Chain Monitor
 * ───────────────────
 * Shows:
 * - Policy range (min/max°C, product class)
 * - Excursion classification (status badge)
 * - Evidence dict
 * - Excursion events (with pattern, duration, peak)
 * - Temperature timeline (SVG sparkline)
 * - Per-reading annotated table
 */
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { DEMO_SHIPMENT_ID, demoColdChain } from '../api/demo';
import type { ColdChainTimelineResponse, SensorReadingOut } from '../api/types';
import { Badge, Card, ErrorBox, KV, SeverityBadge, Spinner } from './ui';

/** SVG temperature sparkline */
function Sparkline({ readings }: { readings: SensorReadingOut[] }) {
  if (readings.length < 2) return null;
  const W = 560, H = 80, PAD = 6;
  const temps = readings.map(r => r.temperature_c);
  const minT = Math.min(...temps) - 1;
  const maxT = Math.max(...temps) + 1;
  const toX = (i: number) => PAD + (i / (readings.length - 1)) * (W - PAD * 2);
  const toY = (t: number) => PAD + (1 - (t - minT) / (maxT - minT)) * (H - PAD * 2);

  const points = readings.map((r, i) => `${toX(i)},${toY(r.temperature_c)}`).join(' ');

  return (
    <div style={{ overflowX: 'auto', marginBottom: 8 }}>
      <svg width={W} height={H} style={{ display: 'block', minWidth: W }}>
        {/* out-of-range segments */}
        {readings.map((r, i) => {
          if (r.in_range) return null;
          const x = toX(i);
          return (
            <rect
              key={i}
              x={x - 6}
              y={PAD}
              width={12}
              height={H - PAD * 2}
              fill="#fee2e2"
              opacity={0.7}
            />
          );
        })}
        {/* line */}
        <polyline
          points={points}
          fill="none"
          stroke="#3b82d4"
          strokeWidth={1.5}
        />
        {/* dots */}
        {readings.map((r, i) => (
          <circle
            key={i}
            cx={toX(i)}
            cy={toY(r.temperature_c)}
            r={3}
            fill={r.in_range ? '#3b82d4' : '#dc2626'}
          />
        ))}
        {/* x-axis label count */}
        <text x={PAD} y={H - 1} fontSize={9} fill="#9ca3af">{readings[0].ts.slice(11, 16)}</text>
        <text x={W - PAD} y={H - 1} fontSize={9} fill="#9ca3af" textAnchor="end">
          {readings[readings.length - 1].ts.slice(11, 16)}
        </text>
      </svg>
    </div>
  );
}

export function ColdChainMonitor() {
  const [data, setData] = useState<ColdChainTimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api.getColdChainTimeline(DEMO_SHIPMENT_ID)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => { setData(demoColdChain); setOffline(true); setLoading(false); });
  }, []);

  if (loading) return <div style={{ padding: 20 }}><Spinner /></div>;
  if (!data) return <ErrorBox message="No cold-chain data" />;

  const { policy, readings, excursion_events, status, evidence } = data;

  return (
    <div>
      {offline && (
        <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 4, padding: '8px 14px', marginBottom: 12, fontSize: 12, color: '#92400e' }}>
          ⚡ Backend offline — showing local demo data
        </div>
      )}

      {/* ── Classification ─────────────────────────────────────────────────── */}
      <Card title="Excursion Classification" accent="yellow">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
          <SeverityBadge status={status} />
          <span style={{ fontSize: 13, color: '#57606a' }}>Shipment {data.shipment_id}</span>
        </div>
        <KV label="Max recorded" value={`${data.max_celsius ?? '—'} °C`} />
        <KV label="Min recorded" value={`${data.min_celsius ?? '—'} °C`} />
        <KV label="Total out-of-range" value={`${data.total_out_of_range_minutes} min`} />
      </Card>

      {/* ── Policy ─────────────────────────────────────────────────────────── */}
      {policy && (
        <Card title="Policy Profile" accent="blue">
          <KV label="Policy ID" value={policy.policy_id} mono />
          <KV label="Product class" value={policy.product_class} />
          <KV label="Allowed range" value={`${policy.min_celsius}°C – ${policy.max_celsius}°C`} />
          <KV label="Sample interval" value={`${policy.sample_interval_minutes} min`} />
          <KV label="Max excursion" value={`${policy.max_excursion_minutes} min`} />
        </Card>
      )}

      {/* ── Sparkline ──────────────────────────────────────────────────────── */}
      <Card title="Temperature Timeline" accent="none">
        <div style={{ fontSize: 11, color: '#57606a', marginBottom: 6 }}>
          Red markers = out-of-range readings
        </div>
        <Sparkline readings={readings} />
        <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4 }}>
          {readings.length} readings · {readings.filter(r => !r.in_range).length} out of range
        </div>
      </Card>

      {/* ── Excursion Events ───────────────────────────────────────────────── */}
      {excursion_events.length > 0 && (
        <Card title="Excursion Events" accent="red">
          {excursion_events.map((ev, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #f3f4f6' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <Badge label={ev.pattern} color="#fee2e2" />
                <span style={{ fontSize: 12, color: '#57606a' }}>{ev.duration_minutes} min</span>
              </div>
              <KV label="Start" value={new Date(ev.start_ts).toLocaleString()} />
              <KV label="End" value={new Date(ev.end_ts).toLocaleString()} />
              <KV label="Peak" value={`${ev.max_celsius}°C`} />
              <KV label="Low" value={`${ev.min_celsius}°C`} />
            </div>
          ))}
        </Card>
      )}

      {/* ── Evidence ───────────────────────────────────────────────────────── */}
      <Card title="Evidence" accent="none">
        <pre style={{
          background: '#f7f8fa',
          border: '1px solid #e5e7eb',
          borderRadius: 4,
          padding: '8px 12px',
          fontSize: 11,
          overflow: 'auto',
          maxHeight: 160,
          margin: 0,
        }}>
          {JSON.stringify(evidence, null, 2)}
        </pre>
      </Card>

      {/* ── Readings Table ─────────────────────────────────────────────────── */}
      <Card title="Sensor Readings" accent="none">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#f7f8fa', borderBottom: '1px solid #e5e7eb' }}>
                {['Sensor', 'Timestamp', 'Temp (°C)', 'Battery', 'In Range'].map(h => (
                  <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: '#57606a', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {readings.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f3f4f6', background: r.in_range ? undefined : '#fff5f5' }}>
                  <td style={{ padding: '5px 10px', fontFamily: 'monospace' }}>{r.sensor_id}</td>
                  <td style={{ padding: '5px 10px', whiteSpace: 'nowrap' }}>{new Date(r.ts).toLocaleString()}</td>
                  <td style={{ padding: '5px 10px', fontWeight: r.in_range ? undefined : 700, color: r.in_range ? undefined : '#dc2626' }}>
                    {r.temperature_c.toFixed(1)}
                  </td>
                  <td style={{ padding: '5px 10px' }}>{r.battery_pct != null ? `${r.battery_pct}%` : '—'}</td>
                  <td style={{ padding: '5px 10px', color: r.in_range ? '#16a34a' : '#dc2626', fontWeight: 700 }}>
                    {r.in_range ? '✓' : '✗'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
