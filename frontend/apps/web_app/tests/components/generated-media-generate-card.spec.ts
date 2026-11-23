import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
/*
 * AI generation skill card (GeneratedMediaGroupEmbedPreview, images.generate):
 * AI sparkle as skill icon, shortened prompt, model, input thumbnail and the
 * partial SVG drawn while the vector author is still working.
 */
const PARENT = '/dev/preview/embeds/GeneratedMediaGroupEmbedPreview?chrome=0&theme=light&background=%23dbeafe';

async function open(page: Page, variant: string) {
  await page.setViewportSize({ width: 600, height: 900 });
  await page.goto(`${PARENT}&variant=${variant}&width=420`);
  await waitForComponentPreview(page);
  const card = page.getByTestId('embed-preview');
  await expect(card).toBeVisible();
  return card;
}

// contract-test: direct surface=gui.web assertions=chats.rendering.skill-card-call-order,images-generate.vector.progressive-drafts
test('generate card shows sparkle skill icon, prompt snippet, model and input thumbnail', async ({ page }, testInfo) => {
  const card = await open(page, 'imageRequest');
  // AI sparkle as the skill icon; the app icon in the circle stays the images icon.
  await expect(card.locator('[data-skill-icon]').first()).toHaveAttribute('data-skill-icon', 'ai');
  await expect(card.getByTestId('image-generate-request-prompt')).toContainText('A pair of stylised mountain peaks');
  await expect(card.getByTestId('image-generate-request-model')).toContainText(/Generating via|via/i);
  await expect(card.getByTestId('image-generate-request-input')).toBeVisible();
  const prompt = card.getByTestId('image-generate-request-prompt');
  // The long prompt is clamped to at most four visible lines (ellipsis), never overflowing the card.
  const lines = await prompt.evaluate((el) => el.clientHeight / Number.parseFloat(getComputedStyle(el).lineHeight));
  expect(lines).toBeLessThanOrEqual(4.1);
  await testInfo.attach('image-request-card', {
    body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  });
});

// contract-test: direct surface=gui.web assertions=chats.rendering.skill-card-call-order,images-generate.vector.progressive-drafts
test('generate card streams the partial SVG while it is drawn', async ({ page }, testInfo) => {
  const card = await open(page, 'svgStreaming');
  const draft = card.getByTestId('image-generate-svg-draft');
  await expect(draft).toBeVisible();
  await expect(draft).toHaveAttribute('data-stage', 'drawing');
  // The partial SVG is drawn as an image of the draft source.
  await expect(draft.locator('img, svg').first()).toBeVisible();
  await testInfo.attach('svg-streaming-card', {
    body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  });
});
