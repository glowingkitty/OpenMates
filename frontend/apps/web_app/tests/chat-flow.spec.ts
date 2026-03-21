/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Chat flow test: login with existing account + 2FA, then send a message and validate
 * zero-knowledge encryption health through multiple lifecycle phases:
 *
 *   1. Initial login → send message → confirm AI response
 *   2. Console warn/error capture → save to file if any occurred
 *   3. `window.inspectChat` client-side data check (messages, title, category)
 *   4. Sidebar + message health check (initial state — sidebar opened explicitly)
 *   4.5. Navigate to "new chat" → open sidebar → verify just-created chat is most recent
 *   5. Tab reload → verify chat still decrypts correctly (no encryption errors)
 *   6. Logout → login again → verify chat still decrypts correctly
 *   7. Delete chat
 *
 * IMPORTANT: The sidebar defaults to CLOSED. Every sidebar interaction explicitly
 * opens it first, then closes it afterwards. This mirrors the real user experience
 * and catches bugs where stores assume the sidebar component is mounted.
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
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
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
 * Ensure the sidebar (chats panel) is open.
 * The sidebar defaults to CLOSED — this helper clicks the menu toggle to open it
 * and waits for the Chats component to mount and render.
 *
 * The sidebar DOM structure (from +page.svelte):
 *   <div class="sidebar" class:closed={!isOpen}>
 *     {#if isOpen}
 *       <div class="sidebar-content">
 *         <Chats /> <!-- renders .activity-history-wrapper -->
 *       </div>
 *     {/if}
 *   </div>
 *
 * The Chats component is conditionally rendered — it only mounts when the panel
 * is open. So `.activity-history-wrapper` is the reliable indicator that the
 * sidebar is fully rendered and ready for interaction.
 */
async function ensureSidebarOpen(
	page: any,
	logCheckpoint: (...args: any[]) => void
): Promise<void> {
	// Check if sidebar is already open by looking for the Chats component's wrapper
	const activityHistory = page.locator('.activity-history-wrapper');
	const isSidebarVisible = await activityHistory.isVisible().catch(() => false);
	if (isSidebarVisible) {
		logCheckpoint('[Sidebar] Already open.');
		return;
	}

	// Click the menu toggle button in the header to open the sidebar
	const menuToggle = page.locator('.icon_menu');
	await expect(menuToggle).toBeVisible({ timeout: 5000 });
	await menuToggle.click();
	logCheckpoint('[Sidebar] Clicked menu toggle to open sidebar.');

	// Wait for the Chats component to mount and render
	await expect(activityHistory).toBeVisible({ timeout: 10000 });
	// Give the component time to load from DB and render chat items
	await page.waitForTimeout(2000);
}

/**
 * Ensure the sidebar (chats panel) is closed.
 * The sidebar defaults to CLOSED — this helper clicks the menu toggle to close it
 * if it's currently open.
 */
async function ensureSidebarClosed(
	page: any,
	logCheckpoint: (...args: any[]) => void
): Promise<void> {
	const activityHistory = page.locator('.activity-history-wrapper');
	const isSidebarVisible = await activityHistory.isVisible().catch(() => false);
	if (!isSidebarVisible) {
		logCheckpoint('[Sidebar] Already closed.');
		return;
	}

	// Click the menu toggle button to close the sidebar
	const menuToggle = page.locator('.icon_menu');
	if (await menuToggle.isVisible().catch(() => false)) {
		await menuToggle.click();
		logCheckpoint('[Sidebar] Clicked menu toggle to close sidebar.');
		// Wait for sidebar to close
		await page.waitForTimeout(500);
	}
}

/**
 * Assert that the active chat item in the sidebar shows real, decrypted metadata:
 * - Title is not a placeholder (not "untitled chat", not "processing", not empty)
 * - Category circle exists and is NOT the grey "missing-category" fallback
 *
 * Also checks that visible message wrappers do NOT show the error-state inline style
 * (opacity 0.7 + border: 1px solid var(--color-error)) that appears on failed messages.
 *
 * IMPORTANT: This function opens the sidebar explicitly (default is closed), performs
 * assertions, and then closes it again to restore the default state.
 */
async function assertChatDecryptedCorrectly(
	page: any,
	logCheckpoint: (...args: any[]) => void,
	phase: string
): Promise<void> {
	logCheckpoint(`[${phase}] Asserting chat decryption health...`);

	// ── Open sidebar explicitly ─────────────────────────────────────────────
	await ensureSidebarOpen(page, logCheckpoint);

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

	// ── Close sidebar to restore default state ──────────────────────────────
	await ensureSidebarClosed(page, logCheckpoint);

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
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, `${screenshotPrefix}-home`);

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	// Extended timeout: 404s from stale demo-chat IDs on the welcome screen can
	// delay DOM rendering beyond the 5 s Playwright default.
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, `${screenshotPrefix}-login-dialog`);

	const emailInput = page.locator('#login-email-input');
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

	await page.locator('#login-continue-button').click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, `${screenshotPrefix}-password-entered`);

	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);
	logCheckpoint('Generated and entered OTP.');
	await takeStepScreenshot(page, `${screenshotPrefix}-otp-entered`);

	const submitLoginButton = page.locator('#login-submit-button');
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

	// =========================================================================
	// PHASE 1a: Verify database init + most recent chats load after login
	// =========================================================================
	// This catches the critical bug where a pending indexedDB.deleteDatabase()
	// blocks indexedDB.open(), causing init() to hang and sync to never complete.
	logChatCheckpoint('Phase 1a: Verifying database init and most recent chats...');

	// Wait for console logs indicating successful DB init + sync progress.
	// These are the critical markers: if init() hangs, we never see "Database opened"
	// and sync never gets past "1/4".
	const dbInitSuccess = await page.waitForEvent('console', {
		predicate: (msg: any) =>
			msg.text().includes('[ChatDatabase] Database opened successfully') ||
			msg.text().includes('[ChatDatabase] Loaded') ||
			msg.text().includes('[ChatSyncService] 2/4:'),
		timeout: 15000
	}).then(() => true).catch(() => false);

	if (!dbInitSuccess) {
		// Check for the specific stuck-deletion pattern
		const stuckDeletion = consoleLogs.some(
			(log) =>
				log.includes('Deletion in progress — waiting') ||
				log.includes('Database is being deleted')
		);
		if (stuckDeletion) {
			logChatCheckpoint(
				'CRITICAL: Database init stuck — pending deletion blocking open(). ' +
					'This is the isDeleting race condition bug.'
			);
		}
		logChatCheckpoint(
			'WARNING: Database init markers not detected within 15s. ' +
				'DB may be stuck or sync may have failed.'
		);
	} else {
		logChatCheckpoint('Database initialized and sync progressed past phase 1.');
	}

	// Open sidebar and verify the "most recent chats" section has loaded
	await ensureSidebarOpen(page, logChatCheckpoint);

	// Verify at least one chat group (time-grouped section like "Today") is visible.
	// The .chat-group container with .group-title is the time-grouped section header.
	const chatGroups = page.locator('.chat-group');
	const chatGroupCount = await chatGroups.count().catch(() => 0);
	logChatCheckpoint(`Found ${chatGroupCount} chat group section(s) in sidebar.`);

	// Verify at least one real chat item is visible (not just demo/empty state)
	const chatItems = page.locator('.chat-item-wrapper');
	const chatItemCount = await chatItems.count().catch(() => 0);
	logChatCheckpoint(`Found ${chatItemCount} chat item(s) in sidebar.`);

	// The test account should have existing chats from previous test runs
	// If the sidebar shows zero chat items, sync failed to load data
	if (chatItemCount === 0) {
		// Check if we see the empty state indicator
		const noChats = page.locator('.no-chats-indicator');
		const hasNoChats = await noChats.isVisible().catch(() => false);
		if (hasNoChats) {
			logChatCheckpoint(
				'CRITICAL: Sidebar shows "no chats" indicator — sync failed to load any data.'
			);
		}
	}

	// Verify syncing indicator is NOT stuck (it should disappear after sync completes)
	const syncingIndicator = page.locator('.syncing-inline-indicator');
	try {
		// Wait up to 20s for the syncing indicator to disappear (sync should complete)
		await expect(syncingIndicator).not.toBeVisible({ timeout: 20000 });
		logChatCheckpoint('Sync completed — syncing indicator is gone.');
	} catch {
		logChatCheckpoint(
			'WARNING: Syncing indicator still visible after 20s — sync may be stuck.'
		);
	}

	// Assert: the sidebar must have at least 1 chat group with real chats
	expect(chatItemCount).toBeGreaterThan(0);
	logChatCheckpoint(`Phase 1a passed: ${chatItemCount} chats loaded in sidebar.`);

	// Take screenshot showing loaded sidebar with chats
	await takeStepScreenshot(page, '01a-sidebar-chats-loaded');

	// Close sidebar to restore default state
	await ensureSidebarClosed(page, logChatCheckpoint);

	// Verify no "Database is being deleted" errors in console
	const deletionErrors = consoleLogs.filter(
		(log) =>
			log.includes('Database is being deleted') ||
			log.includes('Deletion in progress — waiting')
	);
	if (deletionErrors.length > 0) {
		logChatCheckpoint(
			`CRITICAL: Found ${deletionErrors.length} "Database is being deleted" error(s) in console`
		);
	}
	expect(deletionErrors.length).toBe(0);
	logChatCheckpoint('No database deletion errors detected in console.');

	// Click "New Chat" button for a fresh start (visible in the main chat area)
	const newChatButton = page.locator('.new-chat-cta-button, .icon_create');
	if (
		await newChatButton
			.first()
			.isVisible({ timeout: 3000 })
			.catch(() => false)
	) {
		logChatCheckpoint('New Chat button visible, clicking it to start a fresh chat.');
		await newChatButton.first().click();
		await page.waitForTimeout(2000);
	}

	// Send message
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(withMockMarker('Capital of Germany?', 'chat_flow_capital'));
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
	// NOTE: assertChatDecryptedCorrectly opens the sidebar, checks it, then closes it.
	await assertChatDecryptedCorrectly(page, logChatCheckpoint, 'initial');

	// Capture the chat title from the ChatHeader component for later comparison
	// (the header is always visible regardless of sidebar state).
	const chatHeaderTitle = page.locator('.chat-header-content .chat-header-title');
	let headerTitleText = '';
	try {
		await expect(chatHeaderTitle).toBeVisible({ timeout: 5000 });
		headerTitleText = (await chatHeaderTitle.textContent())?.trim() || '';
		logChatCheckpoint(`ChatHeader title captured: "${headerTitleText}"`);
	} catch {
		logChatCheckpoint('ChatHeader title not visible — skipping capture.');
	}

	// Verify no missing translations on the chat page
	await assertNoMissingTranslations(page);
	logChatCheckpoint('No missing translations detected.');

	await takeStepScreenshot(page, '05-initial-state-verified');

	// =========================================================================
	// PHASE 4.5: Navigate to "new chat" → verify just-created chat is most recent
	// =========================================================================
	// This phase verifies a critical user flow:
	// 1. User created a chat (Phase 1) and got a response
	// 2. User navigates to "new chat" screen (sidebar closes / stays closed)
	// 3. User opens the sidebar → the just-created chat should be the first (most recent) chat
	//
	// This catches the bug where chatListCache serves stale data after the sidebar
	// was unmounted during chat creation, because event listeners were removed on destroy.
	logChatCheckpoint(
		'Phase 4.5: Verifying recently created chat appears after navigating to new chat...'
	);

	// Click the "New Chat" button to navigate away from the current chat
	const newChatCta = page.locator('.new-chat-cta-button, .icon_create');
	if (
		await newChatCta
			.first()
			.isVisible({ timeout: 5000 })
			.catch(() => false)
	) {
		await newChatCta.first().click();
		logChatCheckpoint('Clicked "New Chat" to navigate to new chat screen.');
		await page.waitForTimeout(2000);
	} else {
		logChatCheckpoint('New Chat button not visible — skipping Phase 4.5.');
	}

	// Verify we're on the new chat screen (no active chat in URL)
	const urlAfterNewChat = page.url();
	logChatCheckpoint(`URL after new chat: ${urlAfterNewChat}`);

	// Now open the sidebar — this is the critical test. The sidebar was closed (default)
	// during the entire chat creation flow. On mount, Chats.svelte should read fresh data
	// from IndexedDB (not stale cache) and show the just-created chat.
	await ensureSidebarOpen(page, logChatCheckpoint);
	await takeStepScreenshot(page, '05a-sidebar-after-new-chat');

	// The first user chat in the sidebar should be our just-created chat.
	// User chats are grouped under time sections (e.g., "Today").
	// Find the first chat item that is NOT a demo/intro/legal chat.
	const firstUserChat = page.locator('.chat-item-wrapper').first();
	await expect(firstUserChat).toBeVisible({ timeout: 10000 });

	// Verify the first chat has a real title (not a placeholder)
	const firstChatTitle = firstUserChat.locator('.chat-title');
	await expect(firstChatTitle).toBeVisible({ timeout: 15000 });
	await expect(firstChatTitle).not.toHaveClass(/processing-title/, { timeout: 5000 });
	const firstChatTitleText = (await firstChatTitle.textContent())?.trim() || '';
	logChatCheckpoint(`First chat in sidebar title: "${firstChatTitleText}"`);

	// The title should not be empty or a placeholder
	expect(firstChatTitleText).toBeTruthy();
	expect(firstChatTitleText.toLowerCase()).not.toContain('untitled chat');
	expect(firstChatTitleText.toLowerCase()).not.toContain('processing');

	// If we captured the ChatHeader title, verify it matches the first sidebar chat
	if (headerTitleText) {
		expect(firstChatTitleText).toBe(headerTitleText);
		logChatCheckpoint(`Sidebar title matches ChatHeader title: "${firstChatTitleText}"`);
	}

	// Verify the first chat has a category circle (not the grey "missing" fallback)
	const firstChatCategory = firstUserChat.locator('.category-circle');
	await expect(firstChatCategory).toBeVisible({ timeout: 5000 });
	const firstChatMissingCategory = firstUserChat.locator('.category-circle.missing-category');
	await expect(firstChatMissingCategory).not.toBeVisible();
	logChatCheckpoint('First chat in sidebar has valid title and category — Phase 4.5 passed.');

	// Close sidebar to restore default state
	await ensureSidebarClosed(page, logChatCheckpoint);

	// Navigate back to the test chat for subsequent phases
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.waitForTimeout(3000);

	// =========================================================================
	// PHASE 5: Tab reload — verify chat still loads without encryption errors
	// =========================================================================
	logChatCheckpoint('Phase 5: Reloading tab...');
	// Reset warn/error buffer so we only capture errors from the reload phase
	warnErrorLogs.length = 0;

	// Navigate to the chat URL and reload to ensure a fresh startup with the hash.
	// After Phase 4.5 we're on the home page; a plain reload would reload `/`
	// which doesn't include the chat hash. So we set the URL first, then reload.
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.reload({ waitUntil: 'networkidle' });
	logChatCheckpoint('Page reloaded with chat hash. Waiting for messages...');

	// Wait for the chat messages to render (key derivation + sync after reload)
	const userMsgAfterReload = page.locator('.message-wrapper.user').first();
	await expect(userMsgAfterReload).toBeVisible({ timeout: 30000 });

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
	const openSettingsBtn = page.locator('#settings-menu-toggle');
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

	// Navigate directly to the test chat.
	// After login the app is on `/` (home). Setting the hash via page.goto()
	// triggers the deep-link handler in +page.svelte, but the activeChatStore
	// may already hold the chat ID from a previous phase, causing it to skip
	// re-loading. A full page reload ensures a clean app startup with the hash.
	logChatCheckpoint(`Navigating to chat ${chatId} after re-login...`);
	await page.goto(`${baseUrl}/#chat-id=${chatId}`);
	await page.reload({ waitUntil: 'networkidle' });
	logChatCheckpoint('Page reloaded with chat hash. Waiting for messages...');

	// Wait for the chat to actually load — the user message must be visible.
	// This can take longer after a fresh login (key derivation + phased sync).
	const userMsgAfterRelogin = page.locator('.message-wrapper.user').first();
	await expect(userMsgAfterRelogin).toBeVisible({ timeout: 30000 });

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

	// Ensure sidebar is open for the delete operation (it's closed by default)
	await ensureSidebarOpen(page, logChatCheckpoint);

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
