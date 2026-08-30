/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Daily bounded rotating real-inference canary.
 * Selects one reviewed low-cost semantic prompt by UTC date while preserving the
 * same distributed daily budget group as the fixed canary.
 * Contract: architecture.daily-ai-test-inference@1.
 */
// proof-video: not_required reason=account_health
export {};

const { test, expect } = require('./console-monitor');
const { createHash } = require('node:crypto');
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

const PROMPTS = [
	'Answer in German with one short sentence: What is the capital of France?',
	'Reply with one short sentence explaining what twelve squared equals.',
	'Give one concise tip for writing a clear project status update.'
];

// contract-test: direct surface=gui.web assertions=daily-ai-tests.real.fixed-plus-rotating,daily-ai-tests.real.semantic-signal,daily-ai-tests.budget.shared-hard-cap,daily-ai-tests.isolation.ordinary-inference-unchanged
test('daily rotating real-inference canary completes its selected semantic scenario', async ({ page }) => {
	test.setTimeout(180_000);
	if (!getTestAccount().email) {
		throw new Error('Daily AI canary requires configured test-account credentials.');
	}

	const log = createSignupLogger('daily-ai-rotating-canary');
	await archiveExistingScreenshots(log);
	const screenshot = createStepScreenshotter(log);
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const prompt = PROMPTS[rotatingScenarioIndex()];
	const marked = withLiveRealMarker(prompt, dailyRunGroup());
	const marker = marked.match(/<<<TEST_LIVE_REAL:[^>]+>>>$/)?.[0];
	expect(marker).toBeTruthy();
	await sendMessage(page, prompt, log, screenshot, 'daily-ai-rotating', { testMockMarker: marker });
	const assistant = await waitForAssistantMessage(page, { timeout: 120_000, logCheckpoint: log });
	const text = ((await assistant.textContent()) || '').trim();
	expect(text.length).toBeGreaterThan(5);
	expect(text).not.toMatch(/protocol error|internal server error|traceback/i);
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'false', {
		timeout: 120_000
	});
	await deleteActiveChat(page, log, screenshot, 'daily-ai-rotating');
});

function dailyRunGroup(): string {
	return process.env.E2E_DAILY_AI_RUN_ID || `daily_canary_${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`;
}

function rotatingScenarioIndex(): number {
	const rotationKey = process.env.E2E_DAILY_AI_RUN_ID || new Date().toISOString().slice(0, 10);
	return createHash('sha256').update(rotationKey).digest().readUInt32BE(0) % PROMPTS.length;
}
