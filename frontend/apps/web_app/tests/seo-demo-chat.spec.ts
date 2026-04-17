import { expect, test } from './helpers/cookie-audit';
/**
 * Tests for SEO example chat pages at /example/ and /example/[slug].
 *
 * These pages serve two audiences:
 *   - Crawlers (Googlebot): see full server-rendered HTML with chat content, meta tags, JSON-LD
 *   - Human browsers: are redirected to the SPA (/#chat-id={slug}) via onMount
 *
 * Test strategy:
 *   1. Verify server-rendered HTML contains correct SEO content (title, meta, h1, chat messages)
 *   2. Verify human browser is redirected to the SPA root with correct chat-id deep link
 *   3. Verify the sitemap structure is valid
 *   4. Verify the listing page at /example/ is also correct
 *
 * Route architecture:
 *   - Routes live under (seo) layout group: /example/[slug]
 *   - Data is loaded from static hardcoded example chats (no backend API)
 *   - +page.server.ts resolves i18n keys server-side for crawler content
 */
test.describe('SEO example chat pages', () => {
	const EXAMPLE_SLUG = 'gigantic-airplanes-transporting-rocket-parts';
	const EXAMPLE_PATH = `/example/${EXAMPLE_SLUG}`;
	const LISTING_PATH = '/example';

	// =========================================================================
	// 1. SERVER-RENDERED HTML (crawlers see this)
	// =========================================================================

	test('individual example chat page has correct server-rendered <title>', async ({ request }) => {
		const response = await request.get(EXAMPLE_PATH);
		expect(response.status()).toBe(200);

		const html = await response.text();

		// The page-specific <title> should appear in the HTML.
		// Title format: "{chat title} — OpenMates" via +page.svelte <svelte:head>
		expect(html).toMatch(/<title>.+OpenMates<\/title>/i);
	});

	test('individual example chat page has correct canonical URL', async ({ request }) => {
		const response = await request.get(EXAMPLE_PATH);
		const html = await response.text();

		expect(html).toContain(`/example/${EXAMPLE_SLUG}`);
		expect(html).toContain('rel="canonical"');
		const canonicalMatches = html.match(/rel="canonical"\s+href="([^"]+)"/g) || [];
		const lastCanonical = canonicalMatches[canonicalMatches.length - 1];
		expect(lastCanonical).toContain(EXAMPLE_SLUG);
	});

	test('individual example chat page has chat content in HTML', async ({ request }) => {
		const response = await request.get(EXAMPLE_PATH);
		const html = await response.text();

		// The <article> and <main> structural elements must be present
		expect(html).toContain('<main');
		expect(html).toContain('<article');
		expect(html).toContain('<h1>');

		// Should have message content (User: and OpenMates: labels)
		expect(html).toContain('User:');
		expect(html).toContain('OpenMates:');
	});

	test('individual example chat page has JSON-LD structured data', async ({ request }) => {
		const response = await request.get(EXAMPLE_PATH);
		const html = await response.text();

		expect(html).toContain('application/ld+json');
		expect(html).toContain('"@context":"https://schema.org"');
		expect(html).toContain('"headline"');
	});

	test('individual example chat page has OG meta tags', async ({ request }) => {
		const response = await request.get(EXAMPLE_PATH);
		const html = await response.text();

		expect(html).toContain('og:title');
		expect(html).toContain('og:description');
		expect(html).toContain('og:image');
		expect(html).toContain('og:type');
	});

	test('individual example chat page has robots meta tag', async ({ request }) => {
		const response = await request.get(EXAMPLE_PATH);
		const html = await response.text();

		expect(html).toMatch(/name="robots"/);
		// Robots content varies by hostname resolution (Vercel may resolve as prod)
		expect(html).toMatch(/content="(no)?index/i);
	});

	// =========================================================================
	// 2. BROWSER REDIRECT (human users see this)
	// =========================================================================

	test('individual example chat page redirects browser to SPA with correct chat-id', async ({
		page
	}) => {
		test.setTimeout(30000);

		await page.goto(EXAMPLE_PATH, { waitUntil: 'commit' });

		// Wait for the redirect to fire (onMount is fast but needs a tick)
		await page.waitForURL((url: URL) => url.hash.includes('chat-id='), { timeout: 10000 });

		const url = page.url();
		// Should be on the SPA root (path is / or just the hash)
		const parsedUrl = new URL(url);
		expect(parsedUrl.pathname).toBe('/');
	});

	// =========================================================================
	// 3. LISTING PAGE
	// =========================================================================

	test('listing page /example has server-rendered chat list', async ({ request }) => {
		const response = await request.get(LISTING_PATH);
		expect(response.status()).toBe(200);

		const html = await response.text();

		// Should have links to individual example chat pages
		expect(html).toContain('/example/');

		// Title should be set
		expect(html).toMatch(/<title>/i);
	});

	test('listing page redirects browser to SPA root', async ({ page }) => {
		test.setTimeout(20000);

		await page.goto(LISTING_PATH, { waitUntil: 'commit' });

		// Should redirect to / (the SPA root)
		await page.waitForURL('/', { timeout: 10000 });
		expect(page.url()).toMatch(/\/$/);
	});

	// =========================================================================
	// 4. SITEMAP
	// =========================================================================

	test('sitemap.xml is a valid XML sitemap', async ({ request }) => {
		const response = await request.get('/sitemap.xml');
		expect(response.status()).toBe(200);

		const xml = await response.text();

		// Must be valid XML sitemap structure
		expect(xml).toContain('<?xml');
		expect(xml).toContain('<urlset');

		// On dev the sitemap is intentionally empty — no entries served
		// (Production behaviour is verified separately)
	});

	// =========================================================================
	// 5. SLUG VALIDATION
	// =========================================================================

	test('non-existent slug returns 404', async ({ request }) => {
		const response = await request.get('/example/this-does-not-exist-xyz');
		expect(response.status()).toBe(404);
	});
});
