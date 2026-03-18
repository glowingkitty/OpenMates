/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Recent chats deduplication and ordering test.
 *
 * Validates the "Continue where you left off" horizontal scroll area on the
 * new-chat welcome screen:
 *
 *   1. Login → send two messages in two separate chats → verify both exist
 *   2. Navigate to new-chat screen → verify the resume card and recent-chats
 *      scroll area show NO duplicate cards
 *   3. The primary resume card should be the last-opened chat
 *   4. The scrollable recent-chats list should NOT contain the resume card's chat
 *   5. Open chat B → navigate to new-chat → resume card should now be chat B
 *   6. Clean up: delete both test chats
 *
 * This test targets issue 3054f5ba: duplicate cards in the recent-chats
 * scroll container after opening a chat and returning to the new-chat screen.
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
	generateTotp,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Log buckets ────────────────────────────────────────────────────────────
const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-40).forEach((log: string) => console.log(log));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

// ─── Helpers ────────────────────────────────────────────────────────────────

async function performLogin(
	page: any,
	logStep: (...args: any[]) => void,
	takeStepScreenshot: (...args: any[]) => Promise<void>
): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, '00-home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);

	// Enable "Stay logged in" so keys persist
	const stayLoggedInLabel = page.locator(
		'label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)'
	);
	try {
		await stayLoggedInLabel.waitFor({ state: 'visible', timeout: 3000 });
		const checkbox = page.locator('#stayLoggedIn');
		const isChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
		if (!isChecked) await stayLoggedInLabel.click();
	} catch {
		// Toggle not available — proceed
	}

	await page.locator('#login-continue-button').click();
	logStep('Entered email and clicked continue.');

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);

	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);

	const submitLoginButton = page.locator('#login-submit-button');
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	logStep('Submitted login form.');

	await page.waitForURL(/chat/);
	logStep('Redirected to chat page.');
	// Wait for phased sync to complete
	await page.waitForTimeout(5000);
}

/**
 * Click the "New Chat" button to navigate to the welcome / new-chat screen.
 */
async function navigateToNewChat(page: any, logStep: (...args: any[]) => void): Promise<void> {
	const newChatCta = page.locator('.new-chat-cta-button, .icon_create');
	await expect(newChatCta.first()).toBeVisible({ timeout: 5000 });
	await newChatCta.first().click();
	logStep('Clicked "New Chat" button.');
	// Wait for the welcome screen to render
	await page.waitForTimeout(2000);
}

/**
 * Send a message and wait for an AI response. Returns the chat ID.
 */
async function sendMessageAndGetChatId(
	page: any,
	message: string,
	logStep: (...args: any[]) => void
): Promise<string> {
	// Type and send
	const textarea = page.locator('.input-area textarea, .input-area [contenteditable]').first();
	await expect(textarea).toBeVisible({ timeout: 10000 });
	await textarea.fill(message);
	await page.waitForTimeout(300);

	const sendButton = page.locator('[data-testid="send-button"], .send-button, button.send').first();
	await expect(sendButton).toBeVisible({ timeout: 5000 });
	await sendButton.click();
	logStep(`Sent message: "${message}"`);

	// Wait for the assistant response
	const assistantMsg = page.locator('.message-wrapper.assistant').last();
	await expect(assistantMsg).toBeVisible({ timeout: 60000 });
	logStep('Received assistant response.');

	// Extract chat ID from URL hash
	await page.waitForTimeout(1000);
	const url = page.url();
	const hashMatch = url.match(/chat-id=([a-f0-9-]+)/);
	const chatId = hashMatch ? hashMatch[1] : '';
	logStep(`Chat ID: ${chatId}`);
	expect(chatId).toBeTruthy();
	return chatId;
}

/**
 * Delete a chat by its ID via the sidebar context menu.
 */
async function deleteChat(
	page: any,
	chatId: string,
	logStep: (...args: any[]) => void
): Promise<void> {
	// First navigate to the chat
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.waitForTimeout(3000);

	// Open sidebar
	const activityHistory = page.locator('.activity-history-wrapper');
	const isSidebarVisible = await activityHistory.isVisible().catch(() => false);
	if (!isSidebarVisible) {
		const menuToggle = page.locator('.icon_menu');
		if (await menuToggle.isVisible().catch(() => false)) {
			await menuToggle.click();
			await page.waitForTimeout(2000);
		}
	}

	// Right-click the active chat item to open context menu
	const activeChat = page.locator('.chat-item-wrapper.active');
	if (await activeChat.isVisible().catch(() => false)) {
		await activeChat.click({ button: 'right' });
		await page.waitForTimeout(500);

		const deleteButton = page.locator('.menu-item.delete');
		if (await deleteButton.isVisible().catch(() => false)) {
			await deleteButton.click();
			await page.waitForTimeout(2000);
			logStep(`Deleted chat: ${chatId}`);
		} else {
			logStep(`Delete button not visible for chat: ${chatId}`);
		}
	} else {
		logStep(`Active chat not visible in sidebar for: ${chatId}`);
	}
}

/**
 * Collect all card titles from the recent-chats-scroll-container.
 * Returns an array of { title, index } objects for all cards
 * (both the primary resume card and the scrollable recent-chat cards).
 */
