/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Web coverage for Business / Get company financials embeds.
 * Verifies parent app-skill preview registration, fullscreen child grids,
 * SEC financial child fullscreen rendering, source links, and mobile layout.
 * Product contract: docs/specs/business-company-financials/spec.yml
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { verifySearchGrid } = require('./helpers/embed-test-helpers');

async function openComponentPreview(page: any, componentPath: string) {
	const response = await page.goto(`/dev/preview/${componentPath}`, { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	await expect(page.getByTestId('breadcrumb-name')).toContainText(componentPath.split('/').pop() || '', { timeout: 15_000 });
	await expect(page.getByTestId('preview-status-bar')).toContainText('preview.ts loaded', { timeout: 15_000 });
	await expect(page.getByTestId('render-error')).not.toBeVisible({ timeout: 5_000 });
}

test.describe('Business company financials web embeds', () => {
	test('renders parent preview, child grid, source fullscreen, and mobile layout', async ({ page }) => {
		test.setTimeout(120_000);

		await openComponentPreview(page, 'embeds/business/BusinessCompanyFinancialsEmbedPreview');

		const parent = page.locator('[data-testid="embed-preview"][data-app-id="business"][data-skill-id="company_financials"][data-status="finished"]').first();
		await expect(parent).toBeVisible({ timeout: 15_000 });
		await expect(parent.getByTestId('business-financials-preview')).toBeVisible({ timeout: 15_000 });
		await expect(parent).toContainText(/CALM|MU|SEC EDGAR|results/i);

		await openComponentPreview(page, 'embeds/business/BusinessCompanyFinancialsEmbedFullscreen');
		const fullscreen = page.getByTestId('embed-fullscreen-overlay').first();
		await expect(fullscreen).toBeVisible({ timeout: 15_000 });
		const resultCards = await verifySearchGrid(fullscreen, 2, 15_000);
		const firstResultCard = resultCards.first();
		await expect(firstResultCard.getByTestId('business-financial-result-preview')).toBeVisible({ timeout: 15_000 });
		await expect(firstResultCard).toContainText(/Revenue|Net income|CALM|FY 2025/i);

		await page.getByRole('button', { name: 'quarterly' }).click();
		const singleCompanyCards = await verifySearchGrid(fullscreen, 1, 15_000);
		const singleCompanyCard = singleCompanyCards.first();
		await expect(singleCompanyCard.getByTestId('business-financial-result-preview')).toBeVisible({ timeout: 15_000 });
		await expect(singleCompanyCard).toContainText(/VITL|Q1 2026|Revenue|Net income/i);
		await expect(singleCompanyCard).toHaveAttribute('data-status', 'finished', { timeout: 15_000 });

		await singleCompanyCard.click();
		await expect(page.getByTestId('business-financial-result-fullscreen')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('business-financial-result-fullscreen')).toContainText(/SEC filing|Revenue|Net income|Source/i);

		const sourceLink = page.getByTestId('business-open-sec-filing-inline');
		await expect(sourceLink).toBeVisible({ timeout: 15_000 });
		const href = await sourceLink.getAttribute('href');
		expect(href || '').toMatch(/^https:\/\/www\.sec\.gov\//);

		await page.setViewportSize({ width: 390, height: 760 });
		await openComponentPreview(page, 'embeds/business/BusinessCompanyFinancialsEmbedPreview');
		await expect(page.getByTestId('business-financials-preview').first()).toBeVisible({ timeout: 15_000 });
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
		expect(overflow, 'Business financial embeds should not create horizontal overflow on mobile').toBeLessThan(8);
	});
});
