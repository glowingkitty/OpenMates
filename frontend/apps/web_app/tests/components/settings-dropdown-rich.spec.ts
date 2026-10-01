// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helper exports. */
export {};
import type { Page } from '@playwright/test';
const { expect, test } = require('../helpers/cookie-audit');

async function openPreview(page: Page, variant?: string): Promise<void> {
  const query = new URLSearchParams({ theme: 'light', width: '390', chrome: '0' });
  if (variant) query.set('variant', variant);
  await page.goto(`/dev/preview/settings/elements/SettingsDropdown?${query}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
}

// contract-test: direct surface=gui.web assertions=workflows-ui.responsive-accessible-reachable
test('rich dropdown displays icons and supports keyboard selection and dismissal', async ({ page }: { page: Page }) => {
  await page.setViewportSize({ width: 390, height: 650 });
  await openPreview(page);
  const dropdown = page.getByRole('combobox', { name: 'Workflow check source' });
  await expect(dropdown).toContainText('Weather | Get forecast');
  await dropdown.focus();
  await dropdown.press('ArrowDown');
  await expect(dropdown).toHaveAttribute('aria-expanded', 'true');
  const listbox = page.getByRole('listbox', { name: 'Workflow check source' });
  await expect(listbox.getByRole('option')).toHaveCount(4);
  await expect(listbox.locator('.option-icon')).toHaveCount(4);
  await dropdown.press('End');
  await dropdown.press('Enter');
  await expect(dropdown).toContainText('Number');
  await expect(dropdown).toHaveAttribute('aria-expanded', 'false');
  await dropdown.press('Home');
  await dropdown.press('Escape');
  await expect(dropdown).toHaveAttribute('aria-expanded', 'false');
  await dropdown.click();
  await page.locator('body').click({ position: { x: 4, y: 4 } });
  await expect(dropdown).toHaveAttribute('aria-expanded', 'false');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

// contract-test: direct surface=gui.web assertions=workflows-ui.responsive-accessible-reachable
test('default dropdown remains a native select', async ({ page }: { page: Page }) => {
  await openPreview(page, 'native');
  const dropdown = page.getByTestId('preview-rich-dropdown');
  await expect(dropdown).toHaveCount(1);
  await expect(dropdown).toHaveJSProperty('tagName', 'SELECT');
});
