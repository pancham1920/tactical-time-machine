import { columnLabel, formatValue } from '../results.js';

export default function StatCard({ column, value }) {
  return <dl className="stat-card"><dt>{columnLabel(column)}</dt><dd>{formatValue(value, column)}</dd></dl>;
}
