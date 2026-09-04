/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Unauthenticated chat navigation reactivity test.
 *
 * Regression guard for: "new chat screen stops reacting" (dev vault bug report).
 *
 * Symptom: after clicking through 3-4 intro/example chat cards and the New Chat
 * button as an unauthenticated user, the UI silently freezes — onclick handlers
 * still fire and the URL hash updates, but no UI state changes (chats stop
 * loading, settings panel stops opening). No JS errors appear in the console.
 *
 * Root-cause candidates patched alongside this spec:
 *   1. activeChatStore.ts: replaceState to semantic path (/intro/...) could
 *      trigger SvelteKit's client router on prerendered (seo) routes, causing
 *      an unexpected navigation that interrupts loadChat mid-flight.
 *   2. ActiveChat.svelte: $derived creating $state-bearing class instances
 *      (RecentChatTiltState) could produce a Svelte 5 reactive cascade when
 *      the source array is rapidly cleared and repopulated.
 *
 * Test strategy: start on the logged-out welcome screen, cycle through
 * intro/example chat cards ↔ new-chat navigation 5 times, then verify the
 * settings panel can still be opened and closed. If the UI freezes at any
 * point, the corresponding waitForSelector / visibility assertions will time
 * out and fail the spec.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const CYCLES = 5;
const CHAT_LOAD_TIMEOUT = 12000;
const SETTINGS_TIMEOUT = 8000;
const SLIDE_NAVIGATION_TIMEOUT = 5000;
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_VIDEO_HEIGHT = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_HEIGHT || '', 10);
const IS_PROOF_CAPTURE = PROOF_VIDEO_WIDTH > 0 && PROOF_VIDEO_HEIGHT > 0;
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const PROOF_VIEWPORT = IS_PROOF_CAPTURE ? { width: PROOF_VIDEO_WIDTH, height: PROOF_VIDEO_HEIGHT } : null;

const CHAT_NAVIGATION_PROOF = defineVideoProof({
	id: 'unauthenticated-chat-navigation-reactive',
	title: 'Guest example chat navigation stays reactive',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'welcome-cards',
			text: 'The guest welcome screen shows clickable example chat cards after returning from New Chat.',
			checkpoint: 'welcome-cards-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'cycles-stable',
			text: 'Repeated New Chat and example-card navigation keeps loading assistant content instead of freezing.',
			checkpoint: 'navigation-cycles-complete',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'settings-reactive',
			text: 'The Settings menu still opens after the repeated guest navigation cycle.',
			checkpoint: 'settings-menu-responsive',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'guest-navigation.welcome-cards-visible',
			checkpoint: 'welcome-cards-visible',
			visual: 'The guest welcome screen visibly shows example chat cards without the suggestion rail blocking them.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'guest-navigation.example-chat-content-visible',
			checkpoint: 'navigation-cycles-complete',
			visual: 'After repeated New Chat and example-card navigation, an assistant message is visible with no frozen loading state or raw error text.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'guest-navigation.settings-responsive',
			checkpoint: 'settings-menu-responsive',
			visual: 'The Settings menu is visible after the navigation cycles, confirming UI controls still respond.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

function getNewChatButton(page: any) {
	return page.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]').first();
}

async function openFirstIntroOrExampleChat(page: any) {
	const skipInterests = page.getByTestId('guest-interest-skip');
	const firstCard = page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]').first();
	const newChatButton = getNewChatButton(page);

	if (await skipInterests.isVisible({ timeout: 5000 }).catch(() => false)) {
		await skipInterests.click();
		await expect(skipInterests).not.toBeVisible({ timeout: 10000 });
	}

	if (!(await newChatButton.isVisible({ timeout: 1000 }).catch(() => false))) {
		await expect(firstCard).toBeVisible({ timeout: 10000 });
		await firstCard.click();
	}

	await expect(newChatButton).toBeVisible({ timeout: 15000 });
}

async function expectBlankFocusedComposer(page: any) {
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
	await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeFocused({ timeout: 5000 });
}

async function blurComposerAndWaitForWelcome(page: any) {
	const composer = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
	const dismissButton = page.getByTestId('input-dismiss-button');
	if (await dismissButton.isVisible({ timeout: 1000 }).catch(() => false)) {
		await dismissButton.click();
	} else {
		await composer.evaluate((element: HTMLElement) => element.blur());
	}
	await expect(composer).not.toBeFocused();
	await expect(page.getByTestId('daily-inspiration-area')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('suggestions-wrapper')).toHaveCount(0, { timeout: 3000 });
}

