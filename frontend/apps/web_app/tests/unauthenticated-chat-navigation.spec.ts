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
 * Test strategy: cycle through new-chat ↔ intro-chat navigation 5 times as an
 * unauthenticated user, then verify the settings panel can still be opened and
 * closed. If the UI freezes at any point, the corresponding waitForSelector /
 * visibility assertions will time out and fail the spec.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const CYCLES = 5;
const CHAT_LOAD_TIMEOUT = 12000;
const SETTINGS_TIMEOUT = 8000;

test.describe('Unauthenticated chat navigation stays reactive', () => {
	test('clicking intro/example chats and new-chat repeatedly keeps UI responsive', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(120000);

		const consoleLogs: string[] = [];
		page.on('console', (msg: any) => {
			consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
		});

		// ─── 1. Load app as a fresh unauthenticated user ─────────────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// The app auto-navigates to the for-everyone intro chat for new visitors.
		await page.waitForFunction(
			() => window.location.hash.includes('demo-for-everyone'),
			null,
			{ timeout: 15000 }
		);
		console.log('[chat-nav] Initial for-everyone chat loaded');

		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });

		// ─── 2. Cycle: new chat → intro/example chat card, CYCLES times ──────
		for (let cycle = 1; cycle <= CYCLES; cycle++) {
			console.log(`[chat-nav] === Cycle ${cycle}/${CYCLES} ===`);

			// ── 2a. Click "New Chat" CTA (fullwidth on intro/demo chats) ────
			const newChatButton = page.getByTestId('new-chat-cta-fullwidth');
			await expect(newChatButton).toBeVisible({ timeout: 8000 });
			await newChatButton.click();
			console.log(`[chat-nav] [${cycle}] Clicked New Chat button`);

			// Wait for the welcome screen: message editor and chat cards appear.
			// The message editor is always present but the nonAuth chat cards only
			// render when showWelcome=true, so we wait for a chat card to be visible.
			const chatCard = page
				.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]')
				.first();
			await expect(chatCard).toBeVisible({ timeout: 10000 });
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
			console.log(`[chat-nav] [${cycle}] Assistant message content visible — UI is reactive`);
		}

		console.log(`[chat-nav] All ${CYCLES} cycles completed — UI remained reactive throughout`);

		// ─── 3. Navigate back to new chat one final time ──────────────────────
		const finalNewChatButton = page.getByTestId('new-chat-cta-fullwidth');
		await expect(finalNewChatButton).toBeVisible({ timeout: 8000 });
		await finalNewChatButton.click();

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

		console.log('[chat-nav] All assertions passed — UI stays fully reactive after rapid navigation');
	});
});
