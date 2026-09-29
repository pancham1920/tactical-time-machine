import { BarChart as RechartsBarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { columnLabel, formatValue } from '../results.js';

export default function BarChart({ rows, categoryColumn, valueColumn }) {
  // Fixed internal keys avoid interpreting SQL column names as nested paths.
  const data = rows.map(row => ({ category: row[categoryColumn], value: row[valueColumn] }));
  return (
    <div className="result-chart" role="group" aria-label={`${columnLabel(valueColumn)} by ${columnLabel(categoryColumn)}. Exact values in the table below.`}>
      <p className="result-note">{columnLabel(valueColumn)} by {columnLabel(categoryColumn)}</p>
      <ResponsiveContainer width="100%" height={Math.max(220, rows.length * 38 + 40)} minWidth={0}>
        <RechartsBarChart data={data} layout="vertical" margin={{ top: 8, right: 20, bottom: 8, left: 0 }} accessibilityLayer>
          <XAxis type="number" tick={{ fill: '#a3b0a5', fontSize: 10 }} tickFormatter={value => new Intl.NumberFormat('en-GB', { notation: 'compact' }).format(value)} />
          <YAxis type="category" dataKey="category" width={95} tick={{ fill: '#d4e4ca', fontSize: 10 }} tickFormatter={value => value.length > 16 ? `${value.slice(0, 15)}…` : value} />
          <Tooltip formatter={value => [formatValue(value, valueColumn), columnLabel(valueColumn)]} contentStyle={{ background: '#1a2720', border: '1px solid #607654', color: '#eef2e9' }} itemStyle={{ color: '#eef2e9' }} />
          <Bar dataKey="value" fill="#b1e18e" radius={[0, 3, 3, 0]} isAnimationActive={false} />
        </RechartsBarChart>
      </ResponsiveContainer>
    </div>
  );
}
