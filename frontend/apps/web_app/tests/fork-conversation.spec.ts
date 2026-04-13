/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');

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
		consoleLogs.slice(-20).forEach((log) => console.log(log));

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

/**
 * Fork Conversation test: login, send two messages, fork after the first,
 * then verify the forked chat contains the first message but not the second.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test('forks a conversation after the first message', async ({ page }: { page: any }) => {
	// Listen for console logs
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	// Listen for network requests and responses
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	// Fork test involves 2 AI responses + fork operation — allow generous time.
	test.setTimeout(180000);

	const log = createSignupLogger('FORK_FLOW');
	const screenshot = createStepScreenshotter(log);

	// Pre-test skip checks
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(log);

	log('Starting fork conversation test.', { email: TEST_EMAIL });

	// ── 1. Navigate to home ──────────────────────────────────────────────────
	await page.goto(getE2EDebugUrl('/'));
	await screenshot(page, 'home');

	// ── 2. Open login dialog ─────────────────────────────────────────────────
	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();
	await screenshot(page, 'login-dialog');

	// Click Login tab to switch from signup to login view
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	// ── 3. Enter email ───────────────────────────────────────────────────────
	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	log('Entered email and clicked continue.');

	// ── 4. Enter password ────────────────────────────────────────────────────
	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await screenshot(page, 'password-entered');

	// Submit password first — OTP field appears after backend confirms 2FA required
	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();

	// ── 5. Handle 2FA OTP ────────────────────────────────────────────────────
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });
	await otpInput.fill(otpCode);
	log('Generated and entered OTP.');
	await screenshot(page, 'otp-entered');

	// ── 6. Submit login ──────────────────────────────────────────────────────
	await submitLoginButton.click();
	log('Submitted login form.');

	// ── 7. Wait for redirect and open a fresh chat ───────────────────────────
	await page.waitForURL(/chat/);
	log('Redirected to chat. Waiting 5s for initial load...');
	await page.waitForTimeout(5000);

	// Click the new-chat icon to get a clean slate
	const newChatIcon = page.getByTestId('new-chat-button');
	if (await newChatIcon.isVisible()) {
		log('Clicking new-chat icon.');
		await newChatIcon.click();
		await page.waitForTimeout(2000);
	}
	await screenshot(page, 'fresh-chat');

	// ── 8. Send first message ────────────────────────────────────────────────
	// Short, deterministic prompt so the response is predictable and quick.
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(withMockMarker('Reply with the single word: alpha', 'fork_conversation_turn1'));
	log('Typed first message.');
	await screenshot(page, 'first-message-typed');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	log('Sent first message.');

	// Wait for chat ID in URL (assigned after first message)
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });

	// Capture the original chat URL so we can navigate back to it during cleanup
	const originalChatUrl = page.url();
	log(`Original chat URL: ${originalChatUrl}`);

	// ── 9. Wait for first AI response containing "alpha" ────────────────────
	log('Waiting for first AI response...');
	const assistantMessages = page.getByTestId('message-assistant');
	await expect(assistantMessages.last()).toContainText('alpha', { timeout: 45000 });
	log('First response confirmed: contains "alpha".');
	await screenshot(page, 'first-response');

	// ── 10. Send second message ──────────────────────────────────────────────
	await messageEditor.click();
	await page.keyboard.type(withMockMarker('Reply with the single word: beta', 'fork_conversation_turn2'));
	log('Typed second message.');

	await sendButton.click();
	log('Sent second message.');

	// ── 11. Wait for second AI response containing "beta" ───────────────────
	log('Waiting for second AI response...');
	await expect(assistantMessages.last()).toContainText('beta', { timeout: 45000 });
	log('Second response confirmed: contains "beta".');

	// Wait for the AI to FINISH streaming before attempting the right-click.
	// If we right-click while the response is still streaming, Svelte's
	// continuous DOM updates can discard the context menu state.
	// The stop-processing-button disappears once the AI finishes; wait for that.
	log('Waiting for AI to finish streaming (stop-processing-button to disappear)...');
	const stopButton = page.getByTestId('stop-processing-button');
	// First check if it's currently visible; only wait for disappearance if so
	if (await stopButton.isVisible()) {
		await expect(stopButton).not.toBeVisible({ timeout: 30000 });
		log('Stop button disappeared — AI finished streaming.');
	} else {
		log('Stop button already gone — AI finished before check.');
	}
	// Extra buffer to ensure all Svelte state updates have settled
	await page.waitForTimeout(1500);
	log('AI response fully settled.');
	await screenshot(page, 'second-response');

	// ── 12. Right-click first user message to open context menu ─────────────
	// The fork context menu is triggered by right-clicking .user-message-content.
	// We want to fork AFTER the first user message (the "alpha" one), so we
	// grab the first user-message-content element.
	//
	// IMPORTANT: After 2 AI responses the page is scrolled to the bottom.
	// We must scroll the first user message into view before right-clicking,
	// otherwise Playwright cannot interact with an off-screen element.
	// We also wait briefly after scrolling so Svelte can re-render any
	// lazy-loaded content (e.g. decrypted message data) before the click.
	log('Scrolling first user message into view for right-click...');
	const userMessageContents = page.getByTestId('user-message-content');
	const firstUserMessage = userMessageContents.first();
	await expect(firstUserMessage).toBeVisible({ timeout: 10000 });
	await firstUserMessage.scrollIntoViewIfNeeded();
	await page.waitForTimeout(1000); // Allow decrypt/render after scroll

	log('Right-clicking the first user message to open context menu...');
	await firstUserMessage.click({ button: 'right' });
	await screenshot(page, 'context-menu-open');

	// ── 13. Click "Fork Conversation" in context menu ────────────────────────
	// The menu is rendered at document.body level (portal pattern).
	// It is marked .menu-container.show once visible.
	const forkMenuItem = page.getByTestId('chat-context-fork');
	await expect(forkMenuItem).toBeVisible({ timeout: 8000 });
	log('Fork menu item visible, clicking...');
	await forkMenuItem.click();
	await screenshot(page, 'fork-menu-clicked');

	// ── 14. Verify fork settings panel opens ────────────────────────────────
	const forkContainer = page.getByTestId('fork-container');
	await expect(forkContainer).toBeVisible({ timeout: 5000 });
	log('Fork settings panel is visible.');

	// Verify the fork name input is pre-filled (non-empty)
	const forkInput = page.getByTestId('fork-input');
	await expect(forkInput).toBeVisible();
	const forkNameValue = await forkInput.inputValue();
	expect(forkNameValue.trim()).not.toBe('');
	log(`Fork name pre-filled: "${forkNameValue}"`);
	await screenshot(page, 'fork-panel-open');

	// ── 15. Click the Fork button ────────────────────────────────────────────
	const forkButton = page.getByTestId('fork-button');
	await expect(forkButton).toBeEnabled();
	await forkButton.click();
	log('Fork button clicked.');
	await screenshot(page, 'fork-started');

	// ── 16. Wait for the forked chat to appear in the sidebar ────────────────
	// After forking, the new chat should appear at the top of the chat list.
	// We capture the sidebar count BEFORE the fork panel closes, then wait
	// for it to grow by 1. This is robust even with an account that already
	// has many existing chats.
	//
	// Note: the fork panel closes after clicking Fork, the settings panel
	// dismisses, and then the new chat appears at the top of the sidebar.
	log('Waiting for forked chat to appear in sidebar...');
	const chatItems = page.getByTestId('chat-item-wrapper');
	const countBefore = await chatItems.count();
	log(`Sidebar chat count before fork completion: ${countBefore}`);

	// Wait up to 30s for the sidebar to have one more chat than before
	await expect(async () => {
		const countNow = await chatItems.count();
		expect(countNow).toBeGreaterThan(countBefore);
	}).toPass({ timeout: 30000, intervals: [1000] });

	const countAfter = await chatItems.count();
	log(`Sidebar chat count after fork: ${countAfter} (grew by ${countAfter - countBefore}).`);
	await screenshot(page, 'fork-complete-sidebar');

	// ── 17. Open the forked chat (first item = most recent = the fork) ───────
	const firstChatItem = chatItems.first();
	await expect(firstChatItem).toBeVisible();
	await firstChatItem.click();
	log('Opened the forked chat.');
	await page.waitForTimeout(2000);
	await screenshot(page, 'forked-chat-opened');

	// Capture the forked chat URL for cleanup
	const forkedChatUrl = page.url();
	log(`Forked chat URL: ${forkedChatUrl}`);

	// ── 18. Verify forked chat contains "alpha" but NOT "beta" ───────────────
	// The fork was created after the first user message ("alpha"), so:
	// - The forked chat should contain "alpha" in an assistant response
	// - The forked chat should NOT contain "beta" (that was message 2 in original)
	log('Verifying forked chat message content...');
	const allMessages = page.getByTestId('message-wrapper');
	await expect(allMessages.first()).toBeVisible({ timeout: 10000 });

	// Check that "alpha" appears somewhere in the chat (from assistant response)
	const chatContent = page.getByTestId('mate-message-content');
	await expect(chatContent.first()).toContainText('alpha', { timeout: 15000 });
	log('Confirmed "alpha" is present in forked chat.');

	// Verify "beta" is NOT present (fork was before the second message)
	const betaMessage = page.getByTestId('mate-message-content').filter({ hasText: 'beta' });
	await expect(betaMessage).toHaveCount(0);
	log('Confirmed "beta" is absent from forked chat (correct fork point).');
	await screenshot(page, 'forked-chat-verified');

	// ── 19. Check for missing translations ───────────────────────────────────
	// NOTE: settings.fork i18n key is part of this commit — it will pass once
	// this commit is deployed. If the old build is running, this will detect
	// the [T:settings.fork] token and fail, which is the correct behaviour.
	await assertNoMissingTranslations(page);
	log('No missing translations detected.');

	// ── 20. Clean up: delete forked chat ────────────────────────────────────
	// The forked chat is currently active. Right-click the active item.
	log('Cleaning up: deleting forked chat...');
	const activeForkItem = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeForkItem).toBeVisible();
	await activeForkItem.scrollIntoViewIfNeeded();
	await activeForkItem.click({ button: 'right' });
	const deleteBtn = page.getByTestId('chat-context-delete');
	await expect(deleteBtn).toBeVisible({ timeout: 5000 });
	await deleteBtn.click(); // First click: show confirm state
	await expect(deleteBtn).toContainText(/confirm/i, { timeout: 3000 });
	await deleteBtn.click(); // Second click: confirm deletion
	await expect(activeForkItem).not.toBeVisible({ timeout: 10000 });
	log('Forked chat deleted.');

	// ── 21. Clean up: delete original chat ──────────────────────────────────
	// Navigate back to the original chat URL and delete it.
	log('Cleaning up: navigating back to original chat...');
	await page.goto(originalChatUrl);
	await page.waitForTimeout(2000);

	const activeOriginalItem = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeOriginalItem).toBeVisible({ timeout: 10000 });
	await activeOriginalItem.scrollIntoViewIfNeeded();
	await activeOriginalItem.click({ button: 'right' });
	const deleteBtnOriginal = page.getByTestId('chat-context-delete');
	await expect(deleteBtnOriginal).toBeVisible({ timeout: 5000 });
	await deleteBtnOriginal.click(); // First click: show confirm state
	await expect(deleteBtnOriginal).toContainText(/confirm/i, { timeout: 3000 });
	await deleteBtnOriginal.click(); // Second click: confirm deletion
	await expect(activeOriginalItem).not.toBeVisible({ timeout: 10000 });
	log('Original chat deleted.');
	await screenshot(page, 'cleanup-complete');

	log('Fork conversation test passed successfully.');
});
