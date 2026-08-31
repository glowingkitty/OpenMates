/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Daily bounded real-inference baseline canary.
 * Exercises encrypted web chat through preprocessing, main inference, streaming,
 * postprocessing, and persistence without asserting nondeterministic wording.
 * Contract: architecture.daily-ai-test-inference@2.
 */
// proof-video: not_required reason=account_health
export {};

const { test, expect } = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount,
	withLiveRealMarker
} = require('./signup-flow-helpers');
const {
	deleteActiveChat,
	loginToTestAccount,
	sendMessage,
	startNewChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');

const PROMPT = 'In one short sentence, explain why deterministic tests are useful.';

// contract-test: direct surface=cli assertions=daily-ai-tests.real.fixed-plus-rotating,daily-ai-tests.real.semantic-signal,daily-ai-tests.budget.shared-hard-cap,daily-ai-tests.isolation.ordinary-inference-unchanged
test('daily fixed real-inference canary completes the full chat pipeline', async ({ page }) => {
	test.setTimeout(180_000);
	if (!getTestAccount().email) {
		throw new Error('Daily AI canary requires configured test-account credentials.');
	}

	const log = createSignupLogger('daily-ai-fixed-canary');
	await archiveExistingScreenshots(log);
	const screenshot = createStepScreenshotter(log);
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const marked = withLiveRealMarker(PROMPT, dailyRunGroup());
	const marker = marked.match(/<<<TEST_LIVE_REAL:[^>]+>>>$/)?.[0];
	expect(marker).toBeTruthy();
	await sendMessage(page, PROMPT, log, screenshot, 'daily-ai-fixed', { testMockMarker: marker });
	const assistant = await waitForAssistantMessage(page, { timeout: 120_000, logCheckpoint: log });
	const text = ((await assistant.textContent()) || '').trim();
	expect(text.length).toBeGreaterThan(10);
	expect(text).not.toMatch(/protocol error|internal server error|traceback/i);
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'false', {
		timeout: 120_000
	});
	await deleteActiveChat(page, log, screenshot, 'daily-ai-fixed');
});

function dailyRunGroup(): string {
	return process.env.E2E_DAILY_AI_RUN_ID || `daily_canary_${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`;
}
