/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for travel/search_stays skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/travel
 * Phase 2: CLI direct skill command (openmates apps travel search_stays --json)
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
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');
const {
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	verifySearchGrid,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

/** Get a date N days from now in YYYY-MM-DD format */
function futureDate(daysAhead = 14): string {
	const d = new Date();
	d.setDate(d.getDate() + daysAhead);
	return d.toISOString().split('T')[0];
}

test.describe('App: Travel / Skill: search_stays', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/travel', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'travel', log);
	});

	test('Phase 2: CLI apps travel search_stays returns results', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const checkIn = futureDate(14);
		const checkOut = futureDate(16);
		const result = await runCli(
			apiUrl,
			[
				'apps', 'travel', 'search_stays',
				'--input', JSON.stringify({
					requests: [{
						query: 'Hotels in Berlin',
						check_in_date: checkIn,
						check_out_date: checkOut
					}]
				}),
				'--json'
			],
			45_000
		);

		expectCliSuccess(result);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const results = parsed.data?.results?.[0]?.results || [];
		expect(results.length).toBeGreaterThan(0);
		console.log(`[P2] travel/search_stays found ${results.length} hotel(s)`);
	});

	test('Phase 3: CLI chats new triggers stays search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker('Find hotels in Berlin for next week', 'travel_stays_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expectCliSuccess(result);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 4: Web chat triggers stays search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-travel-stays');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Find hotels in Berlin for next week', 'travel_stays_web'),
			logCheckpoint, takeStepScreenshot, 'travel-stays'
		);

		const embed = await waitForEmbedFinished(page, 'travel', 'search_stays');
		logCheckpoint('Travel stays embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		const resultCards = await verifySearchGrid(fullscreenOverlay);
		logCheckpoint(`Found ${await resultCards.count()} hotel result(s).`);

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'travel-stays');
	});
});
