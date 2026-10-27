/* eslint-disable @typescript-eslint/no-require-imports */
/** Product HTTP coverage for isolated CI only; no inference or provider fixtures. */
export {};
import type { Page } from '@playwright/test';
const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { randomUUID } = require('node:crypto');


// Keep startup exceptions available when the app fails before login can render.
// Deliberately exclude ordinary console output, argument objects and HTTP bodies.
const appsRuntimeErrors = new WeakMap<Page, Array<{ source: string; message: string; stack?: string }>>();
function safeRuntimeError(value: string): string {
  return value
    .replace(/https?:\/\/[^\s)]+/g, raw => {
      try { const url = new URL(raw); return `${url.origin}${url.pathname}`; } catch { return '[url]'; }
    })
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, '[email]')
    .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/\b(?:access_token|refresh_token|api_key|password|authorization|cookie)\b\s*[:=]\s*[^\s,;]+/gi, '[credential redacted]')
    .replace(/\b[A-Za-z0-9_+/=-]{48,}\b/g, '[long value redacted]')
    .replace(/\{\s*["'][\s\S]*/, '[structured payload omitted]')
    .slice(0, 700);
}
test.beforeEach(async ({ page }: { page: Page }) => {
  const records: Array<{ source: string; message: string; stack?: string }> = [];
  appsRuntimeErrors.set(page, records);
  const capture = (source: string, message: string, stack?: string) => {
    if (records.length >= 16) return;
    const entry = { source, message: safeRuntimeError(message.split('\n')[0]),
      ...(stack ? { stack: stack.split('\n').filter(line => /^\s*at\s/.test(line)).slice(0, 6).map(safeRuntimeError).join('\n') } : {}) };
    if (!records.some(record => record.source === entry.source && record.message === entry.message)) records.push(entry);
  };
  page.on('pageerror', error => capture('pageerror', `${error.name}: ${error.message}`, error.stack));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    const firstLine = message.text().split('\n')[0];
    if (/(?:InternalError|ReferenceError|TypeError|SyntaxError|RangeError|Uncaught|Cannot access .{0,120} before initialization|Failed to fetch dynamically imported module|Failed to load module script|\[svelte\].*(?:error|exception))/i.test(firstLine)) {
      capture('console.error', firstLine);
    }
  });
});
test.afterEach(async ({ page }: { page: Page }, testInfo: { status?: string; expectedStatus?: string; attach: (name: string, options: { body: string; contentType: string }) => Promise<void> }) => {
  const records = appsRuntimeErrors.get(page) ?? [];
  appsRuntimeErrors.delete(page);
  if (testInfo.status === testInfo.expectedStatus || records.length === 0) return;
  const body = JSON.stringify(records, null, 2);
  await testInfo.attach('apps-client-runtime-errors', { body, contentType: 'application/json' });
  console.info(`[Apps client runtime errors] ${JSON.stringify(records)}`);
});

async function ownerId(page: Page): Promise<string> {
  const value = await page.evaluate(() => new Promise<string>((resolve, reject) => {
    const opened = indexedDB.open('user_db');
    opened.onerror = () => reject(new Error('Cannot read isolated account identity'));
    opened.onsuccess = () => {
      const db = opened.result;
      const read = db.transaction('user_data', 'readonly').objectStore('user_data').get('id');
      read.onerror = () => { db.close(); reject(new Error('Missing isolated account identity')); };
      read.onsuccess = () => { db.close(); resolve(String(read.result ?? '')); };
    };
  }));
  expect(value).toMatch(/^[0-9a-f-]{36}$/i);
  return value;
}

async function rankImage(page: Page): Promise<Record<string, unknown>> {
  const data_base64 = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 280;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Cannot prepare synthetic image');
    context.fillStyle = 'navy';
    context.fillRect(0, 0, 280, 280);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { [randomUUID()]: { type: 'image', format: 'png', data_base64 } };
}

