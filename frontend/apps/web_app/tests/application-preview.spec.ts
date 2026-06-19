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

test('generated application embed starts explicit isolated live preview', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(420_000);

	attachConsoleListeners(page);
	attachNetworkListeners(page);

	const { email, password, otpKey } = getTestAccount();
	skipWithoutCredentials(test, email, password, otpKey);

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
	await expect(page.getByText('application_preview')).toHaveCount(0);
	await expect(page.getByText('json:package.json')).toHaveCount(0);
	await expect(page.getByText('svelte:src/App.svelte')).toHaveCount(0);
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
	await expect(iframe.contentFrame().getByText(/recipe/i).first()).toBeVisible({ timeout: 120_000 });

	await expect(fullscreenOverlay.getByTestId('application-open-preview-window')).toBeVisible({ timeout: 10_000 });
	await expect(fullscreenOverlay.getByTestId('application-stop-preview')).toBeVisible({ timeout: 10_000 });
	await fullscreenOverlay.getByTestId('application-stop-preview').click();
	await expect(fullscreenOverlay.getByTestId('application-preview-status')).toContainText(/stopped|failed|timeout/i, { timeout: 60_000 });
	await expect(fullscreenOverlay.getByTestId('application-preview-logs')).toBeVisible({ timeout: 10_000 });

	await closeFullscreen(page, fullscreenOverlay);
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'application-preview');
});
