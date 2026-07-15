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
	async function expectModels3dExampleVisible(page: any) {
		await expect(page).toHaveURL(/#chat-id=example-printable-benchy-phone-stand/, { timeout: 15000 });

		await expect(page.getByTestId('user-message-content').filter({
			hasText: 'Find 3D-printable Benchy and phone stand models on Printables'
		})).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'The 3DBenchy Collection' })).toBeVisible({ timeout: 15000 });
	}

	async function expectModels3dVisualContract(card: any) {
		const iconCircle = card.getByTestId('app-icon-circle');
		await expect(iconCircle).toBeVisible({ timeout: 15000 });
		expect(await iconCircle.evaluate((el: HTMLElement) => getComputedStyle(el).backgroundImage)).toContain('linear-gradient');

		const bodyBox = await card.getByTestId('models3d-result-card-body').boundingBox();
		const imageBox = await card.getByTestId('models3d-result-card-image').boundingBox();
		expect(bodyBox, 'Models3D result card body should be measurable').not.toBeNull();
		expect(imageBox, 'Models3D result card image should be measurable').not.toBeNull();
		expect(imageBox!.x, 'Models3D result preview image must render to the right of text').toBeGreaterThan(bodyBox!.x);
	}

	async function openResultFullscreen(page: any, resultCard: any) {
		const cardBody = resultCard.getByTestId('models3d-result-card-body');
		await expect(async () => {
			await cardBody.click();
			await expect(page.getByTestId('models3d-result-fullscreen')).toBeVisible({ timeout: 5000 });
		}).toPass({ timeout: 30000 });
	}

	test('renders messages, result embeds, fullscreen, and reloads', async ({ page }: { page: any }) => {
		test.setTimeout(90000);

		await page.goto('/example/printable-benchy-phone-stand-models', {
			waitUntil: 'domcontentloaded'
		});
		await expectModels3dExampleVisible(page);

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
		await expect(childResultCards.first().getByTestId('models3d-open-provider-cta')).toHaveCount(0);
		await expectModels3dVisualContract(childResultCards.first().locator('xpath=ancestor::*[@data-testid="embed-preview"][1]'));

		const fullscreenOverlay = await openFullscreen(page, parentSearchEmbeds.first());
		const fullscreenResults = await verifySearchGrid(fullscreenOverlay, 5, 30000);
		const firstFullscreenCard = fullscreenResults.first();
		await expect(firstFullscreenCard.getByTestId('models3d-result-card')).toBeVisible({ timeout: 15000 });
		await expect(firstFullscreenCard.getByTestId('models3d-open-provider-cta')).toHaveCount(0);
		await expectModels3dVisualContract(firstFullscreenCard);

		await openResultFullscreen(page, firstFullscreenCard);
		const resultFullscreen = page.getByTestId('models3d-result-fullscreen');
		await expect(resultFullscreen).toBeVisible({ timeout: 15000 });
		const cta = page.getByTestId('models3d-open-provider-cta');
		await expect(cta).toBeVisible({ timeout: 15000 });
		await expect(cta).toContainText('Open on Printables');
		expect(await cta.getAttribute('href')).toMatch(/^https:\/\/(www\.)?printables\.com\//);

		await closeFullscreen(page, resultFullscreen.locator('xpath=ancestor::*[@data-testid="embed-fullscreen-overlay"][1]'));
		await closeFullscreen(page, fullscreenOverlay);
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page).toHaveURL(/#chat-id=example-printable-benchy-phone-stand/, { timeout: 15000 });
		await expect(parentSearchEmbeds.first()).toBeVisible({ timeout: 15000 });
	});

	test('keeps the static example chat open when logout cleanup runs', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto('/example/printable-benchy-phone-stand-models', {
			waitUntil: 'domcontentloaded'
		});
		await expectModels3dExampleVisible(page);

		await page.evaluate(() => {
			window.dispatchEvent(new CustomEvent('userLoggingOut'));
		});

		await expectModels3dExampleVisible(page);
		await expect(page.getByTestId('header-login-signup-btn')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('[data-testid="embed-preview"][data-app-id="models3d"][data-skill-id="search"][data-status="finished"]').first()).toBeVisible({ timeout: 15000 });
		await expect(page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]').first()).not.toBeVisible({ timeout: 5000 });
	});
});
