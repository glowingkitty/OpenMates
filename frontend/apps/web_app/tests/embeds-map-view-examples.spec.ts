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
		expect(html).toContain('Build Fridays Berlin');
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

		await page.setViewportSize({ width: 390, height: 844 });
		await page.emulateMedia({ colorScheme: 'dark' });
		await page.goto(getE2EDebugUrl(`/example/${EXAMPLE_SLUG}`), {
			waitUntil: 'domcontentloaded'
		});
		await expect(page).toHaveURL(new RegExp(`#chat-id=${EXAMPLE_CHAT_ID}$`), {
			timeout: 20_000
		});

		const assistantMessage = page.getByTestId('message-assistant').first();
		await expect(assistantMessage).toBeVisible({ timeout: 30_000 });
		await expect(assistantMessage).toContainText('Build Fridays Berlin', { timeout: 30_000 });
		await expect(assistantMessage, 'map-view source must not render as a generic code embed').not.toContainText(/Code snippet/i);
		await expect(assistantMessage, 'raw embeds_map_view fence must be consumed by the map-view renderer').not.toContainText(/embeds_map_view/i);

		const mapView = page.getByTestId('embeds-map-view');
		await expect(mapView).toBeVisible({ timeout: 30_000 });
		await expect(mapView).not.toContainText('Mapped results');
		await expect(mapView).not.toContainText('Map view');
		await expect(mapView).toContainText(/build fridays berlin/i);
		await expect(mapView.getByTestId('embeds-map-view-filter-button')).toBeVisible();
		await mapView.getByTestId('embeds-map-view-filter-button').click();
		await expect(mapView.getByTestId('embeds-map-view-filter-menu')).toBeVisible();
		await expect(mapView.getByTestId('embeds-map-view-filter-menu')).toContainText('event');
		await mapView.getByTestId('embeds-map-view-filter-button').click();
		await expect(mapView.getByTestId('embeds-map-view-filter-menu')).toBeHidden();

		const cards = mapView.getByTestId('embeds-map-view-card');
		await expect(cards).toHaveCount(4, { timeout: 15_000 });
		await expect(cards.first()).toHaveAttribute('data-highlighted', 'true');
		await expect(cards.first()).toHaveAttribute('data-entry-category', 'event');
		const mobileCardMetrics = await mapView.evaluate((element) => {
			function channelToLinear(channel: number): number {
				const normalized = channel / 255;
				return normalized <= 0.03928
					? normalized / 12.92
					: Math.pow((normalized + 0.055) / 1.055, 2.4);
			}

			function luminance(value: string): number {
				const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
				if (!match) return 0;
				const red = Number(match[1]);
				const green = Number(match[2]);
				const blue = Number(match[3]);
				return (
					0.2126 * channelToLinear(red) +
					0.7152 * channelToLinear(green) +
					0.0722 * channelToLinear(blue)
				);
			}

			const cardElements = Array.from(
				element.querySelectorAll<HTMLElement>('[data-testid="embeds-map-view-card"]')
			);
			const firstBox = cardElements[0]?.getBoundingClientRect();
			const secondBox = cardElements[1]?.getBoundingClientRect();
			const firstStyle = cardElements[0] ? getComputedStyle(cardElements[0]) : null;
			const foreground = firstStyle?.color || 'rgb(0, 0, 0)';
			const background = firstStyle?.backgroundColor || 'rgb(0, 0, 0)';
			const foregroundLum = luminance(foreground);
			const backgroundLum = luminance(background);
			const contrastRatio =
				(Math.max(foregroundLum, backgroundLum) + 0.05) /
				(Math.min(foregroundLum, backgroundLum) + 0.05);

			return {
				firstWidth: firstBox?.width || 0,
				firstHeight: firstBox?.height || 0,
				firstRight: firstBox?.right || 0,
				secondLeft: secondBox?.left || 0,
				contrastRatio
			};
		});
		expect(mobileCardMetrics.firstWidth).toBeGreaterThanOrEqual(220);
		expect(mobileCardMetrics.firstHeight).toBeGreaterThanOrEqual(80);
		expect(mobileCardMetrics.secondLeft).toBeGreaterThan(mobileCardMetrics.firstRight);
		expect(mobileCardMetrics.contrastRatio).toBeGreaterThan(3);
		await cards.nth(1).hover();
		await expect(cards.nth(1)).toHaveAttribute('data-hovered', 'true');
		await expect(cards.first()).toHaveAttribute('data-dimmed', 'true');
		await expect(mapView.getByTestId('embeds-map-view-map')).toBeVisible();
		await expect(mapView.getByTestId('embeds-map-view-map')).not.toContainText(
			'Referenced embeds do not expose coordinates yet.'
		);

		expect(forbiddenApiCalls).toEqual([]);
	});
});
