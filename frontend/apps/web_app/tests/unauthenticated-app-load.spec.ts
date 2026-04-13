/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Unauthenticated app load test: verifies the core experience for a brand-new
 * visitor who has never signed up — the most common first impression.
 *
 * Bug history this test suite guards against:
 * - OPE-245: Daily inspirations returned empty when celery beat missed its
 *   06:30 UTC scheduled run after a container restart. The endpoint now falls
 *   back to yesterday's defaults, and the API triggers the task on startup
 *   if today's defaults are missing.
 *
 * Test covers:
 *   1. App loads without errors for a clean browser (no auth, no IndexedDB)
 *   2. The for-everyone demo chat opens automatically within a few seconds
 *   3. The new-chat button opens the new chat interface
 *   4. Daily inspiration banner appears with actual content in the new chat view
 *   5. No missing translation keys visible on the page
 *
 * No credentials required — this tests the non-authenticated flow.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');

test.describe('Unauthenticated app load', () => {
	const consoleLogs: string[] = [];
	const consoleErrors: string[] = [];
	const networkRequests: string[] = [];

	test.beforeEach(async () => {
		consoleLogs.length = 0;
		consoleErrors.length = 0;
		networkRequests.length = 0;
	});

	// eslint-disable-next-line no-empty-pattern
	test.afterEach(async ({}, testInfo: any) => {
		if (testInfo.status !== 'passed') {
			console.log('\n--- DEBUG INFO ON FAILURE ---');
			console.log('\n[RECENT CONSOLE LOGS]');
			consoleLogs.slice(-30).forEach((log) => console.log(log));
			console.log('\n[CONSOLE ERRORS]');
			consoleErrors.forEach((err) => console.log(err));
			console.log('\n[NETWORK REQUESTS]');
			networkRequests.slice(-20).forEach((req) => console.log(req));
			console.log('\n--- END DEBUG INFO ---\n');
		}
	});

	test('app loads, shows for-everyone chat, and daily inspirations appear in new chat', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		// ─── Console + network logging for diagnostics ──────────────────────
		page.on('console', (msg: any) => {
			const timestamp = new Date().toISOString();
			const text = `[${timestamp}] [${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') {
				consoleErrors.push(text);
			}
		});

		page.on('response', (response: any) => {
			const url = response.url();
			if (url.includes('/v1/')) {
				networkRequests.push(`${response.status()} ${url}`);
			}
		});

		// ─── 1. Navigate as a fresh user (clean browser context) ────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// ─── 2. Verify the for-everyone demo chat opens automatically ───────
		// The app auto-navigates to the for-everyone intro chat for new visitors.
		// The chat ID appears in the URL hash.
		await page.waitForFunction(
			() => window.location.hash.includes('demo-for-everyone'),
			null,
			{ timeout: 15000 }
		);
		console.log('[unauthenticated-load] for-everyone demo chat opened in URL hash');

		// Verify the active chat container is visible
		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Active chat container is visible');

		// ─── 3. Click the new-chat button to open the new chat interface ────
		const newChatButton = page.getByTestId('new-chat-button');
		await expect(newChatButton).toBeVisible({ timeout: 10000 });
		await newChatButton.click();
		console.log('[unauthenticated-load] Clicked new-chat button');

		// Wait for the message editor to appear (indicates new chat view is open)
		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] New chat interface opened (message editor visible)');

		// ─── 4. Verify daily inspiration banner appears with content ────────
		// The banner should load from /v1/default-inspirations for unauthenticated
		// users. It may take a moment as the server defaults are fetched async.
		const inspirationBanner = page.getByTestId('daily-inspiration-banner').first();
		await expect(inspirationBanner).toBeVisible({ timeout: 15000 });
		console.log('[unauthenticated-load] Daily inspiration banner is visible');

		// Verify the banner has actual text content (not empty / loading placeholder)
		const bannerText = await inspirationBanner.textContent();
		expect(
			bannerText?.trim().length,
			'Daily inspiration banner should have non-empty text content'
		).toBeGreaterThan(5);
		console.log(
			`[unauthenticated-load] Banner text verified (${bannerText?.trim().length} chars)`
		);

		// Verify the /v1/default-inspirations endpoint was called and succeeded
		const inspirationApiCalled = networkRequests.some(
			(r) => r.includes('/v1/default-inspirations') && r.startsWith('200')
		);
		expect(
			inspirationApiCalled,
			'Expected /v1/default-inspirations API call to succeed (200). ' +
				`Requests seen: ${networkRequests.filter((r) => r.includes('inspiration')).join(', ') || 'none'}`
		).toBe(true);
		console.log('[unauthenticated-load] /v1/default-inspirations returned 200');

		// ─── 5. No missing translations ─────────────────────────────────────
		await assertNoMissingTranslations(page);
		console.log('[unauthenticated-load] No missing translations detected');

		console.log('[unauthenticated-load] All checks passed');
	});

	test('example chat loads with Wikipedia inline links', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		page.on('console', (msg: any) => {
			const text = `[${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') consoleErrors.push(text);
		});

		// ─── 1. Load as fresh user, wait for intro chat ────────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Wait for the for-everyone intro chat to load (default for new visitors)
		await page.waitForFunction(
			() => window.location.hash.includes('demo-for-everyone'),
			null,
			{ timeout: 15000 }
		);
		console.log('[unauthenticated-load] Intro chat loaded');

		// ─── 2. Find and click the Artemis II example chat card ─────────
		// Example chats are shown in an ExampleChatsGroup inside the intro chat.
		// Scroll down to find them and click the Artemis II card.
		const exampleChatsGroup = page.getByTestId('example-chats-group');
		await exampleChatsGroup.scrollIntoViewIfNeeded({ timeout: 15000 });
		await expect(exampleChatsGroup).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Example chats group visible');

		// Click the Artemis II example chat card (find by its title text)
		const artemisCard = exampleChatsGroup.getByTestId('chat-embed-card').filter({
			hasText: /artemis/i
		}).first();
		await expect(artemisCard).toBeVisible({ timeout: 10000 });
		await artemisCard.click();
		console.log('[unauthenticated-load] Clicked Artemis II example chat card');

		// Wait for the example chat to load
		await page.waitForFunction(
			() => window.location.hash.includes('example-artemis'),
			null,
			{ timeout: 10000 }
		);

		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Artemis II example chat loaded');

		// ─── 3. Verify assistant message is visible ────────────────────
		const assistantMessage = page.getByTestId('mate-message-content').first();
		await expect(assistantMessage).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Assistant message content visible');

		// ─── 4. Scroll down to reveal the prose text (below embed preview cards) ──
		// The assistant message starts with large embed previews (search cards).
		// The prose text with wiki-linkable topics is below them.
		// The TipTap editor is lazy-initialized via IntersectionObserver, so the
		// text must scroll near the viewport before wiki inline nodes are created.
		await assistantMessage.evaluate((el: HTMLElement) => {
			el.scrollIntoView({ block: 'end', behavior: 'instant' });
		});
		// Give the IntersectionObserver + TipTap editor time to initialize
		await page.waitForTimeout(3000);
		console.log('[unauthenticated-load] Scrolled to bottom of assistant message');

		// ─── 5. Diagnostics: check wiki data in DOM ───────────────────
		const diagInfo = await page.evaluate(() => {
			// Check for any wiki-inline nodes in the DOM
			const wikiNodes = document.querySelectorAll('[data-type="wiki-inline"]');
			const wikiTestIds = document.querySelectorAll('[data-testid="wiki-inline-link"]');
			// Check for the text "Reid Wiseman" in the page to confirm message rendered
			const bodyText = document.body.innerText;
			const hasReidWiseman = bodyText.includes('Reid Wiseman');
			const hasArtemis = bodyText.includes('Artemis');
			return {
				wikiNodeCount: wikiNodes.length,
				wikiTestIdCount: wikiTestIds.length,
				hasReidWiseman,
				hasArtemis,
				bodyTextLength: bodyText.length,
				// Check for console errors from wiki/parse
				hash: window.location.hash,
			};
		});
		console.log('[unauthenticated-load] Wiki diagnostics:', JSON.stringify(diagInfo));

		// ─── 6. Verify Wikipedia inline links are rendered ──────────────
		// The Artemis II example chat has wikipedia_topics defined.
		// The parse_message pipeline should inject wikiInline TipTap nodes,
		// which render as WikiInlineLink.svelte with data-testid="wiki-inline-link".
		const wikiLinks = page.getByTestId('wiki-inline-link');
		const wikiLinkCount = await wikiLinks.count();
		expect(
			wikiLinkCount,
			`Expected wiki links but found ${wikiLinkCount}. Diagnostics: ${JSON.stringify(diagInfo)}`
		).toBeGreaterThan(0);
		console.log(
			`[unauthenticated-load] Found ${wikiLinkCount} Wikipedia inline link(s)`
		);

		// Verify the first wiki link has a "W" badge and display text
		const firstLink = wikiLinks.first();
		await expect(firstLink).toBeVisible();
		const linkText = await firstLink.textContent();
		expect(
			linkText?.includes('W'),
			'Wiki inline link should contain "W" badge text'
		).toBe(true);
		expect(
			linkText && linkText.length > 2,
			'Wiki inline link should have display text beyond the badge'
		).toBe(true);
		console.log(
			`[unauthenticated-load] First wiki link text: "${linkText}"`
		);

		// ─── 5. Click a wiki link to verify fullscreen opens ────────────
		await firstLink.click();

		// WikipediaFullscreen should appear (it fetches data from Wikipedia API on mount)
		// Look for the fullscreen container — it uses UnifiedEmbedFullscreen which has
		// the embed-fullscreen-container structure
		const wikiFullscreen = page.getByTestId('wiki-fullscreen-content');
		await expect(wikiFullscreen).toBeVisible({ timeout: 15000 });
		console.log('[unauthenticated-load] Wikipedia fullscreen opened');

		// Verify the fullscreen loaded content (article title should appear)
		const wikiTitle = page.getByTestId('wiki-fullscreen-title');
		await expect(wikiTitle).toBeVisible({ timeout: 10000 });
		const titleText = await wikiTitle.textContent();
		expect(
			titleText && titleText.length > 0,
			'Wikipedia fullscreen should show an article title'
		).toBe(true);
		console.log(
			`[unauthenticated-load] Wikipedia article title: "${titleText}"`
		);

		// ─── 6. No missing translations ─────────────────────────────────
		await assertNoMissingTranslations(page);
		console.log('[unauthenticated-load] Wikipedia inline links test passed');
	});

	test('AI model card in for-everyone chat opens settings deep link', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		// ─── Console logging for diagnostics ────────────────────────────
		page.on('console', (msg: any) => {
			const text = `[${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') consoleErrors.push(text);
		});

		// ─── 1. Navigate as a fresh user ────────────────────────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Wait for the for-everyone demo chat to load
		await page.waitForFunction(
			() => window.location.hash.includes('demo-for-everyone'),
			null,
			{ timeout: 15000 }
		);

		// ─── 2. Find and click an AI model card ────────────────────────
		// Scroll until we find a model card (they're in the ai_models_group)
		const modelCard = page.getByTestId('ai-model-card').first();
		await modelCard.scrollIntoViewIfNeeded({ timeout: 15000 });
		await expect(modelCard).toBeVisible({ timeout: 10000 });

		// Get the model name for later verification
		const modelName = await modelCard.getByTestId('model-name').textContent();
		console.log(`[unauthenticated-load] Clicking AI model card: ${modelName}`);

		await modelCard.click();

		// ─── 3. Verify settings panel opens with AI model detail ────────
		// The settings menu should become visible
		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Settings menu opened after model card click');

		// Verify the settings menu navigated to an ai/model/* route
		await expect(settingsMenu).toHaveAttribute('data-active-view', /^ai\/model\//, { timeout: 10000 });
		const activeView = await settingsMenu.getAttribute('data-active-view');
		console.log(`[unauthenticated-load] Settings active view: "${activeView}"`);

		// Verify the banner shell is rendered (model detail page)
		const bannerShell = settingsMenu.getByTestId('settings-banner-shell');
		await expect(bannerShell.first()).toBeVisible({ timeout: 5000 });

		console.log('[unauthenticated-load] AI model deep link test passed');
	});
});
