// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helper exports. */
export {};
import type { Page } from '@playwright/test';
const { expect, test } = require('../helpers/cookie-audit');

// contract-test: direct surface=gui.web assertions=workflows.actions.skill-contract
test('fitness test output shows an embed and readable fields for each result', async ({ page }: { page: Page }) => {
  await page.goto('/dev/preview/workflows/WorkflowValueView?theme=light&background=%23dbeafe&width=700&chrome=0', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
  await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);
  const carousel = page.getByTestId('workflow-result-carousel');
  await expect(carousel).toBeVisible();
  await expect(carousel.getByTestId('fitness-result-preview')).toBeVisible();
  await expect(carousel).toContainText('Yoga Flow');
  await expect(carousel).toContainText('Studio One');
  await expect(carousel.getByTestId('workflow-result-position')).toHaveText('1 of 2');
  const next = carousel.getByTestId('workflow-result-next');
  await next.focus();
  await expect(next).toBeFocused();
  await next.click();
  await expect(carousel).toContainText('Strength Circuit');
  await expect(carousel).toContainText('Studio Two');
  await expect(carousel.getByTestId('workflow-result-position')).toHaveText('2 of 2');
  await expect(next).toBeDisabled();
  await carousel.getByTestId('workflow-result-previous').click();
  await expect(carousel).toContainText('Yoga Flow');
  await test.info().attach('fitness-workflow-output', { body: await page.screenshot(), contentType: 'image/png' });
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
