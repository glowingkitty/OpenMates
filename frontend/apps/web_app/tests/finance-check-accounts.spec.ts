/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Web coverage for Finance / Check accounts embeds.
 * Uses the deployed dev preview route with synthetic redacted fixtures so the UI
 * contract is deterministic and never depends on live connected-account data.
 * Product contract: docs/specs/finance-check-accounts-v1/spec.yml
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');

async function waitForFinancePreview(page: any) {
  const response = await page.goto('/dev/preview/embeds/finance', { waitUntil: 'networkidle' });
  expect(response?.status()).toBe(200);
  await expect(page.getByTestId('unknown-app')).not.toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('app-title')).toContainText('finance', { timeout: 15_000 });
  await expect(async () => {
    expect(await page.getByTestId('section-loading').count()).toBe(0);
  }).toPass({ timeout: 20_000 });
  expect(await page.getByTestId('section-error').count()).toBe(0);
}

test.describe('Finance Check accounts web embeds', () => {
  test('renders aggregate-only preview and filtered transaction fullscreen', async ({ page }: { page: any }) => {
    test.setTimeout(120_000);

    await waitForFinancePreview(page);

    const preview = page.getByTestId('finance-check-accounts-preview').first();
    await expect(preview).toBeVisible({ timeout: 15_000 });
    await expect(preview).toContainText('Net cash flow');
    await expect(preview).not.toContainText('Current total value');
    await expect(preview.getByTestId('finance-net-cash-flow')).toBeVisible();
    await expect(preview.getByTestId('finance-income-expense-chart')).toBeVisible();
    await expect(preview.getByTestId('finance-income-expense-chart')).toHaveAttribute('data-chart-type', 'line');
    await expect(preview.getByTestId('finance-income-line')).toBeVisible();
    await expect(preview.getByTestId('finance-expense-line')).toBeVisible();
    await expect(preview.getByTestId('finance-provider-pill')).toContainText('Revolut Business');
    await expect(preview.getByTestId('finance-transaction-row')).toHaveCount(0);
    await expect(preview).not.toContainText('[MERCHANT_');
    await expect(page.locator('[data-skill-icon="finance"]').first()).toBeVisible();
    await expect(page.locator('body')).not.toContainText('placeholder CSV');
    await expect(page.locator('body')).not.toContainText('CSV statement');
    await expect(page.locator('body')).not.toContainText('sandbox');

    const section = page.getByTestId('skill-section').filter({ has: preview }).first();
    const fullscreenClip = section.getByTestId('fs-clip').first();
    await expect(fullscreenClip.getByTestId('finance-check-accounts-fullscreen')).toBeVisible({ timeout: 15_000 });
    await expect(fullscreenClip.getByTestId('finance-fullscreen-net-cash-flow')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-net-cash-flow-helper')).toContainText('Income - expenses');
    await expect(fullscreenClip.getByTestId('finance-fullscreen-cash-balance')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-summary-grid')).not.toContainText('Total value');
    await expect(fullscreenClip.getByTestId('finance-fullscreen-chart')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-fullscreen-chart').locator('[data-chart-type="line"]')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-fullscreen-income-line')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-fullscreen-expense-line')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filters')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-check-accounts-fullscreen')).toContainText('Revolut Business');

    const chartTop = await fullscreenClip.getByTestId('finance-fullscreen-chart').boundingBox();
    const summaryTop = await fullscreenClip.getByTestId('finance-summary-grid').boundingBox();
    expect(summaryTop?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(chartTop?.y ?? 0);

    await expect(fullscreenClip.getByTestId('finance-filter-account')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-source')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-start-date')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-end-date')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-category')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-direction')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-state')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-placeholder')).toBeVisible();
    await expect(fullscreenClip.getByTestId('finance-filter-source')).toContainText('Revolut Business');

    await expect(fullscreenClip.getByTestId('finance-transaction-row')).toHaveCount(5);
    await expect(fullscreenClip.getByTestId('finance-transaction-list')).toContainText('[MERCHANT_SOFTWARE_001]');
    await expect(fullscreenClip.getByTestId('finance-transaction-list')).not.toContainText('Acme Software Ltd');

    await section.getByRole('button', { name: 'ownerPiiRevealed' }).click();
    await expect(fullscreenClip.getByTestId('finance-transaction-list')).toContainText('Acme Software Ltd');
    await expect(fullscreenClip.getByTestId('finance-transaction-list')).toContainText('Northstar Client');

    await fullscreenClip.getByTestId('finance-filter-direction').selectOption('expense');
    await expect(fullscreenClip.getByTestId('finance-transaction-row')).toHaveCount(3);
    await expect(fullscreenClip.getByTestId('finance-transaction-list')).not.toContainText('[PAYER_REVENUE_001]');
  });
});
