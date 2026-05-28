/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chats loading test: verifies that hardcoded example chats render
 * for NEW USERS (clean browser context, no IndexedDB cache) in the
 * for-everyone demo chat.
 *
 * Architecture: Example chats are now static/hardcoded in exampleChatStore.ts
 * (no backend /v1/demo/chats API call). The ExampleChatsGroup component reads
 * from getAllExampleChats() and renders chat embed cards.
 *
 * Test strategy:
 *   1. Open the app with a clean browser (simulating a brand-new user)
 *   2. Verify ExampleChatsGroup renders with actual chat cards
 *   3. Verify cards have titles and are clickable
 *
 * No credentials required — this tests the non-authenticated flow.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

function countMatches(text: string, pattern: RegExp): number {
	return [...text.matchAll(pattern)].length;
}

function extractExampleSlugs(html: string): string[] {
	const matches = [...html.matchAll(/href="\/example\/([^"]+)"/g)];
	return [...new Set(matches.map((match) => match[1]))];
}

function extractJsonLd(html: string): Record<string, any> {
	const match = html.match(/<script\s+type="application\/ld\+json">([\s\S]*?)<\/script>/i);
	expect(match, 'JSON-LD script should exist').not.toBeNull();
	return JSON.parse(match[1]);
}

test.describe('Example chats loading for new users', () => {
	test('example chats appear in for-everyone intro chat', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		// ─── Console logging for diagnostics ──────────────────────────────
		const consoleLogs: string[] = [];

		page.on('console', (message: any) => {
			const text = message.text();
			consoleLogs.push(`[${message.type()}] ${text}`);
		});

		// ─── Navigate as a fresh user (clean browser context) ───────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Allow time for the example chats component to render
		await page.waitForTimeout(5000);

		// ─── Verify the ExampleChatsGroup rendered with cards ────────────────
		const exampleChatsWrapper = page.getByTestId('example-chats-group-wrapper');
		const chatCards = page
			.getByTestId('example-chats-group')
			.locator('[data-testid="chat-embed-card"]');

		const wrapperCount = await exampleChatsWrapper.count();
		const cardCount = await chatCards.count();

		// Log diagnostics
		console.log('\n--- EXAMPLE CHATS DIAGNOSTICS ---');
		console.log(`ExampleChatsGroup wrappers found: ${wrapperCount}`);
		console.log(`Chat embed cards found: ${cardCount}`);

		const exampleLogs = consoleLogs.filter(
			(l) =>
				l.includes('ExampleChatsGroup') ||
				l.includes('exampleChat') ||
				l.includes('example chat')
		);
		console.log(`\nRelevant console logs (${exampleLogs.length}):`);
		exampleLogs.forEach((l) => console.log(`  ${l}`));
		console.log('--- END DIAGNOSTICS ---\n');

		// ─── Assertions ─────────────────────────────────────────────────────

		// The ExampleChatsGroup wrapper must exist
		expect(wrapperCount, 'ExampleChatsGroup wrapper should be visible').toBeGreaterThan(0);

		// At least 1 example chat card should be rendered (6 are hardcoded)
		expect(cardCount, 'Expected at least 1 example chat card for new users').toBeGreaterThan(0);

		// Verify cards have titles
		if (cardCount > 0) {
			const firstCardTitle = await chatCards.first().getByTestId('card-title').textContent();
			expect(
				firstCardTitle?.trim().length,
				'Chat card should have a non-empty title'
			).toBeGreaterThan(0);
		}
	});

	test('example chat SSR pages are accessible', async ({ request }: { request: any }) => {
		test.setTimeout(30000);

		// Verify at least one example chat has a working SSR page
		const response = await request.get('/example/gigantic-airplanes-transporting-rocket-parts');

		expect(response.status(), 'Example chat SSR page should return 200').toBe(200);

		const html = await response.text();
		expect(html).toContain('<main');
		expect(html).toContain('<article');
		expect(html).toContain('<h1>');
	});

	test('every example chat SSR page has complete crawlable SEO HTML', async ({
		request
	}: {
		request: any;
	}) => {
		test.setTimeout(60000);

		const listingResponse = await request.get('/example');
		expect(listingResponse.status(), 'Example listing page should return 200').toBe(200);

		const listingHtml = await listingResponse.text();
		const slugs = extractExampleSlugs(listingHtml);
		expect(slugs.length, 'Example listing should link to example chat pages').toBeGreaterThan(0);

		for (const slug of slugs) {
			const response = await request.get(`/example/${slug}`);
			expect(response.status(), `/example/${slug} should return 200`).toBe(200);

			const html = await response.text();
			expect(html, `/example/${slug} should render main content without JS`).toContain('<main');
			expect(html, `/example/${slug} should render an article without JS`).toContain('<article');
			expect(html, `/example/${slug} should include user transcript text`).toContain('User:');
			expect(html, `/example/${slug} should include assistant transcript text`).toContain('OpenMates:');
			expect(html, `/example/${slug} should not leak unresolved i18n keys`).not.toContain(
				'example_chats.'
			);

			expect(countMatches(html, /<title[\s>]/gi), `/example/${slug} title count`).toBe(1);
			expect(
				countMatches(html, /<meta\s+name="description"/gi),
				`/example/${slug} meta description count`
			).toBe(1);
			expect(
				countMatches(html, /<link\s+rel="canonical"/gi),
				`/example/${slug} canonical count`
			).toBe(1);
			expect(countMatches(html, /<meta\s+name="robots"/gi), `/example/${slug} robots count`).toBe(
				1
			);
			expect(countMatches(html, /<meta\s+property="og:title"/gi), `/example/${slug} OG title`).toBe(
				1
			);
			expect(
				countMatches(html, /<meta\s+property="og:description"/gi),
				`/example/${slug} OG description`
			).toBe(1);
			expect(countMatches(html, /<meta\s+property="og:image"/gi), `/example/${slug} OG image`).toBe(
				1
			);
			expect(
				countMatches(html, /<meta\s+name="twitter:title"/gi),
				`/example/${slug} Twitter title`
			).toBe(1);
			expect(
				countMatches(html, /<meta\s+name="twitter:description"/gi),
				`/example/${slug} Twitter description`
			).toBe(1);
			expect(
				countMatches(html, /<meta\s+name="twitter:image"/gi),
				`/example/${slug} Twitter image`
			).toBe(1);

			const canonicalMatch = html.match(/<link\s+rel="canonical"\s+href="([^"]+)"/i);
			expect(canonicalMatch?.[1], `/example/${slug} should have slug canonical`).toContain(
				`/example/${slug}`
			);

			const robotsMatch = html.match(/<meta\s+name="robots"\s+content="([^"]+)"/i);
			expect(robotsMatch?.[1], `/example/${slug} should have explicit robots content`).toMatch(
				/^(index, follow|noindex, nofollow)$/
			);

			const jsonLd = extractJsonLd(html);
			expect(jsonLd['@type'], `/example/${slug} JSON-LD type`).toBe('Article');
			expect(jsonLd.headline, `/example/${slug} JSON-LD headline`).toBeTruthy();
			expect(jsonLd.description, `/example/${slug} JSON-LD description`).toBeTruthy();
			expect(jsonLd.dateModified, `/example/${slug} JSON-LD dateModified`).toBeTruthy();
			expect(jsonLd.mainEntityOfPage?.['@id'], `/example/${slug} JSON-LD canonical`).toContain(
				`/example/${slug}`
			);
		}
	});

	test('production sitemap includes every example chat with lastmod', async ({
		request
	}: {
		request: any;
	}) => {
		test.setTimeout(30000);

		const listingResponse = await request.get('/example');
		const listingHtml = await listingResponse.text();
		const slugs = extractExampleSlugs(listingHtml);
		expect(slugs.length, 'Example listing should expose sitemap candidates').toBeGreaterThan(0);

		const sitemapResponse = await request.get('/sitemap.xml', {
			headers: { host: 'openmates.org' }
		});
		expect(sitemapResponse.status(), 'Sitemap should return 200').toBe(200);

		const sitemapXml = await sitemapResponse.text();
		for (const slug of slugs) {
			const entryPattern = new RegExp(
				`<loc>https?://[^<]+/example/${slug}</loc>\\s*<lastmod>\\d{4}-\\d{2}-\\d{2}</lastmod>`
			);
			expect(sitemapXml, `Sitemap should include /example/${slug} with lastmod`).toMatch(
				entryPattern
			);
		}
	});
});
