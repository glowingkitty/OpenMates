// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const previewUrl = (component: string, variant: string, width: number) =>
  `/dev/preview/${component}?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0', variant,
  })}`;

// contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
test('A finished assistant turn without answer text shows the skill failure banner', async ({ page }, testInfo) => {
  test.setTimeout(60_000); // Cold local preview compilation may outlast Playwright's default 30s.
  await page.goto(previewUrl('ChatMessage', 'withEmbedErrors', 820));
  const canvas = await waitForComponentPreview(page);
  const banner = canvas.getByTestId('embed-error-banner');
  await expect(banner).toBeVisible();
  await expect(banner.locator('.embed-error-text')).not.toBeEmpty();
  await testInfo.attach('banner-no-answer-820', { body: await canvas.screenshot(), contentType: 'image/png' });
});

// contract-test: direct surface=gui.web assertions=chats.rendering.skill-failure-banner
test('A finished assistant answer with text shows no failure banner although a skill failed', async ({ page }, testInfo) => {
  test.setTimeout(60_000); // Cold local preview compilation may outlast Playwright's default 30s.
  await page.goto(previewUrl('ChatMessage', 'withPartialEmbedErrors', 820));
  const canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('mate-message-content')).toContainText('two train connections');
  await expect(canvas.getByTestId('embed-error-banner')).toHaveCount(0);
  await testInfo.attach('answer-without-banner-820', { body: await canvas.screenshot(), contentType: 'image/png' });
});

for (const width of [390, 1100]) {
  // contract-test: direct surface=gui.web assertions=events-search.request.validated
  test(`A failed events search shows its reason in fullscreen at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(60_000); // Cold local preview compilation may outlast Playwright's default 30s.
    await page.setViewportSize({ width: Math.max(1280, width + 80), height: 900 });
    await page.goto(previewUrl('embeds/events/EventsSearchEmbedFullscreen', 'requestError', width));
    const canvas = await waitForComponentPreview(page);
    const reason = canvas.getByTestId('events-search-error');
    await expect(reason).toBeVisible();
    await expect(reason).toContainText("missing the required 'query' field");
    const viewport = await canvas.getByTestId('component-preview-viewport').boundingBox();
    const box = await reason.boundingBox();
    expect(viewport).not.toBeNull();
    expect(box).not.toBeNull();
    // The reason keeps a side margin instead of touching the fullscreen edges.
    expect(box!.x).toBeGreaterThanOrEqual(viewport!.x + 12);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.x + viewport!.width - 12);
    await testInfo.attach(`events-request-error-${width}`, { body: await canvas.screenshot(), contentType: 'image/png' });
  });
}
