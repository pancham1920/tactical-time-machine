import test from 'node:test';
import assert from 'node:assert/strict';
import { validateToolResult, chooseDisplay, formatValue, updateAssistant } from '../src/results.js';

const result = (columns, rows, truncated = false) => ({ columns, rows, truncated });
const payload = value => ({ tool_call_id: 'query-1', tool: 'execute_sql', result: value });

test('scalar zero is a stat; identifiers and strings are not', () => {
  assert.equal(chooseDisplay(result(['matches'], [{ matches: 0 }])).kind, 'stat');
  for (const [column, value] of [['player_id', 3], ['matches', '3'], ['matches', null]]) {
    assert.equal(chooseDisplay(result([column], [{ [column]: value }])).kind, 'table');
  }
});

test('chart requires unique categories and real numbers, not IDs', () => {
  assert.deepEqual(chooseDisplay(result(['name', 'goals'], [{ name: 'A', goals: 2 }, { name: 'B', goals: 0 }])),
    { kind: 'chart', categoryColumn: 'name', valueColumn: 'goals' });
  for (const rows of [
    [{ name: 'A', goals: 2 }, { name: 'A', goals: 3 }],
    [{ name: 'A', goals: null }, { name: 'B', goals: 3 }],
    [{ name: 'A', goals: '2' }, { name: 'B', goals: 3 }],
    Array.from({ length: 21 }, (_, i) => ({ name: String(i), goals: i })),
  ]) assert.equal(chooseDisplay(result(['name', 'goals'], rows)).kind, 'table');
  assert.equal(chooseDisplay(result(['name', 'player_id'], [{ name: 'A', player_id: 1 }, { name: 'B', player_id: 2 }])).kind, 'table');
});

test('empty, error and truncated results have honest displays', () => {
  assert.equal(chooseDisplay(result([], [])).kind, 'empty');
  assert.equal(chooseDisplay({ error: 'failed' }).kind, 'error');
  assert.equal(chooseDisplay(result(['count'], [{ count: 100 }], true)).kind, 'table');
});

test('values preserve nulls, zero, text and explicit euro units', () => {
  assert.equal(formatValue(null), '—');
  assert.equal(formatValue(undefined), '—');
  assert.equal(formatValue(0), '0');
  assert.equal(formatValue('001'), '001');
  assert.equal(formatValue(1200000, 'market_value_in_eur'), '€1,200,000');
  assert.equal(formatValue(1200000, 'value'), '1,200,000');
});

test('API validation rejects malformed data and sanitizes tool errors', () => {
  const good = payload(result(['name'], [{ name: '<img src=x>' }]));
  assert.equal(validateToolResult(good), good);
  for (const data of [null, payload('nested JSON'), payload(result(['x', 'x'], [])),
    payload(result(['x'], [{ x: {} }])), payload(result(['x'], [{ x: Infinity }])),
    payload(result(['x'], Array.from({ length: 101 }, () => ({ x: 1 }))))]) {
    assert.throws(() => validateToolResult(data), /invalid database result/);
  }
  assert.doesNotMatch(validateToolResult(payload({ error: '/secret' })).result.error, /secret/);
});

test('results stay with their response, deduplicate by call ID and survive failure', () => {
  const initial = [{ id: 'first', results: [], content: '', status: 'complete' },
    { id: 'second', results: [], content: '', status: 'streaming' }];
  const data = payload(result(['count'], [{ count: 3 }]));
  let messages = updateAssistant(initial, 'second', 'tool_result', data);
  messages = updateAssistant(messages, 'second', 'tool_result', data);
  assert.equal(messages[0], initial[0]);
  assert.equal(messages[1].results.length, 1);
  assert.equal(initial[1].results.length, 0);
  messages = updateAssistant(messages, 'second', 'error');
  assert.equal(messages[1].status, 'error');
  assert.equal(messages[1].results.length, 1);
  messages = updateAssistant(messages, 'second', 'final_answer', { answer: 'Three.' });
  messages = updateAssistant(messages, 'second', 'complete');
  assert.equal(messages[1].content, 'Three.');
  assert.equal(messages[1].status, 'complete');
});
