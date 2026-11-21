/**
 * Component proof: a Memory request offers a clear "Continue without memories"
 * action, and in a voice call it shows a countdown bar along its bottom edge
 * (when it runs out the assistant answers without memories). Text chats show
 * no countdown. Fictional preview fixtures only; nothing is approved.
 * Spec: specifications/features/video-call/specification.yml
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const preview = (variant: string | undefined, width: string, theme: string) =>
  `/dev/preview/AppSettingsMemoriesPermissionDialog?${new URLSearchParams({ chrome: '0', theme, width, ...(variant ? { variant } : {}) })}`;

for (const { width, theme } of [{ width: '900', theme: 'light' }, { width: '390', theme: 'dark' }]) {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
  test(`memory request: continue without memories, call countdown (${width}px, ${theme})`, async ({ page }, testInfo) => {
    await page.goto(preview(undefined, width, theme));
    await waitForComponentPreview(page);
    const card = page.getByTestId('app-settings-memories-permission-card');
    await expect(card).toBeVisible();
    await expect(page.getByTestId('btn-reject')).toHaveText(/Continue without memories/);
    await expect(page.getByTestId('memory-request-call-countdown')).toHaveCount(0);
    await testInfo.attach(`text-chat-${width}-${theme}`, { body: await card.screenshot(), contentType: 'image/png' });

    await page.goto(preview('inCall', width, theme));
    await waitForComponentPreview(page);
    const countdown = page.getByTestId('memory-request-call-countdown');
    await expect(countdown).toBeVisible();
    await expect(countdown).toHaveAttribute('aria-valuenow', '60');
    await expect(countdown).toHaveAttribute('aria-label', /without memories/);
    const cardBox = await card.boundingBox();
    const barBox = await countdown.boundingBox();
    expect(barBox && cardBox && barBox.y + barBox.height).toBeLessThanOrEqual((cardBox?.y ?? 0) + (cardBox?.height ?? 0));
    expect(barBox?.height).toBeLessThanOrEqual(4);
    const fill = await countdown.locator('.call-countdown-bar').boundingBox();
    expect(Math.round(((fill?.width ?? 0) / (barBox?.width ?? 1)) * 100)).toBeGreaterThanOrEqual(58);
    await testInfo.attach(`in-call-${width}-${theme}`, { body: await card.screenshot(), contentType: 'image/png' });
  });
}
