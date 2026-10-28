// Replays genuine captured responses; never calls Gemini or a live backend.
import { chromium, expect } from '@playwright/test';
import { readFile, mkdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const frontend = fileURLToPath(new URL('..', import.meta.url));
const root = path.resolve(frontend, '..');
const media = path.join(root, 'docs/media');
const report = JSON.parse(await readFile(path.join(root, 'docs/evaluation/live-2026-10-15.json'), 'utf8'));
const cases = report.results.filter(item => item.status === 'completed').slice(0, 2);
if (cases.length < 2) throw new Error('Two completed live responses are required.');
await mkdir(media, { recursive: true });
const server = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '5175', '--strictPort'], {
  cwd: frontend, stdio: 'inherit',
  env: { ...process.env, VITE_AUTH_MODE: 'local', VITE_SAMPLE_DATA: 'true', VITE_API_BASE_URL: 'http://127.0.0.1:8000' },
});
let browser;
try {
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt++) {
    if (server.exitCode !== null) throw new Error('Demo server failed to start.');
    try { ready = (await fetch('http://127.0.0.1:5175')).ok; } catch { /* Starting. */ }
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  if (!ready) throw new Error('Demo server did not become ready.');
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 },
    recordVideo: { dir: path.join(root, 'build/demo-video'), size: { width: 1280, height: 900 } } });
  const page = await context.newPage();
  await page.route('http://127.0.0.1:8000/**', async route => {
    const body = route.request().postDataJSON();
    const captured = cases.find(item => item.question === body?.message);
    if (!captured) return route.abort();
    await new Promise(resolve => setTimeout(resolve, 1200));
    const events = [{ event: 'connected', data: {} }, ...captured.events];
    return route.fulfill({ contentType: 'text/event-stream',
      body: events.map(item => `event: ${item.event}\ndata: ${JSON.stringify(item.data)}\n\n`).join('') });
  });
  await page.goto('http://127.0.0.1:5175');
  await page.locator('.sample-banner').evaluate(element => {
    element.textContent = 'RECORDED GEMINI RESPONSE REPLAY · FICTIONAL DATA · Replay timing is not live latency';
  });
  await page.screenshot({ path: path.join(media, 'welcome.png'), fullPage: true });
  await page.waitForTimeout(2000);
  for (const [index, item] of cases.entries()) {
    const input = page.getByRole('textbox', { name: 'Your football question' });
    await input.pressSequentially(item.question, { delay: 55 });
    await input.press('Enter');
    await expect(page.getByText(item.answer, { exact: true })).toBeVisible();
    await page.waitForTimeout(4000);
    if (index === 0) await page.screenshot({ path: path.join(media, 'answer.png'), fullPage: true });
  }
  const video = page.video();
  await context.close();
  await video.saveAs(path.join(media, 'demo.webm'));
  console.log('Saved labelled replay video and screenshots to docs/media.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
}
