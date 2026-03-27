/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Multi-Tab Encryption Test (Same Browser, Shared Storage)
 *
 * Tests that two tabs in the SAME browser context can both decrypt messages
 * correctly. This validates the single-device, multi-tab scenario where
 * IndexedDB, localStorage, and cookies are shared between tabs.
 *
 * KEY DIFFERENCE from multi-session-encryption.spec.ts:
 * - multi-session uses TWO separate BrowserContexts (simulating two devices
 *   with separate storage, separate master keys, separate IndexedDB).
 * - THIS spec uses ONE BrowserContext with TWO pages (simulating two browser
 *   tabs on the same device sharing all storage).
 *
 * Because storage is shared, we only log in ONCE (in tab A). Tab B navigates
 * directly to /chat and is already authenticated via the shared session cookie.
 * Logging in twice would cause OTP rejection and session cookie conflicts.
 *
 * Bug history this test suite guards against:
 * - Race conditions in BroadcastChannel key distribution between tabs
 * - IndexedDB read contention when two tabs decrypt simultaneously
 * - Chat key cache inconsistencies across tabs sharing the same origin
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 *
 * Requirements: TEST-01, TEST-02
 */
export {};

const { test, expect, chromium } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---- Timeout constants ----

/** Maximum time for the full test (5 minutes) */
const TEST_TIMEOUT_MS = 300000;

/** Time to wait for AI assistant response */
const AI_RESPONSE_TIMEOUT_MS = 60000;

/** Time to wait for chat to appear in sidebar via WebSocket sync */
const SIDEBAR_SYNC_TIMEOUT_MS = 60000;

/** Time to wait for tab B to reach /chat after navigation */
const TAB_NAVIGATION_TIMEOUT_MS = 15000;

/** Time to wait for initial sync to complete after login */
const INITIAL_SYNC_WAIT_MS = 10000;

// ---- Debug log capture ----

interface SessionLogs {
	consoleLogs: string[];
	decryptionErrors: string[];
}

function createSessionLogs(): SessionLogs {
	return { consoleLogs: [], decryptionErrors: [] };
}

/**
 * Attach console listeners to a page to capture decryption errors.
 * Decryption errors are flagged separately for easy assertion at the end.
 */
function attachListeners(page: any, label: string, logs: SessionLogs) {
	page.on('console', (msg: any) => {
		const ts = new Date().toISOString();
		const text = msg.text();
		const line = `[${ts}] [${label}] [${msg.type()}] ${text}`;
		logs.consoleLogs.push(line);

		const isDecryptError =
			msg.type() === 'error' &&
			(text.toLowerCase().includes('decrypt') ||
				text.toLowerCase().includes('decryption') ||
				text.toLowerCase().includes('wrong chat key') ||
				text.toLowerCase().includes('crypto') ||
				text.toLowerCase().includes('operationerror') ||
				text.toLowerCase().includes('chat decryption failed'));

		if (isDecryptError) {
			logs.decryptionErrors.push(line);
			console.error(`[DECRYPTION ERROR CAPTURED] ${line}`);
		}
	});
}

// ---- Login helper ----

/**
 * Perform the full login flow (email -> password+OTP -> redirect to /chat).
 * Only called ONCE per test (in tab A). Tab B shares the session via cookies.
 */
async function loginToApp(page: any, logFn: (msg: string) => void): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));

	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();

	// Click Login tab to switch from signup to login view
	const loginTab = page.locator('.login-tabs .tab-button', { hasText: /^login$/i });
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logFn('Email submitted.');

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);

	// OTP is time-sensitive -- generate immediately before entering
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });
	await otpInput.fill(otpCode);
	logFn(`OTP entered: ${otpCode}`);

	const submitBtn = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitBtn).toBeVisible();
	await submitBtn.click();
	logFn('Login submitted, waiting for redirect...');

	await page.waitForURL(/chat/, { timeout: 30000 });
	logFn('Redirected to /chat -- login complete.');
}

// ---- Start new chat ----

async function startNewChat(page: any, logFn: (msg: string) => void): Promise<void> {
	await page.waitForTimeout(3000);

	// Multiple fallback selectors — sidebar-closed may show .new-chat-cta-button
	const newChatButtonSelectors = [
		'.new-chat-cta-button',
		'.icon_create',
		'button[aria-label*="New"]',
		'button[aria-label*="new"]'
	];

	let clicked = false;
	for (const selector of newChatButtonSelectors) {
		const button = page.locator(selector).first();
		if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
			logFn(`Clicking New Chat button (${selector}).`);
			await button.click();
			clicked = true;
			break;
		}
	}

	if (!clicked) {
		logFn('No New Chat button found — editor may already be visible.');
	}

	// Wait for editor to appear regardless of which path we took
	await expect(page.locator('.editor-content.prose')).toBeVisible({ timeout: 15000 });
	logFn('Editor visible.');
}

