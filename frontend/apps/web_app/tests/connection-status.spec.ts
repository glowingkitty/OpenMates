/* eslint-disable @typescript-eslint/no-require-imports -- Existing account helpers use CommonJS. */
import type { WebSocketRoute } from '@playwright/test';
import { test, expect } from './helpers/cookie-audit';
import { waitForComponentMotion } from './helpers/component-preview';
const { getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases,chats.sync.key-gated-recovery,notifications.web.stacked-deck
test('real chat sync and reconnect use one collapsing profile slot without routine notification cards', async ({ page, context }) => {
  test.setTimeout(180_000);
  const credentials = getTestAccount();
  skipWithoutCredentials(test, credentials.email, credentials.password, credentials.otpKey);
  await page.emulateMedia({ reducedMotion: 'no-preference' });

  let holdCompletion = true;
  let blockConnections = false;
  let liveSocket: WebSocketRoute | undefined;
  let requests = 0;
  let completions: Array<() => void> = [];
  // Keep the real backend protocol, delaying only its genuine full-sync completion.
  await page.routeWebSocket(/\/ws(?:[/?]|$)/, ws => {
    if (blockConnections) { void ws.close({ code: 1013, reason: 'test connection interruption' }); return; }
    liveSocket = ws;
    const server = ws.connectToServer();
    ws.onMessage(message => {
      try { if (JSON.parse(message.toString()).type === 'phased_sync_request') requests++; } catch { /* Non-JSON frame. */ }
      server.send(message);
    });
    server.onMessage(message => {
      let isFullCompletion = false;
      try {
        const parsed = JSON.parse(message.toString());
        isFullCompletion = parsed.type === 'phased_sync_complete' && parsed.payload?.phase === 'all';
      } catch { /* Non-JSON frame. */ }
      if (holdCompletion && isFullCompletion) completions.push(() => ws.send(message));
      else ws.send(message);
    });
  });

  await loginToTestAccount(page, undefined, undefined, { credentials, waitForEditor: false });
  const indicator = page.getByTestId('connection-status-indicator');
  const slot = page.getByTestId('connection-status-slot');
  const companion = page.locator('[data-testid="header-github-link"]:visible, [data-testid="referral-cta"]:visible, [data-testid="learning-mode-header-cta"]:visible').first();
  const avatar = page.getByTestId('profile-container');
  const routineCards = page.locator('.notification-connection, .notification-title').filter({
    hasText: /reconnect|you are offline|server updating|chat sync is still recovering/i,
  });
  await expect.poll(() => requests).toBeGreaterThan(0);
  await expect(indicator).toHaveAttribute('data-state', 'syncing', { timeout: 20_000 });
  await expect.poll(() => completions.length).toBeGreaterThan(0);
  await expect(companion).toBeVisible();
  await expect.poll(async () => (await slot.boundingBox())!.width).toBe(30);
  await waitForComponentMotion(companion);
  await expect(routineCards).toHaveCount(0);
  const avatarX = (await avatar.boundingBox())!.x;
  const activeX = (await companion.boundingBox())!.x;
  const companionId = (await companion.getAttribute('data-testid'))!;
  const slotBox = (await slot.boundingBox())!;
  const companionBox = (await companion.boundingBox())!;
  expect(avatarX - slotBox.x - slotBox.width).toBe(8);
  expect(companionBox.x + companionBox.width).toBeLessThanOrEqual(slotBox.x);
  const selector = page.getByTestId('global-header').locator('.workspace-select-shell');
  if (await selector.isVisible()) {
    expect((await selector.boundingBox())!.x + (await selector.boundingBox())!.width).toBeLessThanOrEqual(companionBox.x);
  }
  await page.waitForTimeout(1800); // Retain readable real animation frames.

  const release = () => {
    holdCompletion = false;
    for (const complete of completions) complete();
    completions = [];
  };
  // Capture actual intermediate layout positions during the disappearance.
  await page.evaluate(id => {
    const samples: number[] = [];
    (window as typeof window & { statusMotionSamples?: number[] }).statusMotionSamples = samples;
    const end = performance.now() + 1000;
    const sample = () => {
      samples.push(document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().x);
      if (performance.now() < end) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  }, companionId);
  release();
  await expect(indicator).toHaveCount(0);
  await expect.poll(async () => (await slot.boundingBox())!.width).toBe(0);
  await expect.poll(async () => (await companion.boundingBox())!.x - activeX).toBe(38);
  expect((await avatar.boundingBox())!.x).toBe(avatarX);
  expect(await page.evaluate(({ start, finish }) =>
    (window as typeof window & { statusMotionSamples?: number[] }).statusMotionSamples?.some(x => x > start + 1 && x < finish - 1),
  { start: activeX, finish: activeX + 38 })).toBe(true);
  await expect(routineCards).toHaveCount(0);
  await page.waitForTimeout(1800);

  holdCompletion = true;
  blockConnections = true;
  await context.setOffline(true);
  await expect(indicator).toHaveAttribute('data-state', 'offline');
  await expect(indicator.getByRole('button')).toHaveCount(0);
  expect(await indicator.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
  await liveSocket!.close({ code: 1013, reason: 'test connection interruption' });
  await expect(routineCards).toHaveCount(0);
  await page.waitForTimeout(1800);
  await context.setOffline(false);
  // A brief reconnect after a completed sync intentionally skips redundant full
  // sync. Reload the real cached session to cover reconnect + startup sync too.
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(avatar).toBeVisible();
  // Browser-online alone does not hide sustained server disconnection.
  await expect(indicator).toHaveAttribute('data-state', 'reconnecting', { timeout: 15_000 });
  const requestsBeforeRetry = requests;
  blockConnections = false;
  await indicator.getByRole('button').click();
  await expect.poll(() => requests).toBeGreaterThan(requestsBeforeRetry);
  await expect(indicator).toHaveAttribute('data-state', 'syncing', { timeout: 20_000 });
  await expect.poll(() => completions.length).toBeGreaterThan(0);
  await expect(routineCards).toHaveCount(0);
  await page.waitForTimeout(1800);
  release();
  await expect(indicator).toHaveCount(0);
  await expect.poll(async () => (await slot.boundingBox())!.width).toBe(0);
  await expect.poll(async () => (await companion.boundingBox())!.x - activeX).toBe(38);
  expect((await avatar.boundingBox())!.x).toBe(avatarX);
  await expect(routineCards).toHaveCount(0);
  await page.waitForTimeout(1800);
});

// contract-test: supporting surface=gui.web assertions=sync.access.first-party-authenticated,notifications.web.stacked-deck
test('signed-out users see only a static flight-mode icon offline and no status space online', async ({ page, context }) => {
  await page.goto(getE2EDebugUrl('/#chat-id=demo-who-develops-openmates'), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('global-header')).toBeVisible();
  await expect(page.getByTestId('connection-status-indicator')).toHaveCount(0);
  await context.setOffline(true);
  const indicator = page.getByTestId('connection-status-indicator');
  await expect(indicator).toHaveAttribute('data-state', 'offline');
  await expect(indicator.getByRole('button')).toHaveCount(0);
  expect(await indicator.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
  await page.waitForTimeout(1800);
  await context.setOffline(false);
  await expect(indicator).toHaveCount(0);
  await expect(page.getByTestId('global-header')).not.toHaveClass(/connection-status-visible/);
  await expect.poll(async () => page.getByTestId('connection-status-slot').evaluateAll(slots => slots.every(slot => slot.getBoundingClientRect().width === 0))).toBe(true);
  await page.waitForTimeout(1800);
});
