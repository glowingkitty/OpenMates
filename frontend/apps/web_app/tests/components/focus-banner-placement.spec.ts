import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=isolated_component_preview

// The active focus banner of every focus mode sits directly above the composer without
// overlapping it and stays on screen. Unrelated pills keep their own position (focus-modes.banner-placement).

const viewports = [
  { name: 'phone', width: 390, height: 844 },
  { name: 'laptop', width: 1280, height: 800 },
];
const focusVariants = ['careerInsightsFocus', 'deepResearchFocus', 'projectSpecialist'];

async function openPreview(page: Page, variant: string, width: number) {
  await page.goto(`/dev/preview/enter_message/MessageInput?chrome=0&variant=${variant}&width=${width}`);
  await waitForComponentPreview(page);
}

for (const viewport of viewports) {
  for (const variant of focusVariants) {
    // contract-test: direct surface=gui.web assertions=focus-modes.banner-placement
    test(`${variant} banner sits above the composer on ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await openPreview(page, variant, viewport.width);
      const pill = page.getByTestId('focus-pill');
      await expect(pill).toBeVisible();
      await expect(page.getByTestId('focus-pill-label')).not.toHaveText('');
      const [pillBox, fieldBox] = await Promise.all([
        pill.boundingBox(),
        page.getByTestId('message-field').boundingBox(),
      ]);
      expect(pillBox && fieldBox).toBeTruthy();
      if (!pillBox || !fieldBox) return;
      // Sits above the composer and ends at its top edge: no overlap with the composer,
      // its text or its controls.
      expect(pillBox.y + pillBox.height).toBeLessThanOrEqual(fieldBox.y + 0.5);
      expect(pillBox.y + pillBox.height).toBeGreaterThan(fieldBox.y - 8);
      // Fully on screen and its off control stays usable.
      expect(pillBox.x).toBeGreaterThanOrEqual(0);
      expect(pillBox.x + pillBox.width).toBeLessThanOrEqual(viewport.width);
      await expect(pill.getByTestId('focus-pill-toggle')).toBeVisible();
      await test.info().attach(`${variant}-${viewport.name}`, {
        body: await page.screenshot(),
        contentType: 'image/png',
      });
    });
  }
}

// contract-test: direct surface=gui.web assertions=focus-modes.banner-placement
test('the incognito pill keeps its own position', async ({ page }) => {
  await openPreview(page, 'incognitoPill', 720);
  const pill = page.getByTestId('incognito-pill');
  await expect(pill).toBeVisible();
  const top = await pill.evaluate((element) => getComputedStyle(element).top);
  expect(top).toBe('-20px');
});
