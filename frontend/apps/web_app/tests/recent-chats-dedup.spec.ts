/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Recent chats resume card update test.
 *
 * Validates that the "Continue where you left off" resume card on the
 * new-chat welcome screen updates correctly when switching between chats:
 *
 *   1. Login → verify at least 2 chats exist in sidebar
 *   2. Open chat A from sidebar → click "New Chat" → verify resume card shows chat A's title
 *   3. Open chat B from sidebar → click "New Chat" → verify resume card shows chat B's title
 *   4. Verify no duplicate cards in the recent-chats horizontal scroll area
 *
 * This test catches the bug where the resume card shows a stale chat from
 * initial login instead of the most recently viewed chat.
 *
 * Issue: 3054f5ba — resume card shows stale chat on new-chat transition
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
	getE2EDebugUrl
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
	// Report any warn/error logs even on success
	if (warnErrorLogs.length > 0) {
		console.log(`\n[WARN/ERROR SUMMARY] ${warnErrorLogs.length} warning(s)/error(s) captured`);
		for (const entry of warnErrorLogs.slice(-10)) {
			console.log(`  [${entry.type}] ${entry.text.slice(0, 200)}`);
		}
	}
});

// ─── Helpers ────────────────────────────────────────────────────────────────

async function performLogin(
	page: any,
	logStep: (...args: any[]) => void,
	takeStepScreenshot: (...args: any[]) => Promise<void>
): Promise<void> {
	// Use shared login helper with OTP retry + clock-drift compensation.
	await loginToTestAccount(page, logStep, takeStepScreenshot);
	logStep('Login complete. Waiting for phased sync...');
	// Wait for phased sync to complete
	await page.waitForTimeout(4000);
}

/**
 * Open the sidebar and return the titles of the first N user chats.
 * Closes the sidebar afterwards.
 */
async function getSidebarChatTitles(
	page: any,
	logStep: (...args: any[]) => void,
	count: number = 5
): Promise<string[]> {
	// Open sidebar
	const menuToggle = page.locator('[data-testid="sidebar-toggle"]');
	const activityHistory = page.getByTestId('activity-history-wrapper');
	const isSidebarOpen = await activityHistory.isVisible().catch(() => false);
	if (!isSidebarOpen) {
		await expect(menuToggle).toBeVisible({ timeout: 5000 });
		await menuToggle.click();
		await expect(activityHistory).toBeVisible({ timeout: 10000 });
		await page.waitForTimeout(2000);
	}

	// Get chat titles (skip encrypted/unnamed chats)
	const chatItems = page.locator('[data-testid="chat-item"] .chat-title');
	const chatCount = await chatItems.count();
	const titles: string[] = [];
	for (let i = 0; i < Math.min(chatCount, count); i++) {
		const text = (await chatItems.nth(i).textContent())?.trim() || '';
		// Skip encrypted blobs and processing placeholders
		if (
			text &&
			!text.includes('+') &&
			!text.includes('=') &&
			text !== 'Unnamed chat' &&
			text.toLowerCase() !== 'processing'
		) {
			titles.push(text);
		}
	}
	logStep(`Sidebar has ${titles.length} readable chats (of ${chatCount} total)`);
	return titles;
}

/**
 * Click a chat in the sidebar by its title.
 * Sidebar must already be open.
 */
async function clickChatByTitle(
	page: any,
	title: string,
	logStep: (...args: any[]) => void
): Promise<void> {
	const chatItem = page.locator('[data-testid="chat-item"]').filter({ hasText: title }).first();
	await expect(chatItem).toBeVisible({ timeout: 10000 });
	await chatItem.click();
	logStep(`Clicked chat: "${title}"`);
	// Wait for chat to load (messages appear)
	await page.waitForTimeout(3000);
}

/**
 * Click the "New Chat" button via data-testid.
 */
