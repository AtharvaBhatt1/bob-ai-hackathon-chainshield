import { useState } from 'react';
import { ActionCenter } from './components/ActionCenter';
import { ColdChainMonitor } from './components/ColdChainMonitor';
import { CrisisOverview } from './components/CrisisOverview';
import { ImpactMap } from './components/ImpactMap';

type Tab = 'crisis' | 'impact' | 'action' | 'coldchain';

const TABS: { id: Tab; label: string }[] = [
  { id: 'crisis', label: 'Crisis Overview' },
  { id: 'impact', label: 'Impact Map' },
  { id: 'action', label: 'Action Center' },
  { id: 'coldchain', label: 'Cold-Chain Monitor' },
];

export default function App() {
  const [tab, setTab] = useState<Tab>('crisis');

  return (
    <div style={{ fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif', color: '#1f2328', minHeight: '100vh', background: '#f7f8fa' }}>
      {/* Header */}
      <header style={{
        background: '#1f2328',
        color: '#ffffff',
        padding: '0 24px',
        display: 'flex',
        alignItems: 'center',
        height: 52,
        gap: 16,
      }}>
        <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-0.02em' }}>⛓ ChainShield</span>
        <span style={{ fontSize: 12, color: '#9ca3af', marginLeft: 4 }}>Supply-Chain Disruption Intelligence</span>
      </header>

      {/* Tab bar */}
      <nav style={{
        background: '#ffffff',
        borderBottom: '1px solid #e5e7eb',
        padding: '0 24px',
        display: 'flex',
        gap: 2,
      }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              border: 'none',
              background: 'none',
              padding: '12px 16px',
              fontSize: 13,
              fontWeight: tab === t.id ? 700 : 400,
              color: tab === t.id ? '#3b82d4' : '#57606a',
              borderBottom: tab === t.id ? '2px solid #3b82d4' : '2px solid transparent',
              cursor: 'pointer',
              transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Main content */}
      <main style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px' }}>
        {tab === 'crisis' && <CrisisOverview />}
        {tab === 'impact' && <ImpactMap />}
        {tab === 'action' && <ActionCenter />}
        {tab === 'coldchain' && <ColdChainMonitor />}
      </main>

      <footer style={{ textAlign: 'center', padding: '24px 0', fontSize: 11, color: '#9ca3af', borderTop: '1px solid #e5e7eb', marginTop: 24 }}>
        ChainShield · IBM Bob AI Hackathon · DEMO_MODE
      </footer>
    </div>
  );
}
