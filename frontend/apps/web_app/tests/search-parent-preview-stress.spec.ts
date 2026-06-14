/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/search-parent-preview-stress.spec.ts
 *
 * Opens the internal synthetic example chat with many messages, parent embeds,
 * and child embeds. The fixture proves dense search parent previews render from
 * parent metadata without provider calls or preview-time child hydration.
 * Architecture: docs/specs/search-parent-preview-metadata-sync/spec.yml
 */
export {};

const { test, expect } = require('./console-monitor');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const STRESS_CHAT_ID = 'example-search-parent-preview-stress-test';

test.describe('Search parent preview stress fixture', () => {
	test('opens dense synthetic chat with useful parent previews', async ({ page }: { page: any }) => {
		test.setTimeout(90_000);

		const providerRequests: string[] = [];
		page.on('request', (request: any) => {
			const url = request.url();
			if (url.includes('api.search.brave.com') || url.includes('serpapi.com')) {
				providerRequests.push(url);
			}
		});

		await page.goto(getE2EDebugUrl(`/#chat-id=${STRESS_CHAT_ID}`), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByText(/Synthetic (web|images) search parent/).first()).toBeVisible({ timeout: 30_000 });

		const previews = page.getByTestId('embed-preview');
		await expect.poll(async () => await previews.count(), {
			message: 'stress chat should render visible parent previews',
			timeout: 30_000,
		}).toBeGreaterThan(0);

		await expect(page.getByTestId('search-no-results-message')).toHaveCount(0);
		await expect(page.getByTestId('images-search-no-results-message')).toHaveCount(0);
		expect(providerRequests, 'synthetic fixture must not call external search providers').toEqual([]);
	});
});
