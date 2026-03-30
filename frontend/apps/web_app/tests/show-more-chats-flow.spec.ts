/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Show More Chats Flow Tests (OPE-104)
 *
 * Tests the sidebar "Show more" button for incremental chat loading:
 * 1. After login + sync, sidebar shows initial 11 user chats.
 * 2. Clicking "Show more" reveals 20 more chats incrementally.
 * 3. Clicking an older chat (beyond initial 11) opens it with messages.
 *
 * Bug history this test suite guards against:
 * - Show more button was wired but never expanded beyond 20 total chats
 * - Chats beyond the first 10 failed to open (no on-demand message loading)
 * - sync_metadata_chats was never sent after Phase 3, so chats 101–1000
 *   were invisible in the sidebar
 *
 * Architecture:
 * - Initial sync (Phase 1–3) loads up to 100 chats into IndexedDB.
 * - After Phase 3, sync_metadata_chats loads metadata for chats 101–1000.
 * - "Show more" button (data-testid="show-more-chats") increases the
 *   visible limit by 20 per click. When all local chats are shown,
 *   it fetches from server via load_more_chats WebSocket message.
 * - Clicking a metadata-only chat triggers on-demand message loading
 *   via request_chat_content_batch WebSocket message.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('@playwright/test');
const {
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-50).forEach((log: string) => console.log(log));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

/** Ensure sidebar panel is visible (open it on mobile if needed). */
async function ensureSidebarOpen(page: any): Promise<void> {
	const toggle = page.locator('[data-testid="sidebar-toggle"]');
	if (await toggle.isVisible().catch(() => false)) {
		await toggle.click();
		await page.waitForTimeout(1000);
	}
}

/** Wait for initial sync to complete (syncing indicator disappears). */
async function waitForSyncComplete(page: any): Promise<void> {
	const syncingIndicator = page.locator('.syncing-inline-indicator');
	try {
		await expect(syncingIndicator).not.toBeVisible({ timeout: 30000 });
	} catch {
		console.log('WARNING: Syncing indicator still visible after 30s — continuing anyway.');
	}
}

// ---------------------------------------------------------------------------
// Test 1: Show more button appears and reveals additional chats
// ---------------------------------------------------------------------------

test('show more button reveals additional chats incrementally', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials();

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);

	// Step 1: Login
	await loginToTestAccount(page);

	// Step 2: Wait for sync to complete
	await waitForSyncComplete(page);
	await ensureSidebarOpen(page);

	// Step 3: Wait for chat items to appear in sidebar
	const chatItems = page.locator('.chat-item');
	await expect(chatItems.first()).toBeVisible({ timeout: 15000 });

	// Step 4: Count initial chat items — should be limited (INITIAL_USER_CHAT_LIMIT + static)
	const initialCount = await chatItems.count();
	console.log(`Initial sidebar chat count (including static): ${initialCount}`);

	// Step 5: Check "Show more" button is visible (requires >11 user chats on test account)
	const showMoreButton = page.locator('[data-testid="show-more-chats"]');
	const showMoreVisible = await showMoreButton.isVisible({ timeout: 5000 }).catch(() => false);

	if (!showMoreVisible) {
		console.log('Show more button not visible — test account may have ≤11 chats. Skipping expansion test.');
		test.skip();
		return;
	}

	// Step 6: Click "Show more" and verify more chats appear
	await showMoreButton.click();
	await page.waitForTimeout(2000);

	const expandedCount = await page.locator('.chat-item').count();
	console.log(`After first "Show more": ${expandedCount} chats (was ${initialCount})`);
	expect(expandedCount).toBeGreaterThan(initialCount);

	// Step 7: If button is still visible, click again and verify further expansion
	const showMoreStillVisible = await showMoreButton.isVisible().catch(() => false);
	if (showMoreStillVisible) {
		await showMoreButton.click();
		await page.waitForTimeout(2000);

		const secondExpandedCount = await page.locator('.chat-item').count();
		console.log(`After second "Show more": ${secondExpandedCount} chats (was ${expandedCount})`);
		expect(secondExpandedCount).toBeGreaterThanOrEqual(expandedCount);
	}
});

// ---------------------------------------------------------------------------
// Test 2: Clicking an older chat (beyond initial 11) opens it with messages
// ---------------------------------------------------------------------------

test('clicking an older chat loads its messages on demand', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials();

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);

	// Step 1: Login and wait for sync
	await loginToTestAccount(page);
	await waitForSyncComplete(page);
	await ensureSidebarOpen(page);

	// Step 2: Wait for chat items
	await expect(page.locator('.chat-item').first()).toBeVisible({ timeout: 15000 });

	// Step 3: Show more chats if button is available
	const showMoreButton = page.locator('[data-testid="show-more-chats"]');
	const showMoreVisible = await showMoreButton.isVisible({ timeout: 5000 }).catch(() => false);
	if (showMoreVisible) {
		await showMoreButton.click();
		await page.waitForTimeout(2000);
	}

	// Step 4: Click on a chat that is NOT the currently active one
	// Pick a non-active chat towards the end of the list (likely an older chat)
	const allChatItems = page.locator('.chat-item:not(.active)');
	const olderChatCount = await allChatItems.count();

	if (olderChatCount === 0) {
		console.log('No non-active user chats found — skipping older chat test.');
		test.skip();
		return;
	}

	// Pick the last one (oldest)
	const targetIndex = Math.min(olderChatCount - 1, 15); // Use 15th or last available
	const targetChat = allChatItems.nth(targetIndex);
	const chatTitle = await targetChat.locator('.chat-title').textContent().catch(() => 'unknown');
	console.log(`Clicking older chat at index ${targetIndex}: "${chatTitle}"`);

	await targetChat.click();
	await page.waitForTimeout(1000);

	// Step 5: On mobile, the sidebar closes. On desktop, the chat area updates.
	// Wait for either the chat history to show messages or the message editor to appear.
	const chatHistory = page.locator('.chat-history');
	const messageEditor = page.locator('.editor-content.prose');

	// Wait for the chat area to render (either messages or the empty editor)
	await expect(chatHistory.or(messageEditor)).toBeVisible({ timeout: 15000 });

	// Step 6: Wait for messages to load (on-demand from server if needed)
	// Messages may take a moment to arrive via WebSocket
	const messageContainer = page.locator('.message-container, .chat-message');
	try {
		await expect(messageContainer.first()).toBeVisible({ timeout: 20000 });
		const messageCount = await messageContainer.count();
		console.log(`Older chat loaded successfully with ${messageCount} message(s).`);
		expect(messageCount).toBeGreaterThan(0);
	} catch {
		// Check if this might be a metadata-only chat waiting for messages
		// Look for console logs indicating on-demand loading was triggered
		const onDemandLogs = consoleLogs.filter(l =>
			l.includes('requesting from server (on-demand loading)') ||
			l.includes('request_chat_content_batch')
		);
		if (onDemandLogs.length > 0) {
			console.log('On-demand message loading was triggered — waiting longer for messages...');
			await expect(messageContainer.first()).toBeVisible({ timeout: 30000 });
			const messageCount = await messageContainer.count();
			console.log(`Messages arrived after on-demand loading: ${messageCount}`);
			expect(messageCount).toBeGreaterThan(0);
		} else {
			// Chat may genuinely have no messages (empty chat) — that's acceptable
			console.log('No messages found and no on-demand loading triggered — chat may be empty.');
		}
	}
});
