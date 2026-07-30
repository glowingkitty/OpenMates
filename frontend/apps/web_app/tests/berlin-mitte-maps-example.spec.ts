/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public example-chat coverage for the Berlin Mitte Maps example.
 *
 * The example is generated from a real OpenMates CLI chat and checked in as
 * static public data. The test verifies the deployed page renders messages,
 * Maps search embeds, the inline map-view block, and parent/child fullscreens.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { closeFullscreen, openFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');

const EXAMPLE_SLUG = 'berlin-mitte-work-friendly-restaurants';
const EXAMPLE_CHAT_ID = 'example-berlin-mitte-work-friendly';
const MAPS_SEARCH_SELECTOR = '[data-testid="embed-preview"][data-app-id="maps"][data-skill-id="search"][data-status="finished"]';
const PRIVATE_MARKERS = [
	'#key=',
	'vault_key_id',
	'user_id',
	'vault:v1:',
	'encrypted_content',
	'encrypted_key',
	'dev-openmates-chatfiles',
	'chatfiles/'
];

test.describe('Berlin Mitte Maps public example', () => {
	test('renders messages, maps embeds, map view, fullscreens, and reloads', async ({
		page,
		request
	}: {
		page: any;
		request: any;
	}) => {
		test.setTimeout(150_000);

		const response = await request.get(`/example/${EXAMPLE_SLUG}`);
		expect(response.status(), 'public example page should be reachable').toBe(200);
		const html = await response.text();
		expect(html).toContain('Berlin Mitte Work-Friendly Restaurants Map');
		expect(html).toContain('air conditioning and free Wi-Fi');
		expect(html).toContain('St. Oberholz');
		expect(html).toContain('OpenStreetMap');
		for (const marker of PRIVATE_MARKERS) {
			expect(html, `public HTML should not expose ${marker}`).not.toContain(marker);
		}

		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(getE2EDebugUrl(`/example/${EXAMPLE_SLUG}`), {
			waitUntil: 'domcontentloaded'
		});
		await expect(page).toHaveURL(new RegExp(`#chat-id=${EXAMPLE_CHAT_ID}$`), {
			timeout: 20_000
		});

		await expect(page.getByTestId('user-message-content').filter({
			hasText: 'air conditioning and free Wi-Fi'
		})).toBeVisible({ timeout: 15_000 });

		const assistantMessage = page
			.getByTestId('message-assistant')
			.filter({ hasText: 'Finding a spot in Berlin Mitte' })
			.first();
		await expect(assistantMessage).toBeVisible({ timeout: 30_000 });
		await expect(assistantMessage).toContainText('verified versus what is unknown');
		await expect(assistantMessage).not.toContainText('"type":"app_skill_use"');

		const mapView = assistantMessage.getByTestId('embeds-map-view');
		await expect(mapView).toBeVisible({ timeout: 30_000 });
		await expect(mapView).toContainText('St. Oberholz');
		await expect(mapView.getByTestId('embeds-map-view-card')).toHaveCount(3, { timeout: 15_000 });
		await expect(mapView.getByTestId('embeds-map-view-map')).toBeVisible({ timeout: 15_000 });

		const mapsSearchCards = assistantMessage.locator(MAPS_SEARCH_SELECTOR);
		await expect.poll(async () => mapsSearchCards.count(), {
			message: 'Berlin Mitte example should render both Maps search parent embeds',
			timeout: 20_000
		}).toBe(2);

		const resultsCard = mapsSearchCards.filter({ hasText: 'cafe restaurant with wifi Berlin Mitte' }).first();
		await expect(resultsCard).toBeVisible({ timeout: 15_000 });

		const noResultsCard = mapsSearchCards.filter({ hasText: 'restaurant Berlin Mitte' }).last();
		await expect(noResultsCard).toBeVisible({ timeout: 15_000 });

		const resultsOverlay = await openFullscreen(page, resultsCard);
		await expect(resultsOverlay.getByTestId('embed-header-title')).toContainText(
			'cafe restaurant with wifi Berlin Mitte',
			{ timeout: 15_000 }
		);
		const resultCards = await verifySearchGrid(resultsOverlay, 3, 30_000);
		await expect(resultCards.first()).toContainText(/St\. Oberholz|Cafe Latrio|Father Carpenter/i);

		await resultCards.first().click({ force: true });
		await expect(page.getByTestId('map-location-fullscreen')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('map-location-fullscreen')).toContainText(/Berlin|Rosenthaler|Monbijou|Münzstraße/i);
		await closeFullscreen(page, page.getByTestId('embed-fullscreen-overlay').last());
		await closeFullscreen(page, resultsOverlay);

		const noResultsOverlay = await openFullscreen(page, noResultsCard);
		await expect(noResultsOverlay.getByTestId('embed-header-title')).toContainText('restaurant Berlin Mitte');
		await expect(noResultsOverlay.getByTestId('maps-no-results')).toBeVisible({ timeout: 15_000 });
		await closeFullscreen(page, noResultsOverlay);

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant').filter({
			hasText: 'St. Oberholz'
		})).toBeVisible({ timeout: 30_000 });
	});
});
