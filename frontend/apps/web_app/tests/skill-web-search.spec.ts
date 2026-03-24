/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for web/search skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/web
 * Phase 2: CLI direct skill command (openmates apps web search --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
 * Phase 4: Web UI chat triggers skill with embed rendering + fullscreen
 *
 * All chat phases use withLiveMockMarker — the full pipeline always runs,
 * only external API calls (LLM + HTTP) are cached.
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
	verifySearchGrid,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

test.describe('App: Web / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// ── Phase 1: Embed preview renders ─────────────────────────────────────
	test('Phase 1: embed preview renders at /dev/preview/embeds/web', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'web', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	test('Phase 2: CLI apps web search returns results', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(apiUrl, ['apps', 'web', 'search', 'OpenMates AI assistant']);
		expect(result.code).toBe(0);
		expect(result.stdout.length).toBeGreaterThan(10);
		expect(result.stderr).not.toMatch(/error|failed|exception/i);
		console.log(`[P2] web/search returned ${result.stdout.length} chars`);
	});

	// ── Phase 3: CLI chat send triggers skill ──────────────────────────────
	test('Phase 3: CLI chats new triggers web search', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const message = withLiveMockMarker('Search the web for OpenMates AI assistant', 'web_search_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expect(result.code).toBe(0);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		// Cleanup: extract chat ID and delete
		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	// ── Phase 4: Web UI chat triggers skill ────────────────────────────────
	test('Phase 4: Web chat triggers web search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const { logCheckpoint } = createSignupLogger('skill-web-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Search the web for OpenMates AI assistant',
			'web_search_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'web-search');

		logCheckpoint('Waiting for web search embed to finish...');
		const embed = await waitForEmbedFinished(page, 'web', 'search');
		logCheckpoint('Web search embed finished.');
		await takeStepScreenshot(page, 'web-search-embed-finished');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		const resultCards = await verifySearchGrid(fullscreenOverlay);
		const count = await resultCards.count();
		logCheckpoint(`Found ${count} search result(s) in fullscreen grid.`);

		await closeFullscreen(page, fullscreenOverlay);
		logCheckpoint('Fullscreen closed.');

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'web-search');
	});
});
