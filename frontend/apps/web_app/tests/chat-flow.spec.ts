/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Chat flow test: login with existing account + 2FA, then send a message and validate
 * zero-knowledge encryption health through multiple lifecycle phases:
 *
 *   1. Initial login → send message → confirm AI response
 *   2. Console warn/error capture → save to file if any occurred
 *   3. `window.inspectChat` client-side data check (messages, title, category)
 *   4. Tab reload → verify chat still decrypts correctly (no encryption errors)
 *   5. Logout → login again → verify chat still decrypts correctly
 *   6. Delete chat
 *
 * Any console warn/error logs captured during phases 2–5 are saved to
 * playwright-artifacts/console-warnings-{chatId}.json for offline diagnosis.
 * The test itself only fails if chat data is missing or broken — not on mere warnings.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */
export {};

const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

// ─── Log buckets ────────────────────────────────────────────────────────────
// All console messages captured for failure diagnostics.
const consoleLogs: string[] = [];
// Only warn / error entries — written to file if non-empty.
const warnErrorLogs: Array<{ timestamp: string; type: string; text: string }> = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	warnErrorLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Save warn/error logs to a JSON file in playwright-artifacts/.
 * Only writes the file if warnErrorLogs is non-empty.
 * Appends a new phase entry to an existing file if it already exists.
 */
function saveWarnErrorLogs(chatId: string, phase: string): void {
	if (warnErrorLogs.length === 0) return;

	const artifactsDir = path.resolve(process.cwd(), 'artifacts');
	fs.mkdirSync(artifactsDir, { recursive: true });

	const filePath = path.join(artifactsDir, `console-warnings-${chatId}.json`);

	// Load existing data (from a previous phase of the same test run) or start fresh.
	let existing: any = {
		chat_id: chatId,
		test: 'logs in and sends a chat message',
		run_timestamp: new Date().toISOString(),
		phases: {},
		total_warn_errors: 0
	};
	try {
		if (fs.existsSync(filePath)) {
			existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
		}
	} catch {
		// Ignore parse errors — start fresh
	}

	// Add this phase's entries and update total.
	existing.phases[phase] = warnErrorLogs.slice(); // snapshot of current buffer
	existing.total_warn_errors = Object.values(existing.phases as Record<string, any[]>).reduce(
		(sum: number, entries: any[]) => sum + entries.length,
		0
	);

	fs.writeFileSync(filePath, JSON.stringify(existing, null, 2), 'utf8');
	console.log(
		`[WARN/ERROR LOGS] Saved ${warnErrorLogs.length} entries for phase "${phase}" → ${filePath}`
	);

	// Clear the buffer so the next phase starts fresh.
	warnErrorLogs.length = 0;
}

/**
 * Call window.inspectChat(chatId) inside the browser and return parsed data.
 * Returns null if the utility is not available or the chat has no data.
 */
async function inspectChatClientSide(
	page: any,
	chatId: string
): Promise<Record<string, any> | null> {
	return await page.evaluate(async (id: string) => {
		const inspectChat = (window as any).inspectChat;
		if (typeof inspectChat !== 'function') return null;
		try {
			const report = await inspectChat(id);
			// report is a formatted string — parse key fields from it
			return { raw: report };
		} catch (err: any) {
			return { error: String(err) };
		}
	}, chatId);
}

/**
 * Assert that the active chat item in the sidebar shows real, decrypted metadata:
 * - Title is not a placeholder (not "untitled chat", not "processing", not empty)
 * - Category circle exists and is NOT the grey "missing-category" fallback
 *
 * Also checks that visible message wrappers do NOT show the error-state inline style
 * (opacity 0.7 + border: 1px solid var(--color-error)) that appears on failed messages.
 */
