/* eslint-disable @typescript-eslint/no-require-imports */

const { expect, test } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

/**
 * Public example-chat coverage for the `embeds_map_view` presentation block.
 *
 * The example is generated from a real OpenMates CLI chat and checked in as
 * static public data. The test verifies the deployed example page renders the
 * map/list view without calling app-skill, chat, message, or embed APIs.
 */

const EXAMPLE_SLUG = 'berlin-ai-founder-meetups-map';
const EXAMPLE_CHAT_ID = 'example-berlin-ai-founder-meetups';
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

test.describe('Embeds map view public examples', () => {
	test('renders the CLI-backed Berlin founder events map example without provider calls', async ({
		page,
		request
	}: {
		page: any;
		request: any;
	}) => {
		test.setTimeout(120_000);

		const response = await request.get(`/example/${EXAMPLE_SLUG}`);
		expect(response.status(), 'public example page should be reachable').toBe(200);
		const html = await response.text();
		expect(html).toContain('Berlin AI founder meetups map');
		expect(html).toContain('embeds_map_view');
		for (const marker of PRIVATE_MARKERS) {
			expect(html, `public HTML should not expose ${marker}`).not.toContain(marker);
		}

		const forbiddenApiCalls: string[] = [];
		const forbiddenEndpointPattern =
			/\/v1\/(?:apps|app-skills|skills|chat|chats|messages|embeds|applications)\b/;
		page.on('request', (requestEvent) => {
			const url = requestEvent.url();
			if (forbiddenEndpointPattern.test(url)) {
				forbiddenApiCalls.push(`${requestEvent.method()} ${url}`);
			}
		});

		await page.goto(getE2EDebugUrl(`/example/${EXAMPLE_SLUG}`), {
			waitUntil: 'domcontentloaded'
		});
		await expect(page).toHaveURL(new RegExp(`#chat-id=${EXAMPLE_CHAT_ID}$`), {
			timeout: 20_000
		});

		const assistantMessage = page.getByTestId('message-assistant').first();
		await expect(assistantMessage).toBeVisible({ timeout: 30_000 });
		await expect(assistantMessage).toContainText('Build Fridays Berlin', { timeout: 30_000 });

		const mapView = page.getByTestId('embeds-map-view');
		await expect(mapView).toBeVisible({ timeout: 30_000 });
		await expect(mapView).toContainText('Mapped results');
		await expect(mapView).toContainText('Build Fridays Berlin');

		const cards = mapView.getByTestId('embeds-map-view-card');
		await expect(cards).toHaveCount(4, { timeout: 15_000 });
		await expect(mapView.getByTestId('embeds-map-view-filters')).toContainText('event');
		await expect(mapView.getByTestId('embeds-map-view-map')).toBeVisible();

		expect(forbiddenApiCalls).toEqual([]);
	});
});
