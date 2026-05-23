/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E coverage for electronics/search_components.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/electronics
 * Phase 2: CLI direct skill command returns TI WEBENCH component results
 * Phase 3: Web UI chat triggers the skill and opens the fullscreen result grid
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

test.describe('App: Electronics / Skill: search_components', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/electronics', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'electronics', log);
	});

	test('Phase 2: CLI apps electronics search_components returns component results', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const result = await runCli(
			apiUrl,
			[
				'apps', 'electronics', 'search_components',
				'--input', JSON.stringify({
					requests: [{
						category: 'power_converters',
						input_voltage_min: 12,
						input_voltage_max: 12,
						output_voltage: 3.3,
						output_current_max: 3,
						max_results: 3
					}]
				}),
				'--json'
			],
			60_000
		);

		expect(result.code).toBe(0);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const results = parsed.data?.results?.[0]?.results || [];
		expect(results.length).toBeGreaterThan(0);
		expect(results[0].part_number).toBeTruthy();
		expect(results[0].product_url).toContain('ti.com/product/');
		console.log(`[P2] electronics/search_components found ${results.length} component(s)`);
	});

	test('Phase 3: Web chat triggers electronics search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-electronics-search-components');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Find a TI WEBENCH buck converter for 12V input to 3.3V at 3A', 'electronics_search_web'),
			logCheckpoint,
			takeStepScreenshot,
			'electronics-search'
		);

		const embed = await waitForEmbedFinished(page, 'electronics', 'search_components');
		logCheckpoint('Electronics search embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		const resultCards = await verifySearchGrid(fullscreenOverlay);
		expect(await resultCards.count()).toBeGreaterThan(0);
		await expect(fullscreenOverlay.getByText(/TI WEBENCH|TPS|Buck/i).first()).toBeVisible({ timeout: 15_000 });
		logCheckpoint(`Found ${await resultCards.count()} component result(s).`);

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'electronics-search');
	});
});
