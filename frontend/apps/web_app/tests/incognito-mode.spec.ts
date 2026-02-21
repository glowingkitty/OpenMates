/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');

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
		consoleLogs.slice(-30).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

/**
 * Incognito mode E2E tests.
 *
 * Covers:
 * 1. Enable via settings toggle → info screen → activate → incognito banner visible
 * 2. New chat in incognito mode → incognito label shows in sidebar + banner in chat area
 * 3. Send a message → chat_id in URL is ephemeral (contains 'incognito' or a UUID, never a Directus ID)
 * 4. Disable incognito → all incognito chats are removed from the sidebar immediately
 * 5. Active incognito chat is closed (cleared) when incognito mode is disabled
 * 6. Tab refresh → incognito chats are still visible (sessionStorage persists within tab session)
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

const SELECTORS = {
	// Login / auth
	loginButton: 'button:text-matches("login.*sign up|sign up", "i")',
	emailInput: 'input[name="username"][type="email"]',
	continueButton: 'button:text-matches("continue", "i")',
	passwordInput: 'input[type="password"]',
	otpInput: 'input[autocomplete="one-time-code"]',
	submitLoginButton: 'button[type="submit"]:text-matches("log in|login", "i")',

	// Chat UI
	messageEditor: '.editor-content.prose',
	sendButton: '.send-button',
	newChatButton: '.new-chat-cta-button',
	sidebarToggle: '.sidebar-toggle-button',
	activityHistoryWrapper: '.activity-history-wrapper',
	menuButton: '.menu-button-container button.icon_menu',

	// Settings
	profileButton: '.profile-picture',
	settingsMenuVisible: '.settings-menu.visible',
	closeSettingsButton: '.icon-button .icon_close',

	// Incognito toggle in settings (re-enabled; wrapped in data-testid)
	incognitoToggleWrapper: '[data-testid="incognito-toggle-wrapper"]',
	// The Activate button on the incognito info sub-page
	incognitoActivateButton: '[data-testid="incognito-activate-button"]',

	// Incognito visual indicators
	/** Banner at the top of the chat area when incognito mode is active */
	incognitoBanner: '.incognito-banner',
	/** "Applies to new chats only" warning shown on a regular chat when incognito mode is on */
	incognitoAppliesBanner: '.incognito-mode-applies-banner',
	/** Badge on a chat list item in the sidebar */
	incognitoLabel: '.incognito-label',

	// Chat list — note: the sidebar uses .chat-item (not .chat-item-wrapper)
	activeChatItem: '.chat-item.active',
	chatItems: '.chat-item',
	chatTitle: '.chat-title'
};

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/**
 * Login with email + password + TOTP. Includes retry logic for OTP timing.
 */
