/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for home/search skill (apartment search).
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/home
 * Phase 2: CLI direct skill command (openmates apps home search --json)
 * Phase 3: CLI chat send triggers skill
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

test.describe('App: Home / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/home', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'home', log);
	});

	test('Phase 2: CLI apps home search returns results', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const result = await runCli(
			apiUrl,
			[
				'apps', 'home', 'search',
				'--input', JSON.stringify({
					requests: [{ query: 'Berlin', listing_type: 'rent' }]
				}),
				'--json'
			],
			45_000
		);

		expect(result.code).toBe(0);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const results = parsed.data?.results?.[0]?.results || [];
		expect(results.length).toBeGreaterThan(0);
		expect(results[0].title).toBeTruthy();
		console.log(`[P2] home/search found ${results.length} listing(s)`);
	});

	test('Phase 3: CLI chats new triggers home search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker('Find apartments in Berlin', 'home_search_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expect(result.code).toBe(0);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 4: Web chat triggers home search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-home-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Find apartments in Berlin', 'home_search_web'),
			logCheckpoint, takeStepScreenshot, 'home-search'
		);

		const embed = await waitForEmbedFinished(page, 'home', 'search');
		logCheckpoint('Home search embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		const resultCards = await verifySearchGrid(fullscreenOverlay);
		logCheckpoint(`Found ${await resultCards.count()} listing result(s).`);

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'home-search');
	});
});
