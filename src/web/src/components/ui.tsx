import type { ReactNode } from 'react';

interface CardProps {
  title: string;
  children: ReactNode;
  accent?: 'red' | 'yellow' | 'green' | 'blue' | 'none';
}

const ACCENT_COLORS: Record<string, string> = {
  red: '#dc2626',
  yellow: '#d97706',
  green: '#16a34a',
  blue: '#2563eb',
  none: '#6b7280',
};

export function Card({ title, children, accent = 'none' }: CardProps) {
  return (
    <div style={{
      background: '#ffffff',
      border: `1px solid #e5e7eb`,
      borderTop: `3px solid ${ACCENT_COLORS[accent]}`,
      borderRadius: 6,
      padding: '16px 20px',
      marginBottom: 16,
    }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#57606a' }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

interface BadgeProps { label: string; color?: string; }
export function Badge({ label, color = '#e5e7eb' }: BadgeProps) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 12,
      background: color,
      fontSize: 11,
      fontWeight: 600,
      color: '#1f2328',
      marginRight: 4,
      marginBottom: 4,
      fontFamily: 'monospace',
    }}>
      {label}
    </span>
  );
}

export function Spinner() {
  return (
    <span style={{
      display: 'inline-block',
      width: 16,
      height: 16,
      border: '2px solid #e5e7eb',
      borderTopColor: '#3b82d4',
      borderRadius: '50%',
      animation: 'spin 0.7s linear infinite',
    }} />
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 4, padding: '10px 14px', color: '#dc2626', fontSize: 13 }}>
      ⚠ {message}
    </div>
  );
}

interface KVProps { label: string; value: ReactNode; mono?: boolean; }
export function KV({ label, value, mono }: KVProps) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #f3f4f6', fontSize: 13 }}>
      <span style={{ color: '#57606a' }}>{label}</span>
      <span style={{ fontWeight: 500, fontFamily: mono ? 'monospace' : undefined }}>{value}</span>
    </div>
  );
}

export function SeverityBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    SAFE: '#dcfce7',
    EXCURSION_REVIEW: '#fef9c3',
    URGENT_ESCALATION: '#fee2e2',
    POLICY_REQUIRED: '#e0e7ff',
  };
  const text: Record<string, string> = {
    SAFE: '#15803d',
    EXCURSION_REVIEW: '#a16207',
    URGENT_ESCALATION: '#b91c1c',
    POLICY_REQUIRED: '#3730a3',
  };
  const bg = colors[status] ?? '#f3f4f6';
  const fg = text[status] ?? '#374151';
  return (
    <span style={{ background: bg, color: fg, borderRadius: 12, padding: '2px 10px', fontWeight: 700, fontSize: 12 }}>
      {status}
    </span>
  );
}
