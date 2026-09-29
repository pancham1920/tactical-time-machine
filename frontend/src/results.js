// Keep API validation and display decisions pure so they are easy to test.
export function validateToolResult(data) {
  const invalid = () => { throw new Error('The server returned an invalid database result.'); };
  if (!data || typeof data.tool_call_id !== 'string' || !data.tool_call_id
      || data.tool !== 'execute_sql' || !data.result || typeof data.result !== 'object') invalid();
  const result = data.result;
  if ('error' in result) {
    return { ...data, result: { error: 'This database query could not produce displayable results.' } };
  }
  if (!Array.isArray(result.columns) || !result.columns.every(column => typeof column === 'string')
      || new Set(result.columns).size !== result.columns.length
      || !Array.isArray(result.rows) || result.rows.length > 100
      || typeof result.truncated !== 'boolean') invalid();
  for (const row of result.rows) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) invalid();
    for (const value of Object.values(row)) {
      if (value !== null && typeof value !== 'string' && typeof value !== 'boolean'
          && !(typeof value === 'number' && Number.isFinite(value))) invalid();
    }
  }
  if (result.rows.length && !result.columns.length) invalid();
  return data;
}

export function columnLabel(column) {
  return column.replaceAll('_', ' ');
}

export function formatValue(value, column = '') {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') {
    if (column.endsWith('_in_eur')) {
      return new Intl.NumberFormat('en-GB', {
        style: 'currency', currency: 'EUR', minimumFractionDigits: 0, maximumFractionDigits: 2,
      }).format(value);
    }
    return new Intl.NumberFormat('en-GB', { maximumFractionDigits: 10 }).format(value);
  }
  return String(value);
}

const numeric = value => typeof value === 'number' && Number.isFinite(value);
const identifier = column => /(^|_)id$|^year$|^season$/.test(column);

export function chooseDisplay({ columns, rows, error, truncated }) {
  if (error) return { kind: 'error' };
  if (!rows.length) return { kind: 'empty' };
  if (columns.length === 1 && rows.length === 1 && !truncated
      && !identifier(columns[0]) && numeric(rows[0][columns[0]])) {
    return { kind: 'stat', valueColumn: columns[0] };
  }
  // Don't guess about mixed types, IDs, repeated categories, or large results.
  if (columns.length === 2 && rows.length >= 2 && rows.length <= 20 && !truncated) {
    const category = columns.find(column => rows.every(row => typeof row[column] === 'string' && row[column].trim()));
    const value = columns.find(column => !identifier(column) && rows.every(row => numeric(row[column])));
    if (category && value && new Set(rows.map(row => row[category])).size === rows.length) {
      return { kind: 'chart', categoryColumn: category, valueColumn: value };
    }
  }
  return { kind: 'table' };
}

export function updateAssistant(messages, id, event, data) {
  return messages.map(message => {
    if (message.id !== id) return message;
    if (event === 'tool_result') {
      const results = message.results.filter(result => result.tool_call_id !== data.tool_call_id);
      return { ...message, results: [...results, data] };
    }
    if (event === 'final_answer') return { ...message, content: data.answer };
    if (event === 'complete') return { ...message, status: 'complete' };
    if (event === 'error') return { ...message, status: 'error' };
    return message;
  });
}
