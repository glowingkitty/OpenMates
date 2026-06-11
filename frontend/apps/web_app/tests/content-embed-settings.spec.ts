/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Content embed settings E2E coverage.
 *
 * Verifies the generated app-store Content catalog renders durable embed types,
 * opens the content detail route, and links to a public example chat whose
 * rendered-video Remotion embed can display a public video preview.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openSettingsPanel(page: any, logCheckpoint: (message: string) => void): Promise<void> {
	const profileBtn = page.getByTestId('profile-picture').first();
	await expect(profileBtn).toBeVisible({ timeout: 10000 });
	await profileBtn.click();
	logCheckpoint('Opened settings panel.');
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 10000 });
}

async function navigateToApps(page: any, logCheckpoint: (message: string) => void): Promise<void> {
	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	const appStoreLink = settingsMenu.getByRole('menuitem', { name: /^Apps$/i }).first();
	await expect(appStoreLink).toBeVisible({ timeout: 5000 });
	await appStoreLink.click();
	logCheckpoint('Opened Apps settings.');
	await page.waitForTimeout(800);
}

test.describe('Content embed app-store settings', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('Videos app shows Rendered video content and opens a public rendered-video example', async ({ page }) => {
		const logCheckpoint = createSignupLogger('CONTENT_EMBED_SETTINGS');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'content-embed-settings',
		});

		await archiveExistingScreenshots(logCheckpoint);
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await openSettingsPanel(page, logCheckpoint);
		await navigateToApps(page, logCheckpoint);
		await takeStepScreenshot(page, 'apps-opened');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		const videosCard = settingsMenu.getByTestId('app-store-card').filter({ hasText: /videos/i }).first();
		await expect(videosCard).toBeVisible({ timeout: 10000 });
		await videosCard.click();
		logCheckpoint('Opened Videos app detail page.');

		const renderedVideoCard = settingsMenu.getByTestId('content-embed-card-videos.rendered_video');
		await expect(renderedVideoCard).toBeVisible({ timeout: 10000 });
		await renderedVideoCard.click();
		logCheckpoint('Opened Rendered video content detail page.');

		const contentDetails = settingsMenu.getByTestId('content-embed-details');
		await expect(contentDetails).toBeVisible({ timeout: 10000 });
		await expect(contentDetails).toContainText('Rendered video');
		await expect(settingsMenu.getByTestId('content-embed-example-chats')).toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, 'rendered-video-content-detail');

		const exampleCard = settingsMenu
			.getByTestId('app-store-example-chat-card')
			.filter({ hasText: /Product Teaser Remotion Video/i })
			.first();
		await expect(exampleCard).toBeVisible({ timeout: 10000 });
		await exampleCard.click();
		logCheckpoint('Opened rendered-video example chat.');

		await page.keyboard.press('Escape');
		await page.waitForTimeout(1200);
		await expect(page.getByTestId('video-create-preview').first()).toBeVisible({ timeout: 15000 });
		const previewVideo = page.getByTestId('video-create-preview').locator('video').first();
		await expect(previewVideo).toBeVisible({ timeout: 10000 });
		await expect(previewVideo).toHaveAttribute('src', /\/store-examples\/video-generate-1\.mp4$/);

		await assertNoMissingTranslations(page);
		await takeStepScreenshot(page, 'rendered-video-example-opened');
	});
});
