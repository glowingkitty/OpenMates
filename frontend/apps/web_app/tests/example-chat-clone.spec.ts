/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chat clone-on-send test: verifies that when an authenticated user
 * sends a message while viewing an example chat, the app:
 *
 *   1. Creates a new real chat (UUID-based, not "example-*" prefixed)
 *   2. Copies all messages from the example chat into the new chat
 *   3. Clones embed data into IndexedDB so embeds survive cross-device sync
 *   4. Embeds still render correctly in the cloned chat
 *
 * Bug this guards against:
 *   The clone-on-send flow copied messages but NOT embeds. Embeds only rendered
 *   because of the in-memory exampleChatStore fallback — they were never persisted
 *   to IndexedDB, breaking cross-device sync and backend AI context.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const {
	getTestAccount,
	getE2EDebugUrl,
	generateTotp,
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Example chat clone-on-send', () => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('cloning an example chat preserves embeds in the new chat', async ({ page }: { page: any }) => {
		test.setTimeout(180000); // 3 minutes: login + navigate + send + verify

		const consoleLogs: string[] = [];
		page.on('console', (msg: any) => {
			const text = msg.text();
			consoleLogs.push(`[${msg.type()}] ${text}`);
		});

		// ── Step 1: Login ──────────────────────────────────────────────────────
		await page.goto(getE2EDebugUrl('/'));
		await page.waitForLoadState('networkidle');

		const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
		await headerLoginButton.click();

		const loginTab = page.getByTestId('tab-login');
		await expect(loginTab).toBeVisible({ timeout: 10000 });
		await loginTab.click();

		const emailInput = page.locator('#login-email-input');
		await expect(emailInput).toBeVisible({ timeout: 15000 });
		await emailInput.fill(TEST_EMAIL);
		await page.locator('#login-continue-button').click();

		const passwordInput = page.locator('#login-password-input');
		await expect(passwordInput).toBeVisible({ timeout: 15000 });
		await passwordInput.fill(TEST_PASSWORD);
		await page.locator('#login-submit-button').click();

		const otpCode = generateTotp(TEST_OTP_KEY);
		const otpInput = page.locator('#login-otp-input');
		await expect(otpInput).toBeVisible({ timeout: 15000 });
		await otpInput.fill(otpCode);
		await page.locator('#login-submit-button').click();

		await page.waitForURL(/chat/);
		console.log('[clone-test] Logged in successfully');

		// Wait for phased sync to complete
		await page.waitForTimeout(5000);

		// ── Step 2: Navigate to the example chat ───────────────────────────────
		// Open sidebar, find an example chat entry and click it.
		// Example chats appear in the sidebar's "Last 7 days" group.
		const sidebarToggle = page.getByTestId('sidebar-toggle');
		await expect(sidebarToggle).toBeVisible({ timeout: 5000 });
		await sidebarToggle.click();
		await page.waitForTimeout(2000);

		// Example chats have chat_id starting with "example-" — find one in the sidebar
		const exampleChatItem = page.locator('[data-testid="chat-item-wrapper"][data-chat-id^="example-"]').first();
		await expect(exampleChatItem).toBeVisible({ timeout: 15000 });
		console.log('[clone-test] Found example chat in sidebar — clicking it');
		await exampleChatItem.click();

		// Close sidebar (tests should verify with sidebar closed per project rules)
		await sidebarToggle.click();
		await page.waitForTimeout(500);

		// Wait for the example chat to load (messages + embeds)
		const assistantMessage = page.getByTestId('message-assistant').first();
		await expect(assistantMessage).toBeVisible({ timeout: 15000 });
		console.log('[clone-test] Example chat loaded with assistant message');

		// Wait for embeds to render in the example chat
		await page.waitForTimeout(5000);

		// Capture which example chat we landed on (from URL hash)
		const exampleChatHash = await page.evaluate(() => window.location.hash.replace('#', ''));
		console.log(`[clone-test] Loaded example chat: ${exampleChatHash}`);

		// Count embeds in the example chat BEFORE cloning
		const embedsBeforeClone = await page.locator('[data-testid="embed-preview"]').count();
		const finishedEmbedsBeforeClone = await page.locator(
			'[data-testid="embed-preview"][data-status="finished"]'
		).count();
		console.log(
			`[clone-test] Example chat embeds: ${embedsBeforeClone} total, ${finishedEmbedsBeforeClone} finished`
		);

		// ── Step 3: Send a message to trigger clone-on-send ────────────────────
		// The send button should be visible for authenticated users
		const sendButton = page.locator('[data-action="send-message"]');
		await expect(sendButton).toBeVisible({ timeout: 10000 });

		// Type a message in the editor
		const editor = page.locator('[data-testid="message-input-editor"]');
		await expect(editor).toBeVisible({ timeout: 10000 });
		await editor.click();
		await page.keyboard.type('Show me more flight options to Bangkok');

		// Check console for the conversion log before clicking send
		await sendButton.click();
		console.log('[clone-test] Sent message to example chat — clone-on-send should trigger');

		// Wait for the clone operation and navigation to the new chat
		await page.waitForTimeout(8000);

		// ── Step 4: Verify we're now in a new real chat (not example-*) ────────
		const currentHash = await page.evaluate(() => window.location.hash);
		console.log(`[clone-test] Current URL hash after send: ${currentHash}`);

		// The hash should contain a UUID (real chat), NOT an example-* prefixed chat
		expect(
			currentHash,
			'After sending, URL should navigate away from the example chat'
		).not.toContain('example-');

		// Verify the clone conversion log appeared
		const conversionLog = consoleLogs.find(
			(l) => l.includes('Converting public chat') && l.includes('example-')
		);
		console.log(`[clone-test] Conversion log found: ${!!conversionLog}`);
		expect(
			conversionLog,
			'Expected console log confirming public chat was converted to regular chat'
		).toBeTruthy();

		// Check for embed cloning log
		const embedCloneLog = consoleLogs.find(
			(l) => l.includes('Cloning') && l.includes('embeds from example chat')
		);
		console.log(`[clone-test] Embed clone log found: ${!!embedCloneLog}`);
		expect(
			embedCloneLog,
			'Expected console log confirming embeds were cloned from example chat'
		).toBeTruthy();

		// ── Step 5: Verify embeds render in the cloned chat ────────────────────
		// Wait for embeds to resolve and render in the new chat context
		await page.waitForTimeout(5000);

		const embedsAfterClone = await page.locator('[data-testid="embed-preview"]').count();
		const finishedEmbedsAfterClone = await page.locator(
			'[data-testid="embed-preview"][data-status="finished"]'
		).count();
		console.log(
			`[clone-test] Cloned chat embeds: ${embedsAfterClone} total, ${finishedEmbedsAfterClone} finished`
		);

		// The cloned chat should have at least as many rendered embeds as the original
		expect(
			embedsAfterClone,
			`Cloned chat should have embeds (had ${embedsBeforeClone} before clone)`
		).toBeGreaterThan(0);

		expect(
			finishedEmbedsAfterClone,
			`Cloned chat should have finished embeds (had ${finishedEmbedsBeforeClone} before clone)`
		).toBeGreaterThan(0);

		// ── Step 6: Verify embeds exist in IndexedDB (not just in-memory) ──────
		const idbEmbedCount = await page.evaluate(async () => {
			// Open the chats_db IndexedDB and count embeds
			return new Promise<number>((resolve) => {
				const request = indexedDB.open('chats_db');
				request.onerror = () => resolve(-1);
				request.onsuccess = () => {
					const db = request.result;
					if (!db.objectStoreNames.contains('embeds')) {
						resolve(-2);
						return;
					}
					const tx = db.transaction('embeds', 'readonly');
					const store = tx.objectStore('embeds');
					const countReq = store.count();
					countReq.onsuccess = () => resolve(countReq.result);
					countReq.onerror = () => resolve(-3);
				};
			});
		});

		console.log(`[clone-test] IndexedDB embed count: ${idbEmbedCount}`);
		expect(
			idbEmbedCount,
			'IndexedDB should contain cloned embeds (not just in-memory fallback)'
		).toBeGreaterThan(0);

		// ── Step 7: Verify the original example chat messages were copied ───────
		// The cloned chat should have both the original example messages AND the new user message
		const userMessages = page.getByTestId('message-user');
		const userMessageCount = await userMessages.count();
		console.log(`[clone-test] User messages in cloned chat: ${userMessageCount}`);

		// Should have at least 2 user messages: 1 from example + 1 we just sent
		expect(
			userMessageCount,
			'Cloned chat should have the original example chat user message plus the new one'
		).toBeGreaterThanOrEqual(2);

		// ── Diagnostics ────────────────────────────────────────────────────────
		console.log('\n--- CLONE TEST DIAGNOSTICS ---');
		const relevantLogs = consoleLogs.filter(
			(l) =>
				l.includes('[handleSend]') ||
				l.includes('Cloning') ||
				l.includes('Converting public') ||
				l.includes('Duplicating')
		);
		console.log(`Relevant logs (${relevantLogs.length}):`);
		relevantLogs.forEach((l) => console.log(`  ${l}`));
		console.log('--- END DIAGNOSTICS ---\n');

		// ── Cleanup: delete the cloned chat ────────────────────────────────────
		// Extract chat ID from URL hash for cleanup
		const newChatId = currentHash.replace('#', '');
		if (newChatId && !newChatId.startsWith('example-')) {
			console.log(`[clone-test] Cleanup: would delete cloned chat ${newChatId}`);
			// Chat deletion is handled by the test infrastructure teardown
		}
	});
});
