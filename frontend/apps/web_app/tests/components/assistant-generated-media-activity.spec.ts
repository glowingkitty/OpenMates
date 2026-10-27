// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const variant of ['generatedMusic', 'generatedAudio', 'generatedImage', 'generatedImageLostReferences', 'generatedMusicStreaming']) {
  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,app-skills.media.visible-assistant-results,public-example-chats.transcript.safe-rendering
  test(`${variant} keeps one invocation summary and the genuine result`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/dev/preview/ChatMessage?chrome=0&theme=light&width=390&variant=${variant}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const activity = page.getByTestId('assistant-activity-group');
    await expect(activity).toHaveCount(1);
    const toggle = activity.getByTestId('assistant-activity-toggle');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(activity.getByTestId('assistant-activity-summary-text')).not.toBeEmpty();
    // Generated output is a sibling of collapsed activity, never hidden in it.
    const result = page.locator('[data-type="embed-preview-large"]');
    await expect(result).toHaveCount(1);
    await expect(result).toBeVisible();
    if (variant === 'generatedImageLostReferences') {
      await expect(result.locator('.preview-image')).toBeVisible();
      await expect(page.getByTestId('assistant-activity-body')).not.toBeVisible();
    }
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(activity.getByTestId('assistant-activity-body')).toBeVisible();
    await expect(result).toBeVisible();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(result).toBeVisible();
    if (variant === 'generatedImageLostReferences') {
      await testInfo.attach('saved-image-recovered', { body: await page.screenshot(), contentType: 'image/png' });
    }
  });
}
