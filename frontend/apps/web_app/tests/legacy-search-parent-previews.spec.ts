/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/legacy-search-parent-previews.spec.ts
 *
 * Guards legacy composite search parent embeds that have child embed IDs but no
 * lightweight parent preview metadata. They must not claim zero results before
 * fullscreen loads children and backfills metadata.
 *
 * Architecture: docs/specs/scalable-chat-embed-loading/spec.yml
 */
export {};

const { test, expect } = require('./console-monitor');
const { closeFullscreen, openFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');

const SHARED_CHAT_WITH_LEGACY_SEARCH_PARENTS = 'https://app.dev.openmates.org/s/J0XO58G8#n4oYu6';
const SHARED_CHAT_WITH_RELOAD_REGRESSION = 'https://app.dev.openmates.org/s/pznF7EHJ#s28GVG';

test.describe('Legacy search parent previews', () => {
	test('do not claim zero results before fullscreen backfill', async ({ page }: { page: any }) => {
		const response = await page.goto(SHARED_CHAT_WITH_LEGACY_SEARCH_PARENTS, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		const webPreview = page
			.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')
			.first();
		await expect(webPreview).toBeVisible({ timeout: 30_000 });
		await expect(webPreview.getByTestId('search-no-results-message')).toHaveCount(0);
		await expect(webPreview.getByTestId('search-preview-metadata-missing-message')).toBeVisible();

		const imagePreview = page
			.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="search"]')
			.first();
		await expect(imagePreview).toBeVisible({ timeout: 30_000 });
		await expect(imagePreview.getByTestId('images-search-preview-metadata-missing-message')).toBeVisible();
	});

	test('shared fullscreen backfill survives page reload from local cache', async ({ page }: { page: any }) => {
		const response = await page.goto(SHARED_CHAT_WITH_RELOAD_REGRESSION, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		const webPreview = page
			.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')
			.first();
		await expect(webPreview).toBeVisible({ timeout: 30_000 });
		await expect(webPreview.getByTestId('search-preview-metadata-missing-message')).toBeVisible();

		const fullscreen = await openFullscreen(page, webPreview);
		await verifySearchGrid(fullscreen, 1, 60_000);
		await closeFullscreen(page, fullscreen);

		await expect(webPreview.getByTestId('search-preview-metadata-missing-message')).toHaveCount(0, { timeout: 10_000 });
		await page.reload({ waitUntil: 'networkidle' });

		const reloadedWebPreview = page
			.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')
			.first();
		await expect(reloadedWebPreview).toBeVisible({ timeout: 30_000 });
		await expect(reloadedWebPreview.getByTestId('search-preview-metadata-missing-message')).toHaveCount(0, { timeout: 10_000 });
		await expect(reloadedWebPreview.getByTestId('search-no-results-message')).toHaveCount(0);
	});
});