async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator(SELECTORS.emailInput);
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator(SELECTORS.passwordInput);
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator(SELECTORS.otpInput);
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator(SELECTORS.submitLoginButton);
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		logCheckpoint(`Entered OTP code (attempt ${attempt}).`);

		await expect(submitLoginButton).toBeVisible();
		await submitLoginButton.click();
		logCheckpoint('Submitted login form.');

		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
			logCheckpoint('Login successful.');
		} catch {
			const hasError = await errorMessage.isVisible().catch(() => false);
			if (hasError && attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying...`);
				await page.waitForTimeout(2000);
			} else if (attempt === 3) {
				throw new Error('Login failed after 3 OTP attempts');
			}
		}
	}

	logCheckpoint('Waiting for chat interface to load...');
	await page.waitForTimeout(3000);

	const messageEditor = page.locator(SELECTORS.messageEditor);
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded.');
	await takeStepScreenshot(page, 'logged-in');
}

/**
 * Open the sidebar if it's not already visible.
 */
async function ensureSidebarOpen(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const sidebar = page.locator(SELECTORS.activityHistoryWrapper);
	if (await sidebar.isVisible({ timeout: 1000 }).catch(() => false)) {
		logCheckpoint('Sidebar already open.');
		return;
	}
	const menuButton = page.locator(SELECTORS.menuButton);
	if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
		await menuButton.click();
		logCheckpoint('Opened sidebar via hamburger menu.');
		await page.waitForTimeout(500);
	}
}

/**
 * Open the settings panel via the profile picture button.
 */
async function openSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	const settingsButton = page.locator(SELECTORS.profileButton).first();
	await expect(settingsButton).toBeVisible({ timeout: 10000 });
	await settingsButton.click();
	logCheckpoint('Clicked profile/settings button.');

	const settingsMenu = page.locator(SELECTORS.settingsMenuVisible);
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logCheckpoint('Settings menu visible.');
	await takeStepScreenshot(page, 'settings-open');
}

/**
 * Enable incognito mode via the settings toggle → info sub-page → Activate button.
 *
 * Flow:
 *   1. Open settings
 *   2. Click the incognito toggle (navigates to info sub-page)
 *   3. Click "Activate" on the info page
 *   4. Settings closes and a new incognito chat is auto-created
 */
async function enableIncognitoViaSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await openSettings(page, logCheckpoint, takeStepScreenshot);

	// Find the incognito toggle wrapper
	const toggleWrapper = page.locator(SELECTORS.incognitoToggleWrapper);
	await expect(toggleWrapper).toBeVisible({ timeout: 10000 });
	logCheckpoint('Incognito toggle found in settings.');

	// Clicking the toggle navigates to the info sub-page (mode is currently OFF)
	await toggleWrapper.click();
	logCheckpoint('Clicked incognito toggle — expecting info sub-page.');
	await takeStepScreenshot(page, 'incognito-info-page');

	// Confirm activation
	const activateButton = page.locator(SELECTORS.incognitoActivateButton);
	await expect(activateButton).toBeVisible({ timeout: 10000 });
	await activateButton.click();
	logCheckpoint('Clicked Activate button on incognito info page.');

	// Settings should close after activation (the info page handler closes the menu)
	await page.waitForTimeout(700);
	logCheckpoint('Incognito mode enabled.');
	await takeStepScreenshot(page, 'incognito-enabled');
}

/**
 * Disable incognito mode via the settings toggle (turns off directly, no info page).
 *
 * Handles the case where the settings menu might already be open (e.g., right after
 * enabling incognito mode, the activation flow closes the menu but with a delay).
 */
async function disableIncognitoViaSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	// Check if settings menu is already visible (e.g., still open from a previous action)
	const settingsMenu = page.locator(SELECTORS.settingsMenuVisible);
	const settingsAlreadyOpen = await settingsMenu.isVisible({ timeout: 1000 }).catch(() => false);

	if (settingsAlreadyOpen) {
		logCheckpoint('Settings menu already open — closing first before re-opening.');
		// Close by pressing Escape, then re-open cleanly
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);
	}

	await openSettings(page, logCheckpoint, takeStepScreenshot);

	// When incognito mode is ON, clicking the toggle turns it off directly
	const toggleWrapper = page.locator(SELECTORS.incognitoToggleWrapper);
	await expect(toggleWrapper).toBeVisible({ timeout: 10000 });
	await toggleWrapper.click();
	logCheckpoint('Clicked incognito toggle to disable incognito mode.');

	// Wait for store to process deletion
	await page.waitForTimeout(700);

	// Close settings
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);
	logCheckpoint('Incognito mode disabled.');
	await takeStepScreenshot(page, 'incognito-disabled');
}

/**
 * Start a new chat by clicking the new chat CTA button (if visible).
 */
async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	await page.waitForTimeout(1000);
	const newChatButton = page.locator(SELECTORS.newChatButton);
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		logCheckpoint('Clicked new chat button.');
		await page.waitForTimeout(1500);
	} else {
		logCheckpoint('New chat button not visible — may already be on a fresh chat.');
	}
}

/**
 * Send a message in the current chat.
 */
async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	const messageEditor = page.locator(SELECTORS.messageEditor);
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await messageEditor.click();
	await page.keyboard.type(message);
	logCheckpoint(`Typed message: "${message}"`);
	await takeStepScreenshot(page, `${stepLabel}-message-typed`);

	const sendButton = page.locator(SELECTORS.sendButton);
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send button.');
	await takeStepScreenshot(page, `${stepLabel}-message-sent`);
}

// ---------------------------------------------------------------------------
// Test 1: Enable incognito → banner visible + chat gets incognito label
// ---------------------------------------------------------------------------

test('enables incognito mode and shows incognito banner', async ({ page }: { page: any }) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(
			`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`
		);
	});

	test.slow();
	test.setTimeout(120000);

	const logCheckpoint = createSignupLogger('INCOGNITO_BANNER');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting incognito banner test.', { email: TEST_EMAIL });

	// --- Arrange ---
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// --- Act ---
	await enableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);

	// --- Assert: incognito banner is visible on the chat area ---
	// After activation, a new incognito chat is auto-created via 'triggerNewChat' event
	const incognitoBanner = page.locator(SELECTORS.incognitoBanner);
	await expect(incognitoBanner).toBeVisible({ timeout: 10000 });
	logCheckpoint('Incognito banner is visible in the chat area.');
	await takeStepScreenshot(page, 'incognito-banner-visible');

	// --- Assert: sessionStorage reflects the incognito state ---
	const incognitoEnabled = await page.evaluate(() =>
		sessionStorage.getItem('incognito_mode_enabled')
	);
	expect(incognitoEnabled).toBe('true');
	logCheckpoint('sessionStorage confirms incognito mode is enabled.');

	// Verify no missing translations
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');
});

// ---------------------------------------------------------------------------
// Test 2: Send a message in incognito mode → incognito label in sidebar
// ---------------------------------------------------------------------------

test('creates incognito chat with incognito label in sidebar', async ({ page }: { page: any }) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(
			`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`
		);
	});

	test.slow();
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('INCOGNITO_SIDEBAR_LABEL');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting incognito sidebar label test.');

	// --- Arrange ---
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await enableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);
	await ensureSidebarOpen(page, logCheckpoint);

	// --- Act: send a message in the auto-created incognito chat ---
	await sendMessage(page, 'Hello from incognito', logCheckpoint, takeStepScreenshot, 'incognito');
	logCheckpoint('Sent message in incognito chat.');

	// --- Assert: incognito label visible in sidebar ---
	// After sending a message in incognito mode, the chat should appear in the sidebar
	// with an incognito label. Wait a bit for the UI to settle after the send.
	await page.waitForTimeout(3000);
	await ensureSidebarOpen(page, logCheckpoint);
	await takeStepScreenshot(page, 'sidebar-after-send');

	// Look for incognito label in the sidebar (any chat item, not necessarily .active)
	const incognitoLabel = page.locator(SELECTORS.incognitoLabel);
	await expect(incognitoLabel.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Incognito label visible on a chat item in the sidebar.');
	await takeStepScreenshot(page, 'incognito-label-in-sidebar');
});

// ---------------------------------------------------------------------------
// Test 3: Send message in incognito → chat_id is ephemeral (not a Directus ID)
// ---------------------------------------------------------------------------

test('incognito chat uses ephemeral chat_id, not a persisted server ID', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(
			`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`
		);
	});

	test.slow();
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('INCOGNITO_CHAT_ID');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting incognito chat_id test.');

	// --- Arrange ---
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await enableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);

	// --- Act: send a message ---
	await sendMessage(page, 'What is 2+2?', logCheckpoint, takeStepScreenshot, 'incognito-chat-id');

	// Wait for URL to include chat-id param (set by the frontend after send)
	await expect(page).toHaveURL(/chat-id=/, { timeout: 15000 });
	const url = page.url();
	const chatIdMatch = url.match(/chat-id=([^&]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : null;
	logCheckpoint(`Chat ID in URL: ${chatId}`);

	// --- Assert: the chat_id is in sessionStorage (incognito service), not IndexedDB ---
	// Incognito chat IDs are generated client-side via crypto.randomUUID() (standard UUID format).
	// The key difference from a regular chat is NOT the ID format — it is that the chat
	// is stored in sessionStorage (incognito_chats key) and NOT in IndexedDB.
	// We verify this by checking that sessionStorage has the chat.
	expect(chatId).not.toBeNull();
	// UUID format: 8-4-4-4-12 hex characters
	expect(chatId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
	logCheckpoint('Chat ID is a valid UUID (client-generated, not a server Directus ID).');
	await takeStepScreenshot(page, 'incognito-chat-id-verified');

	// --- Assert: sessionStorage stores the incognito chat metadata ---
	const storedChats = await page.evaluate(() => sessionStorage.getItem('incognito_chats'));
	expect(storedChats).not.toBeNull();
	const parsedChats = JSON.parse(storedChats as string);
	expect(parsedChats.length).toBeGreaterThan(0);
	expect(parsedChats[0].is_incognito).toBe(true);
	logCheckpoint('sessionStorage contains incognito chat metadata.');
});

// ---------------------------------------------------------------------------
// Test 4: Disable incognito → all incognito chats removed from sidebar
// ---------------------------------------------------------------------------

test('disabling incognito mode removes all incognito chats from sidebar', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	test.slow();
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('INCOGNITO_CLEANUP');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting incognito cleanup test.');

	// --- Arrange: enable incognito and send a message to create an incognito chat ---
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await enableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);
	await sendMessage(
		page,
		'Testing incognito cleanup',
		logCheckpoint,
		takeStepScreenshot,
		'pre-disable'
	);

	// Ensure sidebar shows the incognito chat before disabling.
	// Wait for the UI to settle after sending and for the chat to appear in the sidebar.
	await page.waitForTimeout(3000);
	await ensureSidebarOpen(page, logCheckpoint);
	const incognitoLabels = page.locator(SELECTORS.incognitoLabel);
	await expect(incognitoLabels.first()).toBeVisible({ timeout: 15000 });
	const countBefore = await incognitoLabels.count();
	logCheckpoint(`Incognito chats visible in sidebar before disable: ${countBefore}`);
	expect(countBefore).toBeGreaterThan(0);
	await takeStepScreenshot(page, 'incognito-chats-before-disable');

	// --- Act: disable incognito mode ---
	await disableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);

	// --- Assert: incognito labels are gone from the sidebar ---
	await ensureSidebarOpen(page, logCheckpoint);
	// Wait briefly for the UI to settle after deletion
	await page.waitForTimeout(1000);
	const countAfter = await incognitoLabels.count();
	logCheckpoint(`Incognito chats visible in sidebar after disable: ${countAfter}`);
	expect(countAfter).toBe(0);
	await takeStepScreenshot(page, 'incognito-chats-cleared');

	// --- Assert: sessionStorage is cleaned up ---
	const storedChats = await page.evaluate(() => sessionStorage.getItem('incognito_chats'));
	expect(storedChats).toBeNull();
	logCheckpoint('sessionStorage incognito_chats key is cleared after disabling.');
});

// ---------------------------------------------------------------------------
// Test 5: Active incognito chat is closed when incognito mode is disabled
// ---------------------------------------------------------------------------

test('active incognito chat is closed when incognito mode is disabled', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	test.slow();
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('INCOGNITO_CLOSE_ACTIVE');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting incognito active-chat-close test.');

	// --- Arrange ---
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await enableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);

	// Verify we are in the incognito chat (banner visible)
	const incognitoBanner = page.locator(SELECTORS.incognitoBanner);
	await expect(incognitoBanner).toBeVisible({ timeout: 10000 });
	logCheckpoint('Incognito banner visible — active incognito chat confirmed.');

	// Get the current URL (contains the incognito chat-id)
	const urlBefore = page.url();
	logCheckpoint(`URL before disable: ${urlBefore}`);

	// --- Act ---
	await disableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);

	// --- Assert: incognito banner is gone (chat was closed/deselected) ---
	await expect(incognitoBanner).not.toBeVisible({ timeout: 10000 });
	logCheckpoint('Incognito banner no longer visible after disabling mode.');
	await takeStepScreenshot(page, 'incognito-banner-gone');

	// The URL should no longer contain an incognito chat-id
	const urlAfter = page.url();
	logCheckpoint(`URL after disable: ${urlAfter}`);
	// The chat was an incognito chat so its ID starts with 'incognito-'
	// After disabling, the router should deselect or navigate away from it.
	if (urlBefore.includes('incognito-')) {
		expect(urlAfter).not.toMatch(/chat-id=incognito-/);
		logCheckpoint('URL no longer references an incognito chat ID.');
	}
});

// ---------------------------------------------------------------------------
// Test 6: Tab refresh — sessionStorage persists incognito chats within session
// ---------------------------------------------------------------------------

test('incognito chats persist across page refresh within the same tab session', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	test.slow();
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('INCOGNITO_REFRESH');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting incognito refresh-persistence test.');

	// --- Arrange: enable incognito and create a chat ---
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await enableIncognitoViaSettings(page, logCheckpoint, takeStepScreenshot);

	// Send a message to create a named incognito chat (needed for identification after refresh)
	const uniqueMessage = `Incognito refresh test ${Date.now()}`;
	await sendMessage(page, uniqueMessage, logCheckpoint, takeStepScreenshot, 'pre-refresh');

	// Wait for AI response (brief) — not strictly needed but ensures chat is properly stored
	await page.waitForTimeout(3000);

	// Store the current chat_id from URL for post-refresh comparison
	const urlBeforeRefresh = page.url();
	logCheckpoint(`URL before refresh: ${urlBeforeRefresh}`);

	// Verify the incognito chat is in sessionStorage before refresh
	const storedBefore = await page.evaluate(() => sessionStorage.getItem('incognito_chats'));
	expect(storedBefore).not.toBeNull();
	const chatCountBefore = JSON.parse(storedBefore as string).length;
	logCheckpoint(`Incognito chats in sessionStorage before refresh: ${chatCountBefore}`);
	expect(chatCountBefore).toBeGreaterThan(0);

	// --- Act: reload the page (same tab = same sessionStorage) ---
	await page.reload();
	logCheckpoint('Page reloaded.');
	await page.waitForTimeout(4000); // Let app reinitialize

	// Re-login if session was lost (reload may require re-auth if auth is session-based)
	const loginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	if (await loginButton.isVisible({ timeout: 5000 }).catch(() => false)) {
		logCheckpoint('Session lost after reload — re-logging in.');
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	} else {
		const messageEditor = page.locator(SELECTORS.messageEditor);
		await expect(messageEditor).toBeVisible({ timeout: 20000 });
		logCheckpoint('Still logged in after reload.');
	}

	// --- Assert: sessionStorage still has incognito chats ---
	const storedAfter = await page.evaluate(() => sessionStorage.getItem('incognito_chats'));
	// sessionStorage is tab-specific and survives a reload (cleared only on tab close)
	expect(storedAfter).not.toBeNull();
	const chatCountAfter = JSON.parse(storedAfter as string).length;
	logCheckpoint(`Incognito chats in sessionStorage after refresh: ${chatCountAfter}`);
	expect(chatCountAfter).toBe(chatCountBefore);

	// --- Assert: incognito mode is still ON (sessionStorage key persists) ---
	const incognitoEnabled = await page.evaluate(() =>
		sessionStorage.getItem('incognito_mode_enabled')
	);
	expect(incognitoEnabled).toBe('true');
	logCheckpoint('Incognito mode is still enabled after page refresh.');

	// --- Assert: sidebar shows incognito chat (UI hydrated from sessionStorage) ---
	await ensureSidebarOpen(page, logCheckpoint);
	const incognitoLabels = page.locator(SELECTORS.incognitoLabel);
	await expect(incognitoLabels.first()).toBeVisible({ timeout: 15000 });
	const labelCount = await incognitoLabels.count();
	logCheckpoint(`Incognito labels visible in sidebar after refresh: ${labelCount}`);
	expect(labelCount).toBe(chatCountAfter);
	await takeStepScreenshot(page, 'incognito-chats-after-refresh');
});
