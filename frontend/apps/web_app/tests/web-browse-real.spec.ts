/** Real inference/provider acceptance. Deliberately held out of isolated CI. */
import { test, expect, chromium, type Browser, type BrowserContext, type Page, type TestInfo } from '@playwright/test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import fs from 'node:fs';
import path from 'node:path';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

// playwright-account: required reason=real_ai_personal_dev_only
const enabled = process.env.WEB_BROWSE_REAL_AI_DEV === '1';
const APP = 'https://app.dev.openmates.org';
const API = 'https://api.dev.openmates.org';
const LOGIN = 'https://the-internet.herokuapp.com/login';
const ORIGIN = new URL(LOGIN).origin;
const execute = promisify(execFile);
const stateDir = process.env.OPENMATES_STATE_DIR || '';
const browserProfile = path.join(stateDir, 'browse-web-profile');
const project = process.env.WEB_BROWSE_TEST_PROJECT || '';
test.describe.configure({ mode: 'serial', retries: 0, timeout: 420_000 });
test.skip(!enabled, 'Requires explicit dev-only real-inference execution and a shared runtime lease.');

async function guardDevApi(ctx: BrowserContext) {
  await ctx.route('**/v1/**', route => {
    const host = new URL(route.request().url()).hostname;
    return host.startsWith('api.') && host.endsWith('.openmates.org') && host !== 'api.dev.openmates.org'
      ? route.abort('blockedbyclient') : route.continue();
  });
}

