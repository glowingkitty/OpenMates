/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared-recipient application preview E2E coverage.
 *
 * Requires two numbered test accounts and a deployed preview gateway. The shared
 * recipient starts their own preview session from decrypted shared content.
 */
export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withLiveMockMarker
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

test('shared recipient starts an isolated application preview session', async ({ browser, page }: { browser: any; page: any }) => {
	test.slow();
	test.setTimeout(540_000);

	attachConsoleListeners(page);
	attachNetworkListeners(page);

	const creator = getTestAccount(1);
	const recipient = getTestAccount(2);
	skipWithoutCredentials(test, creator.email, creator.password, creator.otpKey);
	test.skip(!process.env.OPENMATES_TEST_ACCOUNT_2_EMAIL, 'OPENMATES_TEST_ACCOUNT_2_* credentials are required for shared-recipient preview coverage.');
	skipWithoutCredentials(test, recipient.email, recipient.password, recipient.otpKey);

	const logCheckpoint = createSignupLogger('application-preview-share');
	await archiveExistingScreenshots(logCheckpoint);
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'application-preview-share'
	});

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot, { credentials: creator });
	await startNewChat(page, logCheckpoint);
	await sendMessage(
		page,
		withLiveMockMarker(
			'Create a tiny Svelte counter application as a runnable application preview with package.json, src/App.svelte, and src/main.ts.',
			'application_preview_share'
		),
		logCheckpoint,
		takeStepScreenshot,
		'application-preview-share'
	);

	await waitForEmbedFinished(page, 'code', 'application', 180_000);

	await page.getByTestId('chat-share-button').click();
	const generateLinkButton = page.getByTestId('share-generate-link');
	await expect(generateLinkButton).toBeVisible({ timeout: 15_000 });
	await generateLinkButton.click();
	await expect(page.getByTestId('share-copy-link')).toBeVisible({ timeout: 30_000 });

	const shortLinkSection = page.getByTestId('share-short-link-section');
	await expect(shortLinkSection).toBeVisible({ timeout: 10_000 });
	await shortLinkSection.getByTestId('short-link-ttl-option').first().click();
	await page.getByTestId('share-short-link-generate').click();
	const shortLinkCopy = page.getByTestId('share-short-link-copy');
	await expect(shortLinkCopy).toBeVisible({ timeout: 30_000 });
	const shareUrl = (await shortLinkCopy.getByTestId('share-short-link-url').innerText()).trim();
	expect(shareUrl).toContain('/');

	const recipientContext = await browser.newContext();
	const recipientPage = await recipientContext.newPage();
	attachConsoleListeners(recipientPage);
	attachNetworkListeners(recipientPage);
	try {
		await loginToTestAccount(recipientPage, logCheckpoint, takeStepScreenshot, { credentials: recipient });
		await recipientPage.goto(shareUrl, { waitUntil: 'load' });

		const recipientEmbed = await waitForEmbedFinished(recipientPage, 'code', 'application', 180_000);
		const recipientFullscreen = await openFullscreen(recipientPage, recipientEmbed);
		const previewStartResponse = recipientPage.waitForResponse(
			(response: any) => response.url().includes('/v1/applications/') && response.url().includes('/preview/start'),
			{ timeout: 90_000 }
		);
		await recipientFullscreen.getByTestId('application-start-preview').click();
		const response = await previewStartResponse;
		expect(response.ok(), `recipient preview start failed with ${response.status()}`).toBe(true);

		const payload = await response.json();
		expect(payload.session_id).toBeTruthy();
		expect(payload.preview_url).toContain('/p/');
		expect(payload.preview_url).not.toContain('e2b.dev');
		await expect(recipientFullscreen.getByTestId('application-preview-iframe')).toBeVisible({ timeout: 180_000 });
		await closeFullscreen(recipientPage, recipientFullscreen);
	} finally {
		await recipientContext.close();
	}

	await page.keyboard.press('Escape');
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'application-preview-share-cleanup');
});
