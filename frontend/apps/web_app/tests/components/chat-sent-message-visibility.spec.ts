// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.layout.responsive-history,chat-message-timeline.access-and-lifecycle
  test(`a send reveals its user row from an older exchange before response text at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 850 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(`/dev/preview/ChatResponseScrollHarness?variant=existingChat&theme=light&background=%23dbeafe&width=${width}&chrome=0`);
    await waitForComponentPreview(page);
    if (width === 390) await page.getByTestId('chat-timeline-toggle').click();
    const rail = page.getByTestId('timeline-rail');
    await expect(rail).toBeVisible();
    await rail.focus(); await rail.press('Home'); await rail.press('Enter');
    await expect(page.locator('.message-wrapper[data-message-id="prior-0"]')).toBeVisible();
    await expect(page.locator('.message-wrapper[data-message-id="scroll-user"]')).toHaveCount(0);
    await page.getByTestId('send-prompt').click();
    const submitted = page.locator('.message-wrapper[data-message-id="scroll-user"]');
    await expect(submitted).toHaveCount(1);
    await expect(submitted).toBeInViewport();
    await expect(submitted).toContainText('Start with a summary.');
    await expect(page.locator('.message-wrapper[data-message-id="scroll-assistant"]')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath(`sent-before-answer-${width}.png`) });
    await page.getByTestId('stream-response').click();
    await expect(page.locator('.message-wrapper[data-message-id="scroll-assistant"]')).toContainText('Here is the beginning');
    await expect(submitted).toHaveCount(1);
    await expect(page.getByTestId('chat-history-container')).toHaveAttribute('data-scroll-state', 'ready');
  });
}
