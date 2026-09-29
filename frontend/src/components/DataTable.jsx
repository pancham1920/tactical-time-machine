import { columnLabel, formatValue } from '../results.js';

export default function DataTable({ columns, rows }) {
  return (
    <div className="result-table-scroll" tabIndex={0} role="region" aria-label="Scrollable query results">
      <table className="result-table">
        <caption>Database query results</caption>
        <thead><tr>{columns.map(column => <th scope="col" key={column}>{columnLabel(column)}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => (
          <tr key={index}>{columns.map(column => <td key={column}>{formatValue(row[column], column)}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}
