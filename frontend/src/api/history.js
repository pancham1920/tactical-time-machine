import { validateToolResult } from '../results.js';

export const CONVERSATION_KEY = 'football-agent.conversation.v1';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export function initialConversation() {
  try {
    const id = sessionStorage.getItem(CONVERSATION_KEY);
    if (id && UUID.test(id)) return { id, restore: true };
  } catch { /* Storage can be unavailable in privacy-restricted browsers. */ }
  return { id: crypto.randomUUID(), restore: false };
}

export function validateHistory(data, conversationId) {
  const invalid = () => { throw new Error('The saved conversation could not be read. Retry or start a new chat.'); };
  if (!data || data.conversation_id !== conversationId || !Array.isArray(data.messages)) invalid();
  const ids = new Set();
  const messages = data.messages.map(message => {
    if (!message || typeof message.id !== 'string' || !message.id || ids.has(message.id)
        || !['user', 'assistant'].includes(message.role) || typeof message.content !== 'string') invalid();
    ids.add(message.id);
    if (message.role === 'user') return { id: message.id, role: 'user', content: message.content };
    if (!['complete', 'error'].includes(message.status) || !Array.isArray(message.results)) invalid();
    return { id: message.id, role: 'assistant', content: message.content,
      status: message.status, results: message.results.map(validateToolResult) };
  });
  return messages;
}

export async function loadConversation(conversationId, { signal, baseUrl = BASE_URL } = {}) {
  let response;
  try {
    response = await fetch(`${baseUrl.replace(/\/+$/, '')}/conversations/${encodeURIComponent(conversationId)}`, {
      signal, cache: 'no-store', headers: { Accept: 'application/json' },
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('Could not load saved chat. Check the backend, then retry or start a new chat.');
  }
  if (response.status === 404) return null;
  if (response.status === 409) throw new Error('This chat is still running. Wait a moment, then retry loading history.');
  if (!response.ok) throw new Error('Could not load saved chat. Retry or start a new chat.');
  let data;
  try { data = await response.json(); }
  catch { throw new Error('The saved conversation response was unreadable. Retry or start a new chat.'); }
  return validateHistory(data, conversationId);
}
