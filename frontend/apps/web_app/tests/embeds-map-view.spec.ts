import { expect, test } from './helpers/cookie-audit';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

/**
 * Deployed preview coverage for the virtual `embeds_map_view` renderer.
 * The route uses static local embed fixtures from `EmbedsMapView.preview.ts`, so
 * this verifies browser rendering without auth, private share keys, or paid
 * app-skill/provider calls.
 */

const PREVIEW_SERVER_STATUS = {
	is_self_hosted: false,
	payment_enabled: true,
	server_edition: 'development',
	domain: 'openmates.org',
	ai_models_configured: true,
	free_testing_credits: null,
	anonymous_free_usage: null
};

const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const PROOF_CLEAN_PREVIEW_STYLE = `
html[data-map-view-proof-clean='true'] .toolbar,
html[data-map-view-proof-clean='true'] .variant-bar,
html[data-map-view-proof-clean='true'] .status-bar {
	display: none !important;
}

html[data-map-view-proof-clean='true'] .preview-page {
	height: 100vh !important;
	overflow: hidden !important;
}

html[data-map-view-proof-clean='true'] .preview-layout,
html[data-map-view-proof-clean='true'] .preview-container,
html[data-map-view-proof-clean='true'] .preview-viewport {
	min-height: 100vh !important;
}

html[data-map-view-proof-clean='true'] .preview-container {
	padding: 12px !important;
	overflow: auto !important;
}
`;

