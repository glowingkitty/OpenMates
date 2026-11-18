// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
/**
 * Focused component proof of the slides template embed (card and fullscreen) and of
 * the deck's template picker, in bare preview with the built-in designs.
 */
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (component: string, variant = '', width = 900) =>
  `/dev/preview/embeds/slides/${component}?${new URLSearchParams({ variant, width: String(width), theme: 'light', background: '#dbeafe', chrome: '0' })}`;

const BUILTIN_IDS = ['builtin:plain', 'builtin:bold-pitch', 'builtin:calm-talk', 'builtin:clean-business', 'builtin:friendly-classroom'];

test.describe('Slides template embed and picker', () => {
  // contract-test: direct surface=gui.web assertions=slides.templates.library,slides.templates.built-in-set
  test('card shows the themed title slide and a Save button', async ({ page }, testInfo) => {
    for (const [variant, width] of [['', 420], ['plain', 420], ['mobile', 360]] as const) {
      await page.goto(preview('SlidesTemplateEmbedPreview', variant, width));
      await waitForComponentPreview(page);
      const card = page.getByTestId('slides-template-card');
      await expect(card).toBeVisible();
      const canvas = card.getByTestId('slide-canvas');
      await expect(canvas).toBeVisible();
      const box = await canvas.boundingBox();
      expect((box?.width ?? 0) / (box?.height ?? 1)).toBeCloseTo(16 / 9, 1);
      const save = page.getByTestId('slides-template-save');
      await expect(save).toBeVisible();
      // The slide fills the card width and the Save pill stays inside the card.
      const cardBox = await card.boundingBox();
      const saveBox = await save.boundingBox();
      expect(box?.width ?? 0).toBeGreaterThan((cardBox?.width ?? 0) * 0.6);
      expect(saveBox?.x ?? -1).toBeGreaterThanOrEqual(cardBox?.x ?? 0);
      expect((saveBox?.x ?? 0) + (saveBox?.width ?? 0)).toBeLessThanOrEqual((cardBox?.x ?? 0) + (cardBox?.width ?? 0) + 1);
      await testInfo.attach(`card-${variant || 'default'}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
  });

  // contract-test: direct surface=gui.web assertions=slides.templates.built-in-set
  test('fullscreen shows one sample per layout with its name', async ({ page }, testInfo) => {
    await page.goto(preview('SlidesTemplateEmbedFullscreen', '', 1100));
    await waitForComponentPreview(page);
    const grid = page.getByTestId('slides-template-fullscreen');
    await expect(grid).toBeVisible();
    for (const layout of ['title', 'section', 'content', 'image', 'quote', 'closing']) {
      const sample = grid.getByTestId(`slides-template-layout-${layout}`);
      await expect(sample).toBeVisible();
      await expect(sample.locator('figcaption')).not.toBeEmpty();
    }
    await expect(page.getByTestId('slides-template-use')).toBeVisible();
    await testInfo.attach('fullscreen-1100', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });

  // contract-test: direct surface=gui.web assertions=slides.templates.apply-to-deck
  test('picker lists the built-in designs and enables Apply only after a choice', async ({ page }, testInfo) => {
    await page.goto(preview('SlidesTemplatePicker', '', 900));
    await waitForComponentPreview(page);
    const picker = page.getByTestId('slides-template-picker');
    await expect(picker).toBeVisible();
    const options = picker.getByTestId('slides-template-option');
    await expect(options).toHaveCount(BUILTIN_IDS.length);
    for (const id of BUILTIN_IDS) {
      const option = picker.locator(`[data-template-id="${id}"]`);
      const thumb = option.getByTestId('slide-canvas');
      await expect(thumb).toBeVisible();
      // The whole title-slide preview shows: the option is taller than its thumbnail, which keeps 16:9.
      const thumbBox = await thumb.boundingBox();
      const optionBox = await option.boundingBox();
      expect((thumbBox?.width ?? 0) / (thumbBox?.height ?? 1)).toBeCloseTo(16 / 9, 1);
      expect(thumbBox?.height ?? 0).toBeGreaterThan(40);
      expect(optionBox?.height ?? 0).toBeGreaterThan(thumbBox?.height ?? Infinity);
    }
    const apply = picker.getByTestId('slides-template-apply');
    await expect(apply).toBeDisabled();
    await testInfo.attach('picker-initial-900', { body: await picker.screenshot(), contentType: 'image/png' });

    const bold = picker.locator('[data-template-id="builtin:bold-pitch"]');
    await bold.click();
    await expect(bold).toHaveAttribute('aria-pressed', 'true');
    await expect(apply).toBeEnabled();
    await testInfo.attach('picker-selected-900', { body: await picker.screenshot(), contentType: 'image/png' });

    await page.goto(preview('SlidesTemplatePicker', 'disabled', 900));
    await waitForComponentPreview(page);
    await page.locator('[data-template-id="builtin:calm-talk"]').click();
    await expect(page.getByTestId('slides-template-apply')).toBeDisabled();
  });

  // contract-test: direct surface=gui.web assertions=slides.templates.apply-to-deck
  test('picker fits a phone width without horizontal overflow', async ({ page }, testInfo) => {
    await page.goto(preview('SlidesTemplatePicker', '', 375));
    await waitForComponentPreview(page);
    const picker = page.getByTestId('slides-template-picker');
    await expect(picker).toBeVisible();
    const overflow = await picker.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await testInfo.attach('picker-375', { body: await picker.screenshot(), contentType: 'image/png' });
  });
});
