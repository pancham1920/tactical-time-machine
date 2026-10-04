import test from 'node:test';
import assert from 'node:assert/strict';
import { loadConversation, validateHistory, initialConversation, CONVERSATION_KEY } from '../src/api/history.js';

const id = '12345678-1234-4234-8234-123456789012';
const messages = [{ id: 'user-1', role: 'user', content: 'Count' },
  { id: 'assistant-1', role: 'assistant', content: 'Three', status: 'complete', results: [
    { tool_call_id: 'q1', tool: 'execute_sql', result: { columns: ['count'], rows: [{ count: 3 }], truncated: false } },
  ] }];

test('history GET sends no model input and returns typed display messages', async t => {
  const mock = t.mock.method(globalThis, 'fetch', async () => Response.json({ conversation_id: id, messages }));
  assert.deepEqual(await loadConversation(id, { baseUrl: 'http://test/', token: 'test-token' }), messages);
  assert.equal(mock.mock.calls[0].arguments[1].headers.Authorization, 'Bearer test-token');
  assert.equal(mock.mock.calls[0].arguments[0], `http://test/conversations/${id}`);
  assert.equal(mock.mock.calls[0].arguments[1].cache, 'no-store');
  assert.equal(mock.mock.calls[0].arguments[1].body, undefined);
});

test('missing history is distinct from server and busy failures', async t => {
  const mock = t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 404 }));
  assert.equal(await loadConversation(id), null);
  mock.mock.mockImplementation(async () => new Response('', { status: 409 }));
  await assert.rejects(loadConversation(id), /still running/);
  mock.mock.mockImplementation(async () => new Response('', { status: 503 }));
  await assert.rejects(loadConversation(id), /Retry/);
});

test('wrong thread, internal roles, duplicate IDs and malformed results are rejected', () => {
  for (const data of [
    { conversation_id: 'other', messages },
    { conversation_id: id, messages: [{ id: 's', role: 'system', content: 'secret' }] },
    { conversation_id: id, messages: [messages[0], messages[0]] },
    { conversation_id: id, messages: [{ ...messages[1], results: [{}] }] },
  ]) assert.throws(() => validateHistory(data, id));
});

test('session ID is reused only if valid; unavailable storage degrades safely', t => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  t.after(() => { if (original) Object.defineProperty(globalThis, 'sessionStorage', original); else delete globalThis.sessionStorage; });
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: {
    getItem: key => { assert.equal(key, CONVERSATION_KEY); return id; },
  } });
  assert.deepEqual(initialConversation(), { id, restore: true });
  globalThis.sessionStorage.getItem = () => 'broken';
  assert.equal(initialConversation().restore, false);
  globalThis.sessionStorage.getItem = () => { throw new Error('denied'); };
  assert.equal(initialConversation().restore, false);
});

test('account-specific storage keys do not restore another account', t => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  t.after(() => { if (original) Object.defineProperty(globalThis, 'sessionStorage', original); else delete globalThis.sessionStorage; });
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: {
    getItem: key => key === `${CONVERSATION_KEY}:user-a` ? id : null,
  } });
  assert.deepEqual(initialConversation(`${CONVERSATION_KEY}:user-a`), { id, restore: true });
  assert.equal(initialConversation(`${CONVERSATION_KEY}:user-b`).restore, false);
});

test('expired history token requires sign-in, not a fresh conversation', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 401 }));
  await assert.rejects(loadConversation(id, { token: 'expired' }), /Leave the demo/);
});
