import test from 'node:test';
import assert from 'node:assert/strict';
import { validateHostedEnv } from '../scripts/check-hosted-env.mjs';

test('hosted build requires an HTTPS backend and rejects local bypass and secrets', () => {
  const valid = { VITE_API_BASE_URL: 'https://demo.onrender.com' };
  assert.doesNotThrow(() => validateHostedEnv(valid));
  for (const env of [{}, { VITE_API_BASE_URL: 'http://localhost:8000' },
    { VITE_API_BASE_URL: 'https://demo.onrender.com/chat' },
    { VITE_API_BASE_URL: 'https://user:pass@demo.onrender.com' },
    { ...valid, VITE_AUTH_MODE: 'local' }, { ...valid, VITE_GEMINI_API_KEY: 'test' },
    { ...valid, VITE_DEMO_ACCESS_CODE: 'test' }]) {
    assert.throws(() => validateHostedEnv(env));
  }
});
