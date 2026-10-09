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
 *   2. The ordinary welcome opens a real example chat
 *   3. The new-chat interface shows daily inspirations with actual content
 *   4. Guest model selection works ephemerally from toggles and model rows
 *   5. No missing translation keys visible on the page
 *
 * No credentials required — this tests the non-authenticated flow.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');
const { closeFullscreen, openFullscreen } = require('./helpers/embed-test-helpers');

function expectNoFullscreenChunkErrors(consoleErrors: string[]) {
	const chunkErrors = consoleErrors.filter((error) =>
		/dynamically imported module|chunk loading error|corrupted_content|fullscreen component/i.test(error)
	);
	expect(chunkErrors, `Unexpected fullscreen chunk error(s): ${chunkErrors.join('\n')}`).toEqual([]);
}

function expectNoWelcomeCarouselRuntimeErrors(consoleErrors: string[]) {
	const runtimeErrors = consoleErrors.filter((error) =>
		/Cannot set properties of undefined \(setting 'el'\)|Cannot read properties of null \(reading 'querySelector'\)|messageHighlights] DB not initialized/i.test(error)
	);
	expect(runtimeErrors, `Unexpected welcome carousel runtime error(s): ${runtimeErrors.join('\n')}`).toEqual([]);
}

async function openRegisteredExample(page: any, chatId: string) {
	const skipInterests = page.getByTestId('guest-interest-skip');
	if (await skipInterests.isVisible({ timeout: 5000 }).catch(() => false)) {
		await skipInterests.click();
		await expect(skipInterests).not.toBeVisible({ timeout: 10000 });
	}
	await page.getByTestId('guest-show-all-examples').click();
	const exampleCard = page.getByTestId('guest-all-examples-grid')
		.locator(`[data-testid="resume-chat-large-card"][data-chat-id="${chatId}"]`);
	await expect(exampleCard).toBeVisible({ timeout: 15000 });
	await exampleCard.click();
	await page.waitForFunction((id: string) => window.location.hash.includes(id), chatId, { timeout: 15000 });
	await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('mate-message-content').first()).toBeVisible({ timeout: 15000 });
}

async function openGuestNewChat(page: any) {
	const skipInterests = page.getByTestId('guest-interest-skip');
	if (await skipInterests.isVisible({ timeout: 5000 }).catch(() => false)) {
		await skipInterests.click();
	}

	if (await page.getByTestId('message-editor').isVisible({ timeout: 1000 }).catch(() => false)) return;
	const newChatButton = page.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]').first();
	if (!(await newChatButton.isVisible({ timeout: 1000 }).catch(() => false))) {
		const firstExampleCard = page.getByTestId('resume-chat-card').first();
		await expect(firstExampleCard).toBeVisible({ timeout: 10000 });
		await firstExampleCard.click();
	}

	await expect(newChatButton).toBeVisible({ timeout: 15000 });
	await newChatButton.click();
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 10000 });
}

async function focusGuestComposer(page: any) {
	const editor = page.getByTestId('message-editor').last();
	await expect(editor).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(600);
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	await expect(page.getByTestId('action-buttons').last()).toBeVisible({ timeout: 10000 });
}

async function readDailyInspirationPhrase(page: any): Promise<string> {
	const phrase = page.getByTestId('daily-inspiration-phrase');
	for (let attempt = 0; attempt < 5; attempt += 1) {
		if (await phrase.isVisible({ timeout: 1000 }).catch(() => false)) break;

		const nextButton = page.getByTestId('daily-inspiration-next');
		if (!(await nextButton.isVisible({ timeout: 1000 }).catch(() => false))) break;
		await nextButton.click();
	}
	await expect(phrase).toBeVisible({ timeout: 15000 });
	const text = (await phrase.textContent())?.trim() ?? '';
	expect(text.length, 'Daily inspiration phrase should be non-empty').toBeGreaterThan(0);
	return text;
}

