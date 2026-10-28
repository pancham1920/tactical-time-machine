// Present a single numeric SQL result. ResultView decides when this is appropriate.
// Shared formatters keep labels and numeric/currency formatting consistent.
import { columnLabel, formatValue } from '../results.js';

export default function StatCard({ column, value }) {
  return <dl className="stat-card"><dt>{columnLabel(column)}</dt><dd>{formatValue(value, column)}</dd></dl>;
}
