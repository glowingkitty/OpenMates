import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
/*
 * design.embroidery request card (GeneratedMediaGroupEmbedPreview) while the
 * conversion runs (TASK-1610): the needle skill icon instead of the AI sparkle,
 * the input graphic from the first frame, and the current step in plain words.
 * Specification: specifications/features/app-skills/design-embroidery/specification.yml
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

async function attach(page: Page, testInfo: { attach: (name: string, body: { body: Buffer; contentType: string }) => Promise<void> }, name: string) {
  await testInfo.attach(name, {
    body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  });
}

// contract-test: direct surface=gui.web assertions=design-embroidery.progress.input-and-stages
test('embroidery card shows the needle icon and the input graphic as soon as it starts', async ({ page }, testInfo) => {
  const card = await open(page, 'embroideryStarted');
  await expect(card.locator('[data-skill-icon]').first()).toHaveAttribute('data-skill-icon', 'embroidery');
  const input = card.getByTestId('image-generate-request-input');
  await expect(input).toBeVisible();
  // The uploaded SVG is drawn, not left as an empty placeholder tile.
  await expect(input.locator('[data-testid="generated-media-thumbnail"] img')).toBeVisible();
  await expect(card.getByTestId('image-generate-request-prompt')).toHaveText('Red fox patch');
  // The first step is named from the first frame, never the bare skill name.
  const step = card.getByTestId('image-generate-request-model');
  await expect(step).toHaveAttribute('data-embroidery-stage', 'reading');
  await expect(step).toHaveText(/Reading the graphic/);
  await attach(page, testInfo, 'embroidery-started');
});

// contract-test: direct surface=gui.web assertions=design-embroidery.progress.input-and-stages
test('embroidery card names the current step next to the input graphic', async ({ page }, testInfo) => {
  for (const [variant, stage, label] of [
    ['embroideryStitching', 'stitching', /Creating stitches and preview/],
    ['embroiderySaving', 'saving', /Saving the machine files/],
  ] as const) {
    const card = await open(page, variant);
    const step = card.getByTestId('image-generate-request-model');
    await expect(step).toHaveAttribute('data-embroidery-stage', stage);
    await expect(step).toHaveText(label);
    await expect(card.getByTestId('image-generate-request-input').locator('img')).toBeVisible();
    await attach(page, testInfo, `embroidery-${stage}`);
  }
});
