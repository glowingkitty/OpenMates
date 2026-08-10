/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public example-chat coverage for the real CLI-created Business financials chat.
 *
 * Product contract: docs/specs/business-company-financials/spec.yml
 * Source chat: 74b72f13-4df1-4409-83e7-672b4bd403ec.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { closeFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');

async function openPublicExample(page: any) {
	const response = await page.goto('/example/vital-farms-sec-financials', {
		waitUntil: 'domcontentloaded'
	});
	expect(response?.status()).toBe(200);
	await expect(page).toHaveURL(/#chat-id=example-vital-farms-sec-financials$/, { timeout: 15_000 });
	await expect(page.getByTestId('message-assistant').first()).toBeVisible({ timeout: 30_000 });
}

test.describe('Business company financials public example chat', () => {
	test('renders the real CLI-created Vital Farms SEC financials example', async ({ page }) => {
		test.setTimeout(120_000);

		await openPublicExample(page);

		await expect(page.getByTestId('user-message-content').filter({ hasText: 'For ticker VITL only' })).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Vital Farms, Inc.' })).toBeVisible({ timeout: 15_000 });
		await expect(page.locator('body')).not.toContainText('vault_key_id');
		await expect(page.locator('body')).not.toContainText('user_id');
		await expect(page.locator('body')).not.toContainText('"type": "app_skill_use"');

		const parent = page.locator('[data-testid="embed-preview"][data-app-id="business"][data-skill-id="company_financials"][data-status="finished"]').first();
		await expect(parent).toBeVisible({ timeout: 30_000 });
		await expect(parent.getByTestId('business-financials-preview')).toBeVisible({ timeout: 15_000 });
		await expect(parent).toContainText(/VITL|SEC EDGAR|result/i);

		const existingFullscreen = page.getByTestId('embed-fullscreen-overlay').first();
		if (await existingFullscreen.isVisible({ timeout: 1000 }).catch(() => false)) {
			await closeFullscreen(page, existingFullscreen);
		}

		await parent.click();
		const fallback = page.locator('.embed-fullscreen-fallback').filter({ hasText: 'Fullscreen view not available for embed type: app-skill-use' }).first();
		if (await fallback.isVisible({ timeout: 15_000 }).catch(() => false)) {
			const debug = await page.getByTestId('embed-fullscreen-debug').first().textContent().catch(() => null);
			throw new Error(`Business financials fullscreen used app-skill fallback. Debug: ${debug ?? 'missing'}`);
		}
		const fullscreen = page.getByTestId('embed-fullscreen-container').filter({ has: page.getByTestId('search-template-grid') }).first();
		await expect(fullscreen).toBeVisible({ timeout: 15_000 });
		const resultCards = await verifySearchGrid(fullscreen, 1, 30_000);
		const resultCard = resultCards.first();
		await expect(resultCard.getByTestId('business-financial-result-preview')).toBeVisible({ timeout: 15_000 });
		await expect(resultCard).toContainText(/Vital Farms|VITL|FY 2025|Revenue|Net income/i);

		await resultCard.click();
		const childFullscreen = page.getByTestId('business-financial-result-fullscreen');
		await expect(childFullscreen).toBeVisible({ timeout: 15_000 });
		await expect(childFullscreen).toContainText(/Vital Farms|SEC filing|Revenue|Net income|Operating cash flow/i);

		const sourceLink = page.getByTestId('business-open-sec-filing-inline');
		await expect(sourceLink).toBeVisible({ timeout: 15_000 });
		expect((await sourceLink.getAttribute('href')) || '').toMatch(/^https:\/\/www\.sec\.gov\//);
	});
});
