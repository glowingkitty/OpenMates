/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Application embed live-preview E2E coverage.
 *
 * Runs against app.dev.openmates.org through scripts/run_tests.py. Do not run
 * locally; Playwright specs require deployed code and shared test accounts.
 */
export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const {
	waitForEmbedFinished,
	openFullscreen,
	closeFullscreen
} = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';

async function assertRecipeAppIsInteractive(previewPageOrFrame: any) {
	await expect(previewPageOrFrame.getByText('Recipe Manager')).toBeVisible({ timeout: 120_000 });
	await expect(previewPageOrFrame.getByTestId('recipe-count')).toContainText('3 recipes', { timeout: 30_000 });

	await previewPageOrFrame.getByTestId('recipe-filter').fill('berry');
	await expect(previewPageOrFrame.getByTestId('recipe-count')).toContainText('1 recipes', { timeout: 10_000 });
	await expect(previewPageOrFrame.getByTestId('recipe-option')).toHaveText(/Berry oats/i, { timeout: 10_000 });
	await previewPageOrFrame.getByTestId('recipe-option').click();
	await expect(previewPageOrFrame.getByTestId('selected-recipe')).toHaveText(/Berry oats/i, { timeout: 10_000 });

	await previewPageOrFrame.getByTestId('cook-button').click();
	await expect(previewPageOrFrame.getByTestId('cook-count')).toContainText('Cooked 1 times', { timeout: 10_000 });
}

async function skipWhenApplicationPreviewDisabled(page: any) {
	const response = await page.request.get(`${API_BASE_URL}/v1/features/availability`);
	if (!response.ok()) return;
	const availability = await response.json();
	test.skip(
		availability?.disabled?.includes('embed:code:application'),
		'application preview embed is disabled on this environment'
	);
}

async function dismissVisibleNotifications(page: any): Promise<void> {
	const notifications = page.getByTestId('notification');
	for (let index = (await notifications.count()) - 1; index >= 0; index -= 1) {
		const notification = notifications.nth(index);
		if (await notification.isVisible().catch(() => false)) {
			await notification.getByTestId('notification-dismiss').dispatchEvent('click').catch(() => undefined);
		}
	}
	await expect(async () => {
		for (let index = 0; index < (await notifications.count()); index += 1) {
			expect(await notifications.nth(index).isVisible()).toBe(false);
		}
	}).toPass({ timeout: 5000 });
}

test('generated application embed starts explicit isolated live preview', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(420_000);

	attachConsoleListeners(page);
	attachNetworkListeners(page);

	const { email, password, otpKey } = getTestAccount();
	skipWithoutCredentials(test, email, password, otpKey);
	await skipWhenApplicationPreviewDisabled(page);

	const logCheckpoint = createSignupLogger('application-preview');
	await archiveExistingScreenshots(logCheckpoint);
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'application-preview'
	});

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	await sendMessage(
		page,
		withMockMarker('Create a svelte based recipe manager application.', 'application_preview'),
		logCheckpoint,
		takeStepScreenshot,
		'application-preview'
	);

	const applicationEmbed = await waitForEmbedFinished(page, 'code', 'application', 180_000);
	const assistantMessages = page.getByTestId('message-assistant');
	await expect(assistantMessages.getByText('application_preview')).toHaveCount(0);
	await expect(assistantMessages.getByText('json:package.json')).toHaveCount(0);
	await expect(assistantMessages.getByText('svelte:src/App.svelte')).toHaveCount(0);
	await expect(applicationEmbed.getByTestId('application-preview-screenshot')).toBeVisible({ timeout: 10_000 });
	await expect(applicationEmbed.getByTestId('application-preview-play-overlay')).toBeVisible({ timeout: 10_000 });

	const fullscreenOverlay = await openFullscreen(page, applicationEmbed);
	await expect(fullscreenOverlay.getByTestId('application-preview-panel')).toBeVisible({ timeout: 10_000 });
	await expect(fullscreenOverlay.getByTestId('application-preview-files')).toBeVisible({ timeout: 10_000 });
	await expect(fullscreenOverlay.getByTestId('application-preview-logs')).toBeVisible({ timeout: 10_000 });

	const previewStartResponse = page.waitForResponse(
		(response: any) => response.url().includes('/v1/applications/') && response.url().includes('/preview/start'),
		{ timeout: 90_000 }
	);
	await dismissVisibleNotifications(page);
	await fullscreenOverlay.getByTestId('application-start-preview').click();
	const startResponse = await previewStartResponse;
	expect(startResponse.ok(), `preview start failed with ${startResponse.status()}`).toBe(true);

	const iframe = fullscreenOverlay.getByTestId('application-preview-iframe');
	await expect(iframe).toBeVisible({ timeout: 180_000 });
	const iframeSrc = await iframe.getAttribute('src');
	expect(iframeSrc, 'preview iframe src missing').toBeTruthy();
	expect(iframeSrc).toContain('/t/');
	expect(iframeSrc).toContain('.openmatesusercontent.org');
	expect(iframeSrc).not.toContain('e2b.dev');
	const previewResponse = await page.request.get(iframeSrc || '');
	expect(previewResponse.ok(), `preview URL failed with ${previewResponse.status()}`).toBe(true);
	const previewFrame = iframe.contentFrame();
	await assertRecipeAppIsInteractive(previewFrame);

	await expect(fullscreenOverlay.getByTestId('application-open-preview-window')).toBeVisible({ timeout: 10_000 });
	const popupPromise = page.waitForEvent('popup');
	await dismissVisibleNotifications(page);
	await fullscreenOverlay.getByTestId('application-open-preview-window').click();
	const previewPopup = await popupPromise;
	attachConsoleListeners(previewPopup);
	attachNetworkListeners(previewPopup);
	await previewPopup.waitForLoadState('domcontentloaded', { timeout: 60_000 });
	await expect(previewPopup).toHaveURL(/openmatesusercontent\.org\/t\//, { timeout: 30_000 });
	await assertRecipeAppIsInteractive(previewPopup);
	await previewPopup.close();

	await expect(fullscreenOverlay.getByTestId('application-stop-preview')).toBeVisible({ timeout: 10_000 });
	await fullscreenOverlay.getByTestId('application-stop-preview').click();
	await expect(fullscreenOverlay.getByTestId('application-preview-status')).toContainText(/stopped|failed|timeout/i, { timeout: 60_000 });
	await expect(fullscreenOverlay.getByTestId('application-preview-logs')).toBeVisible({ timeout: 10_000 });

	await closeFullscreen(page, fullscreenOverlay);
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'application-preview');
});
