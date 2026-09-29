import { test, expect } from '@playwright/test';

const event = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const success = event('connected', {})
  + event('tool_call', { tools: ['execute_sql'] })
  + event('tool_result', { result: '{"rows":[{"matches":3}]}' })
  + event('final_answer', { answer: 'There are 3 test matches.' })
  + event('complete', {});

test('sends a question, prevents duplicate submission, and renders the answer', async ({ page }) => {
  let release;
  let requests = 0;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/chat/stream', async route => {
    requests += 1;
    expect(route.request().postDataJSON()).toEqual({ message: 'Count the matches' });
    await gate;
    await route.fulfill({ contentType: 'text/event-stream', body: success });
  });
  await page.goto('/');
  const input = page.getByRole('textbox', { name: 'Your football question' });
  const send = page.getByRole('button', { name: 'Send', exact: true });
  await expect(send).toBeDisabled();
  await input.fill('   ');
  await expect(send).toBeDisabled();
  await input.fill('Count the matches');
  await send.click();
  await expect(input).toBeDisabled();
  await expect(send).toBeDisabled();
  await expect(page.getByRole('status')).toBeVisible();
  release();
  await expect(page.getByText('There are 3 test matches.', { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue('');
  await expect(page.getByRole('status')).toHaveCount(0);
  expect(requests).toBe(1);
});

test('an HTTP failure restores the composer and allows a new request', async ({ page }) => {
  let fail = true;
  await page.route('**/chat/stream', route => route.fulfill(fail
    ? { status: 502, body: 'private backend detail' }
    : { contentType: 'text/event-stream', body: success }));
  await page.goto('/');
  const input = page.getByRole('textbox', { name: 'Your football question' });
  await input.fill('Count matches');
  await input.press('Enter');
  await expect(page.getByRole('alert')).toContainText('HTTP 502');
  await expect(page.getByRole('alert')).not.toContainText('private backend detail');
  await expect(input).toBeEnabled();
  fail = false;
  await input.fill('Count matches again');
  await input.press('Enter');
  await expect(page.getByText('There are 3 test matches.', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('interrupted streams display an error rather than silently succeeding', async ({ page }) => {
  await page.route('**/chat/stream', route => route.fulfill({
    contentType: 'text/event-stream', body: event('connected', {}),
  }));
  await page.goto('/');
  await page.getByRole('button', { name: /The big picture/ }).click();
  await expect(page.getByRole('alert')).toContainText('interrupted');
  await expect(page.getByRole('textbox')).toBeEnabled();
});

test('Stop cancels a pending browser request', async ({ page }) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/chat/stream', async route => {
    await gate;
    await route.abort();
  });
  await page.goto('/');
  await page.getByRole('button', { name: /The big picture/ }).click();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Request stopped');
  await expect(page.getByRole('textbox')).toBeEnabled();
  release();
});

test('model output is text, not executable HTML', async ({ page }) => {
  await page.route('**/chat/stream', route => route.fulfill({
    contentType: 'text/event-stream',
    body: event('final_answer', { answer: '<img src=x onerror="alert(1)">' }) + event('complete', {}),
  }));
  await page.goto('/');
  await page.getByRole('button', { name: /The big picture/ }).click();
  await expect(page.getByRole('log')).toContainText('<img src=x');
  await expect(page.getByRole('log').locator('img')).toHaveCount(0);
});

test('welcome and composer fit the viewport', async ({ page }, testInfo) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByRole('textbox')).toBeInViewport();
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflows).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('welcome.png'), fullPage: true });
});