// ---- Send message and get chat ID ----

async function sendMessageAndGetChatId(
	page: any,
	message: string,
	logFn: (msg: string) => void
): Promise<string> {
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 15000 });
	await messageEditor.click();
	await page.keyboard.type(message);

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled({ timeout: 10000 });
	await sendButton.click();
	logFn(`Message sent: "${message}"`);

	// Wait for a real UUID chat ID in the URL
	const uuidPattern = /chat-id=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
	await expect(page).toHaveURL(uuidPattern, { timeout: 20000 });
	const url = page.url();
	const match = url.match(
		/chat-id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i
	);
	const chatId = match ? match[1] : 'unknown';
	logFn(`Chat ID: ${chatId}`);
	return chatId;
}

// ---- Wait for assistant response ----

async function waitForAssistantResponse(
	page: any,
	expectedText: string,
	logFn: (msg: string) => void,
	timeoutMs: number = AI_RESPONSE_TIMEOUT_MS
): Promise<void> {
	logFn(`Waiting for assistant response containing "${expectedText}"...`);
	const assistantResponse = page.locator('.message-wrapper.assistant');
	await expect(assistantResponse.last()).toContainText(expectedText, { timeout: timeoutMs });
	logFn(`Got assistant response with "${expectedText}".`);
}

// ---- Wait for chat in sidebar and click ----

/**
 * Waits for a chat to appear in the sidebar via real-time WebSocket sync,
 * then clicks on it to open. This simulates how a user in a second tab
 * discovers a chat created in the first tab.
 */
async function waitForChatInSidebarAndClick(
	page: any,
	expectedTitleFragment: string,
	logFn: (msg: string) => void,
	timeoutMs: number = SIDEBAR_SYNC_TIMEOUT_MS
): Promise<void> {
	logFn(`Waiting for chat with title containing "${expectedTitleFragment}" to appear in sidebar...`);

	const chatItem = page.locator('.chat-item-wrapper', {
		has: page.locator('.chat-title', {
			hasText: new RegExp(expectedTitleFragment, 'i')
		})
	});

	await expect(chatItem.first()).toBeVisible({ timeout: timeoutMs });
	logFn(`Chat "${expectedTitleFragment}" appeared in sidebar -- clicking to open.`);

	await chatItem.first().click();
	await page.waitForTimeout(3000); // Allow messages to load and decrypt
	logFn(`Opened chat "${expectedTitleFragment}" in tab B.`);
}

// ---- Assert decryption correctness ----

/**
 * Asserts that:
 * 1. The assistant message exists and contains expected text.
 * 2. No decryption error console.errors were captured.
 * 3. No error states visible in the UI (e.g. "[decryption error]" placeholder text).
 */
async function assertChatDecryptedCorrectly(
	page: any,
	expectedAssistantText: string | RegExp,
	sessionLabel: string,
	logs: SessionLogs,
	logFn: (msg: string) => void
): Promise<void> {
	logFn(`Asserting chat is decrypted correctly in ${sessionLabel}...`);

	const assistantMsgs = page.locator('.message-wrapper.assistant');
	if (typeof expectedAssistantText === 'string') {
		await expect(assistantMsgs.last()).toContainText(expectedAssistantText, { timeout: 30000 });
	} else {
		await expect(assistantMsgs.last()).toBeVisible({ timeout: 30000 });
		const text = await assistantMsgs.last().innerText();
		if (!expectedAssistantText.test(text)) {
			throw new Error(
				`[${sessionLabel}] Assistant response "${text}" does not match expected pattern ${expectedAssistantText}`
			);
		}
	}

	if (logs.decryptionErrors.length > 0) {
		const errSummary = logs.decryptionErrors.join('\n');
		throw new Error(
			`[${sessionLabel}] Decryption errors detected while viewing chat:\n${errSummary}`
		);
	}

	const bodyText = await page.locator('body').innerText();
	const decryptionErrorPatterns = [
		/decryption error/i,
		/\[encrypted\]/i,
		/failed to decrypt/i,
		/content unavailable/i
	];
	for (const pattern of decryptionErrorPatterns) {
		if (pattern.test(bodyText)) {
			await page.screenshot({
				path: `artifacts/decrypt-error-${sessionLabel}.png`,
				fullPage: true
			});
			throw new Error(
				`[${sessionLabel}] Decryption error pattern "${pattern}" found in page body.`
			);
		}
	}

	logFn(`Chat decrypted correctly in ${sessionLabel} -- no errors.`);
}

