/* eslint-disable @typescript-eslint/no-require-imports */
// frontend/apps/web_app/tests/focus-mode-video-real-request.spec.ts
// Real-provider regression coverage for video focus-mode activation.
// This intentionally does not use TEST_MOCK markers: the bug only reproduced
// after real auto-confirm rebuilt continuation history and called preprocessing.
// The test verifies the video focus embed activates and continuation completes
// without surfacing the raw/technical preprocessing failure to the user.
export {};

const { test, expect } = require('./helpers/cookie-audit');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}

	if (page) {
		const noop = () => {};
		const noopScreenshot = async () => {};
		await deleteActiveChat(page, noop, noopScreenshot, 'afterEach-cleanup').catch(noop);
	}
});

const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const {
	deleteActiveChat,
	loginToTestAccount,
	sendMessage,
	startNewChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const SELECTORS = {
	focusModeBar: '[data-testid="focus-mode-bar"][data-app-id="videos"]',
	focusModeBarActivated: '[data-testid="focus-mode-bar"].activated[data-app-id="videos"]',
	focusActiveBanner: '[data-testid="focus-pill"]',
	focusActiveBannerText: '[data-testid="focus-pill"] [data-testid="focus-pill-label"]'
};

async function getActiveChatId(page: any): Promise<string> {
	await page.waitForFunction(() => window.location.hash.startsWith('#chat-id='), null, {
		timeout: 15000
	});
	const chatId = await page.evaluate(() => window.location.hash.replace('#chat-id=', ''));
	expect(chatId).toBeTruthy();
	return chatId as string;
}

function setupPageListeners(page: any): void {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});
}

async function waitForAssistantIdle(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	logCheckpoint('Waiting for assistant stream to be idle...');
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: 180000 });
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 10000 });
	logCheckpoint('Assistant stream idle and editor is visible.');
}

test('real YouTube analysis request activates video focus mode and continues without preprocessing error', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);
	test.slow();
	test.setTimeout(360000);

	const logCheckpoint = createSignupLogger('FOCUS_VIDEO_REAL');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-video-real'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting real video focus mode regression test.');

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const message =
		'Please analyze this YouTube video. Summarize it, assess credibility and bias, and fact-check the main claims: https://www.youtube.com/watch?v=dQw4w9WgXcQ';
	await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'video-real');

	await waitForAssistantMessage(page, { which: 'first', timeout: 120000, logCheckpoint });
	const chatId = await getActiveChatId(page);
	logCheckpoint(`Active chat id for backend log verification: ${chatId}`);

	const focusModeEmbed = page.locator(SELECTORS.focusModeBar);
	await expect(focusModeEmbed.first()).toBeVisible({ timeout: 120000 });
	const focusId = await focusModeEmbed.first().getAttribute('data-focus-id');
	logCheckpoint(`Video focus mode ID: "${focusId}"`);
	expect(focusId).toBe('videos-analyze_video');
	await takeStepScreenshot(page, 'video-focus-embed-visible');

	const activatedEmbed = page.locator(SELECTORS.focusModeBarActivated);
	await expect(activatedEmbed.first()).toBeVisible({ timeout: 20000 });
	logCheckpoint('Video focus mode activated.');

	const banner = page.locator(SELECTORS.focusActiveBanner);
	await expect(banner).toBeVisible({ timeout: 15000 });
	await expect(page.locator(SELECTORS.focusActiveBannerText)).toContainText(/video/i);
	await expect(banner).toContainText(/focus on/i);

	await waitForAssistantIdle(page, logCheckpoint);

	const assistantMessages = page.getByTestId('message-assistant');
	const assistantText = (await assistantMessages.last().textContent())?.toLowerCase() ?? '';
	logCheckpoint(`Final assistant message text length: ${assistantText.length}`);
	expect(assistantText.length).toBeGreaterThan(80);
	expect(assistantText).not.toContain('chat.an_error_occured');
	expect(assistantText).not.toContain('chat.an_error_occurred');
	expect(assistantText).not.toContain('preprocessing failed');
	expect(assistantText).not.toContain('expected last role');
	expect(assistantText).not.toContain('technical issue');

	await expect(activatedEmbed.first()).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'video-focus-real-complete');
});
