/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * New chat screen — pinned chats sort order test.
 *
 * Validates that the "Continue where you left off" carousel on the new-chat
 * welcome screen respects the sort order:
 *   1. Last opened chat (primary resume card)
 *   2. Pinned chats (before non-pinned)
 *   3. Last edited chats
 *   Total: at most 10 cards
 *
 * Flow:
 *   1. Login → open sidebar → pick a non-first chat and pin it
 *   2. Navigate to new chat screen → verify pinned card appears before non-pinned
 *   3. Verify total card count ≤ 10
 *   4. Cleanup: unpin the chat
 *
 * Bug history this test suite guards against:
 *   - OPE-105: pinned chats not shown first in new chat carousel
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');

const {
	deleteActiveChat,
	loginToTestAccount,
	sendMessage,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const consoleLogs: string[] = [];
const warnErrorLogs: Array<{ timestamp: string; type: string; text: string }> = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	warnErrorLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-50).forEach((log: string) => console.log(log));
		console.log('\n--- END DEBUG INFO ---\n');
	}
	if (warnErrorLogs.length > 0) {
		console.log(`\n[WARN/ERROR SUMMARY] ${warnErrorLogs.length} warning(s)/error(s) captured`);
		for (const entry of warnErrorLogs.slice(-10)) {
			console.log(`  [${entry.type}] ${entry.text.slice(0, 200)}`);
		}
	}
});

// ─── Helpers ────────────────────────────────────────────────────────────────

async function ensureSidebarOpen(page: any, logStep: (...args: any[]) => void): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	const isOpen = await activityHistory.isVisible().catch(() => false);
	if (isOpen) return;
	const menuToggle = page.locator('[data-testid="sidebar-toggle"]');
	await expect(menuToggle).toBeVisible({ timeout: 5000 });
	await menuToggle.click();
	await expect(activityHistory).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(2000);
	logStep('Sidebar opened.');
}

async function closeSidebar(page: any, logStep: (...args: any[]) => void): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	const isOpen = await activityHistory.isVisible().catch(() => false);
	if (!isOpen) return;
	const closeButton = page.getByRole('button', { name: 'Close' });
	if (await closeButton.isVisible({ timeout: 1000 }).catch(() => false)) {
		await closeButton.click();
	} else {
		const menuToggle = page.locator('[data-testid="sidebar-toggle"]');
		if (await menuToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
			await menuToggle.click();
		}
	}
	await page.waitForTimeout(500);
	logStep('Sidebar closed.');
}

/**
 * Pin or unpin a chat item via right-click context menu.
 */
async function togglePinViaContextMenu(
	page: any,
	chatItem: any,
	action: 'pin' | 'unpin',
	logStep: (...args: any[]) => void
): Promise<void> {
	await expect(async () => {
		await page.keyboard.press('Escape');
		await page.waitForTimeout(300);
		await chatItem.click({ button: 'right' });
		const menuItem = page.getByTestId(`chat-context-${action}`);
		await expect(menuItem).toBeVisible({ timeout: 3000 });
		await menuItem.click();
	}).toPass({ timeout: 20000 });
	logStep(`Clicked "${action}" in context menu.`);
	await page.waitForTimeout(1500);
}

/**
 * Get all card elements from the recent-chats carousel (auth section).
 * Returns an array of { title, pinned } for each card (resume + recent).
 */
async function getCarouselCards(page: any): Promise<Array<{ chatId: string | null; title: string; pinned: string | null }>> {
	const container = page.getByTestId('recent-chats-scroll-container').first();
	if (!(await container.isVisible({ timeout: 3000 }).catch(() => false))) {
		return [];
	}

	const cards: Array<{ chatId: string | null; title: string; pinned: string | null }> = [];

	// Resume card (no data-pinned attr — it's the last-opened, always first)
	const resumeLargeTitle = container.locator('[data-testid="resume-chat-large-card"]:not([data-chat-id]) [data-testid="resume-large-title"], [data-testid="resume-chat-card"]:not([data-chat-id]) [data-testid="resume-chat-title"]').first();
	if (await resumeLargeTitle.isVisible({ timeout: 500 }).catch(() => false)) {
		const title = (await resumeLargeTitle.textContent())?.trim() || '';
		if (title) cards.push({ chatId: null, title, pinned: null });
	}

	// Recent chat cards (have data-chat-id and data-pinned)
	const recentCards = container.locator('[data-chat-id]');
	const count = await recentCards.count();
	for (let i = 0; i < count; i++) {
		const card = recentCards.nth(i);
		const chatId = await card.getAttribute('data-chat-id');
		const pinned = await card.getAttribute('data-pinned');
		const titleEl = card.locator('[data-testid="resume-large-title"], [data-testid="resume-chat-title"]').first();
		const title = (await titleEl.textContent())?.trim() || '';
		if (title) cards.push({ chatId, title, pinned });
	}

	return cards;
}

// ─── Test ───────────────────────────────────────────────────────────────────