async function expectGuestWelcomeSuppressedForComposer(page: any) {
	await expect(page.getByTestId('daily-inspiration-area')).not.toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('welcome-content')).not.toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('report-issue-button')).not.toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('guest-input-context-link')).toHaveCount(0);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeFocused({ timeout: 5000 });
}

async function expectNewChatWelcomeSuppressedForComposer(page: any) {
	await expect(page.getByTestId('daily-inspiration-area')).not.toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('welcome-content')).not.toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('report-issue-button')).not.toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('recent-chats-scroll-container')).not.toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeFocused({ timeout: 5000 });
}

async function expectCurrentLandingSlide(page: any, slideIndex: number, inspirationId: string) {
	await expect(page.locator('[data-testid="daily-inspiration-mounted-slide"][data-current="true"]')).toHaveAttribute(
		'data-slide-index',
		String(slideIndex),
		{ timeout: SLIDE_NAVIGATION_TIMEOUT }
	);
	const banner = page.getByTestId('daily-inspiration-banner');
	await expect(banner).toHaveAttribute('data-current-inspiration-id', inspirationId, {
		timeout: SLIDE_NAVIGATION_TIMEOUT
	});
	await expect(banner).toHaveAttribute('data-guest-slide-phase', 'idle', {
		timeout: SLIDE_NAVIGATION_TIMEOUT
	});
}

async function expectLandingCarouselNavigatesBothDirections(page: any) {
	const banner = page.getByTestId('daily-inspiration-banner');
	await expect(banner).toBeVisible({ timeout: 10000 });
	const inspirationIds = (await banner.getAttribute('data-visible-inspiration-ids'))
		?.split(',')
		.filter(Boolean) ?? [];
	expect(inspirationIds.length, 'guest landing carousel should contain multiple slides').toBeGreaterThan(1);

	await expectCurrentLandingSlide(page, 0, inspirationIds[0]);
	for (let slideIndex = 1; slideIndex < inspirationIds.length; slideIndex += 1) {
		await page.getByTestId('daily-inspiration-next').click();
		await expectCurrentLandingSlide(page, slideIndex, inspirationIds[slideIndex]);
	}

	for (let slideIndex = inspirationIds.length - 2; slideIndex >= 0; slideIndex -= 1) {
		await page.getByTestId('daily-inspiration-previous').click();
		await expectCurrentLandingSlide(page, slideIndex, inspirationIds[slideIndex]);
	}
	await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: SLIDE_NAVIGATION_TIMEOUT });
}

async function resolveCssTokenColor(page: any, tokenName: string): Promise<string> {
	return page.evaluate((name: string) => {
		const probe = document.createElement('span');
		probe.style.backgroundColor = `var(${name})`;
		document.body.appendChild(probe);
		const color = getComputedStyle(probe).backgroundColor;
		probe.remove();
		return color;
	}, tokenName);
}

