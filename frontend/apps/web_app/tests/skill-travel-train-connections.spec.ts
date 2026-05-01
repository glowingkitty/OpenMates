/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * E2E test for travel/search_connections with transport_methods: ["train"].
 *
 * Tests the Deutsche Bahn train provider end-to-end:
 * Phase 1: CLI direct skill command with train transport method
 * Phase 2: CLI chat send triggers train search
 * Phase 3: Web UI chat triggers train search with embed rendering,
 *          preview card verification, fullscreen details, and
 *          pre-resolved booking CTA ("Book on Deutsche Bahn")
 *
 * Key differences from the flight spec (skill-travel-connections.spec.ts):
 * - booking_url is pre-set in the result (no on-demand /booking-link call)
 * - CTA shows "Book on Deutsche Bahn" immediately (not "Get booking link")
 * - No airline logos, no flight track, no CO2 data
 * - Carrier shows train product (ICE, IC, etc.) instead of airline
 *
 * Architecture context: docs/architecture/apps/travel-train-api-research.md
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

test.describe('App: Travel / Skill: search_connections (train)', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: CLI train search returns results with booking URLs', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const date = futureDate();
		const result = await runCli(
			apiUrl,
			[
				'apps', 'travel', 'search_connections',
				'--input', JSON.stringify({
					requests: [{
						legs: [{ origin: 'Berlin', destination: 'Munich', date }],
						transport_methods: ['train']
					}]
				}),
				'--json'
			],
			60_000
		);

		expectCliSuccess(result);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const results = parsed.data?.results?.[0]?.results || [];
		expect(results.length).toBeGreaterThan(0);
		console.log(`[P1] train search found ${results.length} connection(s)`);

		// Verify train-specific fields
		const first = results[0];
		expect(first.transport_method).toBe('train');
		expect(first.total_price).toBeTruthy();
		expect(first.booking_url).toBeTruthy();
		expect(first.booking_url).toContain('bahn.de');
		console.log(`[P1] First: ${first.origin} → ${first.destination}, €${first.total_price}, booking: ${first.booking_url.substring(0, 60)}...`);

		// Verify provider attribution
		expect(parsed.data?.provider).toBe('Deutsche Bahn');

		// Verify legs and segments
		expect(first.legs).toBeTruthy();
		expect(first.legs.length).toBeGreaterThanOrEqual(1);
		const leg = first.legs[0];
		expect(leg.segments.length).toBeGreaterThanOrEqual(1);
		const seg = leg.segments[0];
		expect(seg.carrier).toBeTruthy(); // e.g., "ICE"
		expect(seg.number).toBeTruthy(); // e.g., "ICE 505"
		expect(seg.departure_station).toBeTruthy();
		expect(seg.arrival_station).toBeTruthy();
		console.log(`[P1] First segment: ${seg.number} (${seg.carrier}), ${seg.departure_station} → ${seg.arrival_station}`);
	});

	test('Phase 2: CLI chat triggers train search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker(
			'Find train connections from Hamburg to Frankfurt next week',
			'travel_train_cli'
		);
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 90_000);
		expectCliSuccess(result);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P2] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 3: Web chat triggers train search with booking CTA', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-travel-train');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Find trains from Berlin to Dresden next week', 'travel_train_web'),
			logCheckpoint, takeStepScreenshot, 'travel-train'
		);

		const embed = await waitForEmbedFinished(page, 'travel', 'search_connections');
		logCheckpoint('Train connections embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		const resultCards = await verifySearchGrid(fullscreenOverlay);
		const cardCount = await resultCards.count();
		logCheckpoint(`Found ${cardCount} train connection result(s).`);
		expect(cardCount).toBeGreaterThan(0);

		// ── Verify preview card elements ──
		const firstPreview = resultCards.first();
		const previewDetails = firstPreview.getByTestId('connection-preview-details');
		await expect(previewDetails).toBeVisible({ timeout: 5000 });

		// Price should be visible
		const priceEl = previewDetails.getByTestId('connection-price');
		await expect(priceEl).toBeVisible();
		const priceText = await priceEl.textContent();
		expect(priceText).toMatch(/\d/);
		logCheckpoint(`Preview price: ${priceText}`);

		// Route should show origin → destination (station names, not IATA codes)
		const routeEl = previewDetails.getByTestId('connection-route');
		await expect(routeEl).toBeVisible();
		const routeText = await routeEl.textContent();
		expect(routeText).toContain('→');
		logCheckpoint(`Preview route: ${routeText}`);

		// Meta line should show duration/stops
		const metaEl = previewDetails.getByTestId('connection-meta');
		await expect(metaEl).toBeVisible();

		// No airline logos for trains
		const airlineLogos = previewDetails.getByTestId('airline-logos');
		const hasAirlineLogos = await airlineLogos.isVisible({ timeout: 1000 }).catch(() => false);
		expect(hasAirlineLogos).toBe(false);
		logCheckpoint('No airline logos shown (correct for trains).');

		await takeStepScreenshot(page, 'train-preview-verified');

		// ── Open child connection fullscreen ──
		await firstPreview.click();
		await page.waitForTimeout(1500);

		// The details card should be visible
		const detailsCard = page.getByTestId('flight-details-card');
		await expect(detailsCard).toBeVisible({ timeout: 15000 });

		// At least one segment card
		const segmentCards = detailsCard.getByTestId('segment-card');
		await expect(segmentCards.first()).toBeVisible({ timeout: 5000 });
		const segCount = await segmentCards.count();
		expect(segCount).toBeGreaterThanOrEqual(1);
		logCheckpoint(`Details card has ${segCount} segment card(s).`);

		// ── Verify booking CTA is pre-resolved (no loading state) ──
		// Train results have booking_url set directly, so the CTA should
		// immediately show "Book on Deutsche Bahn" without a /booking-link call.
		const bookingCta = page.getByTestId('booking-cta');
		await expect(bookingCta).toBeVisible({ timeout: 5000 });
		const ctaText = await bookingCta.textContent();
		expect(ctaText?.toLowerCase()).toContain('book on');
		expect(ctaText).toContain('Deutsche Bahn');
		logCheckpoint(`Booking CTA: "${ctaText}" (pre-resolved, no API call needed).`);

		await takeStepScreenshot(page, 'train-fullscreen-verified');

		// Navigate back
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'travel-train');
	});
});
