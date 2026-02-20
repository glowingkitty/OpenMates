/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Multi-Session Encryption Test
 *
 * Tests that two browsers logged in as the same user can both:
 * - Send/receive messages without content decryption errors
 * - See the same chat content correctly decrypted
 * - Handle 4 sequential chats all working correctly across both sessions
 *
 * This specifically targets the issue where concurrent sessions cause
 * encryption key conflicts (e.g. a new chat key generated in session A
 * isn't available in session B until synced, leading to decryption errors).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */
export {};

const { test, expect, chromium } = require('@playwright/test');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp
} = require('./signup-flow-helpers');

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// ─── Captured debug data ────────────────────────────────────────────────────

interface SessionLogs {
	consoleLogs: string[];
	decryptionErrors: string[];
}

function createSessionLogs(): SessionLogs {
	return { consoleLogs: [], decryptionErrors: [] };
}

/**
 * Attach console + network listeners to a page.
 * Decryption errors are captured separately for easy assertion.
 */
function attachListeners(page: any, label: string, logs: SessionLogs) {
	page.on('console', (msg: any) => {
		const ts = new Date().toISOString();
		const text = msg.text();
		const line = `[${ts}] [${label}] [${msg.type()}] ${text}`;
		logs.consoleLogs.push(line);

		// Flag any decryption-related errors — these are the core bugs we're hunting
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

// ─── Login helper ────────────────────────────────────────────────────────────

/**
 * Perform the full login flow (email → password+OTP → redirect to /chat).
 * Reuses the same selectors validated in chat-flow.spec.ts.
 */
async function loginToApp(page: any, logFn: (msg: string) => void): Promise<void> {
	await page.goto('/');

	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logFn('Email submitted.');

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);

	// OTP is time-sensitive — generate immediately before entering
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);
	logFn(`OTP entered: ${otpCode}`);

	const submitBtn = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitBtn).toBeVisible();
	await submitBtn.click();
	logFn('Login submitted, waiting for redirect…');

	await page.waitForURL(/chat/, { timeout: 30000 });
	logFn('Redirected to /chat — login complete.');
}

// ─── Start new chat ──────────────────────────────────────────────────────────

async function startNewChat(page: any, logFn: (msg: string) => void): Promise<void> {
	// Wait for page to be stable after login / previous chat
	await page.waitForTimeout(3000);

	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible()) {
		logFn('Clicking New Chat button.');
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}
}

// ─── Send message and get chat ID ────────────────────────────────────────────

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

	// Wait for a real UUID chat ID in the URL (not the demo-for-everyone placeholder).
	// The demo chat uses chat-id=demo-for-everyone; real chats use UUIDs like
	// "2a43c594-cc80-4be2-9148-d41658f7717f". We poll until we see a UUID.
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

// ─── Wait for assistant response ─────────────────────────────────────────────

async function waitForAssistantResponse(
	page: any,
	expectedText: string,
	logFn: (msg: string) => void,
	timeoutMs: number = 60000
): Promise<void> {
	logFn(`Waiting for assistant response containing "${expectedText}"…`);
	const assistantResponse = page.locator('.message-wrapper.assistant');
	await expect(assistantResponse.last()).toContainText(expectedText, { timeout: timeoutMs });
	logFn(`Got assistant response with "${expectedText}".`);
}

// ─── Navigate to a specific chat ─────────────────────────────────────────────

async function navigateToChatById(
	page: any,
	chatId: string,
	logFn: (msg: string) => void
): Promise<void> {
	// Use a relative URL so Playwright's configured baseURL is applied.
	// An absolute URL bypasses baseURL and can hit the wrong host in Docker.
	logFn(`Navigating to chat ${chatId}…`);
	await page.goto(`/chat?chat-id=${chatId}`);
	await page.waitForTimeout(5000); // Allow sync to complete
	logFn(`At chat ${chatId}.`);
}

// ─── Assert messages visible without decryption errors ───────────────────────

/**
 * Asserts that:
 * 1. The assistant message exists and contains the expected text.
 * 2. No decryption error banners / error messages are visible in the chat.
 */
