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

const SHARED_CHAT_WITH_LEGACY_SEARCH_PARENTS = 'https://app.dev.openmates.org/s/J0XO58G8#n4oYu6';

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
});
