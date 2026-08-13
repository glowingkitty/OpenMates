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
const SHARED_CHAT_WITH_IMAGE_CAROUSEL = 'https://app.dev.openmates.org/s/jwSihZe3#YegicRhmrtLe8jSyUtM37y';

async function expectWebPreviewDoesNotClaimZeroResults(webPreview: any) {
	await expect(webPreview.getByTestId('search-no-results-message')).toHaveCount(0);
	await expect(
		webPreview
			.locator('[data-testid="search-preview-metadata-missing-message"], [data-testid="search-preview-remaining-count"]')
			.first()
	).toBeVisible();
}

test.describe('Legacy search parent previews', () => {
	// contract-test: direct surface=gui.web assertions=web-search.no-results.explicit,web-search.surface-parity
	test('do not claim zero results before fullscreen backfill', async ({ page }: { page: any }) => {
		const response = await page.goto(SHARED_CHAT_WITH_LEGACY_SEARCH_PARENTS, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		const webPreview = page
			.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')
			.first();
		await expect(webPreview).toBeVisible({ timeout: 30_000 });
		await expectWebPreviewDoesNotClaimZeroResults(webPreview);

		const imagePreview = page
			.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="search"]')
			.first();
		await expect(imagePreview).toBeVisible({ timeout: 30_000 });
		await expect(imagePreview.getByTestId('images-search-preview-metadata-missing-message')).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=web-search.no-results.explicit,web-search.surface-parity
	test('shared fullscreen backfill survives page reload from local cache', async ({ page }: { page: any }) => {
		const response = await page.goto(SHARED_CHAT_WITH_RELOAD_REGRESSION, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		const webPreview = page
			.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')
			.first();
		await expect(webPreview).toBeVisible({ timeout: 30_000 });
		await expectWebPreviewDoesNotClaimZeroResults(webPreview);

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

	// contract-test: direct surface=gui.web assertions=web-search.surface-parity,chats.surface.semantic-parity
	test('shared image search keeps its six referenced images in a stable large carousel after reload', async ({ page }: { page: any }) => {
		test.setTimeout(180_000);
		const openAndAssertCarousel = async () => {
			const assistantMessage = page
				.getByTestId('message-assistant')
				.filter({ hasText: 'Here are some incredible captures' })
				.last();
			await expect(assistantMessage).toBeVisible({ timeout: 45_000 });

			const searchParents = assistantMessage.locator(
				'[data-testid="embed-preview"][data-app-id="images"][data-skill-id="search"]'
			);
			await expect(searchParents).toHaveCount(1, { timeout: 30_000 });
			await expect(searchParents.first().getByTestId('images-search-preview-metadata-missing-message')).toHaveCount(0);

			const carousel = assistantMessage.getByTestId('embed-preview-large').first();
			await expect(carousel).toBeVisible({ timeout: 45_000 });
			await expect(carousel.getByRole('tab')).toHaveCount(6);

			const firstImage = carousel.getByTestId('image-result-preview-image');
			await expect(firstImage).toBeVisible({ timeout: 30_000 });
			const before = await carousel.boundingBox();
			expect(before).not.toBeNull();
			expect(before.width).toBeGreaterThan(700);
			expect(before.height).toBeLessThan(500);

			await carousel.getByRole('button', { name: 'Next' }).click();
			await expect(carousel.getByRole('tab', { name: 'Go to slide 2 of 6' })).toHaveAttribute('aria-selected', 'true');
			await expect(assistantMessage.getByTestId('image-result-preview-image').nth(1)).toBeVisible({ timeout: 30_000 });

			const after = await carousel.boundingBox();
			expect(after).not.toBeNull();
			expect(Math.abs(after.width - before.width)).toBeLessThanOrEqual(2);
			expect(Math.abs(after.height - before.height)).toBeLessThanOrEqual(40);
		};

		const response = await page.goto(SHARED_CHAT_WITH_IMAGE_CAROUSEL, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);
		await openAndAssertCarousel();

		await page.reload({ waitUntil: 'networkidle' });
		await openAndAssertCarousel();
	});
});
