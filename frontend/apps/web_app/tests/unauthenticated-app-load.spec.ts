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

async function readStartRowInspirationIds(page: any): Promise<string[]> {
	const cards = page.getByTestId('start-row-inspiration-card');
	await expect(cards.first()).toBeVisible({ timeout: 15000 });
	const ids: string[] = await cards.evaluateAll((nodes: Element[]) =>
		nodes.map((node) => node.getAttribute('data-inspiration-id') || '')
	);
	expect(ids.length, 'Start row should contain inspiration cards').toBeGreaterThan(0);
	expect(ids.every((id) => id.length > 0)).toBe(true);
	return ids;
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

		// ─── 4. Verify the start row shows inspiration cards (no banner) ────
		// Inspirations load from /v1/default-inspirations for unauthenticated
		// users and are interleaved as cards with the example chats.
		await expect(page.getByTestId('chat-welcome-heading')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		const inspirationIds = await readStartRowInspirationIds(page);
		expect(inspirationIds.some((id) => /^openmates-(intro|actionable-events|privacy-safety|mates-focus|provider-cross-platform|signup-cta)$/.test(id))).toBe(false);
		const firstInspirationCard = page.getByTestId('start-row-inspiration-card').first();
		await expect(page.getByTestId('start-row-inspiration-label').first()).toBeVisible();
		expect(((await firstInspirationCard.textContent()) ?? '').trim().length, 'Inspiration card should have text').toBeGreaterThan(5);
		await expect(page.getByTestId('start-row-actions')).toBeVisible();
		console.log('[unauthenticated-load] Start row inspiration cards are visible');

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
	test('guest start row keeps stable inspiration cards across app visits', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		async function openStartAndReadIds() {
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await page.waitForLoadState('networkidle');
			await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
			return readStartRowInspirationIds(page);
		}

		const firstIds = await openStartAndReadIds();
		const secondIds = await openStartAndReadIds();
		await page.evaluate(() => window.dispatchEvent(new Event('language-changed-complete')));
		await page.waitForTimeout(250);
		await readStartRowInspirationIds(page);
		const thirdIds = await openStartAndReadIds();

		expect(secondIds).toEqual(firstIds);
		expect(thirdIds).toEqual(firstIds);
	});

	// contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
	test('guest start row shows inspiration cards, scrolls on mobile without starting a chat, and starts one on click', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('chat-welcome-heading')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
		await expect(page.getByTestId('daily-inspiration-next')).toHaveCount(0);

		const row = page.getByTestId('recent-chats-scroll-container');
		await expect(row).toBeVisible({ timeout: 15000 });
		const idsBefore = await readStartRowInspirationIds(page);
		expect(idsBefore.length).toBeLessThanOrEqual(10);

		// Horizontal scrolling of the row must not start a chat.
		await row.evaluate((el: HTMLElement) => el.scrollBy({ left: 200 }));
		await row.evaluate((el: HTMLElement) => el.scrollBy({ left: -200 }));
		expect(page.url(), 'Scrolling the start row should not start a chat').not.toContain('chat-id=');
		expect(await readStartRowInspirationIds(page)).toEqual(idsBefore);

		// Clicking an inspiration card starts the inspiration chat.
		const card = row.getByTestId('start-row-inspiration-card').first();
		await card.scrollIntoViewIfNeeded();
		await card.click();
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 15000 });
		await expect(row).toHaveCount(0, { timeout: 15000 });
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
		await openRegisteredExample(page, 'example-right-to-repair-laws');

		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Right to Repair example chat loaded');

		// ─── 3. Verify assistant message is visible ────────────────────
		const assistantMessage = page.getByTestId('mate-message-content').first();
		await expect(assistantMessage).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Assistant message content visible');

		// ─── 4. Verify image and website embeds open in fullscreen ──────
		// Skill-use embeds live in the collapsed assistant activity group; expand it first.
		await page.getByTestId('assistant-activity-toggle').first().click();
		const imageEmbed = page.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="search"]').first();
		await imageEmbed.scrollIntoViewIfNeeded({ timeout: 15000 });
		await expect(imageEmbed).toBeVisible({ timeout: 10000 });
		const imageFullscreen = await openFullscreen(page, imageEmbed);
		await expect(imageFullscreen).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Image embed fullscreen opened');
		await closeFullscreen(page, imageFullscreen);

		const websiteEmbed = page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]').first();
		await websiteEmbed.scrollIntoViewIfNeeded({ timeout: 15000 });
		await expect(websiteEmbed).toBeVisible({ timeout: 10000 });
		const websiteFullscreen = await openFullscreen(page, websiteEmbed);
		await expect(websiteFullscreen).toBeVisible({ timeout: 10000 });
		await expect(websiteFullscreen).toContainText(/repair|EU|Cybernews/i, { timeout: 10000 });
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
		// The Right to Repair example chat uses inline (wiki:Title) links.
		// convertWikiTopicLinksOnDoc applies wiki links to the TipTap JSON doc,
		// rendering as WikiInlineLink.svelte with data-testid="wiki-inline-link".
		const wikiLinks = page.getByTestId('wiki-inline-link');
		const wikiLinkCount = await wikiLinks.count();
		expect(
			wikiLinkCount,
			`Expected at least one Wikipedia inline link in the Right to Repair example chat, found ${wikiLinkCount}`
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
		// The row appends a server-region flag emoji (regional indicators) to the name; the
		// selector aria-label carries only the plain model name.
		const modelName = (await firstModelRow.getByTestId('composer-model-name').textContent())
			?.replace(/[\u{1F1E6}-\u{1F1FF}]/gu, '')
			.trim();
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

		// The Apps workspace route shows the app home; the horizontally scrolling skill
		// cards live in the app's Settings panel, opened from the app home.
		await page.getByTestId('apps-settings-open').click();
		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toBeVisible({ timeout: 10000 });
		const skillCardsScroll = settingsMenu.getByTestId('settings-skill-cards-scroll');
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

	// contract-test: direct surface=gui.web assertions=app-memories.catalog.no-typed-types
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

		await page.goto(getE2EDebugUrl('/#settings/apps/web'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page).toHaveURL(/#apps\/web(?:&|$)/);
		await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible({ timeout: 30000 });
		// The memories tab was removed from the app home; the app's Settings panel is where
		// memory categories would be listed.
		await page.getByTestId('apps-settings-open').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 10000 });

		// Typed app memories were removed: no app-specific memory categories are listed.
		await expect(page.getByTestId('app-card-name').filter({ hasText: /^Trips$/i })).toHaveCount(0);
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