test.describe('Unauthenticated chat navigation stays reactive', () => {
	// contract-test: direct surface=gui.web assertions=public-example-chats.navigation.selected-state-visible
	test('light-mode sidebar keeps the selected chat distinct and below the active panel shadow', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1366, height: 900 });
		await page.addInitScript(() => {
			localStorage.setItem('theme_mode', 'light');
			localStorage.setItem('theme', 'light');
		});

		await page.goto(getE2EDebugUrl('/#chat-id=demo-who-develops-openmates'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', 'demo-who-develops-openmates', {
			timeout: 15000
		});

		const sidebar = page.getByTestId('activity-history-wrapper');
		if (!(await sidebar.isVisible({ timeout: 1000 }).catch(() => false))) {
			await page.getByTestId('sidebar-toggle').click();
		}
		await expect(sidebar).toBeVisible({ timeout: 10000 });

		const activeRow = page.locator('[data-testid="chat-item-wrapper"][data-chat-id="demo-who-develops-openmates"]');
		await expect(activeRow).toBeVisible({ timeout: 10000 });
		await expect(activeRow).toHaveClass(/active/);
		await expect(activeRow).toHaveCSS('background-color', await resolveCssTokenColor(page, '--color-grey-0'));

		const nonActiveChatId = await page.getByTestId('chat-item-wrapper').evaluateAll(
			(elements: HTMLElement[]) => elements.find((element) => element.dataset.chatId !== 'demo-who-develops-openmates')?.dataset.chatId ?? ''
		);
		expect(nonActiveChatId).not.toBe('');
		const hoveredRow = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${nonActiveChatId}"]`);
		await expect(hoveredRow).not.toHaveClass(/active/);
		await hoveredRow.hover();
		await expect(hoveredRow).toHaveCSS('background-color', await resolveCssTokenColor(page, '--color-grey-10'));

		const layerStyles = await page.getByTestId('active-chat-container').evaluate((activeChat: HTMLElement) => {
			const findFixedLayer = (element: HTMLElement | null): HTMLElement | null => {
				let current = element;
				while (current && getComputedStyle(current).position !== 'fixed') current = current.parentElement;
				return current;
			};
			const sidebarContent = document.querySelector<HTMLElement>('[data-testid="activity-history-wrapper"]');
			const mainLayer = findFixedLayer(activeChat);
			const sidebarLayer = findFixedLayer(sidebarContent);
			return {
				mainZIndex: Number.parseInt(mainLayer ? getComputedStyle(mainLayer).zIndex : '', 10),
				sidebarZIndex: Number.parseInt(sidebarLayer ? getComputedStyle(sidebarLayer).zIndex : '', 10),
				boxShadow: getComputedStyle(activeChat).boxShadow
			};
		});
		expect(layerStyles.mainZIndex).toBeGreaterThan(layerStyles.sidebarZIndex);
		expect(layerStyles.boxShadow).not.toBe('none');
	});

	// contract-test: direct surface=gui.web assertions=message-input.focus.guest-welcome-suppression
	test('focused desktop guest composer suppresses surrounding welcome UI', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(45000);
		await page.setViewportSize({ width: 1366, height: 900 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('daily-inspiration-area')).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('report-issue-button')).toBeVisible({ timeout: 10000 });

		const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
		await editor.click();
		await expectGuestWelcomeSuppressedForComposer(page);
	});

	// contract-test: direct surface=gui.web assertions=message-input.focus.guest-welcome-suppression
	test('focused desktop authenticated composer suppresses surrounding welcome UI', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(120000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		await page.setViewportSize({ width: 1366, height: 900 });

		const log = createSignupLogger('AUTH_COMPOSER_SUPPRESSION');
		const screenshot = createStepScreenshotter(log);
		await loginToTestAccount(page, log, screenshot);

		await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 20000 });
		await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('daily-inspiration-area')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 15000 });

		const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
		await editor.click();
		await expectNewChatWelcomeSuppressedForComposer(page);
	});

	// contract-test: supporting surface=gui.web assertions=message-input.focus.guest-welcome-suppression
	test('clicking intro/example chats and new-chat repeatedly keeps UI responsive', async ({
		page
	}: {
		page: any;
	}, testInfo: any) => {
		test.setTimeout(120000);
		if (PROOF_VIEWPORT) {
			await page.setViewportSize(PROOF_VIEWPORT);
		}
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(CHAT_NAVIGATION_PROOF, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;

		const consoleLogs: string[] = [];
		page.on('console', (msg: any) => {
			consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
		});

		// ─── 1. Load app as a fresh unauthenticated user ─────────────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 10000 });
		expect(await page.evaluate(() => window.location.hash)).not.toContain('demo-for-everyone');
		console.log('[chat-nav] Initial logged-out welcome screen loaded');
		await openFirstIntroOrExampleChat(page);
		console.log('[chat-nav] Intro/example chat opened after guest-interest onboarding');

		// ─── 2. Cycle: new chat → intro/example chat card, CYCLES times ──────
		for (let cycle = 1; cycle <= CYCLES; cycle++) {
			console.log(`[chat-nav] === Cycle ${cycle}/${CYCLES} ===`);

			// ── 2a. Click "New Chat" CTA (fullwidth on intro/demo chats) ────
			const newChatButton = getNewChatButton(page);
			await expect(newChatButton).toBeVisible({ timeout: 8000 });
			await newChatButton.click();
			console.log(`[chat-nav] [${cycle}] Clicked New Chat button`);
			await expectBlankFocusedComposer(page);
			console.log(`[chat-nav] [${cycle}] Blank composer focused after New Chat click`);
			await blurComposerAndWaitForWelcome(page);

			// Wait for the welcome screen: message editor and chat cards appear.
			// The message editor is always present but the nonAuth chat cards only
			// render when showWelcome=true, so we wait for a chat card to be visible.
			const chatCard = page
				.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]')
				.first();
			await expect(chatCard).toBeVisible({ timeout: 10000 });
			if (proof && cycle === 1) {
				await proof.assert('guest-navigation.welcome-cards-visible', async () => {
					await expect(chatCard).toBeVisible();
					await expect(page.getByTestId('suggestions-wrapper')).toHaveCount(0);
				});
				await proof.checkpoint('welcome-cards-visible');
			}
			console.log(`[chat-nav] [${cycle}] Welcome screen cards visible`);

			// ── 2b. Record current hash, then click the first card ───────────
			const hashBefore = await page.evaluate(() => window.location.hash);

			await chatCard.click();
			console.log(`[chat-nav] [${cycle}] Clicked first chat card`);

			// Wait for the URL hash to change (proves navigation happened) and
			// for the active chat container to become visible (proves UI reacted).
			await page.waitForFunction(
				(before: string) => window.location.hash !== before && window.location.hash.includes('chat-id='),
				hashBefore,
				{ timeout: CHAT_LOAD_TIMEOUT }
			);
			const hashAfter = await page.evaluate(() => window.location.hash);
			console.log(`[chat-nav] [${cycle}] URL hash updated: ${hashBefore} → ${hashAfter}`);

			// Verify chat content rendered (at least one assistant message visible).
			const assistantMessage = page.getByTestId('mate-message-content').first();
			await expect(assistantMessage).toBeVisible({ timeout: CHAT_LOAD_TIMEOUT });
			if (proof && cycle === CYCLES) {
				await proof.assert('guest-navigation.example-chat-content-visible', async () => {
					await expect(assistantMessage).toBeVisible();
					await expect(page.getByText('The AI service encountered an error while processing your request.')).toHaveCount(0);
				});
				await proof.checkpoint('navigation-cycles-complete');
			}
			console.log(`[chat-nav] [${cycle}] Assistant message content visible — UI is reactive`);
		}

		console.log(`[chat-nav] All ${CYCLES} cycles completed — UI remained reactive throughout`);

		// ─── 3. Navigate back to new chat one final time ──────────────────────
		const finalNewChatButton = getNewChatButton(page);
		await expect(finalNewChatButton).toBeVisible({ timeout: 8000 });
		await finalNewChatButton.click();
		await expectBlankFocusedComposer(page);
		await blurComposerAndWaitForWelcome(page);
		await page.getByTestId('daily-inspiration-previous').click();
		await expectLandingCarouselNavigatesBothDirections(page);
		console.log('[chat-nav] Guest landing carousel navigated from first to last slide and back');

		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toBeVisible({ timeout: 8000 });
		console.log('[chat-nav] New chat welcome screen confirmed after final New Chat click');

		// ─── 4. Open the settings panel ───────────────────────────────────────
		// profile-container is the settings toggle (avatar / settings icon).
		const settingsToggle = page.getByTestId('profile-container');
		await expect(settingsToggle).toBeVisible({ timeout: 8000 });
		await settingsToggle.click();
		console.log('[chat-nav] Clicked settings toggle');

		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toBeVisible({ timeout: SETTINGS_TIMEOUT });
		await expect(settingsMenu.getByTestId('learning-mode-toggle-wrapper')).toHaveCount(0);
		if (proof) {
			await proof.assert('guest-navigation.settings-responsive', async () => {
				await expect(settingsMenu).toBeVisible();
				await expect(settingsMenu.getByTestId('learning-mode-toggle-wrapper')).toHaveCount(0);
			});
			await proof.checkpoint('settings-menu-responsive');
		}
		console.log('[chat-nav] Settings menu opened — settings panel is reactive');

		// ─── 5. Close the settings panel ─────────────────────────────────────
		const closeButton = page.getByTestId('icon-button-close');
		await expect(closeButton).toBeVisible({ timeout: 5000 });
		await closeButton.click();
		console.log('[chat-nav] Clicked settings close button');

		await expect(settingsMenu).not.toBeVisible({ timeout: SETTINGS_TIMEOUT });
		console.log('[chat-nav] Settings menu closed — close action is reactive');

		// ─── 6. Final: no JS errors occurred during the test ─────────────────
		const jsErrors = consoleLogs.filter(
			(l) =>
				l.startsWith('[error]') &&
				!l.includes('favicon') &&
				!l.includes('net::ERR_') &&
				!l.includes('Failed to load resource')
		);
		if (jsErrors.length > 0) {
			console.warn(`[chat-nav] JS errors detected during test:\n${jsErrors.join('\n')}`);
		}
		expect(
			jsErrors.length,
			`Expected no JS errors during navigation cycles. Errors:\n${jsErrors.join('\n')}`
		).toBe(0);
		if (proof) {
			await proof.attach();
		}

		console.log('[chat-nav] All assertions passed — UI stays fully reactive after rapid navigation');
	});
});