// contract-test: supporting surface=gui.web assertions=chat-navigation.order.sidebar-header-match
test('pinned chats appear before non-pinned in new chat carousel (OPE-105)', async ({
	page
}: {
	page: any;
}) => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.setTimeout(300000);

	const logStep = createSignupLogger('PINNED_SORT');
	const takeStepScreenshot = createStepScreenshotter(logStep, {
		filenamePrefix: 'new-chat-pinned-sort'
	});
	await archiveExistingScreenshots(logStep);

	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});

	// =========================================================================
	// PHASE 1: Login
	// =========================================================================
	logStep('Phase 1: Login...');
	await loginToTestAccount(page, logStep, takeStepScreenshot);
	await page.waitForTimeout(4000);
	await takeStepScreenshot(page, '01-logged-in');

	let targetChatId: string | null = null;
	let targetTitle = '';

	try {
		// =========================================================================
		// PHASE 2: Create and pin a normal run-owned chat. Shared account history can
		// contain demo/incognito chats whose context menu intentionally omits Pin.
		// =========================================================================
		logStep('Phase 2: Creating a normal chat to pin...');
		await startNewChat(page, logStep);
		await sendMessage(
			page,
			withMockMarker(`Pinned sort setup ${Date.now().toString(36)}`, 'chat_flow_capital'),
			logStep,
			takeStepScreenshot,
			'pinned-sort-setup'
		);

		await ensureSidebarOpen(page, logStep);
		const targetChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
		await expect(targetChatItem).toBeVisible({ timeout: 10000 });
		targetChatId = await targetChatItem.getAttribute('data-chat-id');
		targetTitle = (await targetChatItem.getByTestId('chat-title').textContent())?.trim() || '';
		expect(targetChatId, 'Created test chat must expose data-chat-id').toBeTruthy();
		targetTitle ||= targetChatId ?? 'created chat';
		logStep(`Target chat to pin: "${targetTitle}" (${targetChatId})`);

		if (!(await targetChatItem.getByTestId('pin-indicator').isVisible({ timeout: 500 }).catch(() => false))) {
			logStep('Pinning target chat...');
			await togglePinViaContextMenu(page, targetChatItem, 'pin', logStep);
		}

		const pinnedChatItem = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${targetChatId}"]`);
		await expect(async () => {
			await expect(pinnedChatItem.getByTestId('pin-indicator')).toBeVisible();
		}).toPass({ timeout: 10000 });
		logStep('Pin indicator visible.');
		await takeStepScreenshot(page, '02-chat-pinned');
		await startNewChat(page, logStep);

		// =========================================================================
		// PHASE 3: Verify sort order on the new-chat welcome screen carousel.
		// =========================================================================
		logStep('Phase 3: Checking carousel on new chat screen...');
		await closeSidebar(page, logStep);

		// The carousel should be visible on the new chat welcome screen
		const resumeCardTitle = page.locator('[data-testid="resume-large-title"], [data-testid="resume-chat-title"]').first();
		await expect(async () => {
			await expect(resumeCardTitle).toBeVisible();
		}).toPass({ timeout: 30000 });
		await page.waitForTimeout(2000);
		await takeStepScreenshot(page, '03-new-chat-screen');

		// Get all carousel cards
		const cards = await getCarouselCards(page);
		logStep(`Carousel cards (${cards.length}): ${JSON.stringify(cards.map(c => ({ t: c.title.slice(0, 30), p: c.pinned })))}`);

		// ASSERTION 1: Total cards <= 10
		expect(cards.length).toBeLessThanOrEqual(10);
		logStep(`PASS: Total cards = ${cards.length} (<= 10).`);

		// ASSERTION 2: Pinned cards appear before non-pinned cards
		// Skip the first card (resume card, pinned=null) — it's always first by design.
		const recentCards = cards.filter(c => c.pinned !== null);
		let seenNonPinned = false;
		const orderViolations: string[] = [];
		for (const card of recentCards) {
			if (card.pinned === 'true' && seenNonPinned) {
				orderViolations.push(`Pinned "${card.title}" appears after a non-pinned card`);
			}
			if (card.pinned === 'false') {
				seenNonPinned = true;
			}
		}
		if (orderViolations.length > 0) {
			logStep(`FAIL: Sort order violations: ${JSON.stringify(orderViolations)}`);
		}
		expect(orderViolations).toEqual([]);
		logStep('PASS: Pinned chats appear before non-pinned chats.');

		// ASSERTION 3: Our pinned chat is in the carousel
		const pinnedCards = recentCards.filter(c => c.pinned === 'true');
		logStep(`Pinned cards in carousel: ${JSON.stringify(pinnedCards.map(c => c.title.slice(0, 40)))}`);
		const targetInCarousel = cards.some(c => c.chatId === targetChatId);
		expect(targetInCarousel).toBe(true);
		logStep(`PASS: Pinned chat "${targetTitle}" found in carousel.`);

		// ASSERTION 4: Pinned cards show a pin badge icon
		const pinBadges = page.locator('[data-testid="resume-card-pin"]');
		const pinBadgeCount = await pinBadges.count();
		logStep(`Pin badges visible: ${pinBadgeCount}`);
		expect(pinBadgeCount).toBeGreaterThanOrEqual(1);
		logStep('PASS: Pin badge visible on pinned card(s).');

		await takeStepScreenshot(page, '03-verified');

		logStep('Test completed successfully.');
	} finally {
		if (targetChatId) {
			logStep('Phase 4: Cleanup — unpinning and deleting test chat...');
			await ensureSidebarOpen(page, logStep).catch(() => undefined);
			const cleanupChatItem = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${targetChatId}"]`);
			if (await cleanupChatItem.isVisible({ timeout: 5000 }).catch(() => false)) {
				if (await cleanupChatItem.getByTestId('pin-indicator').isVisible({ timeout: 500 }).catch(() => false)) {
					await togglePinViaContextMenu(page, cleanupChatItem, 'unpin', logStep).catch((error: unknown) => {
						logStep(`Cleanup unpin failed (non-fatal): ${String(error)}`);
					});
				}
				await cleanupChatItem.click().catch(() => undefined);
				await deleteActiveChat(page, logStep, takeStepScreenshot, 'pinned-sort-cleanup');
			}
		}
	}
});