async function assertChatDecryptedCorrectly(
	page: any,
	logCheckpoint: (...args: any[]) => void,
	phase: string
): Promise<void> {
	logCheckpoint(`[${phase}] Asserting chat decryption health...`);

	// ── Sidebar assertions ──────────────────────────────────────────────────
	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible({ timeout: 10000 });

	// Title must be real — not a placeholder and not empty
	const chatTitle = activeChatItem.locator('.chat-title');
	await expect(chatTitle).toBeVisible({ timeout: 15000 });
	// Must not still be in "processing" loading state
	await expect(chatTitle).not.toHaveClass(/processing-title/, { timeout: 5000 });
	const titleText = await chatTitle.textContent();
	logCheckpoint(`[${phase}] Chat title: "${titleText}"`);
	expect(titleText).toBeTruthy();
	expect(titleText!.trim()).not.toBe('');
	expect(titleText!.toLowerCase()).not.toContain('untitled chat');
	expect(titleText!.toLowerCase()).not.toContain('processing');

	// Category circle must exist and must NOT be the grey "missing-category" fallback
	const categoryCircle = activeChatItem.locator('.category-circle');
	await expect(categoryCircle).toBeVisible({ timeout: 10000 });
	const missingCategory = activeChatItem.locator('.category-circle.missing-category');
	await expect(missingCategory).not.toBeVisible();

	logCheckpoint(`[${phase}] Sidebar: title and category look healthy.`);

	// ── Message area assertions ─────────────────────────────────────────────
	// Verify the user message and the assistant message are visible.
	const userMsg = page.locator('.message-wrapper.user').first();
	const assistantMsg = page.locator('.message-wrapper.assistant').last();
	await expect(userMsg).toBeVisible({ timeout: 10000 });
	await expect(assistantMsg).toBeVisible({ timeout: 10000 });

	// Confirm assistant response still decrypted — must contain "Berlin".
	await expect(assistantMsg).toContainText('Berlin', { timeout: 15000 });
	logCheckpoint(`[${phase}] Messages: user + assistant visible and contain expected content.`);

	// Check for error-state inline styles: opacity 0.7 + error border.
	// This is the only indicator that a message failed to decrypt/process.
	const errorMessages = await page.evaluate(() => {
		const wrappers = Array.from(document.querySelectorAll('.message-wrapper'));
		return wrappers
			.filter((el: any) => {
				const style = el.getAttribute('style') || '';
				return style.includes('opacity: 0.7') || style.includes('color-error');
			})
			.map((el: any) => ({
				role: el.classList.contains('user') ? 'user' : 'assistant',
				style: el.getAttribute('style')
			}));
	});

	if (errorMessages.length > 0) {
		console.error(
			`[${phase}] Found ${errorMessages.length} message(s) in error state:`,
			errorMessages
		);
	}
	expect(errorMessages.length).toBe(0);
	logCheckpoint(`[${phase}] No messages in error state.`);
}

/**
 * Shared login sequence. Reused for both the initial login and the re-login after logout.
 */
async function performLogin(
	page: any,
	logCheckpoint: (...args: any[]) => void,
	takeStepScreenshot: (...args: any[]) => Promise<void>,
	screenshotPrefix: string
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, `${screenshotPrefix}-home`);

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();
	await takeStepScreenshot(page, `${screenshotPrefix}-login-dialog`);

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);

	// Click the "Stay logged in" label (the visible toggle slider) so keys are persisted
	// to IndexedDB and survive page reloads. The underlying <input> is visually hidden by
	// the Toggle component's CSS, but the <label class="toggle"> wrapping it is clickable.
	const stayLoggedInLabel = page.locator(
		'label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)'
	);
	try {
		await stayLoggedInLabel.waitFor({ state: 'visible', timeout: 3000 });
		const checkbox = page.locator('#stayLoggedIn');
		const isChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
		if (!isChecked) {
			await stayLoggedInLabel.click();
			logCheckpoint('Clicked "Stay logged in" toggle for persistence across reloads.');
		} else {
			logCheckpoint('"Stay logged in" toggle was already on.');
		}
	} catch {
		logCheckpoint('Could not find "Stay logged in" toggle — proceeding without it.');
	}

	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, `${screenshotPrefix}-password-entered`);

	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);
	logCheckpoint('Generated and entered OTP.');
	await takeStepScreenshot(page, `${screenshotPrefix}-otp-entered`);

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	logCheckpoint('Submitted login form.');

	await page.waitForURL(/chat/);
	logCheckpoint('Redirected to chat page.');
	// Wait for phased sync to complete
	await page.waitForTimeout(5000);
}