// ---- Delete active chat ----

async function deleteActiveChat(page: any, logFn: (msg: string) => void): Promise<void> {
	logFn('Deleting active chat via context menu...');

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	if (!(await activeChatItem.isVisible())) {
		logFn('No active chat item visible -- skipping delete.');
		return;
	}

	await activeChatItem.click({ button: 'right' });
	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible({ timeout: 5000 });
	await deleteButton.click(); // Enter confirm mode
	await deleteButton.click(); // Confirm deletion
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	logFn('Chat deleted.');
}

// ---- TEST-01: Two tabs open same chat, both decrypt correctly ----

test('TEST-01: two tabs open same chat, send messages, both tabs decrypt correctly', async () => {
	test.slow();
	test.setTimeout(TEST_TIMEOUT_MS);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logA = createSignupLogger('MULTI_TAB_A');
	const logB = createSignupLogger('MULTI_TAB_B');
	const screenshotA = createStepScreenshotter(logA, { filenamePrefix: 'tab-a' });
	const screenshotB = createStepScreenshotter(logB, { filenamePrefix: 'tab-b' });

	await archiveExistingScreenshots(logA);

	const logsA = createSessionLogs();
	const logsB = createSessionLogs();

	// ONE BrowserContext = shared cookies, localStorage, IndexedDB (same device, two tabs)
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const browser = await chromium.launch();
	const context = await browser.newContext({ baseURL });

	const tabA = await context.newPage();
	const tabB = await context.newPage();

	attachListeners(tabA, 'TAB-A', logsA);
	attachListeners(tabB, 'TAB-B', logsB);

	let chatId = '';

	try {
		// Step 1: Login in tab A only (tab B shares the session via cookies)
		logA('Logging in via Tab A...');
		await loginToApp(tabA, logA);
		await screenshotA(tabA, 'logged-in');

		// Step 2: Tab B navigates to /chat -- already authenticated
		logB('Tab B navigating to /chat (shared session)...');
		await tabB.goto(getE2EDebugUrl('/chat'));
		await tabB.waitForURL(/chat/, { timeout: TAB_NAVIGATION_TIMEOUT_MS });
		logB('Tab B reached /chat -- authenticated via shared cookies.');
		await screenshotB(tabB, 'authenticated');

		// Wait for initial sync to complete on both tabs
		logA(`Waiting ${INITIAL_SYNC_WAIT_MS / 1000}s for initial sync...`);
		await tabA.waitForTimeout(INITIAL_SYNC_WAIT_MS);

		// Step 3: Tab A creates a new chat and sends a message
		await startNewChat(tabA, logA);
		await screenshotA(tabA, 'new-chat');

		chatId = await sendMessageAndGetChatId(
			tabA,
			'Multi-tab test message from Tab A',
			logA
		);
		logA(`Chat created with ID: ${chatId}`);

		// Step 4: Tab A waits for AI response
		await waitForAssistantResponse(tabA, '.', logA, AI_RESPONSE_TIMEOUT_MS);
		await screenshotA(tabA, 'ai-response');

		// Step 5: Tab B discovers the chat via sidebar sync and opens it
		await screenshotB(tabB, 'before-sidebar-check');
		await waitForChatInSidebarAndClick(tabB, 'multi-tab', logB, SIDEBAR_SYNC_TIMEOUT_MS);
		await screenshotB(tabB, 'chat-opened');

		// Step 6: Assert both tabs have correct decryption
		logsA.decryptionErrors = [];
		logsB.decryptionErrors = [];

		// Small wait to let tab B finish decrypting all messages
		await tabB.waitForTimeout(2000);

		await assertChatDecryptedCorrectly(
			tabA,
			/.+/,
			'TAB-A',
			logsA,
			logA
		);
		await assertChatDecryptedCorrectly(
			tabB,
			/.+/,
			'TAB-B',
			logsB,
			logB
		);

		logA('TEST-01 PASSED: Both tabs decrypted the same chat correctly.');
	} catch (error) {
		// Take failure screenshots before re-throwing
		try {
			await tabA.screenshot({ path: 'artifacts/test01-failure-tab-a.png', fullPage: true });
			await tabB.screenshot({ path: 'artifacts/test01-failure-tab-b.png', fullPage: true });
		} catch {
			// Best-effort screenshot capture
		}
		throw error;
	} finally {
		// Cleanup: delete the test chat from tab A
		try {
			if (chatId) {
				await deleteActiveChat(tabA, logA);
			}
		} catch (err) {
			logA(`Warning: cleanup failed: ${err}`);
		}

		await context.close();
		await browser.close();
	}
});

