import test from 'node:test';
import assert from 'node:assert/strict';
import { createSseParser } from '../src/api/sse.js';

test('accepts events split at every character, with comments and split CRLF', () => {
  const events = [];
  const parser = createSseParser(event => events.push(event));
  const input = ': heartbeat\r\nevent: connected\r\ndata: {"message":"Ready"}\r\n\r\n'
    + 'event: complete\ndata: {}\n\n';
  for (const character of input) parser.push(character);
  parser.finish();
  assert.deepEqual(events, [
    { event: 'connected', data: { message: 'Ready' } },
    { event: 'complete', data: {} },
  ]);
});

test('parses multiple events per chunk and multiline JSON data', () => {
  const events = [];
  const parser = createSseParser(event => events.push(event));
  parser.push('event: final_answer\ndata: {\ndata: "answer":"Hello"}\n\n'
    + 'event: complete\ndata: {}\n\n');
  parser.finish();
  assert.equal(events[0].data.answer, 'Hello');
  assert.equal(events[1].event, 'complete');
});

test('supports CR line endings and ignores comments and empty frames', () => {
  const events = [];
  const parser = createSseParser(event => events.push(event));
  parser.push(': comment\r\revent: connected\rdata: {}\r\r');
  parser.finish();
  assert.deepEqual(events, [{ event: 'connected', data: {} }]);
});

test('rejects malformed JSON', () => {
  const parser = createSseParser(() => {});
  assert.throws(() => parser.push('event: tool_call\ndata: not-json\n\n'), /unreadable/);
});

test('does not dispatch unfinished events and rejects premature EOF', () => {
  const events = [];
  const parser = createSseParser(event => events.push(event));
  parser.push('event: final_answer\ndata: {"answer":"Incomplete"}\n');
  assert.equal(events.length, 0);
  assert.throws(() => parser.finish(), /interrupted/);
});
