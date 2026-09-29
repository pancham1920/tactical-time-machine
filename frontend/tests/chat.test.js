import test from 'node:test';
import assert from 'node:assert/strict';
import { answerText, streamChat } from '../src/api/chat.js';

const event = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const success = event('connected', {})
  + event('tool_call', { tools: ['execute_sql'] })
  + event('tool_result', { result: '{"rows":[{"matches":3}]}' })
  + event('final_answer', { answer: 'Müller ⚽: 3 matches' })
  + event('complete', {});

function mockStream(t, text, { byteByByte = false, leaveOpen = false, onCancel } = {}) {
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream({
    start(controller) {
      if (byteByByte) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      } else {
        controller.enqueue(bytes);
      }
      if (!leaveOpen) controller.close();
    },
    cancel: onCancel,
  });
  return t.mock.method(globalThis, 'fetch', async () => new Response(body, {
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
  }));
}

test('posts only the latest question and decodes split UTF-8 correctly', async t => {
  const fetchMock = mockStream(t, success, { byteByByte: true });
  const events = [];
  await streamChat({
    message: '  Count matches  ', baseUrl: 'http://localhost:8000/',
    onEvent: value => events.push(value),
  });
  const [url, options] = fetchMock.mock.calls[0].arguments;
  assert.equal(url, 'http://localhost:8000/chat/stream');
  assert.equal(options.method, 'POST');
  assert.deepEqual(JSON.parse(options.body), { message: 'Count matches' });
  assert.deepEqual(events.map(item => item.event), [
    'connected', 'tool_call', 'tool_result', 'final_answer', 'complete',
  ]);
  assert.equal(events[3].data.answer, 'Müller ⚽: 3 matches');
});

test('complete cancels the reader even if the server leaves the connection open', async t => {
  let cancelled = false;
  mockStream(t, success, { leaveOpen: true, onCancel: () => { cancelled = true; } });
  await streamChat({ message: 'Count matches', onEvent() {} });
  assert.equal(cancelled, true);
});

test('an SSE error is sanitized and is not treated as success', async t => {
  const events = [];
  mockStream(t, event('connected', {}) + event('error', { message: '/private/server/path' }));
  await assert.rejects(
    streamChat({ message: 'Count matches', onEvent: value => events.push(value) }),
    error => error.message.includes('could not complete') && !error.message.includes('/private'),
  );
  assert.deepEqual(events.map(item => item.event), ['connected']);
});

test('a closed stream without complete is an interruption', async t => {
  mockStream(t, event('final_answer', { answer: 'Partial success' }));
  await assert.rejects(streamChat({ message: 'Count matches', onEvent() {} }), /interrupted/);
});

test('complete without an answer is an error', async t => {
  mockStream(t, event('connected', {}) + event('complete', {}));
  await assert.rejects(streamChat({ message: 'Count matches', onEvent() {} }), /without an answer/);
});

test('HTTP failures are reported without exposing response details', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('private traceback', { status: 502 }));
  await assert.rejects(streamChat({ message: 'Count matches', onEvent() {} }), /HTTP 502/);
});

test('JSON responses are not mistaken for event streams', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ answer: 'wrong endpoint' }));
  await assert.rejects(streamChat({ message: 'Count matches', onEvent() {} }), /did not return an event stream/);
});

test('invalid questions are rejected before a request is made', async t => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => { throw new Error('Unexpected call'); });
  for (const message of ['  ', 'x'.repeat(2001)]) {
    await assert.rejects(streamChat({ message, onEvent() {} }), /between 1 and 2,000/);
  }
  assert.equal(fetchMock.mock.callCount(), 0);
});

test('connection errors get a useful backend message', async t => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(streamChat({ message: 'Count matches', onEvent() {} }), /backend is running/);
});

test('an aborted request preserves cancellation', async t => {
  const controller = new AbortController();
  controller.abort();
  t.mock.method(globalThis, 'fetch', async () => { throw controller.signal.reason; });
  await assert.rejects(
    streamChat({ message: 'Count matches', onEvent() {}, signal: controller.signal }),
    error => error.name === 'AbortError',
  );
});

test('extracts visible text blocks without rendering reasoning or HTML', () => {
  assert.equal(answerText([{ type: 'thinking', text: 'hidden' }, { type: 'text', text: 'Answer' }]), 'Answer');
  assert.equal(answerText('<script>example</script>'), '<script>example</script>');
  assert.throws(() => answerText([]), /no readable answer/);
});