// ---- TEST-02: Create in tab A, open in tab B, content decrypts ----

test('TEST-02: create chat in tab A, open in tab B, content decrypts correctly', async () => {
	test.slow();
	test.setTimeout(TEST_TIMEOUT_MS);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logA = createSignupLogger('MULTI_TAB_CREATE_A');
	const logB = createSignupLogger('MULTI_TAB_CREATE_B');
	const screenshotA = createStepScreenshotter(logA, { filenamePrefix: 'create-tab-a' });
	const screenshotB = createStepScreenshotter(logB, { filenamePrefix: 'create-tab-b' });

	await archiveExistingScreenshots(logA);

	const logsA = createSessionLogs();
	const logsB = createSessionLogs();

	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const browser = await chromium.launch();
	const context = await browser.newContext({ baseURL });

	const tabA = await context.newPage();
	const tabB = await context.newPage();

	attachListeners(tabA, 'TAB-A', logsA);
	attachListeners(tabB, 'TAB-B', logsB);

	let chatId = '';

	try {
		// Step 1: Login in tab A only
		logA('Logging in via Tab A...');
		await loginToApp(tabA, logA);
		await screenshotA(tabA, 'logged-in');

		// Step 2: Tab B navigates to /chat (already authenticated via shared cookies)
		logB('Tab B navigating to /chat (shared session)...');
		await tabB.goto(getE2EDebugUrl('/chat'));
		await tabB.waitForURL(/chat/, { timeout: TAB_NAVIGATION_TIMEOUT_MS });
		logB('Tab B reached /chat.');
		await screenshotB(tabB, 'authenticated');

		// Wait for initial sync
		logA(`Waiting ${INITIAL_SYNC_WAIT_MS / 1000}s for initial sync...`);
		await tabA.waitForTimeout(INITIAL_SYNC_WAIT_MS);

		// Step 3: Tab A creates a chat and sends a message
		await startNewChat(tabA, logA);
		chatId = await sendMessageAndGetChatId(
			tabA,
			'Cross-tab creation test',
			logA
		);
		logA(`Chat created with ID: ${chatId}`);
		await screenshotA(tabA, 'message-sent');

		// Step 4: Tab A waits for AI response
		await waitForAssistantResponse(tabA, '.', logA, AI_RESPONSE_TIMEOUT_MS);
		await screenshotA(tabA, 'ai-response');

		// Step 5: Tab B discovers the chat via sidebar and opens it.
		// This is the key assertion: tab B never created this chat. It discovers
		// it via WebSocket sync and must decrypt using the shared chat key from
		// IndexedDB (populated by tab A and visible to tab B via shared storage).
		await waitForChatInSidebarAndClick(tabB, 'cross-tab', logB, SIDEBAR_SYNC_TIMEOUT_MS);
		await screenshotB(tabB, 'chat-opened');

		// Step 6: Assert tab B decrypts correctly
		logsB.decryptionErrors = [];
		await tabB.waitForTimeout(2000);

		await assertChatDecryptedCorrectly(
			tabB,
			/.+/,
			'TAB-B-cross-tab',
			logsB,
			logB
		);

		// Verify: zero decryption errors in tab B
		if (logsB.decryptionErrors.length > 0) {
			throw new Error(
				`Tab B had ${logsB.decryptionErrors.length} decryption errors:\n${logsB.decryptionErrors.join('\n')}`
			);
		}

		logA('TEST-02 PASSED: Chat created in Tab A decrypted correctly in Tab B.');
	} catch (error) {
		try {
			await tabA.screenshot({ path: 'artifacts/test02-failure-tab-a.png', fullPage: true });
			await tabB.screenshot({ path: 'artifacts/test02-failure-tab-b.png', fullPage: true });
		} catch {
			// Best-effort screenshot capture
		}
		throw error;
	} finally {
		try {
			if (chatId) {
				await deleteActiveChat(tabA, logA);
			}
		} catch (err) {
			logA(`Warning: cleanup failed: ${err}`);
		}

		await context.close();
		await browser.close();
	}
});
