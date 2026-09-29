import { lazy, Suspense } from 'react';
import { chooseDisplay } from '../results.js';
import DataTable from './DataTable.jsx';
import StatCard from './StatCard.jsx';

const BarChart = lazy(() => import('./BarChart.jsx'));

export default function ResultView({ payload, index }) {
  const result = payload.result;
  const display = chooseDisplay(result);
  return (
    <section className="query-result" aria-label={`Query result ${index + 1}`}>
      <h3>Query result {index + 1} <span>SQLite data</span></h3>
      {display.kind === 'error' && <p className="result-warning">{result.error}</p>}
      {display.kind === 'empty' && <p className="result-note">No matching records found.</p>}
      {display.kind === 'stat' && <StatCard column={display.valueColumn} value={result.rows[0][display.valueColumn]} />}
      {display.kind === 'chart' && (
        <Suspense fallback={<p className="result-note">Loading chart; values are available below.</p>}>
          <BarChart rows={result.rows} {...display} />
        </Suspense>
      )}
      {(display.kind === 'table' || display.kind === 'chart') && <DataTable {...result} />}
      {result.truncated && <p className="result-warning">Showing the first {result.rows.length} rows; more results exist. Ask a narrower question for a complete result.</p>}
    </section>
  );
}