async function clickNewChat(page: any, logStep: (...args: any[]) => void): Promise<void> {
	const newChatBtn = page.locator('[data-testid="new-chat-button"]');
	await expect(newChatBtn).toBeVisible({ timeout: 5000 });
	await newChatBtn.click();
	logStep('Clicked New Chat button.');
	// Wait for welcome screen to render and resume card to populate
	await page.waitForTimeout(3000);
}

/**
 * Close the sidebar if it's open.
 */
async function closeSidebar(page: any, logStep: (...args: any[]) => void): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	const isOpen = await activityHistory.isVisible().catch(() => false);
	if (!isOpen) return;
	// Try the dedicated Close button first, then the menu toggle (hamburger icon)
	const closeButton = page.getByRole('button', { name: 'Close' });
	if (await closeButton.isVisible({ timeout: 1000 }).catch(() => false)) {
		await closeButton.click();
		logStep('Closed sidebar via Close button.');
	} else {
		const menuToggle = page.locator('[data-testid="sidebar-toggle"]');
		if (await menuToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
			await menuToggle.click();
			logStep('Closed sidebar via menu toggle.');
		}
	}
	await page.waitForTimeout(500);
}

/**
 * Get the resume card title from the welcome screen.
 * Returns null if no resume card is visible.
 */
async function getResumeCardTitle(page: any): Promise<string | null> {
	// Try large card first, then compact card
	const largeTitle = page.getByTestId('resume-large-title').first();
	const compactTitle = page.getByTestId('resume-chat-title').first();

	if (await largeTitle.isVisible({ timeout: 500 }).catch(() => false)) {
		return (await largeTitle.textContent())?.trim() || null;
	}
	if (await compactTitle.isVisible({ timeout: 500 }).catch(() => false)) {
		return (await compactTitle.textContent())?.trim() || null;
	}
	return null;
}

/**
 * Get ALL card titles from the recent-chats-scroll-container (including resume card).
 */
async function getAllRecentCardTitles(page: any): Promise<string[]> {
	const container = page.getByTestId('recent-chats-scroll-container');
	if (!(await container.isVisible({ timeout: 500 }).catch(() => false))) {
		return [];
	}
	const titles = container.locator('[data-testid="resume-large-title"], [data-testid="resume-chat-title"]');
	const count = await titles.count();
	const result: string[] = [];
	for (let i = 0; i < count; i++) {
		const text = (await titles.nth(i).textContent())?.trim() || '';
		if (text) result.push(text);
	}
	return result;
}

// ─── Test ────────────────────────────────────────────────────────────────────

