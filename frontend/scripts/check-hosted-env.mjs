import { pathToFileURL } from 'node:url';

export function validateHostedEnv(env) {
  let url;
  try { url = new URL(env.VITE_API_BASE_URL); } catch { throw new Error('Set VITE_API_BASE_URL to the HTTPS backend origin.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash
      || url.pathname !== '/' || !url.hostname.endsWith('.onrender.com')) {
    throw new Error('VITE_API_BASE_URL must be an HTTPS onrender.com origin without credentials or a path.');
  }
  if (env.VITE_AUTH_MODE === 'local') throw new Error('Remove VITE_AUTH_MODE=local before a hosted build.');
  for (const name of Object.keys(env)) {
    if (name.startsWith('VITE_') && /SECRET|TOKEN|PASSWORD|ACCESS_CODE|API_KEY/i.test(name)) {
      throw new Error('Remove secret-like VITE_ variables: frontend configuration is public.');
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  validateHostedEnv(process.env);
  console.log('Hosted frontend configuration checked (no network calls).');
}