async function cli(args: string[]) {
  const result = await execute('openmates', args, { timeout: 240_000, maxBuffer: 12 * 1024 * 1024,
    env: { ...process.env, OPENMATES_API_URL: API } });
  // Never print command output: client metadata can contain encryption material.
  return JSON.parse(result.stdout);
}
async function createChat(prompt: string) {
  const started = Date.now();
  const result = await cli(['chats', 'new', prompt, '--project', project, '--json']);
  const chatId = String(result.chat_id || result.chatId || result.chat?.id || '');
  expect(chatId).toMatch(/^[a-f0-9-]{36}$/);
  return { chatId, invocationMs: Date.now() - started };
}
function preview(page: Page) {
  return page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="browse"]');
}
async function screenshot(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(`${name}.png`) });
}
async function context(_browser: Browser, info: TestInfo, width: number) {
  // A real Chrome profile preserves native IndexedDB CryptoKey objects. JSON
  // storage snapshots cannot round-trip the authenticated encryption boundary.
  const ctx = await chromium.launchPersistentContext(browserProfile, { headless: true, baseURL: APP,
    viewport: { width, height: width < 600 ? 844 : 1000 },
    recordVideo: { dir: info.outputPath('recordings'), size: { width, height: width < 600 ? 844 : 1000 } } });
  await guardDevApi(ctx);
  return ctx;
}
async function openSession(page: Page, chatId: string) {
  await page.goto(`/#chat-id=${chatId}`);
  await expect(preview(page).last()).toHaveAttribute('data-status', 'finished', { timeout: 90_000 });
  const embedId = await preview(page).last().getAttribute('data-embed-id');
  expect(embedId).toBeTruthy();
  const response = page.waitForResponse(r => new URL(r.url()).pathname.match(/^\/v1\/apps\/web\/browse\/[a-f0-9-]{36}$/) !== null && r.status() === 200);
  const started = Date.now();
  await preview(page).last().click();
  const session = await (await response).json();
  expect(session.chat_id).toBe(chatId);
  await expect(page.getByAltText('Live browser', { exact: true })).toBeVisible({ timeout: 60_000 });
  return { session, embedId: embedId!, viewerOpenToFrameMs: Date.now() - started };
}
async function closeBrowser(page: Page, sessionId: string) {
  const closed = page.waitForResponse(r => r.url().endsWith(`/browse/${sessionId}/control`) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Close browser', exact: true }).click();
  const response = await closed;
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(result.status).toBe('closed');
  await expect(page.getByTestId('browse-session-viewer')).toContainText('Browser closed');
  return result;
}
async function cleanup(ctx: BrowserContext, chatId: string, sessionId: string | undefined) {
  if (!sessionId) return;
  const state = await ctx.request.get(`${API}/v1/apps/web/browse/${sessionId}`);
  if (state.status() === 410) return;
  expect(state.status()).toBe(200);
  expect((await state.json()).chat_id).toBe(chatId);
  const closed = await ctx.request.post(`${API}/v1/apps/web/browse/${sessionId}/control`, { data: { operation: 'close' } });
  expect([200, 410]).toContain(closed.status());
}
async function saveVideo(page: Page, ctx: BrowserContext, info: TestInfo) {
  const video = page.video();
  await ctx.close();
  if (video) await video.saveAs(info.outputPath('video.webm'));
}
function receipt(info: TestInfo, data: Record<string, unknown>) {
  fs.writeFileSync(info.outputPath('browse-runtime.json'), JSON.stringify({ target: APP, automaticRouting: true, ...data }, null, 2), { mode: 0o600 });
}

test.beforeAll(async () => {
  expect(process.env.OPENMATES_CI_ISOLATED).not.toBe('1');
  expect(process.env.PLAYWRIGHT_TEST_BASE_URL).toBe(APP);
  expect(stateDir.startsWith('/tmp/openmates-browse-')).toBe(true);
  expect(project).toMatch(/^[a-f0-9-]{36}$/);
  for (const key of ['OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL', 'OPENMATES_PERSONAL_TEST_ACOUNT_PASSWORD', 'OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY']) expect(process.env[key]).toBeTruthy();
  // No recordings or traces of personal-account authentication or its storage.
  fs.mkdirSync(browserProfile, { recursive: true, mode: 0o700 });
  const ctx = await chromium.launchPersistentContext(browserProfile, { headless: true, baseURL: APP, viewport: { width: 1280, height: 1000 } });
  await guardDevApi(ctx);
  try {
    const page = await ctx.newPage();
    await loginToTestAccount(page, () => {}, async () => {}, { credentials: {
      email: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL,
      password: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_PASSWORD,
      otpKey: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY,
    } });
  } finally { await ctx.close(); }
  const restored = await chromium.launchPersistentContext(browserProfile, { headless: true, baseURL: APP });
  await guardDevApi(restored);
  try {
    const page = restored.pages()[0] || await restored.newPage(); await page.goto('/');
    // Verify only the native key type, never key bytes or stored values. Do
    // this before spending on another real inference request.
    await expect.poll(() => page.evaluate(async () => {
      const databases = await indexedDB.databases();
      if (!databases.some(db => db.name === 'openmates_crypto')) return false;
      return new Promise<boolean>(resolve => {
        const opened = indexedDB.open('openmates_crypto');
        opened.onerror = () => resolve(false);
        opened.onsuccess = () => {
          const db = opened.result;
          if (!db.objectStoreNames.contains('keys')) { db.close(); resolve(false); return; }
          const read = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
          read.onerror = () => { db.close(); resolve(false); };
          read.onsuccess = () => { const native = read.result instanceof CryptoKey; db.close(); resolve(native); };
        };
      });
    }), { timeout: 20_000, message: 'The private browser profile must preserve its native master CryptoKey' }).toBe(true);
    const probeChat = process.env.WEB_BROWSE_PROFILE_PROBE_CHAT;
    if (probeChat) {
      expect(probeChat).toMatch(/^[a-f0-9-]{36}$/);
      await page.goto(`/#chat-id=${probeChat}`);
      await expect(page.getByText('Use the Browse skill to open', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
    }
  } finally { await restored.close(); }
});
test.afterAll(() => { if (enabled && stateDir.startsWith('/tmp/openmates-browse-')) fs.rmSync(browserProfile, { recursive: true, force: true }); });

// contract-test: direct surface=gui.web assertions=web-browse.structured-data,web-browse.embed-and-observation,web-browse.lifecycle,web-browse.private-storage-and-api
test('real Browse JSON, watch, pause/resume and closed saved history on laptop and phone', async ({ browser }, info) => {
  const created = await createChat('Use the Browse skill to open https://httpbin.org/html and return the exact main heading and source URL as JSON. Use the browser session for this task.');
  receipt(info, { ...created, phase: 'chat-created' });
  let sid: string | undefined;
  const ctx = await context(browser, info, 1280), page = ctx.pages()[0] || await ctx.newPage();
  try {
    const opened = await openSession(page, created.chatId); sid = opened.session.session_id;
    receipt(info, { ...created, sessionId: sid, phase: 'viewer-opened' });
    await expect(page.getByTestId('browse-session-viewer')).toContainText('You are watching');
    await page.getByText('Structured data', { exact: true }).click();
    await expect(page.getByTestId('browse-json')).toContainText('Herman Melville - Moby-Dick');
    await screenshot(page, info, 'json-laptop');
    await page.getByRole('button', { name: 'Take control', exact: true }).click();
    await expect(page.getByLabel('Text for the website', { exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Pause', exact: true }).click();
    await expect(page.getByTestId('browse-session-viewer')).toContainText('The browser is paused and compute is free');
    await page.getByRole('button', { name: 'Take control', exact: true }).click();
    await expect(page.getByLabel('Text for the website', { exact: true })).toBeEnabled({ timeout: 30_000 });
    const closed = await closeBrowser(page, sid!);
    await screenshot(page, info, 'closed-laptop');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await preview(page).last().click();
    await expect(page.getByTestId('browse-session-viewer')).toContainText('Session expired');
    await expect(page.getByRole('button', { name: 'Take control', exact: true })).toHaveCount(0);
    await page.getByText('Structured data', { exact: true }).click();
    await expect(page.getByTestId('browse-json')).toContainText('Herman Melville - Moby-Dick');
    await screenshot(page, info, 'closed-history-phone');
    receipt(info, { ...created, ...opened, sessionId: sid, closed });
  } finally { try { await cleanup(ctx, created.chatId, sid); } finally { await saveVideo(page, ctx, info); } }
});

// The fixture explicitly invites automated acceptance tests and publishes its
// disposable demo login: https://github.com/saucelabs/the-internet . No real
// website account, private credential or provider data collection is involved.
async function loginGeometry(browser: Browser) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 },
    userAgent: 'OpenMatesTest/1.0 (+https://openmates.org)' });
  try {
    const page = await ctx.newPage(); await page.goto(LOGIN, { waitUntil: 'domcontentloaded' });
    expect(page.url()).toBe(LOGIN);
    const points = [];
    for (const selector of ['#username', '#password', '#login button']) {
      const rect = await page.locator(selector).boundingBox(); expect(rect).toBeTruthy();
      points.push({ x: rect!.x + rect!.width / 2, y: rect!.y + rect!.height / 2 });
    }
    return points;
  } finally { await ctx.close(); }
}
for (const width of [1280, 390]) {
  // contract-test: direct surface=gui.web assertions=web-browse.exclusive-takeover,web-browse.sign-in,web-browse.embed-and-observation,web-browse.session-and-run,web-browse.lifecycle
  test(`real Browse manual demo sign-in and same-session AI continuation at ${width}px`, async ({ browser }, info) => {
    const created = await createChat(`Use Browse to open ${LOGIN}. Stop and let me take control to sign in manually. After I let AI continue, read the heading of the signed-in page and return it with its source URL as JSON. Never enter credentials yourself.`);
    receipt(info, { ...created, phase: 'chat-created' });
    const ctx = await context(browser, info, width), page = ctx.pages()[0] || await ctx.newPage();
    let sid: string | undefined;
    try {
      const opened = await openSession(page, created.chatId); sid = opened.session.session_id;
      receipt(info, { ...created, sessionId: sid, phase: 'viewer-opened' });
      const points = await loginGeometry(browser);
      await page.getByRole('button', { name: 'Take control', exact: true }).click();
      await expect(page.getByLabel('Text for the website', { exact: true })).toBeEnabled();
      const command = async (action: () => Promise<unknown>) => {
        const reply = page.waitForResponse(r => r.url().endsWith(`/browse/${sid}/control`) && r.request().method() === 'POST');
        await action(); const response = await reply; expect(response.status()).toBe(200);
        return response.json();
      };
      const input = async (action: () => Promise<unknown>) => {
        const result = await command(action);
        if (result.needs_sign_in_consent) {
          expect(result.sign_in_origin).toBe(ORIGIN);
          const notice = page.getByRole('region', { name: 'Before you sign in', exact: true });
          await expect(notice).toContainText('Relevant page content may be sent to our AI providers');
          await expect(notice.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible();
          await expect(page.getByRole('button', { name: 'Let AI continue', exact: true })).toBeDisabled();
          await screenshot(page, info, `sign-in-notice-${width}`);
          await notice.getByRole('button', { name: 'Continue to sign in', exact: true }).click();
          await expect(notice).toHaveCount(0);
          // The server explicitly refused this gesture before executing it.
          // The test owner now performs it after reviewing the notice.
          expect((await command(action)).needs_sign_in_consent).not.toBe(true);
        }
      };
      const click = (point: { x: number; y: number }) => async () => {
        const frame = page.getByTestId('browse-frame'), rect = await frame.boundingBox(); expect(rect).toBeTruthy();
        await frame.click({ position: { x: point.x * rect!.width / 1280, y: point.y * rect!.height / 800 } });
      };
      const type = (value: string) => async () => {
        const field = page.getByLabel('Text for the website', { exact: true });
        await field.fill(value); await page.getByRole('button', { name: 'Send text', exact: true }).click();
        await expect(field).toHaveValue('');
      };
      await input(click(points[0])); await input(type('tomsmith'));
      await input(click(points[1])); await input(type('SuperSecretPassword!'));
      await input(click(points[2]));
      await screenshot(page, info, `manual-login-${width}`);
      await page.getByRole('button', { name: 'Let AI continue', exact: true }).click();
      await expect(page.getByTestId('browse-fullscreen')).toHaveCount(0);
      await expect(preview(page)).toHaveCount(2, { timeout: 120_000 });
      await expect(preview(page).last()).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });
      const completed = await openSession(page, created.chatId);
      expect(completed.session.session_id).toBe(sid);
      expect(completed.session.max_credits).toBe(opened.session.max_credits);
      await page.getByText('Structured data', { exact: true }).click();
      await expect(page.getByTestId('browse-json')).toContainText('Secure Area');
      await screenshot(page, info, `continued-${width}`);
      const closed = await closeBrowser(page, sid!);
      receipt(info, { ...created, ...opened, sessionId: sid, finalEmbedId: completed.embedId, closed });
    } finally { try { await cleanup(ctx, created.chatId, sid); } finally { await saveVideo(page, ctx, info); } }
  });
}
