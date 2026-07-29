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
		await expect(mapView).toContainText('Berlin AI events and routes');

		const cards = mapView.getByTestId('embeds-map-view-card');
		await expect(cards).toHaveCount(3, { timeout: 15_000 });
		await expect(cards.first()).toContainText('Factory Berlin');
		await expect(cards.first()).toHaveAttribute('data-highlighted', 'true');
		await expect(cards.first()).toHaveAttribute('data-entry-category', 'place');

		const filters = mapView.getByTestId('embeds-map-view-filters');
		await expect(filters).toContainText('event');
		await expect(filters).toContainText('place');
		await expect(filters).toContainText('route');
		await filters.getByRole('button', { name: 'route' }).click();
		await expect(cards).toHaveCount(1);
		await expect(cards.first()).toContainText('Berlin Hbf');
		await filters.getByRole('button', { name: 'All' }).click();
		await expect(cards).toHaveCount(3);

		await cards.nth(1).hover();
		await expect(cards.nth(1)).toHaveAttribute('data-selected', 'true');

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
});
