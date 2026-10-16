import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

async function openPreview(page: import('@playwright/test').Page, width: number, variant?: string) {
  await page.setViewportSize({ width, height: 720 });
  const query = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(width), chrome: '0' });
  if (variant) query.set('variant', variant);
  await page.goto(`/dev/preview/settings/ProjectFocusPolicySelector?${query}`, { waitUntil: 'domcontentloaded' });
  return waitForComponentPreview(page);
}

// contract-test: direct surface=gui.web assertions=projects.focus.auto-selection-setting
test('policy selector exposes three options and delivers each selection', async ({ page }) => {
  await openPreview(page, 720);
  const select = page.getByRole('combobox', { name: 'Inferred Project focus' });
  await expect(select).toBeVisible();
  await expect(select).toHaveValue('delayed');
  await expect(select.locator('option')).toHaveCount(3);
  await select.focus();
  await expect(select).toBeFocused();
  for (const policy of ['immediate', 'approval', 'delayed']) {
    await select.selectOption(policy);
    await expect(select).toHaveValue(policy);
    await expect.poll(() => page.locator('body').getAttribute('data-project-focus-policy-changed')).toBe(policy);
  }
});

// contract-test: direct surface=gui.web assertions=projects.focus.auto-selection-setting
test('saved policy variants render their selected value', async ({ page }) => {
  for (const policy of ['immediate', 'approval']) {
    await openPreview(page, 720, policy);
    await expect(page.getByTestId('project-settings-focus-activation-policy')).toHaveValue(policy);
  }
});

// contract-test: direct surface=gui.web assertions=projects.focus.auto-selection-setting
test('disabled policy stays inactive and fits a phone viewport', async ({ page }) => {
  const canvas = await openPreview(page, 390, 'disabled');
  const select = page.getByTestId('project-settings-focus-activation-policy');
  await expect(select).toBeVisible();
  await expect(select).toBeDisabled();
  await expect(select).toHaveValue('delayed');
  const bounds = await select.boundingBox();
  const canvasBounds = await canvas.boundingBox();
  expect(bounds && canvasBounds).toBeTruthy();
  expect(bounds!.x).toBeGreaterThanOrEqual(canvasBounds!.x - 1);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(canvasBounds!.x + canvasBounds!.width + 1);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(await page.locator('body').getAttribute('data-project-focus-policy-changed')).toBeNull();
});