test.describe('Apps workspace product HTTP contracts', () => {
  test.setTimeout(180_000);

  // contract-test: direct surface=rest_api assertions=apps.recommendations.public-daily
  test('public recommendations are read-only, unpersonalized and bounded by expiry', async ({ page }: { page: Page }) => {
    const base = `${workflowApiUrl()}/v1/apps/workspace/public`;
    const response = await page.request.get(`${base}/code?language=en`);
    expect(response.status()).toBe(200);
    expect(response.headers()['cache-control']).toContain('no-store');
    const body = await response.json();
    expect(body.app_id).toBe('code');
    expect(body.cta.label).toEqual(expect.any(String));
    expect(body.cta.query).toEqual(expect.any(String));
    expect(Array.isArray(body.recommendations)).toBe(true);
    for (const field of ['user_id', 'team_id', 'saved_searches', 'daily_searches_enabled']) {
      expect(body).not.toHaveProperty(field);
      for (const batch of body.recommendations) expect(batch).not.toHaveProperty(field);
    }
    for (const batch of body.recommendations) {
      expect(batch.skill_id).toBe('search_repos');
      expect(batch.expires_at - batch.created_at).toBe(86_400);
      expect(batch.expires_at).toBeGreaterThan(Date.now() / 1000);
    }
    // Neither a visitor nor a disallowed personalized app can start a paid job.
    expect((await page.request.post(`${base}/code`)).status()).toBe(405);
    const health = await page.request.get(`${base}/health`);
    expect(health.status()).toBe(200);
    expect(await health.json()).toMatchObject({
      app_id: 'health', created_at: null, expires_at: null, recommendations: [], cta: null,
    });
    expect((await page.request.get(`${base}/code?language=invalid`)).status()).toBe(422);
  });

  // contract-test: direct surface=rest_api assertions=apps.requests.natural-language,apps.recommendations.private-daily,apps.library.embeds-account-paginated
  test('public and invalid credentials cannot access private library or bypass parser validation', async ({ page }: { page: Page }) => {
    const base = workflowApiUrl();
    const library = await page.request.get(`${base}/v1/apps/workspace/library/web`);
    expect(library.status()).toBe(401);
    const invalidCredential = await page.request.post(`${base}/v1/apps/workspace/interpret`, {
      headers: { Authorization: 'Bearer invalid-apps-credential' },
      data: { app_id: 'web', text: 'Synthetic Berlin museums', request_id: randomUUID(), timezone: 'UTC', locale: 'en' },
    });
    expect([401, 403]).toContain(invalidCredential.status());
    // Invalid body is rejected before any guest allowance/provider admission.
    const invalidText = await page.request.post(`${base}/v1/apps/workspace/interpret`, {
      data: { app_id: 'web', text: '', request_id: randomUUID(), timezone: 'UTC', locale: 'en' },
    });
    expect(invalidText.status()).toBe(422);
    const rank = await page.request.post(`${base}/v1/apps/workspace/rank`, {
      data: { app_id: 'web', request_id: randomUUID(), text: 'Synthetic blue coat',
        assets: await rankImage(page), candidates: [{ id: 'synthetic-result', title: 'Blue coat' }] },
    });
    expect(rank.status()).toBe(401);
  });

  // contract-test: direct surface=rest_api assertions=apps.requests.natural-language,apps.recommendations.private-daily,apps.library.embeds-account-paginated
  test('session saves reload privately and disable persists while account/team/invalid input gates reject changes', async ({ page }: { page: Page }) => {
    const { email, password, otpKey } = getTestAccount();
    skipWithoutCredentials(test, email, password, otpKey);
    await loginToTestAccount(page);
    const base = workflowApiUrl(), expected_user_id = await ownerId(page);
    const url = `${base}/v1/apps/workspace/library/web`;
    const marker = `Isolated Apps saved search ${randomUUID()}`;
    const parameters = { requests: [{ query: 'Synthetic Berlin museums', count: 1 }] };
    // This disposable CI account is explicitly disabled before saving; this test
    // proves persistence and guards without authorizing a background paid rerun.
    const disabled = await page.request.patch(`${url}/settings`, {
      data: { expected_user_id, daily_searches_enabled: false },
    });
    expect(disabled.status()).toBe(200);
    expect((await disabled.json()).daily_searches_enabled).toBe(false);
    const saved = await page.request.post(`${url}/saved-searches`, {
      data: { expected_user_id, skill_id: 'search', title: marker, query: 'Synthetic Berlin museums', parameters },
    });
    expect(saved.status()).toBe(200);
    const savedBody = await saved.json();
    expect(savedBody.daily_searches_enabled).toBe(false);
    const row = savedBody.saved_searches.find((item: any) => item.title === marker);
    expect(row?.id).toMatch(/^[0-9a-f-]{36}$/i);
    const reloaded = await page.request.get(url);
    expect(reloaded.status()).toBe(200);
    expect(reloaded.headers()['cache-control']).toContain('no-store');
    const reloadedBody = await reloaded.json();
    expect(reloadedBody.saved_searches.find((item: any) => item.id === row.id)?.parameters).toEqual(parameters);
    expect(reloadedBody.daily_searches_enabled).toBe(false);

    const accountChanged = await page.request.patch(`${url}/settings`, {
      data: { expected_user_id: randomUUID(), daily_searches_enabled: true },
    });
    expect(accountChanged.status()).toBe(409);
    const changedInterpreter = await page.request.post(`${base}/v1/apps/workspace/interpret`, {
      data: { app_id: 'web', expected_user_id: randomUUID(), request_id: randomUUID(), text: 'Synthetic museums', timezone: 'UTC', locale: 'en' },
    });
    expect(changedInterpreter.status()).toBe(409);
    const changedRank = await page.request.post(`${base}/v1/apps/workspace/rank`, {
      data: { app_id: 'web', expected_user_id: randomUUID(), request_id: randomUUID(), text: 'Synthetic blue coat',
        assets: await rankImage(page), candidates: [{ id: 'synthetic-result', title: 'Blue coat' }] },
    });
    expect(changedRank.status()).toBe(409);

    const team = randomUUID();
    const teamLibrary = await page.request.get(`${url}?team_id=${team}`);
    expect(teamLibrary.status()).toBe(403);
    expect(await teamLibrary.text()).not.toContain(marker);
    const teamSettings = await page.request.patch(`${url}/settings`, {
      data: { expected_user_id, team_id: team, daily_searches_enabled: true },
    });
    expect(teamSettings.status()).toBe(403);
    const teamRank = await page.request.post(`${base}/v1/apps/workspace/rank`, {
      data: { app_id: 'web', team_id: team, request_id: randomUUID(), text: 'Synthetic blue coat',
        assets: await rankImage(page), candidates: [{ id: 'synthetic-result', title: 'Blue coat' }] },
    });
    expect(teamRank.status()).toBe(403);
    const invalidParameters = await page.request.post(`${url}/saved-searches`, {
      data: { expected_user_id, skill_id: 'search', title: 'Invalid synthetic search', query: 'Synthetic', parameters: { requests: [{}] } },
    });
    expect(invalidParameters.status()).toBe(409);
    const invalidTimezone = await page.request.post(`${base}/v1/apps/workspace/interpret`, {
      data: { app_id: 'web', text: 'Synthetic', request_id: randomUUID(), timezone: 'invalid-zone', locale: 'en' },
    });
    expect(invalidTimezone.status()).toBe(422);
    const foreignRecommendation = await page.request.get(`${url}/recommendations/${randomUUID()}`);
    expect(foreignRecommendation.status()).toBe(404);
    expect(await foreignRecommendation.text()).not.toContain(marker);
    const finalState = await page.request.get(url);
    expect(finalState.status()).toBe(200);
    expect((await finalState.json()).daily_searches_enabled).toBe(false);
  });
});