async function assertChatDecryptedCorrectly(
	page: any,
	expectedAssistantText: string,
	sessionLabel: string,
	logs: SessionLogs,
	logFn: (msg: string) => void
): Promise<void> {
	logFn(`Asserting chat is decrypted correctly in ${sessionLabel}…`);

	// 1. The last assistant message should contain the expected text
	const assistantMsgs = page.locator('.message-wrapper.assistant');
	await expect(assistantMsgs.last()).toContainText(expectedAssistantText, { timeout: 30000 });

	// 2. No console decryption errors should have been captured for this session
	if (logs.decryptionErrors.length > 0) {
		const errSummary = logs.decryptionErrors.join('\n');
		throw new Error(
			`[${sessionLabel}] Decryption errors detected while viewing chat:\n${errSummary}`
		);
	}

	// 3. No error states visible in the UI (e.g. "[decryption error]" placeholder text)
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

	logFn(`Chat decrypted correctly in ${sessionLabel} — no errors.`);
}

// ─── Delete active chat ───────────────────────────────────────────────────────

async function deleteActiveChat(page: any, logFn: (msg: string) => void): Promise<void> {
	logFn('Deleting active chat via context menu…');

	// Ensure sidebar is visible
	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	if (!(await activeChatItem.isVisible())) {
		logFn('No active chat item visible — skipping delete.');
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

// ─── Main test ───────────────────────────────────────────────────────────────

test('multi-session encryption: two simultaneous sessions can send and read 4 chats without decryption errors', async () => {
	test.slow();
	// 4 chats × ~60s AI response + login + sync time = budget 10 minutes
	test.setTimeout(600000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const logA = createSignupLogger('MULTI_SESSION_A');
	const logB = createSignupLogger('MULTI_SESSION_B');
	const screenshotA = createStepScreenshotter(logA, { filenamePrefix: 'a' });
	const screenshotB = createStepScreenshotter(logB, { filenamePrefix: 'b' });

	await archiveExistingScreenshots(logA);

	const logsA = createSessionLogs();
	const logsB = createSessionLogs();

	// ── Open two independent browser contexts ────────────────────────────
	// Using a fresh browser launch to guarantee separate storage (separate IndexedDB,
	// separate in-memory master keys) — exactly what happens with two real browsers.
	// IMPORTANT: manually created contexts do NOT inherit playwright.config.ts baseURL,
	// so we must pass it explicitly so that page.goto('/...') resolves correctly.
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const browser = await chromium.launch();
	const contextA = await browser.newContext({ baseURL });
	const contextB = await browser.newContext({ baseURL });
	const pageA = await contextA.newPage();
	const pageB = await contextB.newPage();

	attachListeners(pageA, 'SESSION-A', logsA);
	attachListeners(pageB, 'SESSION-B', logsB);

	const chatIds: string[] = [];

	try {
		// ── Step 1: Log in both sessions concurrently ─────────────────────
		logA('Logging in Session A…');
		logB('Logging in Session B…');
		// Log in A first to get the OTP window, then B with a fresh OTP
		await loginToApp(pageA, logA);
		await screenshotA(pageA, 'logged-in');

		// Wait until the TOTP window rolls over before logging in Session B.
		// TOTP codes are 30-second windows; reusing the same code in the same window
		// is rejected by the server. We calculate how many ms remain in the current
		// window and wait for it to expire + a small buffer.
		{
			const msInWindow = Date.now() % 30000;
			const msUntilNextWindow = 30000 - msInWindow + 500; // +500ms buffer
			logA(
				`Waiting ${Math.ceil(msUntilNextWindow / 1000)}s for new OTP window before Session B login…`
			);
			await pageA.waitForTimeout(msUntilNextWindow);
		}

		await loginToApp(pageB, logB);
		await screenshotB(pageB, 'logged-in');

		logA('Both sessions logged in successfully.');

		// ── Steps 2–5: 4 chat rounds ──────────────────────────────────────
		const chatScenarios = [
			{ question: 'What is the capital of France?', expectedAnswer: 'Paris' },
			{ question: 'What is 5 multiplied by 7?', expectedAnswer: '35' },
			{
				question: 'Name one planet in our solar system.',
				expectedAnswer: /(Mercury|Venus|Earth|Mars|Jupiter|Saturn|Uranus|Neptune)/i
			},
			{ question: 'What color is the sky on a clear day?', expectedAnswer: 'blue' }
		];

		for (let i = 0; i < chatScenarios.length; i++) {
			const { question, expectedAnswer } = chatScenarios[i];
			const chatNum = i + 1;
			const expectedText = typeof expectedAnswer === 'string' ? expectedAnswer : 'planet'; // fallback label for logging

			logA(`\n===== CHAT ${chatNum}/4 =====`);
			logA(`Question: "${question}"`);

			// ── Start a new chat in Session A and send the message ────────
			await startNewChat(pageA, logA);
			await screenshotA(pageA, `chat${chatNum}-new-chat`);

			const chatId = await sendMessageAndGetChatId(pageA, question, logA);
			chatIds.push(chatId);

			// ── Wait for AI response in Session A ─────────────────────────
			if (typeof expectedAnswer === 'string') {
				await waitForAssistantResponse(pageA, expectedAnswer, logA);
			} else {
				// Regex case — wait for any assistant response to appear
				logA('Waiting for assistant response (regex match)…');
				const assistantMsgA = pageA.locator('.message-wrapper.assistant');
				await expect(assistantMsgA.last()).toBeVisible({ timeout: 60000 });
				logA('Assistant response visible in Session A.');
			}

			await screenshotA(pageA, `chat${chatNum}-response-a`);

			// ── Assert no decryption errors in Session A ──────────────────
			if (typeof expectedAnswer === 'string') {
				await assertChatDecryptedCorrectly(pageA, expectedAnswer, 'SESSION-A', logsA, logA);
			} else {
				// For regex: just check no decryption errors exist
				if (logsA.decryptionErrors.length > 0) {
					throw new Error(
						`[SESSION-A] Decryption errors at chat ${chatNum}:\n${logsA.decryptionErrors.join('\n')}`
					);
				}
			}

			// ── Navigate Session B to the same chat ───────────────────────
			logB(`Navigating Session B to chat ${chatId}…`);
			await navigateToChatById(pageB, chatId, logB);
			await screenshotB(pageB, `chat${chatNum}-session-b-view`);

			// ── Assert chat is readable in Session B without errors ────────
			if (typeof expectedAnswer === 'string') {
				await assertChatDecryptedCorrectly(pageB, expectedAnswer, 'SESSION-B', logsB, logB);
			} else {
				// For regex: check the assistant message is visible and no decrypt errors
				const assistantMsgB = pageB.locator('.message-wrapper.assistant');
				await expect(assistantMsgB.last()).toBeVisible({ timeout: 30000 });
				if (logsB.decryptionErrors.length > 0) {
					throw new Error(
						`[SESSION-B] Decryption errors at chat ${chatNum}:\n${logsB.decryptionErrors.join('\n')}`
					);
				}
				logB(`Chat ${chatNum} readable in Session B — no decryption errors.`);
			}

			await screenshotB(pageB, `chat${chatNum}-verified-b`);
			logA(`Chat ${chatNum} verified on both sessions ✓`);

			// ── After each round, reset Session B to home so it can see sidebar ──
			// This simulates the real user flow where Session B discovers the new chat
			// via the sidebar, rather than being navigated directly.
			if (i < chatScenarios.length - 1) {
				await pageB.goto('/');
				await pageB.waitForTimeout(2000);
			}
		}

		// ── Final summary ─────────────────────────────────────────────────
		logA(`\n=== ALL 4 CHATS VERIFIED ===`);
		logA(`Total decryption errors in Session A: ${logsA.decryptionErrors.length}`);
		logA(`Total decryption errors in Session B: ${logsB.decryptionErrors.length}`);
		logB(`Total console logs in Session B: ${logsB.consoleLogs.length}`);

		// Fail the test explicitly if there were any decryption errors in either session
		expect(logsA.decryptionErrors.length).toBe(0);
		expect(logsB.decryptionErrors.length).toBe(0);
	} finally {
		// ── Cleanup: delete all test chats from Session A ─────────────────
		logA('Cleaning up test chats…');
		for (const chatId of chatIds) {
			try {
				await navigateToChatById(pageA, chatId, logA);
				await deleteActiveChat(pageA, logA);
			} catch (err) {
				// Best-effort cleanup — don't fail the test on cleanup errors
				logA(`Warning: could not delete chat ${chatId}: ${err}`);
			}
		}

		await contextA.close();
		await contextB.close();
		await browser.close();
	}
});