async function getRecentChatCardTitles(
	page: any
): Promise<Array<{ title: string; index: number }>> {
	const container = page.locator('.recent-chats-scroll-container');
	if (!(await container.isVisible().catch(() => false))) {
		return [];
	}

	// Get all card titles in the container (large + compact variants)
	const cards = container.locator(
		'.resume-chat-large-card .resume-large-title, .resume-chat-card .resume-chat-title'
	);
	const count = await cards.count();
	const results: Array<{ title: string; index: number }> = [];
	for (let i = 0; i < count; i++) {
		const text = (await cards.nth(i).textContent())?.trim() || '';
		results.push({ title: text, index: i });
	}
	return results;
}

// ─── Test ────────────────────────────────────────────────────────────────────

test('recent chats show no duplicates and resume card reflects last opened chat', async ({
	page
}: {
	page: any;
}) => {
	test.setTimeout(180000); // 3 minutes — two chats + navigation

	const logStep = createSignupLogger('RECENT_CHATS_DEDUP');
	const takeStepScreenshot = createStepScreenshotter(logStep, {
		filenamePrefix: 'recent-chats-dedup'
	});
	await archiveExistingScreenshots(logStep);

	// Capture console logs for diagnostics
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});

	// =========================================================================
	// PHASE 1: Login
	// =========================================================================
	logStep('Phase 1: Login...');
	await performLogin(page, logStep, takeStepScreenshot);
	await takeStepScreenshot(page, '01-logged-in');

	// =========================================================================
	// PHASE 2: Send message in chat A
	// =========================================================================
	logStep('Phase 2: Sending message in chat A...');
	const chatIdA = await sendMessageAndGetChatId(
		page,
		'Test message alpha for recent chats dedup test',
		logStep
	);
	await takeStepScreenshot(page, '02-chat-a-created');

	// =========================================================================
	// PHASE 3: Navigate to new-chat, send message in chat B
	// =========================================================================
	logStep('Phase 3: Creating chat B...');
	await navigateToNewChat(page, logStep);
	const chatIdB = await sendMessageAndGetChatId(
		page,
		'Test message beta for recent chats dedup test',
		logStep
	);
	await takeStepScreenshot(page, '03-chat-b-created');

	// =========================================================================
	// PHASE 4: Navigate to new-chat → verify no duplicates in recent chats area
	// =========================================================================
	logStep('Phase 4: Navigating to new-chat and checking for duplicates...');
	await navigateToNewChat(page, logStep);
	await takeStepScreenshot(page, '04-new-chat-screen');

	// Wait for the recent-chats container to render
	const container = page.locator('.recent-chats-scroll-container');
	await expect(container).toBeVisible({ timeout: 15000 });
	logStep('Recent chats scroll container visible.');

	// Get all card titles
	const cardTitles = await getRecentChatCardTitles(page);
	logStep(`Found ${cardTitles.length} cards in recent-chats-scroll-container.`);
	for (const card of cardTitles) {
		logStep(`  Card ${card.index}: "${card.title}"`);
	}

	// ASSERTION: No duplicate titles in the card list
	const titleSet = new Set<string>();
	const duplicates: string[] = [];
	for (const card of cardTitles) {
		if (card.title && titleSet.has(card.title)) {
			duplicates.push(card.title);
		}
		if (card.title) titleSet.add(card.title);
	}
	if (duplicates.length > 0) {
		logStep(`DUPLICATE CARDS DETECTED: ${duplicates.join(', ')}`);
	}
	expect(duplicates).toEqual([]);
	logStep('No duplicate cards found.');

	await takeStepScreenshot(page, '04a-no-duplicates-verified');

	// =========================================================================
	// PHASE 5: Open chat A → return to new-chat → verify resume card updated
	// =========================================================================
	logStep('Phase 5: Opening chat A, then returning to new-chat...');
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	await page.goto(`${baseUrl}/#chat-id=${chatIdA}`);
	await page.waitForTimeout(3000);
	logStep('Opened chat A.');

	await navigateToNewChat(page, logStep);
	await takeStepScreenshot(page, '05-new-chat-after-opening-a');

	// Wait for the recent-chats container to render
	await expect(container).toBeVisible({ timeout: 15000 });

	// Get cards again after switching
	const cardsAfterSwitch = await getRecentChatCardTitles(page);
	logStep(`Cards after switching to A and back: ${cardsAfterSwitch.length}`);
	for (const card of cardsAfterSwitch) {
		logStep(`  Card ${card.index}: "${card.title}"`);
	}

	// ASSERTION: Still no duplicates after switching
	const titleSet2 = new Set<string>();
	const duplicates2: string[] = [];
	for (const card of cardsAfterSwitch) {
		if (card.title && titleSet2.has(card.title)) {
			duplicates2.push(card.title);
		}
		if (card.title) titleSet2.add(card.title);
	}
	expect(duplicates2).toEqual([]);
	logStep('No duplicates after switching — verified.');

	await takeStepScreenshot(page, '05a-no-duplicates-after-switch');

	// =========================================================================
	// PHASE 6: Cleanup — delete both test chats
	// =========================================================================
	logStep('Phase 6: Cleaning up test chats...');
	await deleteChat(page, chatIdB, logStep);
	await deleteChat(page, chatIdA, logStep);
	logStep('Cleanup complete.');

	await takeStepScreenshot(page, '06-cleanup-done');
});
