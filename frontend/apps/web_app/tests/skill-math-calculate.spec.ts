/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for math/calculate skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/math
 * Phase 2: CLI direct skill command (openmates apps math calculate --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
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

test.describe('App: Math / Skill: calculate', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// ── Phase 1: Embed preview renders ─────────────────────────────────────
	test('Phase 1: embed preview renders at /dev/preview/embeds/math', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'math', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	test('Phase 2: CLI apps math calculate returns correct result', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps', 'math', 'calculate',
				'--input', JSON.stringify({ expression: 'sqrt(144)', mode: 'numeric', precision: 10 }),
				'--json'
			],
			25_000
		);

		expect(result.code).toBe(0);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const skillData = parsed.data;
		const results = skillData.results || [];
		expect(results.length).toBeGreaterThan(0);

		const item = (results[0].results || [])[0];
		expect(item).toBeTruthy();

		// sqrt(144) = 12 exactly
		const resultStr = String(item.result || '');
		expect(resultStr).toMatch(/^12(\.0*)?$/);
		console.log(`[P2] math/calculate sqrt(144) = ${item.result} (mode=${item.mode})`);
	});

	// ── Phase 3: CLI chat send triggers skill ──────────────────────────────
	test('Phase 3: CLI chats new triggers math calculate', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const message = withLiveMockMarker('Calculate the square root of 144', 'math_calculate_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expect(result.code).toBe(0);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	// ── Phase 4: Web UI chat triggers skill ────────────────────────────────
	test('Phase 4: Web chat triggers math calculate with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-math-calculate');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Calculate the square root of 144',
			'math_calculate_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'math-calculate');

		logCheckpoint('Waiting for math calculate embed to finish...');
		const embed = await waitForEmbedFinished(page, 'math', 'calculate');
		logCheckpoint('Math calculate embed finished.');
		await takeStepScreenshot(page, 'math-calculate-embed-finished');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		await closeFullscreen(page, fullscreenOverlay);
		logCheckpoint('Fullscreen closed.');

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'math-calculate');
	});
});
