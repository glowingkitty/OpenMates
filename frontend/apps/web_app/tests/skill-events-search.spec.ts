/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for events/search skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/events
 * Phase 2: CLI direct skill command (openmates apps events search --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
 * Phase 4: Web UI chat triggers skill with embed rendering + fullscreen grid
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

test.describe('App: Events / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// ── Phase 1: Embed preview renders ─────────────────────────────────────
	test('Phase 1: embed preview renders at /dev/preview/embeds/events', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'events', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	test('Phase 2: CLI apps events search returns results', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps', 'events', 'search',
				'--input', JSON.stringify({
					requests: [{ query: 'technology meetup', location: 'Berlin', provider: 'auto' }]
				}),
				'--json'
			],
			45_000
		);

		expect(result.code).toBe(0);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const skillData = parsed.data;
		expect(Array.isArray(skillData.results)).toBe(true);
		expect(skillData.results.length).toBeGreaterThan(0);

		const events = skillData.results[0].results || [];
		expect(events.length).toBeGreaterThan(0);

		const ev = events[0];
		expect(ev.name || ev.title).toBeTruthy();
		expect(ev.url).toBeTruthy();
		console.log(`[P2] events/search found ${events.length} event(s). First: "${ev.name || ev.title}"`);
	});

	// ── Phase 3: CLI chat send triggers skill ──────────────────────────────
	test('Phase 3: CLI chats new triggers events search', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const message = withLiveMockMarker('Find tech events in Berlin this week', 'events_search_cli');
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
	test('Phase 4: Web chat triggers events search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const { logCheckpoint } = createSignupLogger('skill-events-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Find tech events in Berlin this week',
			'events_search_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'events-search');

		logCheckpoint('Waiting for events search embed to finish...');
		const embed = await waitForEmbedFinished(page, 'events', 'search');
		logCheckpoint('Events search embed finished.');
		await takeStepScreenshot(page, 'events-search-embed-finished');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		const resultCards = await verifySearchGrid(fullscreenOverlay);
		const count = await resultCards.count();
		logCheckpoint(`Found ${count} event result(s) in fullscreen grid.`);

		await closeFullscreen(page, fullscreenOverlay);
		logCheckpoint('Fullscreen closed.');

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'events-search');
	});
});
