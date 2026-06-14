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
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { openFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const PUBLIC_EXAMPLE_BROKEN_MARKERS = [
	'Presigned URL request failed',
	'Network error fetching S3',
	'Transcript not available',
	'[Interactive Question - Invalid JSON]',
	'vault_wrapped_aes_key',
	'vault:v1:',
	'dev-openmates-chatfiles',
	'chatfiles/',
	's3_key:',
	'docx_s3_key:',
	'screenshot_s3_keys:',
	'app_settings_memories_request',
	'app_settings_memories_response',
	'git checkout -- .',
	'"type":"focus_mode_activation"',
	'"type": "focus_mode_activation"'
];

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
	async function ensureSidebarVisible(page: any): Promise<void> {
		const history = page.getByTestId('activity-history-wrapper');
		if (await history.isVisible().catch(() => false)) {
			return;
		}

		const toggle = page.getByTestId('sidebar-toggle');
		await expect(toggle).toBeVisible({ timeout: 10000 });
		await toggle.click();
		await expect(history).toBeVisible({ timeout: 10000 });
	}

	function examplesSidebarGroup(page: any): any {
		return page.locator('[data-testid="chat-group"][data-group-key="examples"]').first();
	}

	async function sidebarExampleIds(page: any): Promise<string[]> {
		const group = examplesSidebarGroup(page);
		await expect(group).toBeVisible({ timeout: 15000 });
		return group.getByTestId('chat-item-wrapper').evaluateAll((nodes: Element[]) =>
			nodes
				.map((node) => node.getAttribute('data-chat-id') || '')
				.filter(Boolean)
		);
	}

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

	test('deep research example renders static sub-chat cards without a forced focus mention', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/#chat-id=example-us-egg-prices-deep'), {
			waitUntil: 'domcontentloaded'
		});

		const userMessage = page.getByTestId('user-message-content').filter({
			hasText: 'Why did US egg prices stay high after avian flu eased?'
		});
		await expect(userMessage).toBeVisible({ timeout: 15000 });
		await expect(
			userMessage,
			'Deep research example should demonstrate auto-selection, not @focus forcing.'
		).not.toContainText('@focus:');

		const carousel = page.getByTestId('sub-chats-carousel');
		await expect(carousel).toBeVisible({ timeout: 15000 });
		await expect(carousel.getByTestId('sub-chat-card')).toHaveCount(3);

		const focusBar = page.getByTestId('focus-mode-bar');
		await expect(focusBar).toBeVisible({ timeout: 15000 });
		await expect(focusBar.getByTestId('focus-status-label')).toContainText('Deep research');
		await expect(page.locator('body')).not.toContainText('"type":"focus_mode_activation"');
	});

	test('memory example cards update the reloadable chat hash on wide viewports', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 1600, height: 900 });

		await page.goto(getE2EDebugUrl('/#settings/app_store/books/settings_memories/currently_reading'), {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 15000 });
		const exampleCard = settingsMenu
			.locator('[data-testid="app-store-example-chat-card"][data-chat-id="example-memory-books-currently-reading"]')
			.first();
		await expect(exampleCard).toBeVisible({ timeout: 15000 });

		await exampleCard.click();
		await expect(page).toHaveURL(/#chat-id=example-memory-books-currently-reading/, { timeout: 15000 });
		await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 15000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page).toHaveURL(/#chat-id=example-memory-books-currently-reading/, { timeout: 15000 });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'spoiler-free one-week reading plan' })).toBeVisible({ timeout: 15000 });
	});

	test('reported memory examples render current text content without interactive-question errors', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);

		await page.goto(getE2EDebugUrl('/#chat-id=example-memory-books-currently-reading'), {
			waitUntil: 'domcontentloaded'
		});
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'spoiler-free one-week reading plan' })).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memories-summary')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memory-category-badge')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('body')).not.toContainText('[Interactive Question - Invalid JSON]');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_request');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_response');
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Project Hail Mary' })).toBeVisible({ timeout: 15000 });

		await page.goto(getE2EDebugUrl('/#chat-id=example-memory-mail-writing-styles'), {
			waitUntil: 'domcontentloaded'
		});
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Friday Update - [Project Name]' })).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memories-summary')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memory-category-badge')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('body')).not.toContainText('[Interactive Question - Invalid JSON]');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_request');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_response');
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Best, Alex' })).toBeVisible({ timeout: 15000 });
	});

	test('nutrition example renders Edamam recipe search embed card', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/#chat-id=example-chickpea-spinach-protein-dinners'), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('user-message-content').filter({
			hasText: 'Find 3 vegetarian chickpea and spinach dinner recipes'
		})).toBeVisible({ timeout: 15000 });

		const nutritionSearchCardSelector = '[data-testid="embed-preview"][data-app-id="nutrition"][data-skill-id="search_recipes"][data-status="finished"]';
		const assistantMessageWithNutritionCard = page
			.getByTestId('message-assistant')
			.filter({ hasText: 'Here are three delicious' })
			.filter({ has: page.locator(nutritionSearchCardSelector) })
			.first();
		await expect(assistantMessageWithNutritionCard).toBeVisible({ timeout: 15000 });

		const nutritionSearchCard = assistantMessageWithNutritionCard.locator(nutritionSearchCardSelector);
		await expect(nutritionSearchCard).toBeVisible({ timeout: 15000 });
		await expect(nutritionSearchCard).toContainText('chickpea and spinach dinner');
		await expect(nutritionSearchCard).toContainText('Edamam');
		await expect(assistantMessageWithNutritionCard).not.toContainText('"type":"app_skill_use"');
		expect(
			await assistantMessageWithNutritionCard.evaluate((message, selector) => {
				const card = message.querySelector(selector);
				const walker = document.createTreeWalker(message, NodeFilter.SHOW_TEXT);
				let answerTextNode: Node | null = null;
				while (walker.nextNode()) {
					if (walker.currentNode.textContent?.includes('Here are three delicious')) {
						answerTextNode = walker.currentNode;
						break;
					}
				}
				return !!(
					card &&
					answerTextNode &&
					(card.compareDocumentPosition(answerTextNode) & Node.DOCUMENT_POSITION_FOLLOWING)
				);
			}, nutritionSearchCardSelector)
		).toBe(true);

		const fullscreenOverlay = await openFullscreen(page, nutritionSearchCard);
		const resultCards = await verifySearchGrid(fullscreenOverlay, 3, 30000);
		await expect(resultCards.first().getByTestId('nutrition-recipe-preview-image')).toBeVisible({ timeout: 15000 });

		await resultCards.first().click();
		await expect(page.getByTestId('nutrition-recipe-image')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('nutrition-recipe-details')).toContainText('4 servings');
		await expect(page.getByTestId('nutrition-recipe-tags')).toContainText('Vegetarian');
		await expect(page.getByTestId('nutrition-recipe-categories')).toContainText('middle eastern');
		await expect(page.locator('body')).toContainText('8.7g');
	});

	test('sidebar example chats show newest first and append older results after show more', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		await loginToTestAccount(page);
		await ensureSidebarVisible(page);

		const initialIds = await sidebarExampleIds(page);
		expect(initialIds.length, 'Examples group should show the initial example batch').toBeGreaterThan(0);
		expect(
			initialIds,
			'Habit Garden should be in the initial newest-first example batch'
		).toContain('example-habit-garden-vite-app');

		const showMoreExamples = page.getByTestId('show-more-example-chats');
		await expect(showMoreExamples).toBeVisible({ timeout: 10000 });
		await showMoreExamples.click();

		await expect.poll(async () => (await sidebarExampleIds(page)).length, {
			message: 'Show more should reveal more example chats after the initial batch',
			timeout: 10000
		}).toBeGreaterThan(initialIds.length);

		const expandedIds = await sidebarExampleIds(page);
		for (const id of initialIds) {
			expect(expandedIds, `Show more should keep already-visible example ${id}`).toContain(id);
		}
		expect(
			new Set(expandedIds).size,
			'Show more should not duplicate example chat rows'
		).toBe(expandedIds.length);
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
			for (const marker of PUBLIC_EXAMPLE_BROKEN_MARKERS) {
				expect(html, `/example/${slug} should not contain broken public marker ${marker}`).not.toContain(
					marker
				);
			}

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
			const qaPage = jsonLd['@graph']?.find((node: Record<string, any>) => node['@type'] === 'QAPage');
			expect(qaPage, `/example/${slug} JSON-LD QAPage`).toBeTruthy();
			expect(qaPage.name, `/example/${slug} JSON-LD name`).toBeTruthy();
			expect(qaPage.description, `/example/${slug} JSON-LD description`).toBeTruthy();
			expect(qaPage.dateModified, `/example/${slug} JSON-LD dateModified`).toBeTruthy();
			expect(qaPage.url, `/example/${slug} JSON-LD canonical`).toContain(
				`/example/${slug}`
			);
			expect(
				qaPage.mainEntity?.length,
				`/example/${slug} JSON-LD QAPage should include question/answer entries`
			).toBeGreaterThan(0);
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

		const sitemapResponse = await request.get('/sitemap.xml');
		expect(sitemapResponse.status(), 'Sitemap should return 200').toBe(200);

		const sitemapXml = await sitemapResponse.text();
		test.skip(
			!sitemapXml.includes(`/example/${slugs[0]}`),
			'This environment intentionally does not expose example URLs in sitemap.xml; build-time SEO audit validates production sitemap output.'
		);

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
