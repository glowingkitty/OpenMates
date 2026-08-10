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
	withMockMarker,
	withLiveMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	waitForChatReady,
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
const {
	saveCurrentFullscreenEmbed,
	verifySavedMemoryEntry
} = require('./helpers/saved-memory-test-helpers');

const TRAIN_MIN_TRANSFER_MINUTES = 15;

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

	test('Phase 1: CLI train search returns a valid train response', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const date = futureDate();
		const result = await runCli(
			apiUrl,
			[
				'apps', 'travel', 'search_connections',
				'--input', JSON.stringify({
					requests: [{
						legs: [{ origin: 'Berlin', destination: 'Hamburg', date }],
						providers: ['deutsche_bahn'],
						transport_methods: ['train'],
						owned_passes: ['deutschland_ticket'],
						pass_only: true,
						rail_products: ['regional', 'regional_express', 's_bahn'],
						min_transfer_minutes: TRAIN_MIN_TRANSFER_MINUTES
					}]
				}),
				'--json'
			],
			60_000
		);

		expectCliSuccess(result);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const firstGroup = parsed.data?.results?.[0] || {};
		const results = firstGroup.results || [];
		expect(parsed.data?.provider).toMatch(/Deutsche Bahn|Flix/i);
		console.log(`[P1] train search found ${results.length} connection(s)`);

		if (results.length === 0) {
			expect(firstGroup.result_count).toBe(0);
			expect(firstGroup.no_result_reason).toMatch(/no_matches|filtered_out/);
			console.log(`[P1] train provider returned a valid empty state: ${firstGroup.no_result_reason}`);
			return;
		}

		// Verify train-specific fields
		const first = results[0];
		expect(first.transport_method).toBe('train');
		expect(first.transfer_quality?.min_transfer_minutes).toBe(TRAIN_MIN_TRANSFER_MINUTES);
		if (first.fare?.is_pass_only) {
			expect(first.total_price).toBeNull();
			expect(first.fare.covered_by_passes).toContain('deutschland_ticket');
			expect(first.fare.confidence).toBe('pass_only');
			console.log(`[P1] First: ${first.origin} → ${first.destination}, covered by Deutschland Ticket`);
		} else {
			expect(first.total_price).toBeTruthy();
			expect(first.booking_url).toBeTruthy();
			expect(first.booking_url).toMatch(/bahn\.de|flixbus\.com|flixtrain\./i);
			console.log(`[P1] First: ${first.origin} → ${first.destination}, €${first.total_price}, booking: ${first.booking_url.substring(0, 60)}...`);
		}

		const optimizedResults = results.filter((item: any) => item.optimization?.optimized_by === 'openmates');
		for (const optimized of optimizedResults) {
			expect(optimized.optimization.badge).toBe('Optimized by OpenMates');
			expect(optimized.optimization.optimized_transfer_station).toBeTruthy();
		}
		console.log(`[P1] Optimized route candidates: ${optimizedResults.length}`);

		// Verify provider attribution
		expect(parsed.data?.provider).toContain('Deutsche Bahn');

		// Verify legs and segments
		expect(first.legs).toBeTruthy();
		expect(first.legs.length).toBeGreaterThanOrEqual(1);
		const leg = first.legs[0];
		expect(leg.segments.length).toBeGreaterThanOrEqual(1);
		for (const layover of leg.layovers || []) {
			if (typeof layover.duration_minutes === 'number') {
				expect(layover.duration_minutes).toBeGreaterThanOrEqual(TRAIN_MIN_TRANSFER_MINUTES);
			}
			if (layover.amenities?.groups) {
				expect(layover.amenities.groups.food_drink).toBeTruthy();
				expect(layover.amenities.groups.shops).toBeTruthy();
				expect(layover.amenities.groups.toilets).toBeTruthy();
			}
		}
		const seg = leg.segments[0];
		expect(seg.carrier).toBeTruthy(); // e.g., "ICE"
		expect(seg.departure_station).toBeTruthy();
		expect(seg.arrival_station).toBeTruthy();
		expect(seg.scheduled_departure_time || seg.departure_time).toBeTruthy();
		expect(seg.scheduled_arrival_time || seg.arrival_time).toBeTruthy();
		if (first.source_provider === 'deutsche_bahn') {
			expect(seg.number).toBeTruthy(); // e.g., "ICE 505"
			expect(seg.actual_departure_time).toBeTruthy();
			expect(seg.actual_arrival_time).toBeTruthy();
			expect(seg.departure_platform).toBeTruthy();
			expect(seg.arrival_platform).toBeTruthy();
		}
		console.log(`[P1] First segment: ${seg.number} (${seg.carrier}), ${seg.departure_station} → ${seg.arrival_station}`);
	});

	test('Phase 2: CLI chat triggers train search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');
		const date = futureDate();

		const message = withLiveMockMarker(
			`I have a Deutschland Ticket. Find regional trains from Berlin to Hamburg on ${date} with at least ${TRAIN_MIN_TRANSFER_MINUTES} minutes to change and tell me what is at the transfer station.`,
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
		const date = futureDate();

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);
		await waitForChatReady(page, logCheckpoint, 90_000);

		await sendMessage(
			page,
			withMockMarker(`I have a Deutschland Ticket. Find regional trains from Berlin to Hamburg on ${date} with at least ${TRAIN_MIN_TRANSFER_MINUTES} minutes to change and tell me what is at the transfer station.`, 'travel_train_web'),
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

		// Departure/arrival times should be visible directly in the preview card
		const timeEl = previewDetails.getByTestId('connection-time');
		await expect(timeEl).toBeVisible();
		const timeText = await timeEl.textContent();
		expect(timeText).toContain('→');
		logCheckpoint(`Preview time: ${timeText}`);

		// DB/Flix provider favicon should be available in the preview card without opening fullscreen
		await expect(previewDetails.getByTestId('airline-logos')).toBeVisible();

		// Meta line should show duration/stops
		const metaEl = previewDetails.getByTestId('connection-meta');
		await expect(metaEl).toBeVisible();

		const optimizationBadges = fullscreenOverlay.getByTestId('connection-optimization-badge');
		const optimizationBadgeCount = await optimizationBadges.count();
		if (optimizationBadgeCount > 0) {
			await expect(optimizationBadges.first()).toContainText('Optimized by OpenMates');
			logCheckpoint(`Optimized route badge shown on ${optimizationBadgeCount} preview card(s).`);
		} else {
			logCheckpoint('No optimized route candidate returned by DB for this run; continuing with transfer-quality checks.');
		}

		logCheckpoint('Provider favicon shown in the preview card.');

		await takeStepScreenshot(page, 'train-preview-verified');

		// ── Open child connection fullscreen ──
		let selectedPreview = firstPreview;
		for (let i = 0; i < cardCount; i += 1) {
			const candidate = resultCards.nth(i);
			const candidateMeta = await candidate.getByTestId('connection-meta').textContent();
			if (candidateMeta && !/\bDirect\b/i.test(candidateMeta)) {
				selectedPreview = candidate;
				break;
			}
		}
		await selectedPreview.click();
		await page.waitForTimeout(1500);

		// The details card should be visible
		const detailsCard = page.getByTestId('flight-details-card');
		await expect(detailsCard).toBeVisible({ timeout: 15000 });

		const savedTitle = await saveCurrentFullscreenEmbed(page, logCheckpoint, routeText?.trim() || undefined);

		// At least one segment card
		const segmentCards = detailsCard.getByTestId('segment-card');
		await expect(segmentCards.first()).toBeVisible({ timeout: 5000 });
		const segCount = await segmentCards.count();
		expect(segCount).toBeGreaterThanOrEqual(1);
		logCheckpoint(`Details card has ${segCount} segment card(s).`);

		const transferQualitySummary = detailsCard.getByTestId('transfer-quality-summary');
		await expect(transferQualitySummary).toBeVisible({ timeout: 5000 });
		await expect(transferQualitySummary).toContainText(`${TRAIN_MIN_TRANSFER_MINUTES} min`);
		logCheckpoint(`Transfer quality summary: ${await transferQualitySummary.textContent()}`);

		const layoverStatuses = detailsCard.getByTestId('layover-transfer-status');
		if (await layoverStatuses.count()) {
			await expect(layoverStatuses.first()).toContainText('transfer');
			logCheckpoint(`Layover transfer status: ${await layoverStatuses.first().textContent()}`);
		}

		const transferAmenities = detailsCard.getByTestId('transfer-amenities');
		if (await transferAmenities.count()) {
			await expect(transferAmenities.first().getByTestId('transfer-amenity-food-drink')).toBeVisible();
			await expect(transferAmenities.first().getByTestId('transfer-amenity-shops')).toBeVisible();
			await expect(transferAmenities.first().getByTestId('transfer-amenity-toilets')).toBeVisible();
			logCheckpoint(`Transfer amenities: ${await transferAmenities.first().textContent()}`);
		}

		// ── Verify booking CTA is pre-resolved (no loading state) ──
		// Train results have booking_url set directly, so the CTA should
		// immediately show a provider-specific "Book on ..." label without a /booking-link call.
		const bookingCta = page.getByTestId('booking-cta');
		await expect(bookingCta).toBeVisible({ timeout: 5000 });
		const ctaText = await bookingCta.textContent();
		expect(ctaText?.toLowerCase()).toContain('book on');
		expect(ctaText).toMatch(/Deutsche Bahn|FlixBus|FlixTrain/i);
		logCheckpoint(`Booking CTA: "${ctaText}" (pre-resolved, no API call needed).`);

		await takeStepScreenshot(page, 'train-fullscreen-verified');

		await closeFullscreen(page, page.getByTestId('embed-fullscreen-overlay').last());
		await closeFullscreen(page, fullscreenOverlay);
		await verifySavedMemoryEntry(page, 'travel', 'saved_connections', savedTitle, logCheckpoint);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'travel-train');
	});
});
