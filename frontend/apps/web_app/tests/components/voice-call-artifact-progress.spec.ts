// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.use({ viewport: { width: 1280, height: 900 } });

const preview = (variant = 'voiceCallProcessingArtifact') =>
  `/dev/preview/ChatMessage?chrome=0&theme=light&background=%23dbeafe&width=820&variant=${variant}`;
const skill = '[data-testid="embed-preview"][data-embed-id="preview-voice-artifact-skill"]';
const source = '[data-testid="skill-input-images"] button[data-embed-id="preview-voice-artifact-source"]';

// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,chat-processing-feedback.completed-processing-summary
test('durably saved call artifact expands while its skill runs, then collapses with the saved source retained', async ({ page }) => {
  await page.goto(preview());
  await waitForComponentPreview(page);
  const toggle = page.getByTestId('assistant-activity-toggle');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  const card = page.locator(skill);
  await expect(card).toHaveAttribute('data-status', 'processing');
  // The card itself cannot open yet; its independently available inputs can.
  await expect(card).toHaveAttribute('role', 'group');
  await expect(card).toHaveAttribute('tabindex', '-1');
  await expect(card.locator(source)).toBeEnabled();
  await expect.poll(() => card.locator(`${source} img`).evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  await page.evaluate(() => document.addEventListener('imagefullscreen', ((event: CustomEvent) => {
    document.body.dataset.openedVoiceArtifactSource = event.detail.embedId;
    document.body.dataset.voiceArtifactSourceOpens = String(Number(document.body.dataset.voiceArtifactSourceOpens ?? 0) + 1);
  }) as EventListener));
  await expect(card.locator(source)).toHaveCSS('pointer-events', 'auto');
  await card.locator(source).hover();
  await card.locator(source).click();
  await expect(page.locator('body')).toHaveAttribute('data-opened-voice-artifact-source', 'preview-voice-artifact-source');
  await expect(page.locator('body')).toHaveAttribute('data-voice-artifact-source-opens', '1');
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('preview:finish-voice-artifact')));
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByTestId('assistant-activity-body')).toHaveCount(0);
  await toggle.click();
  await expect(card).toHaveAttribute('data-status', 'finished');
  await expect(card).toHaveAttribute('role', 'button');
  await expect(card.locator(source)).toBeEnabled();
  await expect(card.locator('[data-testid="skill-input-images"]')).toContainText('Image used');
  await expect(card.locator(source)).toHaveCSS('pointer-events', 'auto');
  await card.locator(source).hover();
  await card.locator(source).click();
  await expect(page.locator('body')).toHaveAttribute('data-voice-artifact-source-opens', '2');
});

// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance,chat-processing-feedback.completed-processing-summary
test('manual activity expansion remains authoritative when a durable call skill completes', async ({ page }) => {
  await page.goto(preview());
  await waitForComponentPreview(page);
  const toggle = page.getByTestId('assistant-activity-toggle');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await toggle.click();
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('preview:finish-voice-artifact')));
  await expect(page.locator(skill)).toHaveAttribute('data-status', 'finished');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator(skill).locator(source)).toBeEnabled();
});

// contract-test: supporting surface=gui.web assertions=chat-processing-feedback.completed-processing-summary
test('an ordinary saved message keeps its existing collapsed activity behavior', async ({ page }) => {
  await page.goto(preview('durableProcessingArtifact'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('assistant-activity-toggle')).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByTestId('assistant-activity-body')).toHaveCount(0);
});
