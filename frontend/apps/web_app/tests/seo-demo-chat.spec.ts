import { expect, test } from '@playwright/test';

/**
 * Tests for SEO demo chat pages at /demo/chat/ and /demo/chat/[slug].
 *
 * These pages serve two audiences:
 *   - Crawlers (Googlebot): see full server-rendered HTML with chat content, meta tags, JSON-LD
 *   - Human browsers: are redirected to the SPA (/#chat-id={slug}) via onMount
 *
 * Test strategy:
 *   1. Verify server-rendered HTML contains correct SEO content (title, meta, h1, chat messages)
 *   2. Verify human browser is redirected to the SPA root with correct chat-id deep link
 *   3. Verify the sitemap includes demo chat URLs
 *   4. Verify the listing page at /demo/chat/ is also correct
 */
test.describe('SEO demo chat pages', () => {
	// Known demo chat slug from the backend — capital of spain is a stable demo
	const DEMO_SLUG = 'demo-capital-of-spain';
	const DEMO_PATH = `/demo/chat/${DEMO_SLUG}`;
	const LISTING_PATH = '/demo/chat';

	// =========================================================================
	// 1. SERVER-RENDERED HTML (crawlers see this)
	// =========================================================================

	test('individual demo chat page has correct server-rendered <title>', async ({ request }) => {
		// Fetch the raw HTML directly (no JS execution — like a crawler)
		const response = await request.get(DEMO_PATH);
		expect(response.status()).toBe(200);

		const html = await response.text();

		// The page-specific <title> should appear in the HTML.
		// It is injected via <svelte:head> server-side.
		// The root layout previously suppressed all SSR output — this test
		// verifies that the (seo) layout group fix is working.
		expect(html).toContain('Capital of Spain');
		expect(html).toMatch(/<title>Capital of Spain/i);
	});

	test('individual demo chat page has correct canonical URL', async ({ request }) => {
		const response = await request.get(DEMO_PATH);
		const html = await response.text();

		// canonical should point to /demo/chat/demo-capital-of-spain (not openmates.org root)
		expect(html).toContain(`/demo/chat/${DEMO_SLUG}`);
		expect(html).toContain('rel="canonical"');
		// Should NOT have the fallback openmates.org canonical from app.html
		// (the page-specific canonical should override it via svelte:head)
		const canonicalMatches = html.match(/rel="canonical"\s+href="([^"]+)"/g) || [];
		// The last canonical wins in the SSR output (page overrides layout)
		const lastCanonical = canonicalMatches[canonicalMatches.length - 1];
		expect(lastCanonical).toContain(DEMO_SLUG);
	});

	test('individual demo chat page has chat content in HTML', async ({ request }) => {
		const response = await request.get(DEMO_PATH);
		const html = await response.text();

		// The main article content must be in the server-rendered HTML for indexing.
		// "capital of spain" is the first user message in this demo chat.
		expect(html.toLowerCase()).toContain('capital of spain');
		// Madrid is the answer — should be in the assistant message
		expect(html.toLowerCase()).toContain('madrid');

		// The <article> and <main> structural elements must be present
		expect(html).toContain('<main');
		expect(html).toContain('<article');
		expect(html).toContain('<h1>');
	});

	test('individual demo chat page has JSON-LD structured data', async ({ request }) => {
		const response = await request.get(DEMO_PATH);
		const html = await response.text();

		// JSON-LD script block must be present
		expect(html).toContain('application/ld+json');
		expect(html).toContain('"@context":"https://schema.org"');
		// headline should match the chat title
		expect(html).toContain('"headline"');
	});

	test('individual demo chat page has OG meta tags', async ({ request }) => {
		const response = await request.get(DEMO_PATH);
		const html = await response.text();

		expect(html).toContain('og:title');
		expect(html).toContain('og:description');
		expect(html).toContain('og:image');
		// OG type should be 'article' for individual chat pages
		expect(html).toContain('og:type');
	});

	test('individual demo chat page has robots=index,follow', async ({ request }) => {
		const response = await request.get(DEMO_PATH);
		const html = await response.text();

		expect(html).toContain('index, follow');
	});

	// =========================================================================
	// 2. BROWSER REDIRECT (human users see this)
	// =========================================================================

	test('individual demo chat page redirects browser to SPA with correct chat-id', async ({
		page
	}) => {
		test.setTimeout(30000);

		// Navigate to the SEO page — onMount should redirect to /#chat-id={slug}
		await page.goto(DEMO_PATH, { waitUntil: 'commit' });

		// Wait for the redirect to fire (onMount is fast but needs a tick)
		await page.waitForURL((url) => url.hash.includes('chat-id='), { timeout: 10000 });

		const url = page.url();
		expect(url).toContain(`chat-id=${DEMO_SLUG}`);

		// Should be on the SPA root (path is / or just the hash)
		const parsedUrl = new URL(url);
		expect(parsedUrl.pathname).toBe('/');
	});

	// =========================================================================
	// 3. LISTING PAGE
	// =========================================================================

	test('listing page /demo/chat has server-rendered chat list', async ({ request }) => {
		const response = await request.get(LISTING_PATH);
		expect(response.status()).toBe(200);

		const html = await response.text();

		// The listing page must have the Demo Chats heading
		expect(html).toContain('Demo Chats');
		expect(html).toContain('<h1>');

		// Should have links to individual demo chat pages
		expect(html).toContain('/demo/chat/demo-');

		// Title should be set for the listing page
		expect(html).toMatch(/<title>Demo Chats/i);
	});

	test('listing page redirects browser to SPA root', async ({ page }) => {
		test.setTimeout(20000);

		await page.goto(LISTING_PATH, { waitUntil: 'commit' });

		// Should redirect to / (the SPA root)
		await page.waitForURL('/', { timeout: 10000 });
		expect(page.url()).toMatch(/\/$|\/$/);
	});

	// =========================================================================
	// 4. SITEMAP
	// =========================================================================

	test('sitemap.xml includes demo chat URLs', async ({ request }) => {
		const response = await request.get('/sitemap.xml');
		expect(response.status()).toBe(200);

		const xml = await response.text();

		// Must be valid XML sitemap
		expect(xml).toContain('<?xml');
		expect(xml).toContain('<urlset');
		expect(xml).toContain('<url>');
		expect(xml).toContain('<loc>');

		// Must include demo chat URLs
		expect(xml).toContain('/demo/chat/demo-');

		// The known capital-of-spain demo should be in the sitemap
		expect(xml).toContain(DEMO_SLUG);
	});

	// =========================================================================
	// 5. SLUG VALIDATION
	// =========================================================================

	test('non-existent slug returns 404', async ({ request }) => {
		const response = await request.get('/demo/chat/demo-this-does-not-exist-xyz');
		expect(response.status()).toBe(404);
	});

	test('slug without demo- prefix returns 404', async ({ request }) => {
		const response = await request.get('/demo/chat/capital-of-spain');
		expect(response.status()).toBe(404);
	});
});
