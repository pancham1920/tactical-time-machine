import { test, expect } from '@playwright/test';

const event = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
const success = event('connected', {})
  + event('tool_call', { tools: ['execute_sql'] })
  + event('tool_result', { tool_call_id: 'count', tool: 'execute_sql', result: { columns: ['matches'], rows: [{ matches: 3 }], truncated: false } })
  + event('final_answer', { answer: 'There are 3 test matches.' })
  + event('complete', {});

const toolEvent = (id, result) => event('tool_result', { tool_call_id: id, tool: 'execute_sql', result });

test('renders charts, tables and multiple results without mixing successive responses', async ({ page }, testInfo) => {
  let count = 0;
  await page.route('**/chat/stream', route => {
    count += 1;
    const body = count === 1
      ? toolEvent('values', { columns: ['name', 'market_value_in_eur'], rows: [
        { name: 'Player A', market_value_in_eur: 1200000 }, { name: 'Player B', market_value_in_eur: 800000 },
      ], truncated: false }) + toolEvent('matches', { columns: ['home_team', 'away_team', 'home_score'], rows: [
        { home_team: '<img src=x>', away_team: 'Visitors', home_score: null },
      ], truncated: true })
      : toolEvent('values', { columns: ['total'], rows: [{ total: 12 }], truncated: false });
    return route.fulfill({ contentType: 'text/event-stream', body: body
      + event('final_answer', { answer: `Answer ${count}` }) + event('complete', {}) });
  });
  await page.goto('/');
  const input = page.getByRole('textbox');
  await input.fill('Show player values and matches');
  await input.press('Enter');
  await expect(page.getByText('Answer 1', { exact: true })).toBeVisible();
  await expect(page.locator('.result-chart svg')).toBeVisible();
  await expect(page.getByRole('cell', { name: '€1,200,000', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: '—', exact: true })).toBeVisible();
  await expect(page.getByText(/Showing the first 1 rows/)).toBeVisible();
  await expect(page.getByRole('log').locator('img')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('block6-results.png'), fullPage: true });
  await input.fill('Count something else');
  await input.press('Enter');
  await expect(page.getByText('Answer 2', { exact: true })).toBeVisible();
  const answers = page.locator('.message-assistant');
  await expect(answers.nth(0).locator('.query-result')).toHaveCount(2);
  await expect(answers.nth(1).locator('.stat-card dd')).toHaveText('12');
});

test('retains empty and failed query states when the explanation stream fails', async ({ page }) => {
  await page.route('**/chat/stream', route => route.fulfill({ contentType: 'text/event-stream', body:
    toolEvent('empty', { columns: [], rows: [], truncated: false })
    + toolEvent('failed', { error: '/private/sql/error' })
    + event('error', { message: 'private model detail' }),
  }));
  await page.goto('/');
  await page.getByRole('button', { name: /The big picture/ }).click();
  await expect(page.getByText('No matching records found.')).toBeVisible();
  await expect(page.getByText('This database query could not produce displayable results.')).toBeVisible();
  await expect(page.getByText(/Response incomplete/)).toBeVisible();
  await expect(page.getByRole('log')).not.toContainText('/private');
  await expect(page.getByRole('textbox')).toBeEnabled();
});

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
  await expect(page.locator('.stat-card dd')).toHaveText('3');
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
