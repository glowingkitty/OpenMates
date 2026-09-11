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
	id: 'embeds-map-view-filter-calendar-figma-alignment',
	title: 'Embeds map view Filter and Calendar Figma alignment proof',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'carousel-context',
			text: 'The redesigned preview starts with a compact result carousel above the map.',
			checkpoint: 'carousel-context',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'calendar-tab-week',
			text: 'The Calendar view shows all five flights in a full Monday-first week.',
			checkpoint: 'calendar-tab-week',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'filter-panel',
			text: 'The Filter view replaces the results with a dedicated panel showing the result count and available controls.',
			checkpoint: 'filter-panel',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'local-route-filter',
			text: 'Selecting Qatar Airways narrows the shared result set from five flights to two.',
			checkpoint: 'local-route-filter',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'carousel-context',
			checkpoint: 'carousel-context',
			visual: 'The initial view shows the compact result carousel above the map before switching into Calendar and Filter proof states.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'calendar-tab-week',
			checkpoint: 'calendar-tab-week',
			visual: 'The Calendar tab is selected and the complete Monday-first weekly calendar visibly contains all five flight results with contained week navigation.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'filter-panel',
			checkpoint: 'filter-panel',
			visual: 'The dedicated Filter panel is visible with five of five results, Price and Carrier controls, and no Map or Calendar content showing through.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'local-route-filter',
			checkpoint: 'local-route-filter',
			visual: 'The Qatar carrier chip is selected and the Filter summary visibly shows two of five results remain.',
			devices: ['web-laptop', 'web-phone']
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

        const markerIcons = mapPane.locator('.leaflet-marker-icon svg.embed-map-pin');
        await expect(markerIcons.first()).toBeVisible();
        expect(await mapPane.locator('.leaflet-marker-icon').count()).toBe(await markerIcons.count());
        const pinAppearance = await markerIcons.evaluateAll((icons) => {
            const probe = document.createElement('span');
            probe.style.color = 'var(--color-app-travel-start)';
            icons[0].parentElement!.appendChild(probe);
            const expectedColor = getComputedStyle(probe).color;
            probe.remove();
            return icons.map((icon) => {
                const style = getComputedStyle(icon);
                return { color: style.color, expectedColor, background: style.backgroundImage, mask: style.maskImage };
            });
        });
        for (const pin of pinAppearance) {
            expect(pin.color).toBe(pin.expectedColor);
            expect(pin.background).toBe('none');
            expect(pin.mask).toBe('none');
        }
        const attribution = mapPane.locator('.leaflet-control-attribution');
        const attributionSize = await attribution.evaluate((element) => ({
            text: parseFloat(getComputedStyle(element).fontSize),
            link: parseFloat(getComputedStyle(element.querySelector('a')!).fontSize),
        }));
        expect(attributionSize.text).toBeLessThanOrEqual(12);
        expect(attributionSize.link).toBeLessThanOrEqual(12);


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
		expect(visualTabsBox!.width).toBeCloseTo(170, 0);
		const tabButtons = visualTabs.getByRole('tab');
		expect((await tabButtons.first().boundingBox())?.width).toBeCloseTo(85, 0);
		expect((await tabButtons.last().boundingBox())?.width).toBeCloseTo(85, 0);
		expect(await mapView.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe('rgb(243, 243, 243)');
		const calendarTab = mapView.getByTestId('embeds-results-view-tab-calendar');
		if (proof) {
			await proof.assert('carousel-context', async () => {
				await expect(carousel).toBeVisible();
				await expect(cards).toHaveCount(5);
				await expect(mapPane).toHaveAttribute('data-map-hydrated', 'true');
			});
			await proof.checkpoint('carousel-context');
			await proof.action('open-calendar-tab', async () => {
				await calendarTab.click();
			});
		} else {
			await calendarTab.click();
		}
		await expect(mapView.getByTestId('embeds-results-view-pane')).toHaveAttribute('data-active-tab', 'calendar');
		const calendarItems = mapView.getByTestId('embeds-results-view-calendar-item');
		await expect(calendarItems).toHaveCount(5);
        // A timed block must occupy its scheduled duration, not a fixed card height.
        const eventGeometry = await calendarItems.evaluateAll((elements) => elements.map((element) => {
            const style = getComputedStyle(element);
            const start = Number((element as HTMLElement).dataset.startMinutes);
            const end = Number((element as HTMLElement).dataset.endMinutes);
            const hourHeight = parseFloat(style.getPropertyValue('--calendar-hour-height'));
            return { actual: element.getBoundingClientRect().height, expected: (end - start) / 60 * hourHeight };
        }));
        for (const geometry of eventGeometry) {
            expect(geometry.expected).toBeGreaterThan(0);
            expect(Math.abs(geometry.actual - geometry.expected)).toBeLessThanOrEqual(2);
        }

		await expect(mapView.getByTestId('embeds-results-view-calendar-week')).toBeVisible();
		await expect(mapView.getByTestId('embeds-results-view-calendar-day')).toHaveCount(7);
		await expect(mapView.getByTestId('embeds-results-view-calendar-week-label')).toContainText('Apr 13');
		await expect(mapView.getByRole('button', { name: 'Previous week', exact: true })).toBeDisabled();
		await expect(mapView.getByRole('button', { name: 'Next week', exact: true })).toBeDisabled();
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
		const filterButton = mapView.getByTestId('embeds-map-view-filter-button');
		await expect(filterButton).toBeVisible();
		await expect(filterButton).toHaveAttribute('data-icon', 'filter');
		const filterButtonBox = await filterButton.boundingBox();
		expect(filterButtonBox, 'filter button box should exist').not.toBeNull();
		expect(filterButtonBox!.y).toBeLessThan(mapViewBox!.y);
		expect(filterButtonBox!.y + filterButtonBox!.height).toBeGreaterThan(mapViewBox!.y);
		expect(filterButtonBox!.width).toBeCloseTo(42, 0);
		expect(filterButtonBox!.height).toBeCloseTo(42, 0);
		expect(await filterButton.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe('rgb(255, 255, 255)');
		if (proof) {
			await proof.action('open-filter-panel', async () => {
				await mapTab.click();
				await expect(mapView.getByTestId('embeds-results-view-pane')).toHaveAttribute('data-active-tab', 'map');
				await filterButton.click();
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

		if (!proof) {
			await filterButton.click();
		}
		const filterMenu = mapView.getByTestId('embeds-map-view-filter-menu');
		await expect(filterButton).toHaveAttribute('data-icon', 'close');
		await expect(filterMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('5 of 5 results remain');
		await expect(filterMenu.getByTestId('embeds-map-view-filter-controls')).toBeVisible();
		await expect(filterMenu).toHaveAttribute('data-layout', 'results-panel');
        const filterLayout = await filterMenu.evaluate((panel: HTMLElement) => {
            const summary = panel.querySelector<HTMLElement>('.filter-menu-summary')!;
            const controls = panel.querySelector<HTMLElement>('[data-testid="embeds-map-view-filter-controls"]')!;
            const before = summary.getBoundingClientRect();
            controls.scrollTop = 100;
            const after = summary.getBoundingClientRect();
            controls.scrollTop = 0;
            return {
                width: panel.clientWidth,
                summaryRight: before.right,
                controlsLeft: controls.getBoundingClientRect().left,
                summaryMovement: after.top - before.top,
            };
        });
        expect(filterLayout.summaryMovement).toBe(0);
        if (filterLayout.width > 520) expect(filterLayout.summaryRight).toBeLessThanOrEqual(filterLayout.controlsLeft);
        const rangeMin = filterMenu.locator('input[type="range"]').first();
        const rangeMax = filterMenu.locator('input[type="range"]').nth(1);
        expect((await rangeMin.boundingBox())!.y).toBeCloseTo((await rangeMax.boundingBox())!.y, 0);

        // Exercise real pointer dragging (native input.fill bypasses Safari hit testing).
        for (const rail of await filterMenu.locator('.range-controls').all()) {
            await rail.scrollIntoViewIfNeeded();
            const box = (await rail.boundingBox())!;
            const minimum = rail.locator('input.lower');
            const maximum = rail.locator('input.upper');
            const initialMin = Number(await minimum.inputValue());
            const initialMax = Number(await maximum.inputValue());
            if (initialMin === initialMax) continue;
            const left = box.x + 14;
            const right = box.x + box.width - 14;
            const y = box.y + box.height / 2;
            await page.mouse.move(left, y);
            await page.mouse.down();
            await page.mouse.move(left + (right - left) * 0.25, y, { steps: 8 });
            await page.mouse.up();
            expect(Number(await minimum.inputValue())).toBeGreaterThan(initialMin);
            await page.mouse.move(right, y);
            await page.mouse.down();
            await page.mouse.move(left + (right - left) * 0.75, y, { steps: 8 });
            await page.mouse.up();
            expect(Number(await maximum.inputValue())).toBeLessThan(initialMax);
        }
        await filterMenu.getByTestId('embeds-map-view-clear-filters').click();
        await filterMenu.getByTestId('embeds-map-view-filter-controls').evaluate((controls) => { controls.scrollTop = 0; });

		await expect(filterMenu).toContainText('Price');
		await expect(filterMenu).toContainText('Carrier');
		if (proof) {
			await proof.assert('filter-panel', async () => {
				await expect(filterMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('5 of 5 results remain');
				await expect(filterMenu.getByTestId('embeds-map-view-filter-controls')).toBeVisible();
				await expect(filterMenu).toContainText('Price');
				await expect(filterMenu).toContainText('Carrier');
			});
			await proof.checkpoint('filter-panel');
		}
		const qatarCarrier = filterMenu.getByTestId('embeds-map-view-option-carrier-qr');
		if (proof) {
			await proof.action('select-route-filter', async () => {
				for (const option of await filterMenu.locator('[data-testid^="embeds-map-view-option-carrier-"]').all()) {
 if (await option.getAttribute('data-testid') !== 'embeds-map-view-option-carrier-qr') await option.click();
}
			});
		} else {
			for (const option of await filterMenu.locator('[data-testid^="embeds-map-view-option-carrier-"]').all()) {
 if (await option.getAttribute('data-testid') !== 'embeds-map-view-option-carrier-qr') await option.click();
}
		}
		await expect(filterMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('2 of 5 results remain');
		await expect(qatarCarrier).toHaveAttribute('aria-checked', 'true');
		if (proof) {
			await proof.assert('local-route-filter', async () => {
				await expect(filterMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('2 of 5 results remain');
				await expect(qatarCarrier).toHaveAttribute('aria-checked', 'true');
			});
			await proof.checkpoint('local-route-filter');
		}
		await filterButton.click();
		await expect(filterButton).toHaveAttribute('data-icon', 'filter');
		await expect(cards).toHaveCount(2);
		await expect(mapPane).toHaveAttribute('data-route-count', '2');
		await expect(mapPane).toHaveAttribute('data-marker-count', '3');

		const sharedStop = mapPane.locator('[data-marker-label="Hamad International Airport (DOH)"]');
		await expect(sharedStop).toHaveCount(1);
		await sharedStop.click();
		await expect(cards).toHaveCount(2);
		await expect(mapPane).toContainText('Hamad International Airport (DOH)');
		await expect(mapPane).toHaveAttribute('data-route-count', '2');
		await mapView.getByTestId('embeds-map-view-show-all-results').click();
		await expect(cards).toHaveCount(2);

		await filterButton.click();
		const resetMenu = mapView.getByTestId('embeds-map-view-filter-menu');
		await resetMenu.getByTestId('embeds-map-view-clear-filters').click();
		await expect(resetMenu.getByTestId('embeds-map-view-filter-summary')).toContainText('5 of 5 results remain');
		await filterButton.click();
		await expect(filterButton).toHaveAttribute('data-icon', 'filter');
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
		}
		if (!proof) {
			await calendarTab.click();
			const mobileWeekLabel = mapView.getByTestId('embeds-results-view-calendar-week-label');
			await expect(mobileWeekLabel).toContainText('Week 16 2026');
			expect(await mobileWeekLabel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
			const mobileMapViewBox = await mapView.boundingBox();
			const previousWeekBox = await mapView.getByRole('button', { name: 'Previous week' }).boundingBox();
			const nextWeekBox = await mapView.getByRole('button', { name: 'Next week' }).boundingBox();
			expect(mobileMapViewBox, 'mobile map view box should exist').not.toBeNull();
			expect(previousWeekBox, 'previous week button box should exist').not.toBeNull();
			expect(nextWeekBox, 'next week button box should exist').not.toBeNull();
			expect(previousWeekBox!.x).toBeGreaterThanOrEqual(mobileMapViewBox!.x);
			expect(nextWeekBox!.x + nextWeekBox!.width).toBeLessThanOrEqual(mobileMapViewBox!.x + mobileMapViewBox!.width);
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