// ─── Test ────────────────────────────────────────────────────────────────────

test('logs in and sends a chat message', async ({ page }: { page: any }) => {
	// ── Console log listeners ────────────────────────────────────────────────
	// Capture ALL console messages for failure diagnostics.
	// Separately track warn/error for the warn-log save feature.
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type(); // 'log', 'info', 'warning', 'error', 'debug', etc.
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});

	// Network activity for failure diagnostics.
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(300000); // 5 minutes: covers send + reload + logout + relogin + delete

	const logChatCheckpoint = createSignupLogger('CHAT_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logChatCheckpoint);

	// Pre-test skip checks
	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logChatCheckpoint);
	logChatCheckpoint('Starting chat flow test.', { email: TEST_EMAIL });

	// =========================================================================
	// PHASE 1: Login + send message
	// =========================================================================
	await performLogin(page, logChatCheckpoint, takeStepScreenshot, '01');

	// Check if "New Chat" button is visible and click it for a fresh start
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible()) {
		logChatCheckpoint('New Chat button visible, clicking it to start a fresh chat.');
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}

	// Send message
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type('Capital of Germany?');
	await takeStepScreenshot(page, '02-message-filled');

	// The send button only appears when the editor has content (hasContent reactive state).
	// Use data-action for a stable selector; wait up to 15s for Svelte reactivity + fly-in animation.
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	logChatCheckpoint('Sent message: "Capital of Germany?"');
	await takeStepScreenshot(page, '03-message-sent');

	// Wait for chat ID in URL
	logChatCheckpoint('Waiting for Chat ID to appear in URL...');
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterSend = page.url();
	const chatIdMatch = urlAfterSend.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logChatCheckpoint(`Chat ID detected: ${chatId}`, { chatId });

	// Wait for assistant response containing "Berlin"
	logChatCheckpoint('Waiting for assistant response...');
	const assistantResponse = page.locator('.message-wrapper.assistant');
	await expect(assistantResponse.last()).toContainText('Berlin', { timeout: 45000 });
	await takeStepScreenshot(page, '04-response-received');
	logChatCheckpoint('Confirmed "Berlin" in assistant response.');

	// =========================================================================
	// PHASE 2: Console warn/error check — save logs if any occurred during send
	// =========================================================================
	logChatCheckpoint(
		`Phase 2: Checking console warnings/errors after initial response. Count: ${warnErrorLogs.length}`
	);
	if (warnErrorLogs.length > 0) {
		logChatCheckpoint(
			`Saving ${warnErrorLogs.length} warn/error log(s) — phase: after_initial_response`
		);
		// Save ALL console logs (not just warn/error) together with the warn/error entries
		// so there is context for debugging.
		const artifactsDir = path.resolve(process.cwd(), 'artifacts');
		fs.mkdirSync(artifactsDir, { recursive: true });
		const allLogsPath = path.join(artifactsDir, `console-all-logs-${chatId}-after-response.txt`);
		fs.writeFileSync(allLogsPath, consoleLogs.join('\n'), 'utf8');
		logChatCheckpoint(`All console logs saved to ${allLogsPath}`);
		saveWarnErrorLogs(chatId, 'after_initial_response');
	} else {
		logChatCheckpoint('No console warnings/errors during message send phase. Skipping log save.');
	}

	// =========================================================================
	// PHASE 3: Client-side data check via window.inspectChat
	// =========================================================================
	logChatCheckpoint('Phase 3: Inspecting client-side data via window.inspectChat...');
	const inspectResult = await inspectChatClientSide(page, chatId);
	if (inspectResult) {
		if (inspectResult.error) {
			logChatCheckpoint(`inspectChat error: ${inspectResult.error}`);
		} else {
			const rawReport = inspectResult.raw as string;
			logChatCheckpoint('window.inspectChat result (truncated):');
			// Log first 1000 chars to keep output readable
			console.log(rawReport?.substring(0, 1000));

			// Assert that the report contains key indicators of a valid chat
			expect(rawReport).toContain(chatId);
			// The inspectChat report uses [assistant] and [user     ] labels (not "role:" keys).
			// Count message role entries by matching those labels.
			const messageMatches = (rawReport.match(/\[(assistant|user\s*)\]/g) || []).length;
			logChatCheckpoint(`Message count in inspectChat report: ${messageMatches}`);
			expect(messageMatches).toBeGreaterThanOrEqual(2);
		}
	} else {
		logChatCheckpoint('window.inspectChat not available — skipping client-side data check.');
	}

	// =========================================================================
	// PHASE 4: Sidebar + message health check (initial state)
	// =========================================================================
	await assertChatDecryptedCorrectly(page, logChatCheckpoint, 'initial');

	// Verify no missing translations on the chat page
	await assertNoMissingTranslations(page);
	logChatCheckpoint('No missing translations detected.');

	await takeStepScreenshot(page, '05-initial-state-verified');

	// =========================================================================
	// PHASE 5: Tab reload — verify chat still loads without encryption errors
	// =========================================================================
	logChatCheckpoint('Phase 5: Reloading tab...');
	// Reset warn/error buffer so we only capture errors from the reload phase
	warnErrorLogs.length = 0;

	await page.reload();
	logChatCheckpoint('Page reloaded. Waiting for sync...');
	await page.waitForTimeout(5000); // Allow phased sync + decryption

	// Navigate directly to the test chat by URL (in case active chat changed after reload)
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.waitForTimeout(3000);

	logChatCheckpoint('Verifying chat after tab reload...');
	// Re-assert full decryption health
	await assertChatDecryptedCorrectly(page, logChatCheckpoint, 'after_reload');
	await takeStepScreenshot(page, '06-after-reload');

	// Run inspectChat again to confirm client-side data survived the reload
	logChatCheckpoint('Running inspectChat after reload...');
	const inspectAfterReload = await inspectChatClientSide(page, chatId);
	if (inspectAfterReload && !inspectAfterReload.error) {
		const rawReport = inspectAfterReload.raw as string;
		const messageMatches = (rawReport.match(/\[(assistant|user\s*)\]/g) || []).length;
		logChatCheckpoint(`Message count in inspectChat after reload: ${messageMatches}`);
		expect(messageMatches).toBeGreaterThanOrEqual(2);
	}

	// Save any warn/error logs from the reload phase
	if (warnErrorLogs.length > 0) {
		logChatCheckpoint(`Saving ${warnErrorLogs.length} warn/error log(s) — phase: after_reload`);
		const artifactsDir = path.resolve(process.cwd(), 'artifacts');
		const allLogsPath = path.join(artifactsDir, `console-all-logs-${chatId}-after-reload.txt`);
		fs.writeFileSync(allLogsPath, consoleLogs.join('\n'), 'utf8');
		logChatCheckpoint(`All console logs saved to ${allLogsPath}`);
		saveWarnErrorLogs(chatId, 'after_reload');
	} else {
		logChatCheckpoint('No console warnings/errors during reload phase.');
	}

	// =========================================================================
	// PHASE 6: Logout
	// =========================================================================
	logChatCheckpoint('Phase 6: Logging out...');
	// Reset warn/error buffer for the relogin phase
	warnErrorLogs.length = 0;

	// Open the settings menu (the gear/profile toggle button)
	const openSettingsBtn = page.getByRole('button', { name: /open settings menu/i });
	await expect(openSettingsBtn).toBeVisible({ timeout: 10000 });
	await openSettingsBtn.click();
	await page.waitForTimeout(500);

	// Click the Logout menu item (role=menuitem with text "Logout")
	const logoutItem = page.getByRole('menuitem', { name: /logout/i });
	await expect(logoutItem).toBeVisible({ timeout: 5000 });
	await logoutItem.click();
	logChatCheckpoint('Clicked Logout.');

	// After logout: the app stays on the same SPA page but shows the "Login / Sign up" button
	// URL hash changes to demo-for-everyone
	await page.waitForTimeout(3000);
	const loginSignupBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginSignupBtn).toBeVisible({ timeout: 15000 });
	logChatCheckpoint('Logout confirmed — "Login / Sign up" button visible.');
	await takeStepScreenshot(page, '07-logged-out');

	// =========================================================================
	// PHASE 7: Login again + navigate to the same chat
	// =========================================================================
	logChatCheckpoint('Phase 7: Logging in again...');
	await performLogin(page, logChatCheckpoint, takeStepScreenshot, '08');

	// Navigate directly to the test chat
	logChatCheckpoint(`Navigating to chat ${chatId} after re-login...`);
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.waitForTimeout(5000); // Allow phased sync + re-decryption of key + chat data

	await takeStepScreenshot(page, '09-after-relogin');

	logChatCheckpoint('Verifying chat after re-login...');
	await assertChatDecryptedCorrectly(page, logChatCheckpoint, 'after_relogin');

	// Run inspectChat a third time to confirm data is intact after full logout/login cycle
	logChatCheckpoint('Running inspectChat after re-login...');
	const inspectAfterRelogin = await inspectChatClientSide(page, chatId);
	if (inspectAfterRelogin && !inspectAfterRelogin.error) {
		const rawReport = inspectAfterRelogin.raw as string;
		const messageMatches = (rawReport.match(/\[(assistant|user\s*)\]/g) || []).length;
		logChatCheckpoint(`Message count in inspectChat after re-login: ${messageMatches}`);
		expect(messageMatches).toBeGreaterThanOrEqual(2);
	}

	// Verify no missing translations on the chat page after re-login
	await assertNoMissingTranslations(page);
	logChatCheckpoint('No missing translations after re-login.');

	// Save any warn/error logs from the relogin phase
	if (warnErrorLogs.length > 0) {
		logChatCheckpoint(`Saving ${warnErrorLogs.length} warn/error log(s) — phase: after_relogin`);
		const artifactsDir = path.resolve(process.cwd(), 'artifacts');
		const allLogsPath = path.join(artifactsDir, `console-all-logs-${chatId}-after-relogin.txt`);
		fs.writeFileSync(allLogsPath, consoleLogs.join('\n'), 'utf8');
		logChatCheckpoint(`All console logs saved to ${allLogsPath}`);
		saveWarnErrorLogs(chatId, 'after_relogin');
	} else {
		logChatCheckpoint('No console warnings/errors during re-login phase.');
	}

	await takeStepScreenshot(page, '10-relogin-state-verified');

	// =========================================================================
	// PHASE 8: Delete the chat via context menu
	// =========================================================================
	logChatCheckpoint('Phase 8: Deleting test chat...');

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible({ timeout: 10000 });

	// Right-click to open context menu
	await activeChatItem.click({ button: 'right' });
	await takeStepScreenshot(page, '11-context-menu-open');
	logChatCheckpoint('Opened chat context menu.');

	// Click delete (first click = confirm mode, second click = confirm deletion)
	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click();
	await takeStepScreenshot(page, '12-delete-confirm-mode');
	logChatCheckpoint('Clicked delete — now in confirm mode.');

	await deleteButton.click();
	logChatCheckpoint('Confirmed chat deletion.');

	// Verify chat is removed
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, '13-chat-deleted');
	logChatCheckpoint('Chat deleted successfully. Test complete.');
});
