/** Focused status appearance, reduced motion, retry and collapsing-slot coverage. */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
// contract-test-file: tooling
/* eslint-disable @typescript-eslint/no-require-imports -- Shared proof helpers use CommonJS. */
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const IS_PHONE = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === 390;
const DEVICE = IS_PHONE ? 'web-phone' : 'web-laptop';
const WIDTH = IS_PHONE ? 390 : 1440;
const STATES = ['offline', 'reconnecting', 'syncing', 'idle'] as const;
const LABELS = { offline: 'You are offline', reconnecting: 'Reconnecting to server', syncing: 'Syncing chats', idle: '' };
const PROOF = defineVideoProof({
  id: 'connection-status-visual-proposal',
  title: 'Header reconnect, sync and collapsing status slot',
  surface: 'web',
  devices: ['web-laptop', 'web-phone'],
  domain: 'app.dev.openmates.org',
  transcript: STATES.map(state => ({
    id: state, checkpoint: state, devices: ['web-laptop', 'web-phone'],
    text: state === 'offline' ? 'A static airplane shows the device is offline.'
      : state === 'reconnecting' ? 'A quiet Wi-Fi ripple shows reconnection beside the profile.'
      : state === 'syncing' ? 'Rotating arrows use the same slot during chat sync.'
        : 'The indicator disappears and neighboring controls slide into its space; the profile stays fixed.',
  })),
  assertions: STATES.map(state => ({
    id: `proposal.${state}`, checkpoint: state, devices: ['web-laptop', 'web-phone'],
    visual: state === 'idle' ? 'The profile keeps its position and no empty status space remains.'
      : 'One small animated status icon appears immediately left of the profile without overlap.',
  })),
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

async function openPreview(page: Page, state: typeof STATES[number], theme = 'light', width = WIDTH, companion = 'github') {
  const params = new URLSearchParams({
    theme, background: '#dbeafe', width: String(width), chrome: '0',
    ...(state !== 'reconnecting' ? { variant: state } : {}),
    ...(companion === 'referral' ? { props: JSON.stringify({ companion }) } : {}),
  });
  await page.goto(`/dev/preview/ConnectionStatusPreviewHarness?${params}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('global-header')).toBeVisible();
}

async function expectPlacement(page: Page, state: typeof STATES[number] = 'reconnecting') {
  const avatar = page.getByTestId('preview-profile-image');
  const slot = page.getByTestId('connection-status-slot');
  await expect(avatar).toBeVisible();
  const [avatarBox, slotBox] = await Promise.all([avatar.boundingBox(), slot.boundingBox()]);
  expect(avatarBox).not.toBeNull();
  expect(slotBox).not.toBeNull();
  expect(slotBox!.width).toBe(state === 'idle' ? 0 : 30);
  expect(avatarBox!.x - slotBox!.x - slotBox!.width).toBe(8);
  expect(Math.abs(avatarBox!.y + avatarBox!.height / 2 - slotBox!.y - slotBox!.height / 2)).toBeLessThan(1);
  expect(avatarBox!.x + avatarBox!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  const header = page.getByTestId('global-header');
  const selector = header.locator('.workspace-select-shell');
  const companionBox = await page.getByTestId('preview-companion-control').boundingBox();
  expect(companionBox).not.toBeNull();
  expect(companionBox!.x + companionBox!.width).toBeLessThanOrEqual(slotBox!.x);
  if (await selector.isVisible()) {
    const selectBox = await selector.boundingBox();
    expect(selectBox!.x + selectBox!.width).toBeLessThanOrEqual(companionBox!.x);
  }
  expect(await page.getByTestId('connection-status-preview').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  return avatarBox;
}

test('records reconnect, sync and idle in light and dark headers', async ({ page }, testInfo) => {
  // Six real animation holds plus initial Vite compilation exceed the default 30s.
  test.setTimeout(90_000);
  await page.setViewportSize({ width: WIDTH, height: IS_PHONE ? 844 : 900 });
  const proof = createVideoProofRuntime(PROOF, { device: DEVICE, attach: testInfo.attach.bind(testInfo) });
  let originalAvatarPosition: { x: number; y: number } | undefined;
  for (const theme of ['light', 'dark']) {
    await openPreview(page, 'offline', theme);
    const activeCompanionX = (await page.getByTestId('preview-companion-control').boundingBox())!.x;
    for (const state of STATES) {
      if (state !== 'offline') {
        await page.evaluate(next => window.dispatchEvent(new CustomEvent('openmates-preview-connection-state', { detail: next })), state);
        await expect.poll(async () => (await page.getByTestId('connection-status-slot').boundingBox())!.width).toBe(state === 'idle' ? 0 : 30);
      }
      await proof.assert(`proposal.${state}`, async () => {
        const box = await expectPlacement(page, state);
        originalAvatarPosition ??= { x: box!.x, y: box!.y };
        expect({ x: box!.x, y: box!.y }).toEqual(originalAvatarPosition);
        const indicator = page.getByTestId('connection-status-indicator');
        if (state === 'idle') {
          await expect(indicator).toHaveCount(0);
          const idleCompanionX = (await page.getByTestId('preview-companion-control').boundingBox())!.x;
          expect(idleCompanionX - activeCompanionX).toBe(38);
          return;
        }
        await expect(indicator).toHaveAttribute('data-state', state);
        await expect(indicator).toHaveAccessibleName(LABELS[state]);
        await expect(indicator.locator('svg')).toBeVisible();
        await indicator.hover();
        await expect(indicator).toHaveAttribute('title', LABELS[state]);
        const moving = await indicator.evaluate(element => element.getAnimations({ subtree: true }).some(animation => animation.playState === 'running'));
        expect(moving).toBe(state !== 'offline');
        if (state === 'offline') await expect(indicator.getByRole('button')).toHaveCount(0);
        await page.mouse.move(WIDTH / 2, 130);
      });
      await proof.checkpoint(state);
      // Keep real moving frames so the user can judge the proposed animation.
      await page.waitForTimeout(state === 'idle' ? 1800 : 3600);
    }
  }
  await proof.attach();
});

test('keeps both statuses static with reduced motion and fits the smallest phone header', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: IS_PHONE ? 320 : WIDTH, height: IS_PHONE ? 844 : 900 });
  for (const state of ['offline', 'reconnecting', 'syncing'] as const) {
    await openPreview(page, state, 'light', IS_PHONE ? 320 : WIDTH);
    await expectPlacement(page);
    const indicator = page.getByTestId('connection-status-indicator');
    await expect(indicator).toBeVisible();
    expect(await indicator.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
    await page.waitForTimeout(1800);
  }
  await openPreview(page, 'reconnecting', 'light', IS_PHONE ? 320 : WIDTH, 'referral');
  await expectPlacement(page);
  await expect(page.getByTestId('preview-companion-control')).toHaveAccessibleName('Get free credits');
  await page.evaluate(() => {
    window.addEventListener('openmates-preview-reconnect', () => { document.documentElement.dataset.retryClicked = 'true'; }, { once: true });
  });
  await page.getByRole('button', { name: 'Tap to reconnect' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-retry-clicked', 'true');
  await page.waitForTimeout(1800);
});