const EMBEDS_MAP_VIEW_PROOF_CONTRACT = defineVideoProof({
	id: 'embeds-map-view-figma-alignment',
	title: 'Embeds map view Figma alignment proof',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'map-carousel-previews',
			text: 'The map results view opens with reusable embed previews grouped in a horizontal carousel.',
			checkpoint: 'map-carousel-previews',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'calendar-tab-week',
			text: 'The map state switches into a full weekly calendar with the same flight results.',
			checkpoint: 'calendar-tab-week',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'local-route-filter',
			text: 'Selecting Qatar Airways in the local filter narrows the view from five flights to two.',
			checkpoint: 'local-route-filter',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'local-filter-reset',
			text: 'The filter can return the view to all five results.',
			checkpoint: 'local-filter-reset',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'mobile-carousel-map-layout',
			text: 'On phone, the carousel stays above the hydrated map and remains within the narrow layout.',
			checkpoint: 'mobile-carousel-map-layout',
			devices: ['web-phone']
		}
	],
	assertions: [
		{
			id: 'map-carousel-previews',
			checkpoint: 'map-carousel-previews',
			visual: 'The map view is visible with reusable embed preview cards in a horizontal carousel above a hydrated map.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'calendar-tab-week',
			checkpoint: 'calendar-tab-week',
			visual: 'The Calendar tab is selected and a full weekly calendar with the flight results is visible.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'local-route-filter',
			checkpoint: 'local-route-filter',
			visual: 'The Qatar carrier chip is selected and the filter summary visibly shows two of five results remain.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'local-filter-reset',
			checkpoint: 'local-filter-reset',
			visual: 'The filter summary shows all five results are available again.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'mobile-carousel-map-layout',
			checkpoint: 'mobile-carousel-map-layout',
			visual: 'The phone-width layout keeps the preview carousel above the hydrated map without horizontal overflow.',
			devices: ['web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function getMapTileThemeState(map: any): Promise<'dark' | 'light' | 'missing'> {
	return map.evaluate((element: HTMLElement) => {
		const classedElements = Array.from(element.querySelectorAll('[class]')) as HTMLElement[];
		const hasLeafletMap = classedElements.some((node) => node.classList.contains('leaflet-container'));
		if (!hasLeafletMap) return 'missing';

		const hasDarkTiles = classedElements.some((node) =>
			node.classList.contains('dark-tiles')
		);
		return hasDarkTiles ? 'dark' : 'light';
	});
}

test.describe('Embeds map view preview', () => {
	test.beforeEach(async ({ page }) => {
		await page.route('**/v1/settings/server-status', async (route) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(PREVIEW_SERVER_STATUS)
			});
		});
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('renders source-backed refs responsively without app-skill or embed API calls', async ({ page }, testInfo) => {
		test.setTimeout(90_000);

		const forbiddenApiCalls: string[] = [];
		const forbiddenEndpointPattern = /\/v1\/(?:apps|app-skills|skills|chat|chats|messages|embeds|applications)\b/;
		page.on('request', (request) => {
			const url = request.url();
			if (forbiddenEndpointPattern.test(url)) {
				forbiddenApiCalls.push(`${request.method()} ${url}`);
			}
		});

		await page.goto('/dev/preview/embeds/EmbedsMapView', { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('breadcrumb-name')).toHaveText('EmbedsMapView');

		const mapView = page.getByTestId('embeds-map-view');
		const mapPane = mapView.getByTestId('embeds-map-view-map');
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(EMBEDS_MAP_VIEW_PROOF_CONTRACT, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;
		if (proof) {
			await page.addStyleTag({ content: PROOF_CLEAN_PREVIEW_STYLE });
			await page.evaluate(() => {
				document.documentElement.dataset.mapViewProofClean = 'true';
			});
		}
		await expect(mapView).toBeVisible({ timeout: 30_000 });
		await expect(mapView).toHaveAttribute('aria-label', 'Berlin to Bangkok flight options');
		await expect(mapPane).toHaveAttribute('data-map-hydrated', 'true', { timeout: 15_000 });

		const carousel = mapView.getByTestId('embeds-map-view-carousel');
		await expect(carousel).toBeVisible();
		const cards = mapView.getByTestId('embeds-map-view-card');
		await expect(cards).toHaveCount(5, { timeout: 15_000 });
		await expect(cards.getByTestId('embed-preview')).toHaveCount(5);
		await expect(cards.first()).toContainText('Berlin (BER)');
		await expect(cards.first()).toContainText('Bangkok (BKK)');
		await expect(cards.first()).toHaveAttribute('data-highlighted', 'true');
		await expect(cards.first()).toHaveAttribute('data-entry-category', 'route');
		await expect(cards.getByTestId('connection-preview-details')).toHaveCount(5);
		await expect(mapView).not.toContainText('Search connections');
		await expect(mapView).not.toContainText('0 connections');
		if (proof) {
			await proof.assert('map-carousel-previews', async () => {
				await expect(carousel).toBeVisible();
				await expect(cards.first()).toContainText('Berlin (BER)');
				await expect(mapPane).toHaveAttribute('data-map-hydrated', 'true');
			});
			await proof.checkpoint('map-carousel-previews');
		}

		const visualTabs = mapView.getByTestId('embeds-results-view-tabs');
		await expect(visualTabs).toBeVisible();
		await expect(visualTabs).toContainText('Map');
		await expect(visualTabs).toContainText('Calendar');
		await expect(mapView.getByTestId('embeds-results-view-tab-list')).toHaveCount(0);
		const mapViewBox = await mapView.boundingBox();
		const visualTabsBox = await visualTabs.boundingBox();
		expect(mapViewBox, 'map view box should exist').not.toBeNull();
		expect(visualTabsBox, 'visual tabs box should exist').not.toBeNull();
		expect(visualTabsBox!.y).toBeLessThan(mapViewBox!.y);
		expect(visualTabsBox!.y + visualTabsBox!.height).toBeGreaterThan(mapViewBox!.y);
		expect(await mapView.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe('rgb(243, 243, 243)');
		const calendarTab = mapView.getByTestId('embeds-results-view-tab-calendar');
		if (proof) {
			await proof.action('open-calendar-tab', async () => {
				await calendarTab.click();
			});
		} else {
			await calendarTab.click();
		}
		await expect(mapView.getByTestId('embeds-results-view-pane')).toHaveAttribute('data-active-tab', 'calendar');
		const calendarItems = mapView.getByTestId('embeds-results-view-calendar-item');
		await expect(calendarItems).toHaveCount(5);
		await expect(mapView.getByTestId('embeds-results-view-calendar-week')).toBeVisible();
		await expect(mapView.getByTestId('embeds-results-view-calendar-day')).toHaveCount(7);
		await expect(mapView.getByTestId('embeds-results-view-calendar-week-label')).toContainText('Apr 13');
		await expect(calendarItems.filter({ hasText: 'Berlin (BER)' })).toHaveCount(5);
		await expect(cards).toHaveCount(0);
		if (PROOF_DEVICE === 'web-phone') {
			const calendar = mapView.getByTestId('embeds-results-view-calendar');
			const firstCalendarDayBox = await mapView.getByTestId('embeds-results-view-calendar-day').first().boundingBox();
			expect(firstCalendarDayBox?.width).toBeGreaterThanOrEqual(88);
			expect(await calendar.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
		}
		if (proof) {
			await proof.assert('calendar-tab-week', async () => {
				await expect(mapView.getByTestId('embeds-results-view-calendar-week')).toBeVisible();
				await expect(calendarItems.filter({ hasText: 'Berlin (BER)' })).toHaveCount(5);
			});
			await proof.checkpoint('calendar-tab-week');
		}
		const mapTab = mapView.getByTestId('embeds-results-view-tab-map');
		if (proof) {
			await proof.action('return-to-map-tab', async () => {
				await mapTab.click();
			});
		} else {
			await mapTab.click();
		}
		await expect(mapView.getByTestId('embeds-results-view-pane')).toHaveAttribute('data-active-tab', 'map');
		await expect(mapPane).toHaveAttribute('data-map-hydrated', 'true');
		await expect(cards).toHaveCount(5);
		await expect(mapPane).toHaveAttribute('data-marker-count', '6');
		await expect(mapPane).toHaveAttribute('data-endpoint-marker-count', '2');
		await expect(mapPane).toHaveAttribute('data-stop-marker-count', '4');
		const zoomControls = mapPane.getByTestId('embed-map-zoom-controls');
		await expect(zoomControls).toBeVisible();

		const filterButton = mapView.getByTestId('embeds-map-view-filter-button');
		await expect(filterButton).toBeVisible();
		const filterButtonBox = await filterButton.boundingBox();
		expect(filterButtonBox, 'filter button box should exist').not.toBeNull();
		expect(filterButtonBox!.y).toBeLessThan(mapViewBox!.y);
		expect(filterButtonBox!.y + filterButtonBox!.height).toBeGreaterThan(mapViewBox!.y);
		expect(await filterButton.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe('rgb(255, 255, 255)');
		if (proof) {
			await proof.action('open-filter-menu', async () => {
				await filterButton.click();
			});
		} else {
			await filterButton.click();
		}
		const filterMenu = mapView.getByTestId('embeds-map-view-filter-menu');
		await expect(filterMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('5 of 5 results remain');
		await expect(filterMenu.getByTestId('embeds-map-view-filter-controls')).toBeVisible();
		await expect(filterMenu).toHaveAttribute('data-layout', 'results-panel');
		await expect(filterMenu).toContainText('route');
		await expect(filterMenu).toContainText('Price');
		await expect(filterMenu).toContainText('Carrier');
		const qatarCarrier = filterMenu.getByTestId('embeds-map-view-option-carrier-qr');
		if (proof) {
			await proof.action('select-route-filter', async () => {
				await qatarCarrier.click();
			});
		} else {
			await qatarCarrier.click();
		}
		await expect(filterMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('2 of 5 results remain');
		await expect(qatarCarrier).toHaveAttribute('aria-pressed', 'true');
		if (proof) {
			await proof.assert('local-route-filter', async () => {
				await expect(filterMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('2 of 5 results remain');
				await expect(qatarCarrier).toHaveAttribute('aria-pressed', 'true');
			});
			await proof.checkpoint('local-route-filter');
		}
		const resetMenu = mapView.getByTestId('embeds-map-view-filter-menu');
		if (proof) {
			await proof.action('select-all-results', async () => {
				await resetMenu.getByTestId('embeds-map-view-clear-filters').click();
			});
		} else {
			await resetMenu.getByTestId('embeds-map-view-clear-filters').click();
		}
		await expect(resetMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('5 of 5 results remain');
		if (proof) {
			await proof.assert('local-filter-reset', async () => {
				await expect(resetMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('5 of 5 results remain');
			});
			await proof.checkpoint('local-filter-reset');
		}
		await filterButton.click();
		await expect(cards).toHaveCount(5);

		await cards.nth(1).hover();
		await expect(cards.nth(1)).toHaveAttribute('data-hovered', 'true');

		const desktopListBox = await carousel.boundingBox();
		const desktopMapBox = await mapView.getByTestId('embeds-map-view-map').boundingBox();
		expect(desktopListBox, 'desktop list box should exist').not.toBeNull();
		expect(desktopMapBox, 'desktop map box should exist').not.toBeNull();
		expect(desktopMapBox!.y).toBeGreaterThan(desktopListBox!.y);
		expect(desktopListBox!.width).toBeGreaterThanOrEqual(desktopMapBox!.width - 2);
		expect(desktopMapBox!.width).toBeLessThanOrEqual(652);
		const firstCardBox = await cards.first().boundingBox();
		expect(firstCardBox?.width).toBeCloseTo(300, 0);
		expect(firstCardBox?.height).toBeCloseTo(200, 0);
		const zoomBox = await zoomControls.boundingBox();
		expect(zoomBox, 'zoom controls should exist').not.toBeNull();
		expect(zoomBox!.x).toBeLessThan(desktopMapBox!.x + desktopMapBox!.width / 2);

		if (!proof) {
			await page.getByRole('button', { name: /Mobile\s+375px/ }).click();
			await expect(page.getByTestId('preview-status-bar')).toContainText('375px');
		}
		if (!proof || PROOF_DEVICE === 'web-phone') {
			const mobileListBox = await carousel.boundingBox();
			const mobileMapBox = await mapView.getByTestId('embeds-map-view-map').boundingBox();
			expect(mobileListBox, 'mobile list box should exist').not.toBeNull();
			expect(mobileMapBox, 'mobile map box should exist').not.toBeNull();
			expect(mobileMapBox!.y).toBeGreaterThan(mobileListBox!.y);
			expect(mobileListBox!.width).toBeLessThanOrEqual(390);
			if (proof) {
				await proof.assert('mobile-carousel-map-layout', async () => {
					await expect(carousel).toBeVisible();
					await expect(mapPane).toHaveAttribute('data-map-hydrated', 'true');
				});
				await proof.checkpoint('mobile-carousel-map-layout');
			}
		}

		expect(forbiddenApiCalls).toEqual([]);
		if (proof) await proof.attach();
	});

	// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('uses manual light theme for OpenStreetMap tiles when OS is dark', async ({ page }) => {
		test.setTimeout(90_000);

		await page.emulateMedia({ colorScheme: 'dark' });
		await page.addInitScript(() => {
			localStorage.setItem('theme_mode', 'light');
			localStorage.setItem('theme', 'light');
		});

		await page.goto('/dev/preview/embeds/EmbedsMapView', { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('breadcrumb-name')).toHaveText('EmbedsMapView');
		await expect
			.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme')))
			.toBe('light');

		const map = page.getByTestId('embeds-map-view-map');
		await expect(map).toBeVisible({ timeout: 30_000 });
		await expect.poll(async () => getMapTileThemeState(map)).toBe('light');
	});
});
