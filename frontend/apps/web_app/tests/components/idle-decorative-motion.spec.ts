// playwright-account: not_required reason=isolated_component_preview
import type { Locator, Page, TestInfo } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

async function openPreview(page: Page, path: string, width: number, variant?: string) {
  await page.setViewportSize({ width, height: 844 });
  const query = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(width), chrome: '0' });
  if (variant) query.set('variant', variant);
  await page.goto(`/dev/preview/${path}?${query}`);
  await waitForComponentPreview(page);
}

async function expectStaticDecoration(elements: Locator) {
  await expect(elements.first()).toBeAttached();
  await expect.poll(() => elements.evaluateAll(nodes =>
    nodes.some(node => node.getAnimations({ subtree: true }).some(animation => animation.playState === 'running')),
  )).toBe(false);
}

async function capture(locator: Locator, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, { body: await locator.screenshot(), contentType: 'image/png' });
}

// contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-cards
test('chat start cards keep their static decoration and press feedback', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  for (const width of [390, 1280]) {
    await openPreview(page, 'welcome/StartScreenRowPreviewHarness', width);
    const row = page.getByTestId('recent-chats-scroll-container');
    const card = row.getByTestId('resume-chat-large-card').first();
    await expect(card).toBeVisible();
    await expect(card).toHaveCSS('background-image', /gradient/);
    await expectStaticDecoration(row.getByTestId('start-card-glows'));
    await expectStaticDecoration(row.getByTestId('start-card-decoration'));
    await capture(row, testInfo, `chat-start-${width}`);
    if (width === 1280) {
      await card.hover();
      await expect(card).not.toHaveCSS('transform', 'none');
      await page.mouse.down();
      await expect(card).toHaveCSS('transform', 'matrix(0.96, 0, 0, 0.96, 0, 0)');
      await page.mouse.up();
      await card.focus();
      await expect(card).toBeFocused();
    }
  }
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.start.available-space-cards
test('workspace start cards and inspiration banner keep the gradient without idle motion', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  for (const width of [390, 1280]) {
    await openPreview(page, 'workflows/WorkflowHomePreviewHarness', width);
    const row = page.getByTestId('workflow-mixed-row');
    const card = row.getByTestId('workflow-landing-card').first();
    await expect(card).toBeVisible();
    await expect(card).toHaveCSS('background-image', /gradient/);
    await expectStaticDecoration(row.getByTestId('start-card-glows'));
    await capture(row, testInfo, `workspace-start-${width}`);
  }
  await openPreview(page, 'DailyInspirationBanner', 1100, 'germanPersonalized');
  const banner = page.getByTestId('daily-inspiration-banner');
  await expect(banner).toBeVisible();
  await expectStaticDecoration(banner.getByTestId('inspiration-banner-glows'));
  await capture(banner, testInfo, 'workspace-inspiration-banner');
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('open chat keeps a static gradient and video covers stay still before play', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  for (const width of [390, 1280]) {
    await openPreview(page, 'ChatHeader', width);
    const header = page.getByTestId('chat-header-banner');
    await expect(header.getByTestId('chat-header-title')).toBeVisible();
    await expect(header).toHaveCSS('background-image', /gradient/);
    await expectStaticDecoration(header.getByTestId('chat-header-glows'));
    await expectStaticDecoration(header.getByTestId('chat-header-decoration'));
    await capture(header, testInfo, `chat-header-${width}`);
  }
  await openPreview(page, 'ChatHeader', 390, 'introPoster');
  const header = page.getByTestId('chat-header-banner');
  await expect(header.getByTestId('chat-header-title')).toBeVisible();
  const play = header.getByRole('button', { name: 'Play video' });
  await expect(play).toBeInViewport();
  await expect(header.getByTestId('chat-header-teaser-poster')).toHaveJSProperty('complete', true);
  await expect(header.locator('video')).toHaveCount(0);
  await expectStaticDecoration(header.getByTestId('chat-header-teaser'));
  await capture(header, testInfo, 'chat-header-video-cover-390');
  await play.press('Enter');
  await expect(header.getByTestId('chat-header-video')).toBeAttached();
});
