/** Deterministic first-party HTTP boundaries; no inference or sandbox is started. */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

import type { Page } from '@playwright/test';
const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { randomUUID } = require('node:crypto');

test.describe('Browse first-party HTTP contract', () => {
  test.setTimeout(240_000);

  // contract-test: direct surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run,web-browse.budgets-and-stop
  test('rejects public and foreign sessions, redacts malformed input and enforces owner quotas without paid work', async ({ page }: { page: Page }) => {
    const api = workflowApiUrl();
    expect(process.env.CI, 'Quota proof requires an isolated runtime').toBeTruthy();
    expect(new URL(api).hostname, 'Never spend a shared dev quota').toBe('localhost');
    const sessionId = randomUUID();
    const prefix = `${api}/v1/apps/web/browse/${sessionId}`;
    for (const suffix of ['', '/frame']) {
      const response = await page.request.get(prefix + suffix);
      expect(response.status()).toBe(401);
    }
    const unauthorized = await page.request.post(`${prefix}/control`, { data: { operation: 'resume' } });
    expect(unauthorized.status()).toBe(401);

    await loginToTestAccount(page);
    const missing = await page.request.get(prefix);
    expect(missing.status()).toBe(404);
    for (const operation of ['take_control', 'resume', 'stop', 'close']) {
      const response = await page.request.post(`${prefix}/control`, { data: { operation } });
      expect(response.status()).toBe(404);
    }
    const marker = 'BROWSE-PRIVATE-INPUT-MUST-NOT-BE-ECHOED';
    const invalid = await page.request.post(`${prefix}/control`, {
      data: { operation: 'input', action: { kind: 'type', text: marker, operation: 'observe' } }
    });
    expect(invalid.status()).toBe(422);
    expect(await invalid.json()).toEqual({ detail: 'Invalid browser request.' });
    expect(await invalid.text()).not.toContain(marker);

    const foreignChat = await page.request.post(`${api}/v1/apps/web/skills/browse`, {
      data: { task: 'Read Example Domain', start_url: 'https://example.com', chat_id: randomUUID(), message_id: randomUUID() }
    });
    expect(foreignChat.status()).toBe(404);
    expect(await foreignChat.text()).not.toContain('sandbox');

    // Exactly ninety state reads are admitted per owner/minute. The first read
    // above consumed one; none of these missing sessions can reach E2B.
    for (let index = 0; index < 89; index++) {
      const response = await page.request.get(prefix);
      expect(response.status()).toBe(404);
    }
    const limited = await page.request.get(prefix);
    expect(limited.status()).toBe(429);
    expect(limited.headers()['retry-after']).toBe('60');
  });
});
