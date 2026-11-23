/* eslint-disable @typescript-eslint/no-require-imports */
// frontend/apps/web_app/tests/real-inference-focus-mode-video.spec.ts
// Real-provider regression coverage for video focus-mode activation.
// This intentionally does not use TEST_MOCK markers: the bug only reproduced
// after real auto-confirm rebuilt continuation history and called preprocessing.
// The test verifies the video focus embed activates and continuation completes
// without surfacing the raw/technical preprocessing failure to the user.
// Runs in the `real_inference` CI group (isolated per-run stack with real Gemini, Mistral, Brave
// and Jev keys) and still manually against dev (OPENMATES_PROOF_REAL_DEV=1).
// proof-video: not_required reason=account_health
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
const { requireRealInference } = require('./helpers/real-inference-guard');
const { expandActivity } = require('./helpers/assistant-activity');
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';

const { email: TEST_EMAIL } = getTestAccount();

const SELECTORS = {
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

// contract-test: direct surface=gui.web assertions=daily-ai-tests.real.semantic-signal
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

	requireRealInference('Focus mode video', BASE_URL);
	if (!TEST_EMAIL) throw new Error('Real-inference CI requires a provisioned test account.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting real video focus mode regression test.');

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const message =
		'Please start the Analyze video focus mode for this YouTube video, then summarize it, assess credibility and bias, and fact-check the main claims: https://www.youtube.com/watch?v=dQw4w9WgXcQ';
	await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'video-real');

	await waitForAssistantMessage(page, { which: 'first', timeout: 120000, logCheckpoint });
	const chatId = await getActiveChatId(page);
	logCheckpoint(`Active chat id for backend log verification: ${chatId}`);

	// The pill above the composer is the persistent state of an active focus.
	const banner = page.locator(SELECTORS.focusActiveBanner);
	await expect(banner).toBeVisible({ timeout: 120000 });
	await expect(page.locator(SELECTORS.focusActiveBannerText)).toContainText(/video/i);
	await expect(banner).toContainText(/focus on/i);

	await waitForAssistantIdle(page, logCheckpoint);

	// A settled activation folds into the reply's collapsed activity summary; open it so the
	// activated focus bar renders again and its focus id can be read.
	await expandActivity(page);
	const activatedEmbed = page.locator(SELECTORS.focusModeBarActivated);
	await expect(activatedEmbed.first()).toBeVisible({ timeout: 20000 });
	const focusId = await activatedEmbed.first().getAttribute('data-focus-id');
	logCheckpoint(`Video focus mode ID: "${focusId}"`);
	expect(focusId).toBe('videos-analyze_video');
	await takeStepScreenshot(page, 'video-focus-embed-visible');
	logCheckpoint('Video focus mode activated.');

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
