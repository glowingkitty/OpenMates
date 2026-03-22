/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E test for reminder/set-reminder skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/reminder
 * Phase 2: SKIPPED — CLI direct command creates server state (stateful)
 * Phase 3: CLI chat send triggers skill
 * Phase 4: Web UI chat triggers skill with embed rendering
 *
 * Architecture context: docs/architecture/embeds.md
 */
export {};

const { test, expect } = require('./console-monitor');
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
const { deriveApiUrl, runCli, parseCliJson } = require('./helpers/cli-test-helpers');
const {
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

test.describe('App: Reminder / Skill: set-reminder', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/reminder', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'reminder', log);
	});

	// Phase 2: SKIPPED — set-reminder via CLI creates real server state
	// and would need cleanup. Covered by Phase 3 + 4 instead.

	test('Phase 3: CLI chats new triggers reminder set', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker(
			'Remind me to check my email tomorrow at 9am',
			'reminder_set_cli'
		);
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expect(result.code).toBe(0);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 4: Web chat triggers reminder with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const { logCheckpoint } = createSignupLogger('skill-reminder-set');
		await archiveExistingScreenshots('skill-reminder-set');
		const takeStepScreenshot = createStepScreenshotter('skill-reminder-set');

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Remind me to check my email tomorrow at 9am', 'reminder_set_web'),
			logCheckpoint, takeStepScreenshot, 'reminder-set'
		);

		const embed = await waitForEmbedFinished(page, 'reminder', 'set-reminder');
		logCheckpoint('Reminder embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'reminder-set');
	});
});
