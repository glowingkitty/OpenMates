/* eslint-disable @typescript-eslint/no-require-imports */
const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

const slug = 'social-app-name-domain-search';

for (const [viewport, size] of [
	['phone', { width: 390, height: 844 }],
	['laptop', { width: 1440, height: 1000 }]
] as const) {
	// contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.surface-parity,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test(`real Hosting naming example renders its complete domain graph on ${viewport}`, async ({
		page,
		request
	}: any, testInfo: any) => {
		test.setTimeout(120_000);
		const response = await request.get(`/example/${slug}`);
		expect(response.status()).toBe(200);
		const html = await response.text();
		expect(html).toContain('Orbitfolk');
		expect(html).toContain('Kinloop');
		for (const marker of [
			'vault:v1:',
			'aes_key',
			'aes_nonce',
			'example_chats.social_app_name_domain_search'
		]) {
			expect(html).not.toContain(marker);
		}

		await page.setViewportSize(size);
		await page.goto(`/example/${slug}`, { waitUntil: 'domcontentloaded' });
		const openChat = page.getByRole('link', {
			name: 'Open this conversation in OpenMates',
			exact: true
		});
		await expect(openChat).toBeVisible();
		const chatUrl = await openChat.getAttribute('href');
		expect(chatUrl).toContain('example-social-app-name-domain');
		const spaTarget = new URL(chatUrl, page.url());
		await page.goto(getE2EDebugUrl(spaTarget.pathname + spaTarget.search + spaTarget.hash), {
			waitUntil: 'domcontentloaded'
		});
		const parents = page
			.getByTestId('embed-preview')
			.filter({ has: page.getByTestId('hosting-search-preview') });
		await expect(async () => expect(await parents.count()).toBeGreaterThan(0)).toPass({
			timeout: 30_000
		});
		const parent = parents.first();
		await parent.scrollIntoViewIfNeeded();
		await expect(parent.locator('[data-app-icon="hosting"]').first()).toBeVisible();
		await expect(parent).toContainText('Gandi');
		await testInfo.attach(`hosting-example-${viewport}-preview`, {
			body: await parent.screenshot(),
			contentType: 'image/png'
		});
		const search = await openFullscreen(page, parent);
		await search.getByTestId('hosting-view-all').click();
		const domains = search.getByTestId('hosting-domain-grid').getByTestId('embed-preview');
		// Each of this real conversation's four groups checked 40 domains.
		await expect(domains).toHaveCount(40, { timeout: 30_000 });
		await testInfo.attach(`hosting-example-${viewport}-checked`, {
			body: await page.screenshot(),
			contentType: 'image/png'
		});
		await domains.first().click();
		const detail = page.getByTestId('hosting-domain-fullscreen');
		await expect(detail).toBeVisible();
		await expect(detail.getByTestId('hosting-domain-ascii')).toHaveText(/\.[a-z]+$/);
		await expect(detail.getByRole('link', { name: /Gandi/ })).toHaveAttribute(
			'href',
			/^https:\/\/shop\.gandi\.net\//
		);
		const bounds = await detail.getByTestId('hosting-domain-details').boundingBox();
		expect(bounds).toBeTruthy();
		expect(bounds.x).toBeGreaterThanOrEqual(-1);
		expect(bounds.x + bounds.width).toBeLessThanOrEqual(size.width + 1);
		await testInfo.attach(`hosting-example-${viewport}-domain`, {
			body: await page.screenshot(),
			contentType: 'image/png'
		});
		await detail.getByTestId('embed-fullscreen-close').click();
		await expect(detail).not.toBeVisible();
		await expect(search).toBeVisible();
		await closeFullscreen(page, search);
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(async () => expect(await parents.count()).toBeGreaterThan(0)).toPass({
			timeout: 30_000
		});
	});
}
