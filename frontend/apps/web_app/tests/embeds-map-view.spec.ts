import { expect, test } from './helpers/cookie-audit';

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

	test('renders source-backed refs responsively without app-skill or embed API calls', async ({ page }) => {
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
		await expect(mapView).toBeVisible({ timeout: 30_000 });
		await expect(mapView).toHaveAttribute('aria-label', 'Berlin AI events and routes');

		const cards = mapView.getByTestId('embeds-map-view-card');
		await expect(cards).toHaveCount(3, { timeout: 15_000 });
		await expect(cards.first()).toContainText('Factory Berlin');
		await expect(cards.first()).toHaveAttribute('data-highlighted', 'true');
		await expect(cards.first()).toHaveAttribute('data-entry-category', 'place');

		const filterButton = mapView.getByTestId('embeds-map-view-filter-button');
		await expect(filterButton).toBeVisible();
		await filterButton.click();
		const filterMenu = mapView.getByTestId('embeds-map-view-filter-menu');
		await expect(filterMenu).toContainText('event');
		await expect(filterMenu).toContainText('place');
		await expect(filterMenu).toContainText('route');
		await filterMenu.getByRole('menuitemradio', { name: 'route' }).click();
		await expect(cards).toHaveCount(1);
		await expect(cards.first()).toContainText('Berlin Hbf');
		await filterButton.click();
		await mapView
			.getByTestId('embeds-map-view-filter-menu')
			.getByRole('menuitemradio', { name: 'All results' })
			.click();
		await expect(cards).toHaveCount(3);

		await cards.nth(1).hover();
		await expect(cards.nth(1)).toHaveAttribute('data-hovered', 'true');

		const desktopListBox = await mapView.getByTestId('embeds-map-view-list').boundingBox();
		const desktopMapBox = await mapView.getByTestId('embeds-map-view-map').boundingBox();
		expect(desktopListBox, 'desktop list box should exist').not.toBeNull();
		expect(desktopMapBox, 'desktop map box should exist').not.toBeNull();
		expect(desktopMapBox!.x).toBeGreaterThan(desktopListBox!.x);
		expect(desktopMapBox!.width).toBeGreaterThan(desktopListBox!.width);

		await page.getByRole('button', { name: /Mobile\s+375px/ }).click();
		await expect(page.getByTestId('preview-status-bar')).toContainText('375px');
		const mobileListBox = await mapView.getByTestId('embeds-map-view-list').boundingBox();
		const mobileMapBox = await mapView.getByTestId('embeds-map-view-map').boundingBox();
		expect(mobileListBox, 'mobile list box should exist').not.toBeNull();
		expect(mobileMapBox, 'mobile map box should exist').not.toBeNull();
		expect(mobileMapBox!.y).toBeGreaterThan(mobileListBox!.y);
		expect(mobileListBox!.width).toBeLessThanOrEqual(390);

		expect(forbiddenApiCalls).toEqual([]);
	});

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