async function expectDailyInspirationPhraseToChange(page: any, previousPhrase: string): Promise<string> {
	const phrase = page.getByTestId('daily-inspiration-phrase');
	await expect
		.poll(async () => (await phrase.textContent())?.trim() ?? '', { timeout: 3000 })
		.not.toBe(previousPhrase);
	return readDailyInspirationPhrase(page);
}

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

	// contract-test: direct surface=gui.web assertions=daily-inspiration.public-defaults,daily-inspiration.guest-isolated,landing-onboarding.uses-real-chat-shell
	test('app loads ordinary guest welcome with daily inspirations and a new chat editor', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

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

		// The guest welcome is the real new-chat shell.
		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 10000 });
		await openGuestNewChat(page);

		// ─── 4. Verify daily inspiration banner appears with content ────────
		// The banner should load from /v1/default-inspirations for unauthenticated
		// users. It may take a moment as the server defaults are fetched async.
		const inspirationBanner = page.getByTestId('daily-inspiration-banner').first();
		await expect(inspirationBanner).toBeVisible({ timeout: 15000 });
		await expect(inspirationBanner).not.toHaveAttribute('data-current-inspiration-id', /^openmates-(intro|actionable-events|privacy-safety|mates-focus|provider-cross-platform|signup-cta)$/);
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
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

		// Mobile regression check: horizontal swipe should navigate the carousel,
		// not trigger the banner click that starts a chat.
		const phrase = page.getByTestId('daily-inspiration-phrase');
		const firstPhrase = (await phrase.textContent())?.trim();
		await expect(page.getByTestId('daily-inspiration-next')).toBeVisible();
		const box = await inspirationBanner.boundingBox();
		expect(box, 'Daily inspiration banner must have bounds for swipe test').toBeTruthy();
		await inspirationBanner.dispatchEvent('touchstart', {
			touches: [{ identifier: 0, clientX: box!.x + box!.width - 48, clientY: box!.y + box!.height / 2 }],
			changedTouches: [{ identifier: 0, clientX: box!.x + box!.width - 48, clientY: box!.y + box!.height / 2 }]
		});
		await inspirationBanner.dispatchEvent('touchmove', {
			touches: [{ identifier: 0, clientX: box!.x + 48, clientY: box!.y + box!.height / 2 }],
			changedTouches: [{ identifier: 0, clientX: box!.x + 48, clientY: box!.y + box!.height / 2 }]
		});
		await inspirationBanner.dispatchEvent('touchend', {
			touches: [],
			changedTouches: [{ identifier: 0, clientX: box!.x + 48, clientY: box!.y + box!.height / 2 }]
		});
		await expect(phrase).not.toHaveText(firstPhrase ?? '', { timeout: 3000 });
		expect(page.url(), 'Swipe navigation should not start a chat').not.toContain('chat-id=');
		console.log('[unauthenticated-load] Mobile swipe navigation changed the banner phrase');

		// Public defaults may replace the immediate ordinary fallback. The
		// banner remains populated if the endpoint is unavailable.
		const inspirationApiResponses = networkRequests.filter((r) =>
			r.includes('/v1/default-inspirations')
		);
		console.log(`[unauthenticated-load] Public default responses: ${inspirationApiResponses.join(', ') || 'none'}`);

		// ─── 5. No missing translations ─────────────────────────────────────
		await assertNoMissingTranslations(page);
		console.log('[unauthenticated-load] No missing translations detected');

		console.log('[unauthenticated-load] All checks passed');
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
	test('real example follow-up suggestion opens signup for unauthenticated users', async ({
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

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await openRegisteredExample(page, 'example-community-garden-planning-mindmap');

		const followUpSuggestion = page.getByTestId('follow-up-suggestion-item').first();
		await expect(followUpSuggestion).toBeVisible({ timeout: 10000 });
		await followUpSuggestion.click();
		await expect(page.getByTestId('follow-up-suggestion-item')).toHaveCount(0, { timeout: 1000 });

		await expect(page.getByTestId('login-wrapper')).toBeVisible({ timeout: 10000 });
		await expect(page.locator('[data-testid="tab-signup"].active')).toBeVisible({ timeout: 5000 });
	});

	// contract-test: direct surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
	test('daily inspiration banner keeps a stable initial item across app visits', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		async function openNewChatAndReadPhrase() {
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await page.waitForLoadState('networkidle');
			await openGuestNewChat(page);

			return readDailyInspirationPhrase(page);
		}

		const firstPhrase = await openNewChatAndReadPhrase();
		const secondPhrase = await openNewChatAndReadPhrase();
		await page.evaluate(() => window.dispatchEvent(new Event('language-changed-complete')));
		await page.waitForTimeout(250);
		await readDailyInspirationPhrase(page);
		const thirdPhrase = await openNewChatAndReadPhrase();

		expect(secondPhrase).toBe(firstPhrase);
		expect(thirdPhrase).toBe(firstPhrase);
	});

	// contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
	test('daily inspiration banner navigates with arrows and touch swipes on mobile', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await openGuestNewChat(page);

		const banner = page.getByTestId('daily-inspiration-banner').first();
		const firstPhrase = await readDailyInspirationPhrase(page);

		const bannerBox = await banner.boundingBox();
		expect(bannerBox, 'Daily inspiration banner must have bounds for gesture tests').toBeTruthy();

		await page.getByTestId('daily-inspiration-next').click();
		const secondPhrase = await expectDailyInspirationPhraseToChange(page, firstPhrase);

		await page.getByTestId('daily-inspiration-previous').click();
		await expect(page.getByTestId('daily-inspiration-phrase')).toHaveText(firstPhrase, { timeout: 3000 });

		const centerY = bannerBox!.y + bannerBox!.height / 2;
		await banner.dispatchEvent('touchstart', {
			touches: [{ identifier: 0, clientX: bannerBox!.x + bannerBox!.width - 48, clientY: centerY }],
			changedTouches: [{ identifier: 0, clientX: bannerBox!.x + bannerBox!.width - 48, clientY: centerY }]
		});
		await banner.dispatchEvent('touchmove', {
			touches: [{ identifier: 0, clientX: bannerBox!.x + 48, clientY: centerY }],
			changedTouches: [{ identifier: 0, clientX: bannerBox!.x + 48, clientY: centerY }]
		});
		await banner.dispatchEvent('touchend', {
			touches: [],
			changedTouches: [{ identifier: 0, clientX: bannerBox!.x + 48, clientY: centerY }]
		});
		await expect(page.getByTestId('daily-inspiration-phrase')).toHaveText(secondPhrase, { timeout: 3000 });

		await banner.dispatchEvent('touchstart', {
			touches: [{ identifier: 0, clientX: bannerBox!.x + 48, clientY: centerY }],
			changedTouches: [{ identifier: 0, clientX: bannerBox!.x + 48, clientY: centerY }]
		});
		await banner.dispatchEvent('touchmove', {
			touches: [{ identifier: 0, clientX: bannerBox!.x + bannerBox!.width - 48, clientY: centerY }],
			changedTouches: [{ identifier: 0, clientX: bannerBox!.x + bannerBox!.width - 48, clientY: centerY }]
		});
		await banner.dispatchEvent('touchend', {
			touches: [],
			changedTouches: [{ identifier: 0, clientX: bannerBox!.x + bannerBox!.width - 48, clientY: centerY }]
		});
		await expect(page.getByTestId('daily-inspiration-phrase')).toHaveText(firstPhrase, { timeout: 3000 });
		expect(page.url(), 'Carousel navigation should not start a chat').not.toContain('chat-id=');
	});

	// contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
	test('daily inspiration banner auto-rotates for unauthenticated users', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await openGuestNewChat(page);

		const firstPhrase = await readDailyInspirationPhrase(page);

		// Speed up the actual progress animation so this test verifies the
		// animationend-driven carousel path without waiting for the 20s production duration.
		await page.getByTestId('daily-inspiration-carousel-progress').evaluate((el: HTMLElement) => {
			el.style.setProperty('--carousel-progress-duration', '250ms');
		});

		const secondPhrase = await expectDailyInspirationPhraseToChange(page, firstPhrase);

		await page.getByTestId('daily-inspiration-next').click();
		const manuallyAdvancedPhrase = await expectDailyInspirationPhraseToChange(page, secondPhrase);
		await expect(page.getByTestId('daily-inspiration-phrase')).toHaveText(manuallyAdvancedPhrase);
		await page.getByTestId('daily-inspiration-carousel-progress').evaluate((el: HTMLElement) => {
			el.style.setProperty('--carousel-progress-duration', '250ms');
		});
		const nextAutoPhrase = await expectDailyInspirationPhraseToChange(page, manuallyAdvancedPhrase);

		await page.getByTestId('daily-inspiration-carousel-progress').evaluate((el: HTMLElement) => {
			el.style.setProperty('--carousel-progress-duration', '250ms');
		});
		await expect(page.getByTestId('daily-inspiration-banner')).not.toHaveAttribute('data-current-inspiration-id', /^openmates-(intro|actionable-events|privacy-safety|mates-focus|provider-cross-platform|signup-cta)$/);
		expect(nextAutoPhrase.length).toBeGreaterThan(0);
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,landing-onboarding.guest-examples
	test('guest welcome keeps interest and all-example controls without promotional slides', async ({ page }: { page: any }) => {
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		const bannerHeight = (await page.getByTestId('daily-inspiration-banner').boundingBox())?.height ?? 0;
		expect(bannerHeight).toBeGreaterThan(0);
		expect(bannerHeight).toBeLessThanOrEqual(420);
		await expect(page.getByTestId('guest-interest-select-interests')).toBeVisible();
		await expect(page.getByTestId('guest-show-all-examples')).toBeVisible();
		await expect(page.getByTestId('resume-chat-card').first()).toBeVisible();
		const beforeSlide = await page.getByTestId('resume-chat-card').evaluateAll((cards: HTMLElement[]) =>
			cards.map((card) => card.dataset.chatId).filter(Boolean)
		);
		expect(beforeSlide.length).toBeGreaterThan(1);
		await page.getByTestId('daily-inspiration-next').click();
		const afterSlide = await page.getByTestId('resume-chat-card').evaluateAll((cards: HTMLElement[]) =>
			cards.map((card) => card.dataset.chatId).filter(Boolean)
		);
		expect(afterSlide).toEqual(beforeSlide);
		await page.getByTestId('guest-show-all-examples').click();
		await expect(page.getByTestId('guest-all-examples-grid').getByTestId('resume-chat-large-card').first()).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=landing-onboarding.uses-real-chat-shell,public-example-chats.catalog.discoverable
	test('desktop welcome opens real example chats without runtime errors', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 1440, height: 1000 });

		page.on('console', (msg: any) => {
			const text = `[${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') consoleErrors.push(text);
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		const exampleCard = page.locator(
			'[data-testid="resume-chat-large-card"][data-chat-id^="example-"], [data-testid="resume-chat-card"][data-chat-id^="example-"]'
		).first();
		await expect(exampleCard).toBeVisible({ timeout: 15000 });
		expectNoWelcomeCarouselRuntimeErrors(consoleErrors);

		const exampleChatId = await exampleCard.getAttribute('data-chat-id');
		expect(exampleChatId, 'Desktop welcome carousel example card should expose its chat id').toBeTruthy();
		await exampleCard.click();
		await page.waitForFunction(
			(chatId: string) => window.location.hash.includes(chatId),
			exampleChatId,
			{ timeout: 10000 }
		);
		await expect(page.getByTestId('mate-message-content').first()).toBeVisible({ timeout: 10000 });
		expectNoWelcomeCarouselRuntimeErrors(consoleErrors);
	});

	// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('example chat loads and fullscreen wiki, website, and image embeds open for unauthenticated users', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);

		page.on('console', (msg: any) => {
			const text = `[${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') consoleErrors.push(text);
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await openRegisteredExample(page, 'example-artemis-ii-mission');

		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Artemis II example chat loaded');

		// ─── 3. Verify assistant message is visible ────────────────────
		const assistantMessage = page.getByTestId('mate-message-content').first();
		await expect(assistantMessage).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Assistant message content visible');

		// ─── 4. Verify image and website embeds open in fullscreen ──────
		const imageEmbed = page.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="search"]').first();
		await imageEmbed.scrollIntoViewIfNeeded({ timeout: 15000 });
		await expect(imageEmbed).toBeVisible({ timeout: 10000 });
		const imageFullscreen = await openFullscreen(page, imageEmbed);
		await expect(imageFullscreen).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Image embed fullscreen opened');
		await closeFullscreen(page, imageFullscreen);

		const websiteEmbed = page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="website"]').first();
		await websiteEmbed.scrollIntoViewIfNeeded({ timeout: 15000 });
		await expect(websiteEmbed).toBeVisible({ timeout: 10000 });
		const websiteFullscreen = await openFullscreen(page, websiteEmbed);
		await expect(websiteFullscreen).toBeVisible({ timeout: 10000 });
		await expect(websiteFullscreen).toContainText(/Artemis|NASA|Launch/i, { timeout: 10000 });
		console.log('[unauthenticated-load] Website embed fullscreen opened');
		await closeFullscreen(page, websiteFullscreen);

		// ─── 5. Scroll down to reveal the prose text (below embed preview cards) ──
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

		// ─── 6. Verify Wikipedia inline links are rendered ──────────────
		// The Artemis II example chat has wikipedia_topics defined (10 topics).
		// convertWikiTopicLinksOnDoc applies wiki links to the TipTap JSON doc,
		// rendering as WikiInlineLink.svelte with data-testid="wiki-inline-link".
		const wikiLinks = page.getByTestId('wiki-inline-link');
		const wikiLinkCount = await wikiLinks.count();
		expect(
			wikiLinkCount,
			`Expected at least one Wikipedia inline link in the Artemis II example chat, found ${wikiLinkCount}`
		).toBeGreaterThan(0);
		console.log(
			`[unauthenticated-load] Found ${wikiLinkCount} Wikipedia inline link(s)`
		);

		// Verify the first wiki link has display text (badge is rendered as icon, not text)
		const firstLink = wikiLinks.first();
		await expect(firstLink).toBeVisible();
		const linkText = await firstLink.textContent();
		expect(
			linkText && linkText.trim().length > 0,
			'Wiki inline link should have display text (topic phrase)'
		).toBe(true);
		console.log(
			`[unauthenticated-load] First wiki link text: "${linkText}"`
		);

		// ─── 7. Click two wiki links to verify fullscreen opens repeatedly ─
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
		await closeFullscreen(page, page.getByTestId('embed-fullscreen-overlay'));

		const secondLink = wikiLinks.nth(1);
		await expect(secondLink).toBeVisible({ timeout: 10000 });
		const secondLinkText = await secondLink.textContent();
		await secondLink.click();
		await expect(wikiFullscreen).toBeVisible({ timeout: 15000 });
		await expect(wikiTitle).toBeVisible({ timeout: 10000 });
		const secondTitleText = await wikiTitle.textContent();
		expect(
			secondTitleText && secondTitleText.length > 0,
			'Second Wikipedia fullscreen should show an article title'
		).toBe(true);
		console.log(
			`[unauthenticated-load] Second wiki link "${secondLinkText}" opened article: "${secondTitleText}"`
		);
		await closeFullscreen(page, page.getByTestId('embed-fullscreen-overlay'));

		expectNoFullscreenChunkErrors(consoleErrors);

		// ─── 8. No missing translations ─────────────────────────────────
		await assertNoMissingTranslations(page);
		console.log('[unauthenticated-load] Example fullscreen embeds test passed');
	});

	// contract-test: direct surface=gui.web assertions=ai-model-routing.composer.responsive-actions,ai-model-routing.composer.mention-to-exact-selection
	test('guest can select a composer model ephemerally from its toggle or model row', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 1440, height: 900 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await openGuestNewChat(page);
		await focusGuestComposer(page);

		const selector = page.getByTestId('composer-model-selector');
		await expect(selector).toBeVisible({ timeout: 10000 });
		await expect(selector).toHaveAttribute('aria-label', /Auto select/i);

		await selector.click();
		const menu = page.getByTestId('composer-model-selector-menu');
		await menu.getByTestId('composer-model-provider-label').first().click();
		const firstModelRow = menu.getByTestId('composer-model-row').first();
		const modelName = (await firstModelRow.getByTestId('composer-model-name').textContent())?.trim();
		expect(modelName, 'The guest model picker should expose at least one model').toBeTruthy();
		await firstModelRow.getByTestId('composer-model-toggle').click();
		await expect(selector).toHaveAttribute('aria-label', new RegExp(modelName!, 'i'));

		await selector.click();
		await menu.getByTestId('composer-model-back').click();
		await menu.getByTestId('composer-model-auto').click();
		await expect(selector).toHaveAttribute('aria-label', /Auto select/i);

		await selector.click();
		await menu.getByTestId('composer-model-provider-label').first().click();
		await menu.getByTestId('composer-model-row').first().getByTestId('composer-model-name').click();
		await expect(page.getByTestId('ai-model-details')).toBeVisible({ timeout: 10000 });
		await page.getByTestId('icon-button-close').click();
		await expect(selector).toHaveAttribute('aria-label', new RegExp(modelName!, 'i'));

		await page.reload({ waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await openGuestNewChat(page);
		await focusGuestComposer(page);
		await expect(page.getByTestId('composer-model-selector')).toHaveAttribute('aria-label', /Auto select/i);
	});

	// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
	test('guest app cards keep native touch scrolling on mobile', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		const TOUCH_DRAG_DISTANCE_PX = 120;
		await page.setViewportSize({ width: 390, height: 844 });

		page.on('console', (msg: any) => {
			const text = `[${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') consoleErrors.push(text);
		});

		await page.goto(getE2EDebugUrl('/#settings/apps/images'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page).toHaveURL(/#apps\/images(?:&|$)/);

		const skillCardsScroll = page.locator('[data-testid="settings-skill-cards-scroll"]:visible');
		await expect(skillCardsScroll).toBeVisible({ timeout: 10000 });
		const touchMoveWasCanceled = await skillCardsScroll.evaluate(
			(container: HTMLElement, dragDistancePx: number) => {
				const rect = container.getBoundingClientRect();
				const startX = rect.left + rect.width / 2;
				const startY = rect.top + rect.height / 2;
				const createTouch = (x: number) =>
					new Touch({
						identifier: 1,
						target: container,
						clientX: x,
						clientY: startY
					});

				container.dispatchEvent(
					new TouchEvent('touchstart', {
						bubbles: true,
						cancelable: true,
						touches: [createTouch(startX)],
						targetTouches: [createTouch(startX)],
						changedTouches: [createTouch(startX)]
					})
				);

				const moveEvent = new TouchEvent('touchmove', {
					bubbles: true,
					cancelable: true,
					touches: [createTouch(startX - dragDistancePx)],
					targetTouches: [createTouch(startX - dragDistancePx)],
					changedTouches: [createTouch(startX - dragDistancePx)]
				});

				container.dispatchEvent(moveEvent);
				return moveEvent.defaultPrevented;
			},
			TOUCH_DRAG_DISTANCE_PX
		);

		expect(touchMoveWasCanceled).toBe(false);
		await expect(skillCardsScroll).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=app-memories.catalog.declared-types-only
	test('guest app memories only show categories with examples', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		page.on('console', (msg: any) => {
			const text = `[${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') consoleErrors.push(text);
		});

		await page.goto(getE2EDebugUrl('/#settings/apps/travel'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page).toHaveURL(/#apps\/travel(?:&|$)/);
		await page.getByTestId('apps-tab-settings_memories').click();

		const memoryCards = page.locator('[data-testid="settings-memory-cards-scroll"]:visible');
		await expect(memoryCards).toBeVisible({ timeout: 10000 });
		await expect(memoryCards.getByTestId('app-card-name').filter({ hasText: /^Trips$/i })).toBeVisible();
		await expect(memoryCards.getByTestId('app-card-name').filter({ hasText: /^Saved connections$/i })).toHaveCount(0);
		await expect(memoryCards.getByTestId('app-card-name').filter({ hasText: /^Saved stays$/i })).toHaveCount(0);

		await memoryCards.getByTestId('app-card-name').filter({ hasText: /^Trips$/i }).click();
		await expect(page).toHaveURL(/#apps\/travel\/memory\/trips/, { timeout: 10000 });
		await expect(page.getByText('Examples').first()).toBeVisible({ timeout: 10000 });
	});

	// contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
	test('guest sidebar omits promotional announcement demo chats', async ({ page }) => {
		test.setTimeout(60000);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		const sidebarToggle = page.getByTestId('sidebar-toggle');
		await expect(sidebarToggle).toBeVisible({ timeout: 10000 });
		await sidebarToggle.click();
		await expect(page.getByTestId('chat-group').filter({ hasText: /announcements/i })).toHaveCount(0);
	});
});
