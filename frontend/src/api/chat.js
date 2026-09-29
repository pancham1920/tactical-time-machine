import { createSseParser } from './sse.js';

const DEFAULT_BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const INTERRUPTED = 'The response was interrupted. Please try your question again.';

// LangChain content can be plain text or an array of typed content blocks.
export function answerText(content) {
  if (typeof content === 'string' && content.trim()) return content;
  if (Array.isArray(content)) {
    const text = content
      .filter(block => block?.type === 'text' && typeof block.text === 'string')
      .map(block => block.text)
      .join('\n');
    if (text.trim()) return text;
  }
  throw new Error('The agent returned no readable answer. Please try again.');
}

/** Submit one question and deliver progress events; never automatically retry. */
export async function streamChat({ message, onEvent, signal, baseUrl = DEFAULT_BASE_URL }) {
  const question = message.trim();
  if (!question || question.length > 2000) {
    throw new Error('Enter a question between 1 and 2,000 characters.');
  }

  let response;
  try {
    response = await fetch(`${baseUrl.replace(/\/+$/, '')}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message: question }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('Could not reach the football API. Check that the backend is running.');
  }

  if (!response.ok) {
    await response.body?.cancel();
    if (response.status === 422) throw new Error('The question was rejected. Use 1–2,000 characters.');
    if (response.status === 429) throw new Error('Too many requests. Wait a moment and try again.');
    throw new Error(`The football API could not complete this request (HTTP ${response.status}).`);
  }
  if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
    await response.body?.cancel();
    throw new Error('The server did not return an event stream. Check the API address.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let completed = false;
  let answered = false;
  const parser = createSseParser(({ event, data }) => {
    if (completed) return;
    if (event === 'error') {
      // Do not display raw backend exception text to visitors.
      throw new Error('The football agent could not complete this request. Please try again.');
    }
    if (event === 'final_answer') {
      if (answered) return;
      const answer = answerText(data?.answer);
      answered = true;
      onEvent({ event, data: { answer } });
      return;
    }
    if (event === 'complete') {
      if (!answered) throw new Error('The agent finished without an answer. Please try again.');
      completed = true;
    }
    onEvent({ event, data });
  });

  try {
    while (!completed) {
      const { value, done } = await reader.read();
      if (done) {
        parser.push(decoder.decode());
        parser.finish();
        break;
      }
      parser.push(decoder.decode(value, { stream: true }));
    }
    if (!completed) throw new Error(INTERRUPTED);
  } finally {
    // Release the connection on success, parse errors, and cancellation.
    try { await reader.cancel(); } catch { /* The network may already be closed. */ }
    reader.releaseLock();
  }
}