test('resume card updates to last opened chat on each new-chat transition', async ({
	page
}: {
	page: any;
}) => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.setTimeout(300000); // 5 minutes

	const logStep = createSignupLogger('RESUME_CARD');
	const takeStepScreenshot = createStepScreenshotter(logStep, {
		filenamePrefix: 'recent-chats-dedup'
	});
	await archiveExistingScreenshots(logStep);

	// Capture console logs
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
	// PHASE 1: Login and discover chats
	// =========================================================================
	logStep('Phase 1: Login...');
	await performLogin(page, logStep, takeStepScreenshot);
	await takeStepScreenshot(page, '01-logged-in');

	// Get sidebar chat titles — need at least 2 real chats
	const chatTitles = await getSidebarChatTitles(page, logStep, 10);
	logStep(`Available chats: ${JSON.stringify(chatTitles.slice(0, 5))}`);
	expect(chatTitles.length).toBeGreaterThanOrEqual(2);

	const chatA_title = chatTitles[0];
	const chatB_title = chatTitles[1];
	logStep(`Chat A: "${chatA_title}", Chat B: "${chatB_title}"`);

	// =========================================================================
	// PHASE 2: Open chat A → New Chat → verify resume card shows chat A
	// =========================================================================
	logStep('Phase 2: Opening chat A...');
	await clickChatByTitle(page, chatA_title, logStep);
	await takeStepScreenshot(page, '02-chat-a-opened');

	// Close sidebar before clicking New Chat (to see the welcome screen)
	await closeSidebar(page, logStep);

	logStep('Phase 2: Clicking New Chat...');
	await clickNewChat(page, logStep);
	await takeStepScreenshot(page, '02-new-chat-after-a');

	// Wait for resume card to appear (loadResumeChatFromDB retries for up to 10s)
	const resumeContainer = page.getByTestId('recent-chats-scroll-container');
	await expect(resumeContainer).toBeVisible({ timeout: 20000 });

	const resumeTitle1 = await getResumeCardTitle(page);
	logStep(`Resume card after chat A: "${resumeTitle1}"`);

	// ASSERTION 1: Resume card should show chat A's title
	expect(resumeTitle1).toBe(chatA_title);
	logStep('PASS: Resume card correctly shows chat A.');

	// Check for duplicates
	const allTitles1 = await getAllRecentCardTitles(page);
	logStep(`All card titles: ${JSON.stringify(allTitles1)}`);
	const titleSet1 = new Set<string>();
	const dupes1: string[] = [];
	for (const t of allTitles1) {
		if (titleSet1.has(t)) dupes1.push(t);
		titleSet1.add(t);
	}
	expect(dupes1).toEqual([]);
	logStep('PASS: No duplicate cards found.');

	await takeStepScreenshot(page, '02-verified');

	// =========================================================================
	// PHASE 3: Open chat B → New Chat → verify resume card shows chat B
	// =========================================================================
	logStep('Phase 3: Opening chat B...');

	// Open sidebar, click chat B
	const menuToggle = page.locator('[data-testid="sidebar-toggle"]');
	await expect(menuToggle).toBeVisible({ timeout: 5000 });
	await menuToggle.click();
	await page.waitForTimeout(2000);

	await clickChatByTitle(page, chatB_title, logStep);
	await takeStepScreenshot(page, '03-chat-b-opened');

	// Close sidebar
	await closeSidebar(page, logStep);

	logStep('Phase 3: Clicking New Chat...');
	await clickNewChat(page, logStep);
	await takeStepScreenshot(page, '03-new-chat-after-b');

	// Wait for resume card
	await expect(resumeContainer).toBeVisible({ timeout: 20000 });

	const resumeTitle2 = await getResumeCardTitle(page);
	logStep(`Resume card after chat B: "${resumeTitle2}"`);

	// ASSERTION 2: Resume card should now show chat B's title
	expect(resumeTitle2).toBe(chatB_title);
	logStep('PASS: Resume card correctly updated to chat B.');

	// Check for duplicates again
	const allTitles2 = await getAllRecentCardTitles(page);
	logStep(`All card titles: ${JSON.stringify(allTitles2)}`);
	const titleSet2 = new Set<string>();
	const dupes2: string[] = [];
	for (const t of allTitles2) {
		if (titleSet2.has(t)) dupes2.push(t);
		titleSet2.add(t);
	}
	expect(dupes2).toEqual([]);
	logStep('PASS: No duplicate cards after second switch.');

	await takeStepScreenshot(page, '03-verified');

	// =========================================================================
	// PHASE 4: Verify no error logs
	// =========================================================================
	const errors = warnErrorLogs.filter(
		(e) =>
			e.type === 'error' &&
			// Ignore known benign errors
			!e.text.includes('net::ERR_') &&
			!e.text.includes('favicon') &&
			!e.text.includes('ResizeObserver') &&
			!e.text.includes('Decryption failed (likely stale data')
	);

	if (errors.length > 0) {
		logStep(`WARNING: ${errors.length} unexpected error(s) in console:`);
		for (const e of errors) {
			logStep(`  [ERROR] ${e.text.slice(0, 200)}`);
		}
	}
	// Don't fail on console errors — they may be unrelated. Just log them.

	logStep('Test completed successfully.');
	await takeStepScreenshot(page, '04-done');
});
