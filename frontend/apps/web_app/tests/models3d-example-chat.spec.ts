/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public-page coverage for the Printables Models3D example chat.
 *
 * This spec intentionally avoids authenticated flows so the public example can
 * be verified independently of test-account OTP availability.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { closeFullscreen, openFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');

test.describe('Example chat: Models3D Printables', () => {
	test('renders messages, result embeds, fullscreen, and reloads', async ({ page }: { page: any }) => {
		test.setTimeout(90000);

		await page.goto('/example/printable-benchy-phone-stand-models', {
			waitUntil: 'domcontentloaded'
		});
		await expect(page).toHaveURL(/#chat-id=example-printable-benchy-phone-stand/, { timeout: 15000 });

		await expect(page.getByTestId('user-message-content').filter({
			hasText: 'Find 3D-printable Benchy and phone stand models on Printables'
		})).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'The 3DBenchy Collection' })).toBeVisible({ timeout: 15000 });

		const parentSearchEmbeds = page.locator(
			'[data-testid="embed-preview"][data-app-id="models3d"][data-skill-id="search"][data-status="finished"]'
		);
		await expect(parentSearchEmbeds.first()).toBeVisible({ timeout: 15000 });
		expect(
			await parentSearchEmbeds.count(),
			'Models3D example should render both Benchy and phone stand parent search embeds'
		).toBeGreaterThanOrEqual(2);

		const childResultCards = page.getByTestId('models3d-result-card');
		await expect(childResultCards.first()).toBeVisible({ timeout: 15000 });
		expect(
			await childResultCards.count(),
			'Models3D example should render static child model result cards in chat'
		).toBeGreaterThanOrEqual(5);

		const fullscreenOverlay = await openFullscreen(page, parentSearchEmbeds.first());
		const fullscreenResults = await verifySearchGrid(fullscreenOverlay, 5, 30000);
		await expect(fullscreenResults.first().getByTestId('models3d-result-card')).toBeVisible({ timeout: 15000 });

		const cta = fullscreenResults.first().getByTestId('models3d-open-provider-cta');
		await expect(cta).toBeVisible({ timeout: 15000 });
		await expect(cta).toContainText('Open on Printables');
		expect(await cta.getAttribute('href')).toMatch(/^https:\/\/(www\.)?printables\.com\//);

		await closeFullscreen(page, fullscreenOverlay);
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page).toHaveURL(/#chat-id=example-printable-benchy-phone-stand/, { timeout: 15000 });
		await expect(parentSearchEmbeds.first()).toBeVisible({ timeout: 15000 });
	});
});
