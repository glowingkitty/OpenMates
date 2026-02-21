/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

/**
 * Incognito mode E2E test — single test, one login, all scenarios in sequence.
 *
 * Scenarios covered (in order):
 * 1. Enable via settings toggle → info screen → activate → settings closes → incognito banner visible
 * 2. Send a message → incognito label in sidebar + chat_id is a UUID (not a server ID)
 * 3. Refresh page → sessionStorage persists (incognito chats + mode still active)
 * 4. Disable incognito → all incognito chats removed from sidebar immediately
 * 5. Active incognito chat banner disappears after disable
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

const SELECTORS = {
	// Login / auth
	emailInput: 'input[name="username"][type="email"]',
	passwordInput: 'input[type="password"]',
	otpInput: 'input[autocomplete="one-time-code"]',
	submitLoginButton: 'button[type="submit"]:text-matches("log in|login", "i")',

	// Chat UI
	messageEditor: '.editor-content.prose',
	sendButton: '.send-button',
	menuButton: '.menu-button-container button.icon_menu',
	activityHistoryWrapper: '.activity-history-wrapper',

	// Settings
	profileButton: '.profile-picture',
	settingsMenuVisible: '.settings-menu.visible',

	// Incognito controls
	incognitoToggleWrapper: '[data-testid="incognito-toggle-wrapper"]',
	incognitoActivateButton: '[data-testid="incognito-activate-button"]',

	// Incognito visual indicators
	incognitoBanner: '.incognito-banner',
	// The incognito group header is an h2.group-title rendered inside the INCOGNITO chat group.
	// It replaces the old per-chat .incognito-label badge (removed in favour of a single group header).
	incognitoGroupHeader: 'h2.group-title',

	// Chat list
	chatItems: '.chat-item'
};

// ---------------------------------------------------------------------------
// The test
// ---------------------------------------------------------------------------

test('incognito mode — full flow', async ({ page }: { page: any }) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (req: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`);
	});
	page.on('response', (res: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`);
	});

	test.slow();
	test.setTimeout(300000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const logCheckpoint = createSignupLogger('INCOGNITO');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting incognito mode full-flow test.', { email: TEST_EMAIL });

	// -------------------------------------------------------------------------
	// Login (once)
	// -------------------------------------------------------------------------

	await page.goto('/');
	await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {
		logCheckpoint('WARNING: networkidle timeout — continuing anyway.');
	});
	await takeStepScreenshot(page, '01-home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();

	// Wait a moment for the login dialog to mount and render
	await page.waitForTimeout(2000);
	await takeStepScreenshot(page, '02-login-dialog');

	// Diagnostic: dump DOM state to understand what rendered
	const loginWrapperCount = await page.locator('.login-wrapper').count();
	const emailInputCount = await page.locator(SELECTORS.emailInput).count();
	const activeChatLoginMode = await page.locator('.active-chat-container.login-mode').count();
	// Check the actual store value from inside the page context
	const storeValues = await page.evaluate(() => {
		// Try to access the Svelte store via window (if exported)
		const w = window as any;
		return {
			loginInterfaceOpen: w.__loginInterfaceOpen ?? 'not exposed',
			hasActiveChatContainer: !!document.querySelector('.active-chat-container'),
			bodyChildren: document.body.children.length,
			htmlSnippet:
				document.querySelector('.active-chat-container')?.innerHTML?.slice(0, 500) ?? 'not found'
		};
	});
	logCheckpoint('DOM diagnostic after login button click.', {
		loginWrapperCount,
		emailInputCount,
		activeChatLoginMode,
		storeValues,
		url: page.url()
	});

	const emailInput = page.locator(SELECTORS.emailInput);
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator(SELECTORS.passwordInput);
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator(SELECTORS.otpInput);
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator(SELECTORS.submitLoginButton);
	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		logCheckpoint(`OTP attempt ${attempt}.`);
		await submitLoginButton.click();
		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
		} catch {
			if (attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying...`);
				await page.waitForTimeout(2000);
			} else {
				throw new Error('Login failed after 3 OTP attempts');
			}
		}
	}

	await page.waitForTimeout(3000);
	const messageEditor = page.locator(SELECTORS.messageEditor);
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Logged in. Chat interface loaded.');
	await takeStepScreenshot(page, '03-logged-in');

	// -------------------------------------------------------------------------
	// Ensure sidebar is open
	// -------------------------------------------------------------------------

	const sidebar = page.locator(SELECTORS.activityHistoryWrapper);
	if (!(await sidebar.isVisible({ timeout: 2000 }).catch(() => false))) {
		const menuButton = page.locator(SELECTORS.menuButton);
		if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
			await menuButton.click();
			await page.waitForTimeout(500);
		}
	}
	logCheckpoint('Sidebar open.');

	// -------------------------------------------------------------------------
	// Scenario 1: Enable incognito via settings
	// -------------------------------------------------------------------------

	logCheckpoint('--- Scenario 1: Enable incognito ---');

	// Open settings
	const profileButton = page.locator(SELECTORS.profileButton).first();
	await expect(profileButton).toBeVisible({ timeout: 10000 });
	await profileButton.click();
	const settingsMenu = page.locator(SELECTORS.settingsMenuVisible);
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logCheckpoint('Settings open.');
	await takeStepScreenshot(page, '04-settings-open');

	// Click the incognito toggle — navigates to the info sub-page
	const toggleWrapper = page.locator(SELECTORS.incognitoToggleWrapper);
	await expect(toggleWrapper).toBeVisible({ timeout: 10000 });
	await toggleWrapper.click();
	logCheckpoint('Clicked incognito toggle → expecting info sub-page.');
	await takeStepScreenshot(page, '05-incognito-info-page');

	// Confirm activation
	const activateButton = page.locator(SELECTORS.incognitoActivateButton);
	await expect(activateButton).toBeVisible({ timeout: 10000 });
	await activateButton.click();
	logCheckpoint('Clicked Activate.');

	// Settings should close (the closeSettingsMenu window event is dispatched)
	await expect(settingsMenu).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Settings menu closed after activation.');

	// Wait for triggerNewChat to fire and the incognito welcome state to settle
	await page.waitForTimeout(1000);
	await takeStepScreenshot(page, '06-incognito-enabled');

	// Assert: incognito banner visible (showWelcome=true && $incognitoMode=true)
	const incognitoBanner = page.locator(SELECTORS.incognitoBanner);
	await expect(incognitoBanner).toBeVisible({ timeout: 10000 });
	logCheckpoint('✓ Incognito banner visible.');

	// Assert: sessionStorage reflects the incognito state
	const incognitoEnabled = await page.evaluate(() =>
		sessionStorage.getItem('incognito_mode_enabled')
	);
	expect(incognitoEnabled).toBe('true');
	logCheckpoint('✓ sessionStorage incognito_mode_enabled = true.');

	await assertNoMissingTranslations(page);
	logCheckpoint('✓ No missing translations.');

	// -------------------------------------------------------------------------
	// Scenario 2: Send a message → sidebar label + ephemeral chat_id
	// -------------------------------------------------------------------------

	logCheckpoint('--- Scenario 2: Send message, check sidebar label + chat_id ---');

	// Type and send a message
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await messageEditor.click();
	await page.keyboard.type('Hello from incognito');
	await takeStepScreenshot(page, '07-message-typed');

	const sendButton = page.locator(SELECTORS.sendButton);
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Message sent.');
	await takeStepScreenshot(page, '08-message-sent');

	// Wait for URL to update with chat-id param
	await expect(page).toHaveURL(/chat-id=/, { timeout: 15000 });
	const url = page.url();
	const chatIdMatch = url.match(/chat-id=([^&]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : null;
	logCheckpoint(`Chat ID in URL: ${chatId}`);

	// Assert: chat_id is a UUID (ephemeral, client-generated)
	expect(chatId).not.toBeNull();
	expect(chatId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
	logCheckpoint('✓ Chat ID is a valid UUID (not a server ID).');

	// Wait for sidebar to update with the new chat
	await page.waitForTimeout(3000);

	// Ensure sidebar still open
	if (!(await sidebar.isVisible({ timeout: 1000 }).catch(() => false))) {
		const menuButton = page.locator(SELECTORS.menuButton);
		if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
			await menuButton.click();
			await page.waitForTimeout(500);
		}
	}

	await takeStepScreenshot(page, '09-sidebar-after-send');

	// Assert: INCOGNITO group header visible in the sidebar (replaced per-chat badges)
	const incognitoGroupHeader = page
		.locator(SELECTORS.incognitoGroupHeader)
		.filter({ hasText: /incognito/i });
	await expect(incognitoGroupHeader.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('✓ Incognito group header visible in sidebar.');

	// Assert: sessionStorage has the incognito chat
	const storedChats = await page.evaluate(() => sessionStorage.getItem('incognito_chats'));
	expect(storedChats).not.toBeNull();
	const parsedChats = JSON.parse(storedChats as string);
	expect(parsedChats.length).toBeGreaterThan(0);
	expect(parsedChats[0].is_incognito).toBe(true);
	logCheckpoint('✓ sessionStorage contains incognito chat metadata.');
	await takeStepScreenshot(page, '10-incognito-label-in-sidebar');

	// -------------------------------------------------------------------------
	// Scenario 3: Page refresh → sessionStorage persists
	// -------------------------------------------------------------------------

	logCheckpoint('--- Scenario 3: Page refresh, sessionStorage persists ---');

	const chatCountBefore = parsedChats.length;
	const urlBeforeRefresh = page.url();
	logCheckpoint(`URL before refresh: ${urlBeforeRefresh}, chat count: ${chatCountBefore}`);

	await page.reload();
	logCheckpoint('Page reloaded.');
	await page.waitForTimeout(4000);

	// Re-login if session was lost
	const loginButtonAfterReload = page.getByRole('button', { name: /login.*sign up|sign up/i });
	if (await loginButtonAfterReload.isVisible({ timeout: 5000 }).catch(() => false)) {
		logCheckpoint('Session lost — re-logging in.');
		await loginButtonAfterReload.click();
		const emailInput2 = page.locator(SELECTORS.emailInput);
		await expect(emailInput2).toBeVisible();
		await emailInput2.fill(TEST_EMAIL);
		await page.getByRole('button', { name: /continue/i }).click();
		const passwordInput2 = page.locator(SELECTORS.passwordInput);
		await expect(passwordInput2).toBeVisible({ timeout: 15000 });
		await passwordInput2.fill(TEST_PASSWORD);
		const otpInput2 = page.locator(SELECTORS.otpInput);
		await expect(otpInput2).toBeVisible({ timeout: 15000 });
		for (let attempt = 1; attempt <= 3; attempt++) {
			const otpCode = generateTotp(TEST_OTP_KEY);
			await otpInput2.fill(otpCode);
			await page.locator(SELECTORS.submitLoginButton).click();
			try {
				await expect(otpInput2).not.toBeVisible({ timeout: 15000 });
				logCheckpoint('Re-login successful.');
				break;
			} catch {
				if (attempt === 3) throw new Error('Re-login failed after 3 attempts');
				await page.waitForTimeout(2000);
			}
		}
		await page.waitForTimeout(3000);
	}

	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded after reload.');

	// Assert: incognito chats still in sessionStorage
	const storedAfter = await page.evaluate(() => sessionStorage.getItem('incognito_chats'));
	expect(storedAfter).not.toBeNull();
	const chatCountAfter = JSON.parse(storedAfter as string).length;
	expect(chatCountAfter).toBe(chatCountBefore);
	logCheckpoint(`✓ sessionStorage preserved ${chatCountAfter} incognito chat(s) across reload.`);

	// Assert: incognito mode still enabled
	const modeAfterReload = await page.evaluate(() =>
		sessionStorage.getItem('incognito_mode_enabled')
	);
	expect(modeAfterReload).toBe('true');
	logCheckpoint('✓ Incognito mode still enabled after reload.');

	// Assert: sidebar shows incognito label(s)
	if (!(await sidebar.isVisible({ timeout: 1000 }).catch(() => false))) {
		const menuButton = page.locator(SELECTORS.menuButton);
		if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
			await menuButton.click();
			await page.waitForTimeout(500);
		}
	}
	await expect(incognitoGroupHeader.first()).toBeVisible({ timeout: 15000 });
	// Verify the incognito chat items under the group match the expected count
	const incognitoChatItems = page.locator('.chat-item.incognito');
	const itemCount = await incognitoChatItems.count();
	expect(itemCount).toBe(chatCountAfter);
	logCheckpoint(
		`✓ Sidebar shows INCOGNITO group header with ${itemCount} chat item(s) after reload.`
	);
	await takeStepScreenshot(page, '11-after-reload');

	// -------------------------------------------------------------------------
	// Scenario 4 + 5: Disable incognito → chats removed, banner gone
	// -------------------------------------------------------------------------

	logCheckpoint('--- Scenario 4+5: Disable incognito, chats removed + banner gone ---');

	// Record whether the INCOGNITO group header is visible before disabling (to verify it's gone later)
	const groupHeaderVisibleBeforeDisable = await incognitoGroupHeader
		.first()
		.isVisible()
		.catch(() => false);
	logCheckpoint(
		`Incognito group header visible before disable: ${groupHeaderVisibleBeforeDisable}`
	);
	expect(groupHeaderVisibleBeforeDisable).toBe(true);

	// Open settings and disable the toggle
	await profileButton.click();
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logCheckpoint('Settings reopened to disable incognito.');
	await takeStepScreenshot(page, '12-settings-to-disable');

	// When incognito is ON, clicking the toggle turns it OFF directly (no info sub-page)
	const toggleWrapper2 = page.locator(SELECTORS.incognitoToggleWrapper);
	await expect(toggleWrapper2).toBeVisible({ timeout: 10000 });
	await toggleWrapper2.click();
	logCheckpoint('Clicked toggle to disable incognito.');

	// Wait for the store to process deletion and incognitoChatsDeleted to propagate
	await page.waitForTimeout(2000);

	// Close settings via the window event (more reliable than click-outside on desktop)
	await page.evaluate(() => window.dispatchEvent(new CustomEvent('closeSettingsMenu')));
	await page.waitForTimeout(500);
	await takeStepScreenshot(page, '13-incognito-disabled');

	// Assert (Scenario 4): incognito labels gone from sidebar
	if (!(await sidebar.isVisible({ timeout: 1000 }).catch(() => false))) {
		const menuButton = page.locator(SELECTORS.menuButton);
		if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
			await menuButton.click();
			await page.waitForTimeout(500);
		}
	}
	await page.waitForTimeout(2000);
	const groupHeaderVisibleAfterDisable = await incognitoGroupHeader
		.first()
		.isVisible()
		.catch(() => false);
	logCheckpoint(`Incognito group header visible after disable: ${groupHeaderVisibleAfterDisable}`);
	expect(groupHeaderVisibleAfterDisable).toBe(false);
	logCheckpoint('✓ Incognito group header removed from sidebar after disable.');

	// Assert (Scenario 5): incognito banner gone
	await expect(incognitoBanner).not.toBeVisible({ timeout: 10000 });
	logCheckpoint('✓ Incognito banner no longer visible.');

	// Assert: sessionStorage cleaned up
	const storedChatsAfterDisable = await page.evaluate(() =>
		sessionStorage.getItem('incognito_chats')
	);
	expect(storedChatsAfterDisable).toBeNull();
	logCheckpoint('✓ sessionStorage incognito_chats cleared.');

	const modeAfterDisable = await page.evaluate(() =>
		sessionStorage.getItem('incognito_mode_enabled')
	);
	expect(modeAfterDisable).toBe('false');
	logCheckpoint('✓ sessionStorage incognito_mode_enabled = false.');

	await takeStepScreenshot(page, '14-all-cleared');
	logCheckpoint('All incognito scenarios passed.');
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, info: any) => {
	if (info.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-50).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((a) => console.log(a));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});
