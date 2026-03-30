/* eslint-disable no-console */
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

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
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
	const activityHistory = page.locator('.activity-history-wrapper');
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
	const activityHistory = page.locator('.activity-history-wrapper');
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

async function clickNewChat(page: any, logStep: (...args: any[]) => void): Promise<void> {
	const newChatBtn = page.locator('[data-testid="new-chat-button"]');
	await expect(newChatBtn).toBeVisible({ timeout: 5000 });
	await newChatBtn.click();
	logStep('Clicked New Chat button.');
	await page.waitForTimeout(3000);
}

/**
 * Pin or unpin a chat item via right-click context menu.
 * The chatItem locator must already point to the .chat-item-wrapper to right-click.
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
		const menuItem = page.locator(`.menu-item.${action}`);
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
async function getCarouselCards(page: any): Promise<Array<{ title: string; pinned: string | null }>> {
	const container = page.locator('.recent-chats-scroll-container').first();
	if (!(await container.isVisible({ timeout: 3000 }).catch(() => false))) {
		return [];
	}

	const cards: Array<{ title: string; pinned: string | null }> = [];

	// Resume card (no data-pinned attr — it's the last-opened, always first)
	const resumeLargeTitle = container.locator('.resume-chat-large-card:not([data-chat-id]) .resume-large-title, .resume-chat-card:not([data-chat-id]) .resume-chat-title').first();
	if (await resumeLargeTitle.isVisible({ timeout: 500 }).catch(() => false)) {
		const title = (await resumeLargeTitle.textContent())?.trim() || '';
		if (title) cards.push({ title, pinned: null });
	}

	// Recent chat cards (have data-chat-id and data-pinned)
	const recentCards = container.locator('[data-chat-id]');
	const count = await recentCards.count();
	for (let i = 0; i < count; i++) {
		const card = recentCards.nth(i);
		const pinned = await card.getAttribute('data-pinned');
		const titleEl = card.locator('.resume-large-title, .resume-chat-title').first();
		const title = (await titleEl.textContent())?.trim() || '';
		if (title) cards.push({ title, pinned });
	}

	return cards;
}

// ─── Test ───────────────────────────────────────────────────────────────────

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

	// =========================================================================
	// PHASE 2: Find a chat to pin — pick the 3rd chat (index 2) from sidebar
	// so it's not already the last-opened/resume chat
	// =========================================================================
	logStep('Phase 2: Finding a chat to pin...');
	await ensureSidebarOpen(page, logStep);

	// Wait for chat items to populate after sync
	const chatItemsLocator = page.locator('.chat-item-wrapper');
	await expect(chatItemsLocator.first()).toBeVisible({ timeout: 20000 });
	// Allow more items to load
	await page.waitForTimeout(3000);

	const chatCount = await chatItemsLocator.count();
	logStep(`Sidebar shows ${chatCount} chats.`);
	expect(chatCount).toBeGreaterThanOrEqual(3);

	// Pick the 3rd chat (unlikely to be resume card)
	const targetIndex = 2;
	const targetChatItem = chatItemsLocator.nth(targetIndex);
	const targetTitle = (await targetChatItem.locator('.chat-title').textContent())?.trim() || '';
	logStep(`Target chat to pin: "${targetTitle}" (index ${targetIndex})`);
	expect(targetTitle).toBeTruthy();

	// Check if already pinned (has pin-indicator) — if so, skip pinning
	const alreadyPinned = await targetChatItem.locator('.pin-indicator').isVisible({ timeout: 500 }).catch(() => false);

	if (!alreadyPinned) {
		logStep('Pinning target chat...');
		await togglePinViaContextMenu(page, targetChatItem, 'pin', logStep);

		// After pinning, the chat reorders in the sidebar — find it by title
		const pinnedChatItem = page.locator('.chat-item-wrapper').filter({ hasText: targetTitle }).first();
		await expect(async () => {
			const pinIndicator = pinnedChatItem.locator('.pin-indicator');
			await expect(pinIndicator).toBeVisible();
		}).toPass({ timeout: 10000 });
		logStep('Pin indicator visible.');
	} else {
		logStep('Chat already pinned — skipping pin step.');
	}
	await takeStepScreenshot(page, '02-chat-pinned');

	// =========================================================================
	// PHASE 3: Navigate to new chat screen and verify sort order
	// =========================================================================
	logStep('Phase 3: Navigating to new chat screen...');
	await closeSidebar(page, logStep);
	await clickNewChat(page, logStep);

	const resumeContainer = page.locator('.recent-chats-scroll-container').first();
	await expect(resumeContainer).toBeVisible({ timeout: 20000 });
	await page.waitForTimeout(2000);
	await takeStepScreenshot(page, '03-new-chat-screen');

	// Get all carousel cards
	const cards = await getCarouselCards(page);
	logStep(`Carousel cards (${cards.length}): ${JSON.stringify(cards.map(c => ({ t: c.title.slice(0, 30), p: c.pinned })))}`);

	// ASSERTION 1: Total cards ≤ 10
	expect(cards.length).toBeLessThanOrEqual(10);
	logStep(`PASS: Total cards = ${cards.length} (≤ 10).`);

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
	const targetInCarousel = cards.some(c => c.title === targetTitle);
	expect(targetInCarousel).toBe(true);
	logStep(`PASS: Pinned chat "${targetTitle}" found in carousel.`);

	await takeStepScreenshot(page, '03-verified');

	// =========================================================================
	// PHASE 4: Cleanup — unpin the chat
	// =========================================================================
	logStep('Phase 4: Cleanup — unpinning chat...');
	await ensureSidebarOpen(page, logStep);

	// Find the chat again in sidebar
	const cleanupChatItem = page.locator('.chat-item-wrapper').filter({ hasText: targetTitle }).first();
	await expect(cleanupChatItem).toBeVisible({ timeout: 10000 });
	await togglePinViaContextMenu(page, cleanupChatItem, 'unpin', logStep);

	// Verify pin indicator gone
	await expect(async () => {
		const pinIndicator = cleanupChatItem.locator('.pin-indicator');
		await expect(pinIndicator).not.toBeVisible();
	}).toPass({ timeout: 10000 });
	logStep('Cleanup done — chat unpinned.');
	await takeStepScreenshot(page, '04-cleanup-done');

	logStep('Test completed successfully.');
});
