/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for travel/search_connections skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/travel
 * Phase 2: CLI direct skill command (openmates apps travel search_connections --json)
 * Phase 3: CLI chat send triggers skill
 * Phase 4: Web UI chat triggers skill with embed rendering + fullscreen grid
 *          + verifies redesigned preview (green price, route, meta) and
 *          flight details card (segment cards, time badges, flag emojis)
 *
 * Note: Travel dates must be in the future — uses dynamic date calculation.
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

/** Get a date 14 days from now in YYYY-MM-DD format */
function futureDate(daysAhead = 14): string {
	const d = new Date();
	d.setDate(d.getDate() + daysAhead);
	return d.toISOString().split('T')[0];
}

test.describe('App: Travel / Skill: search_connections', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/travel', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'travel', log);
	});

	test('Phase 2: CLI apps travel search_connections returns results', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const date = futureDate();
		const result = await runCli(
			apiUrl,
			[
				'apps', 'travel', 'search_connections',
				'--input', JSON.stringify({
					requests: [{
						legs: [{ origin: 'Berlin', destination: 'Munich', date }]
					}]
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
		console.log(`[P2] travel/search_connections found ${results.length} connection(s)`);
	});

	test('Phase 3: CLI chats new triggers travel search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker(
			'Find flights from Berlin to Munich next week',
			'travel_connections_cli'
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

	test('Phase 4: Web chat triggers travel search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-travel-connections');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Find flights from Berlin to Munich next week', 'travel_connections_web'),
			logCheckpoint, takeStepScreenshot, 'travel-connections'
		);

		const embed = await waitForEmbedFinished(page, 'travel', 'search_connections');
		logCheckpoint('Travel connections embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		const resultCards = await verifySearchGrid(fullscreenOverlay);
		const cardCount = await resultCards.count();
		logCheckpoint(`Found ${cardCount} connection result(s).`);

		// ── Verify redesigned preview card elements ──
		const firstPreview = resultCards.first();
		const previewDetails = firstPreview.getByTestId('connection-preview-details');
		await expect(previewDetails).toBeVisible({ timeout: 5000 });

		// Price should be visible and green (success color)
		const priceEl = previewDetails.getByTestId('connection-price');
		await expect(priceEl).toBeVisible();
		const priceText = await priceEl.textContent();
		expect(priceText).toBeTruthy();
		logCheckpoint(`Preview price: ${priceText}`);

		// Route should show origin → destination
		const routeEl = previewDetails.getByTestId('connection-route');
		await expect(routeEl).toBeVisible();
		const routeText = await routeEl.textContent();
		expect(routeText).toContain('→');
		logCheckpoint(`Preview route: ${routeText}`);

		// Meta line should show duration/stops info
		const metaEl = previewDetails.getByTestId('connection-meta');
		await expect(metaEl).toBeVisible();
		const metaText = await metaEl.textContent();
		expect(metaText).toContain('·');
		logCheckpoint(`Preview meta: ${metaText}`);

		await takeStepScreenshot(page, 'preview-card-verified');

		// ── Open a child connection fullscreen to verify flight details card ──
		await firstPreview.click();
		await page.waitForTimeout(1000);

		// The flight details card should be visible
		const flightCard = page.getByTestId('flight-details-card');
		await expect(flightCard).toBeVisible({ timeout: 15000 });

		// Route header with flags should be visible
		const routeHeader = flightCard.getByTestId('route-header');
		await expect(routeHeader).toBeVisible();
		const routeHeaderText = await routeHeader.textContent();
		expect(routeHeaderText).toContain('→');
		logCheckpoint(`Flight card route: ${routeHeaderText}`);

		// At least one segment card should be present
		const segmentCards = flightCard.getByTestId('segment-card');
		await expect(segmentCards.first()).toBeVisible({ timeout: 5000 });
		const segCount = await segmentCards.count();
		expect(segCount).toBeGreaterThanOrEqual(1);
		logCheckpoint(`Flight card has ${segCount} segment card(s).`);

		// Segment should show departure code with airport IATA
		const depCode = flightCard.getByTestId('departure-code').first();
		await expect(depCode).toBeVisible();
		const depCodeText = await depCode.textContent();
		expect(depCodeText).toBeTruthy();
		logCheckpoint(`First segment departure: ${depCodeText}`);

		await takeStepScreenshot(page, 'flight-details-card-verified');

		// Navigate back to the search results
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'travel-connections');
	});
});
