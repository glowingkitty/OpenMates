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

// An answer body shows only result embeds: the generation parent card never
// renders in the body, neither next to its child nor alone (old answers).
for (const variant of ['imageChildAndParentInBody', 'imageParentOnlyInBody']) {
  // contract-test: direct surface=gui.web assertions=app-skills.answer.only-result-embeds-in-body
  test(`${variant} shows only the generated image in the answer body`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/dev/preview/ChatMessage?chrome=0&theme=light&width=390&variant=${variant}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const activity = page.getByTestId('assistant-activity-group');
    await expect(activity).toHaveCount(1);
    await expect(activity.getByTestId('assistant-activity-toggle')).toContainText('Images');
    const result = page.locator('[data-type="embed-preview-large"]');
    await expect(result).toHaveCount(1);
    await expect(result).toBeVisible();
    const image = result.locator('[data-testid="image-generate-preview-image"][data-embed-version]');
    await expect(image).toBeVisible();
    await expect(result.locator('[data-embed-id]').first()).toBeAttached();
    // One result: no carousel dots, no slot for the parent.
    await expect(result.locator('.carousel-dots')).toHaveCount(0);
    const bodyParentCards = () => page.locator('[data-testid="generated-media-parent-preview"]').evaluateAll(
      (cards) => cards.filter((card) => !card.closest('[data-testid="assistant-activity-group"]')).length);
    expect(await bodyParentCards()).toBe(0);
    await testInfo.attach(`${variant}-collapsed`, { body: await page.screenshot(), contentType: 'image/png' });

    const toggle = activity.getByTestId('assistant-activity-toggle');
    await toggle.click();
    await expect(activity.getByTestId('assistant-activity-body')).toBeVisible();
    await expect(result).toHaveCount(1);
    expect(await bodyParentCards()).toBe(0);
    await testInfo.attach(`${variant}-expanded`, { body: await page.screenshot(), contentType: 'image/png' });
  });
}
