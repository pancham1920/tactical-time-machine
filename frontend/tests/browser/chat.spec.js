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
    expect(route.request().postDataJSON()).toEqual({ message: 'Count the matches', conversation_id: expect.any(String) });
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
  await expect(page.getByRole('button', { name: 'New chat', exact: true })).toBeDisabled();
  release();
  await expect(page.getByText('There are 3 test matches.', { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue('');
  await expect(page.getByRole('status')).toHaveCount(0);
  expect(requests).toBe(1);
  await expect(page.locator('.stat-card dd')).toHaveText('3');
});

test('follow-ups reuse the ID, New chat resets, refresh restores', async ({ page }) => {
  const bodies = [];
  await page.route('**/conversations/*', route => route.fulfill({ json: {
    conversation_id: bodies.at(-1).conversation_id,
    messages: [
      { id: 'saved-user', role: 'user', content: 'New question' },
      { id: 'saved-assistant', role: 'assistant', content: 'Saved answer', status: 'complete', results: [
        { tool_call_id: 'q1', tool: 'execute_sql', result: { columns: ['matches'], rows: [{ matches: 3 }], truncated: false } },
      ] },
    ],
  } }));
  await page.route('**/chat/stream', route => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({ contentType: 'text/event-stream', body: success });
  });
  await page.goto('/');
  async function ask(text) {
    const input = page.getByRole('textbox');
    await input.fill(text);
    await input.press('Enter');
    await expect(input).toBeEnabled();
  }
  await ask('Show Arsenal');
  await expect(page.locator('.message-assistant')).toHaveCount(1);
  await ask('How many did they win?');
  await expect(page.locator('.message-assistant')).toHaveCount(2);
  expect(bodies[0].conversation_id).toBe(bodies[1].conversation_id);
  expect(bodies[1].message).toBe('How many did they win?');
  expect(Object.keys(bodies[1]).sort()).toEqual(['conversation_id', 'message']);
  await page.getByRole('textbox').fill('Unsubmitted draft');
  await page.getByRole('button', { name: 'New chat', exact: true }).click();
  await expect(page.locator('.message')).toHaveCount(0);
  await expect(page.getByRole('textbox')).toHaveValue('');
  await ask('New question');
  await expect(page.locator('.message-assistant')).toHaveCount(1);
  expect(bodies[2].conversation_id).not.toBe(bodies[0].conversation_id);
  await page.reload();
  await expect(page.getByText('Saved answer', { exact: true })).toBeVisible();
  await expect(page.locator('.stat-card dd')).toHaveText('3');
  await ask('After refresh');
  await expect(page.locator('.message-assistant')).toHaveCount(2);
  expect(bodies[3].conversation_id).toBe(bodies[2].conversation_id);
});

test('history failures block sending, retry restores charts and incomplete responses', async ({ page }) => {
  const id = '12345678-1234-4234-8234-123456789012';
  await page.addInitScript(value => sessionStorage.setItem('football-agent.conversation.v1', value), id);
  let fail = true;
  await page.route('**/conversations/*', route => route.fulfill(fail
    ? { status: 503, body: 'private storage path' }
    : { json: { conversation_id: id, messages: [
      { id: 'u', role: 'user', content: 'Compare players' },
      { id: 'a', role: 'assistant', content: '', status: 'error', results: [
        { tool_call_id: 'q', tool: 'execute_sql', result: { columns: ['name', 'goals'], rows: [{ name: 'A', goals: 2 }, { name: 'B', goals: 1 }], truncated: false } },
      ] },
    ] } }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Could not load');
  await expect(page.getByRole('textbox')).toBeDisabled();
  await expect(page.getByRole('alert')).not.toContainText('private');
  fail = false;
  await page.getByRole('button', { name: 'Retry loading history' }).click();
  await expect(page.locator('.result-chart svg')).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByText(/Response incomplete/)).toBeVisible();
  await expect(page.getByRole('textbox')).toBeEnabled();
});

test('missing saved history starts a new conversation with an explanation', async ({ page }) => {
  const id = '12345678-1234-4234-8234-123456789012';
  await page.addInitScript(value => sessionStorage.setItem('football-agent.conversation.v1', value), id);
  await page.route('**/conversations/*', route => route.fulfill({ status: 404, body: '' }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Saved chat was not found');
  await expect(page.getByRole('textbox')).toBeEnabled();
  expect(await page.evaluate(() => sessionStorage.getItem('football-agent.conversation.v1'))).not.toBe(id);
});

test('New chat cancels pending restoration and ignores its old response', async ({ page }) => {
  const id = '12345678-1234-4234-8234-123456789012';
  await page.addInitScript(value => sessionStorage.setItem('football-agent.conversation.v1', value), id);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/conversations/*', async route => {
    await gate;
    await route.fulfill({ json: { conversation_id: id, messages: [{ id: 'old', role: 'user', content: 'Old saved text' }] } });
  });
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('Loading saved');
  await expect(page.getByRole('textbox')).toBeDisabled();
  await page.getByRole('button', { name: 'New chat', exact: true }).click();
  release();
  await expect(page.getByRole('textbox')).toBeEnabled();
  await expect(page.getByText('Old saved text', { exact: true })).toHaveCount(0);
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
