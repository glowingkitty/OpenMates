import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Locator, Page } from '@playwright/test';

async function open(page: Page, component: string, variant = '', width = 390, theme = 'light') {
  await page.setViewportSize({ width, height: width < 600 ? 844 : 950 });
  await page.goto(`/dev/preview/embeds/business/${component}?theme=${theme}&background=%23dbeafe&width=${width}&chrome=0${variant ? '&variant=' + variant : ''}`);
  await waitForComponentPreview(page);
}
async function fits(page: Page, element: Locator) {
  await expect(element).toBeVisible();
  const box = await element.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(-1);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
}

// contract-test: supporting surface=gui.web assertions=investors.results,investors.limits,investors.regions,investors.unavailable
test('investor preview shows query, regions, count, names and terminal states', async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const root = page.locator('.unified-embed-preview').first();
  await open(page, 'BusinessInvestorSearchEmbedPreview');
  await fits(page, root);
  await expect(root).toContainText('climate software seed');
  await expect(root.getByTestId('investor-preview-regions')).toContainText('DE · AT');
  await expect(root.getByTestId('investor-preview-count')).toContainText('Investors: 4');
  await expect(root.getByTestId('investor-preview-names')).toContainText('Alex Sample');
  await expect(root.getByTestId('investor-preview-names').locator('li')).toHaveCount(3);
  await root.screenshot({ path: testInfo.outputPath('investor-preview-phone-light.png'), animations: 'disabled' });
  for (const variant of ['processing', 'cancelled', 'error', 'empty', 'warning', 'long']) {
    await open(page, 'BusinessInvestorSearchEmbedPreview', variant);
    await fits(page, root);
    if (variant === 'error') await expect(root.getByTestId('investor-preview-error')).toContainText('not available');
    if (variant === 'empty') await expect(root.getByTestId('investor-preview-empty')).toBeVisible();
    if (variant === 'cancelled') await expect(root).toContainText(/cancelled/i);
  }
  await open(page, 'BusinessInvestorSearchEmbedPreview', '', 1280, 'dark');
  await fits(page, root);
  await root.screenshot({ path: testInfo.outputPath('investor-preview-laptop-dark.png'), animations: 'disabled' });
});

// contract-test: supporting surface=gui.web assertions=investors.results,investors.limits,investors.regions,investors.unavailable
test('investor fullscreen shows cards, ticket range, warnings, links and limitation', async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const root = page.getByTestId('investor-search-fullscreen');
  await open(page, 'BusinessInvestorSearchEmbedFullscreen', 'warning');
  await fits(page, root);
  const cards = page.getByTestId('investor-card');
  await expect(cards).toHaveCount(4);
  await expect(cards.first()).toContainText('Alex Sample');
  await expect(cards.first().getByTestId('investor-type')).toContainText('Angel');
  await expect(cards.first().getByTestId('investor-ticket')).toContainText('€25K – €100K');
  await expect(cards.first()).toContainText('Seed');
  await expect(cards.first().getByTestId('investor-profile-link')).toHaveAttribute('target', '_blank');
  await expect(cards.first().getByTestId('investor-profile-link')).toHaveAttribute('href', 'https://example.org/investors/alex-sample');
  await expect(page.getByTestId('investor-warnings')).toContainText('was not searched');
  await expect(page.getByTestId('investor-limitation')).toContainText('not a recommendation');
  await expect(root).not.toContainText('undefined');
  await cards.first().getByRole('button', { name: 'Show more' }).click();
  await expect(cards.first().getByRole('button', { name: 'Show less' })).toBeVisible();
  await root.screenshot({ path: testInfo.outputPath('investor-fullscreen-phone-light.png'), animations: 'disabled' });
  await open(page, 'BusinessInvestorSearchEmbedFullscreen', '', 1280, 'dark');
  await fits(page, root);
  await expect(page.getByTestId('investor-warnings')).toHaveCount(0);
  await root.screenshot({ path: testInfo.outputPath('investor-fullscreen-laptop-dark.png'), animations: 'disabled' });
  await open(page, 'BusinessInvestorSearchEmbedFullscreen', 'sparse');
  await expect(page.getByTestId('investor-card')).toHaveCount(1);
  await expect(page.getByTestId('investor-card')).not.toContainText('undefined');
  await open(page, 'BusinessInvestorSearchEmbedFullscreen', 'empty');
  await expect(page.getByTestId('investor-empty')).toBeVisible();
  await open(page, 'BusinessInvestorSearchEmbedFullscreen', 'error');
  await expect(page.getByTestId('investor-error')).toContainText('not available');
  await open(page, 'BusinessInvestorSearchEmbedFullscreen', 'long');
  await fits(page, page.getByTestId('investor-card'));
});
