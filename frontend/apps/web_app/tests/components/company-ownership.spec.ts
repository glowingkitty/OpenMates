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

async function fitsVertically(summary: Locator) {
  // The preview content must fit its card: no line under the header or cut off at the bottom.
  const overflow = await summary.evaluate((el) => el.getBoundingClientRect().height - (el.parentElement?.clientHeight ?? 0));
  expect(overflow).toBeLessThanOrEqual(1);
}

// contract-test: supporting surface=gui.web assertions=ownership.results
test('company ownership preview shows subject, counts, top owners with shares and terminal states', async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const root = page.locator('.unified-embed-preview').first();
  await open(page, 'BusinessCompanyOwnershipEmbedPreview');
  await fits(page, root);
  await expect(root).toContainText('Example Robotics GmbH');
  await expect(root.getByTestId('company-ownership-preview-facts')).toContainText('DE');
  await expect(root.getByTestId('company-ownership-preview-facts')).toContainText('GmbH');
  await expect(root.getByTestId('company-ownership-preview-counts')).toContainText('Owners: 3');
  await expect(root.getByTestId('company-ownership-preview-counts')).toContainText('Officers: 2');
  const owners = root.getByTestId('company-ownership-preview-owners').locator('li');
  // Two records: the "+1 more" line takes the third owner's row.
  await expect(owners).toHaveCount(2);
  await fitsVertically(root.getByTestId('company-ownership-preview'));
  await expect(owners.first()).toContainText('Jane Example');
  await expect(owners.first()).toContainText('42%');
  await root.screenshot({ path: testInfo.outputPath('company-ownership-preview-phone-light.png'), animations: 'disabled' });
  await open(page, 'BusinessCompanyOwnershipEmbedPreview', 'uk');
  await expect(root.getByTestId('company-ownership-preview-owners')).toContainText('50-75%');
  await open(page, 'BusinessCompanyOwnershipEmbedPreview', 'person');
  await expect(root.getByTestId('company-ownership-preview-counts')).toContainText('Holdings: 2');
  for (const variant of ['processing', 'cancelled', 'error', 'empty', 'ambiguous', 'coverage_gap', 'long']) {
    await open(page, 'BusinessCompanyOwnershipEmbedPreview', variant);
    await fits(page, root);
    if (!['processing', 'cancelled', 'error'].includes(variant)) await fitsVertically(root.getByTestId('company-ownership-preview'));
    if (variant === 'error') await expect(root.getByTestId('company-ownership-preview-error')).toBeVisible();
    if (variant === 'empty') await expect(root.getByTestId('company-ownership-preview-empty')).toBeVisible();
    if (variant === 'ambiguous') await expect(root.getByTestId('company-ownership-preview-empty')).toContainText(/several/i);
    if (variant === 'cancelled') await expect(root).toContainText(/cancelled/i);
  }
  await open(page, 'BusinessCompanyOwnershipEmbedPreview', '', 1280, 'dark');
  await fits(page, root);
  await root.screenshot({ path: testInfo.outputPath('company-ownership-preview-laptop-dark.png'), animations: 'disabled' });
});

// contract-test: supporting surface=gui.web assertions=ownership.results
test('company ownership fullscreen shows owners, holdings, officers, candidates and limitation', async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const root = page.getByTestId('company-ownership-fullscreen');
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen');
  await fits(page, root);
  const records = page.getByTestId('company-ownership-record');
  await expect(records).toHaveCount(2);
  await expect(records.first()).toContainText('Example Robotics GmbH');
  await expect(records.first().getByTestId('company-ownership-owner')).toHaveCount(3);
  await expect(records.first().getByTestId('company-ownership-owner-share').first()).toContainText('42%');
  await expect(records.first().getByTestId('company-ownership-officer')).toHaveCount(2);
  await expect(records.first().getByTestId('company-ownership-source-link')).toHaveAttribute('href', 'https://example.org/register/de/hrb-123456');
  await expect(records.nth(1).getByTestId('company-ownership-owner-share').first()).toContainText('50-75%');
  await expect(page.getByTestId('company-ownership-limitation')).toBeVisible();
  await expect(root).not.toContainText('undefined');
  await root.screenshot({ path: testInfo.outputPath('company-ownership-fullscreen-phone-light.png'), animations: 'disabled' });
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'person');
  await expect(page.getByTestId('company-ownership-holding')).toHaveCount(2);
  await expect(page.getByTestId('company-ownership-ended')).toHaveCount(1);
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'ambiguous');
  await expect(page.getByTestId('company-ownership-candidate')).toHaveCount(3);
  await expect(page.getByTestId('company-ownership-candidate').first()).toContainText('123456789');
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'coverage_gap');
  await expect(page.getByTestId('company-ownership-lookup-error')).toContainText('not covered');
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'mixed');
  await expect(page.getByTestId('company-ownership-warnings')).toContainText('not looked up');
  await expect(page.getByTestId('company-ownership-record')).toHaveCount(2);
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', '', 1280, 'dark');
  await fits(page, root);
  await root.screenshot({ path: testInfo.outputPath('company-ownership-fullscreen-laptop-dark.png'), animations: 'disabled' });
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'sparse');
  await expect(page.getByTestId('company-ownership-record')).not.toContainText('undefined');
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'empty');
  await expect(page.getByTestId('company-ownership-empty')).toBeVisible();
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'error');
  await expect(page.getByTestId('company-ownership-error')).toBeVisible();
  await open(page, 'BusinessCompanyOwnershipEmbedFullscreen', 'long');
  await fits(page, page.getByTestId('company-ownership-record'));
});
