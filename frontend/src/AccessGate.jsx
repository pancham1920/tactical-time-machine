import { useState } from 'react';
import App from './App.jsx';

const STORAGE_KEY = 'football-demo-access';
const local = Boolean(import.meta.env.DEV && import.meta.env.VITE_AUTH_MODE === 'local');

function savedAccess() {
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
    if (value?.code && /^[a-f0-9]{64}$/.test(value.session)) return value;
  } catch { /* A new browser session needs a fresh invitation code. */ }
  return null;
}

export default function AccessGate() {
  const [access, setAccess] = useState(savedAccess);
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function enter(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const session = Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('');
    try {
      const base = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
      const response = await fetch(`${base.replace(/\/+$/, '')}/access`, {
        headers: { Authorization: `Bearer ${code.trim()}`, 'X-Demo-Session': session },
      });
      if (!response.ok) throw new Error(response.status === 401 ? 'Invalid access code.' : 'Demo unavailable or busy. Try later.');
      const value = { code: code.trim(), session };
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
      setAccess(value);
      setCode('');
    } catch (failure) { setError(failure.message || 'Could not access the demo.'); }
    finally { setBusy(false); }
  }
  function leave() {
    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* Clear in-memory access too. */ }
    setAccess(null);
  }
  if (local) return <App />;
  if (!access) return <main className="auth-panel">
    <h1>Tactical Time-Machine</h1>
    <p>Private portfolio demo. Ask the owner for an access code.</p>
    <form onSubmit={enter}>
      <label htmlFor="access-code">Access code</label>
      <input id="access-code" type="password" value={code} onChange={e => setCode(e.target.value)} required autoComplete="off" />
      <button className="stop-button" disabled={busy || !code.trim()}>Enter demo</button>
    </form>
    <p>Chat history is temporary. Questions and query results are sent to Gemini. Do not enter sensitive information.</p>
    {error && <p role="alert">{error}</p>}
  </main>;
  return <div className="authenticated-shell">
    <div className="account-bar"><span>Invite-only demo</span><button className="stop-button" onClick={leave}>Leave demo</button></div>
    <App key={access.session} userId={access.session} access={access} />
  </div>;
}
