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
		consoleLogs.slice(-20).forEach((log: string) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp
} = require('./signup-flow-helpers');

/**
 * Chat scroll & streaming behavior test:
 * Validates the ChatGPT-like UX after sending a message:
 *
 * 1. User message scrolls to the top of the chat area
 * 2. AI loading indicator (pulsing dots) appears in the assistant message placeholder
 * 3. Assistant response streams in without disrupting scroll position
 * 4. Mate profile image and name remain stable during streaming
 * 5. User can scroll up during streaming without being interrupted
 *
 * REQUIRED ENV VARS (same as chat-flow.spec.ts):
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('scroll and streaming behavior after sending a message', async ({ page }: { page: any }) => {
	// Listen for console logs
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	// Listen for network activity
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(120000);

	const logCheckpoint = createSignupLogger('SCROLL_STREAM');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	// Pre-test skip checks
	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);

	logCheckpoint('Starting chat scroll & streaming test.', { email: TEST_EMAIL });

	// ───────────────────────────────────────────────────
	// 1. Login flow (reused from chat-flow.spec.ts)
	// ───────────────────────────────────────────────────
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);

	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();

	await page.waitForURL(/chat/);
	await page.waitForTimeout(5000);

	// Start a fresh chat
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible()) {
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}

	logCheckpoint('Logged in and ready for scroll test.');
	await takeStepScreenshot(page, 'ready-for-scroll-test');

	// ───────────────────────────────────────────────────
	// 2. Get the chat container reference for scroll measurements
	// ───────────────────────────────────────────────────
	const chatContainer = page.locator('.chat-history-container');
	await expect(chatContainer).toBeVisible();

	// ───────────────────────────────────────────────────
	// 3. Type and send a message
	// ───────────────────────────────────────────────────
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type('What is the capital of France? Please explain in detail.');
	await takeStepScreenshot(page, 'message-typed');

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();

	// Record scroll position BEFORE sending
	const scrollBefore = await chatContainer.evaluate((el: HTMLElement) => ({
		scrollTop: el.scrollTop,
		scrollHeight: el.scrollHeight,
		clientHeight: el.clientHeight
	}));
	logCheckpoint('Scroll before send', scrollBefore);

	await sendButton.click();
	logCheckpoint('Message sent.');
	await takeStepScreenshot(page, 'message-sent');

	// ───────────────────────────────────────────────────
	// 4. Verify user message scrolls to the top of the chat area
	//    After sending, the bottom of the user message should be near the top
	//    of the viewport (within ~100px from top), leaving space below for the response.
	// ───────────────────────────────────────────────────
	logCheckpoint('Waiting for user message to appear and scroll...');

	const userMessage = page.locator('.message-wrapper.user').last();
	await expect(userMessage).toBeVisible({ timeout: 10000 });

	// Wait for the scroll animation to complete (the effect uses tick() + 350ms + smooth scroll)
	await page.waitForTimeout(1500);

	await takeStepScreenshot(page, 'after-scroll');

	// Check that user message is positioned near the top of the chat container
	const userMessagePosition = await page.evaluate(() => {
		const container = document.querySelector('.chat-history-container') as HTMLElement;
		const userMsg = Array.from(
			container.querySelectorAll('.message-wrapper.user')
		).pop() as HTMLElement;
		if (!container || !userMsg) return null;

		const containerRect = container.getBoundingClientRect();
		const msgRect = userMsg.getBoundingClientRect();

		return {
			// How far the bottom of the user message is from the top of the container
			bottomFromTop: msgRect.bottom - containerRect.top,
			// Container dimensions
			containerHeight: containerRect.height,
			// Message dimensions
			messageHeight: msgRect.height,
			// The user message bottom should be in the upper portion of the container
			isInUpperHalf: msgRect.bottom - containerRect.top < containerRect.height / 2
		};
	});

	logCheckpoint('User message position after scroll', userMessagePosition);

	// The bottom of the user message should be in the upper half of the chat container
	// This confirms the ChatGPT-style scroll worked: user message at top, space below for response
	expect(userMessagePosition).not.toBeNull();
	if (userMessagePosition) {
		expect(userMessagePosition.isInUpperHalf).toBe(true);
		logCheckpoint('PASS: User message is in upper half of chat area.');
	}

	// ───────────────────────────────────────────────────
	// 5. Check for AI loading indicator (pulsing dots)
	//    This appears as a placeholder assistant message during "Processing..."
	// ───────────────────────────────────────────────────
	logCheckpoint('Checking for AI loading indicator...');

	// The loading indicator may appear briefly before streaming starts.
	// We check for either the loading dots OR the assistant message wrapper appearing.
	const aiLoadingOrAssistant = page.locator('.ai-loading-indicator, .message-wrapper.assistant');
	await expect(aiLoadingOrAssistant.first()).toBeVisible({ timeout: 30000 });

	const hasLoadingIndicator = await page
		.locator('.ai-loading-indicator')
		.isVisible()
		.catch(() => false);
	if (hasLoadingIndicator) {
		logCheckpoint('PASS: AI loading indicator (pulsing dots) is visible.');
		await takeStepScreenshot(page, 'ai-loading-indicator');
	} else {
		logCheckpoint('NOTE: AI loading indicator was not captured (streaming started quickly).');
	}

	// ───────────────────────────────────────────────────
	// 6. Wait for streaming to start and verify scroll stability
	//    During streaming, the scroll position should stay stable.
	//    The assistant response grows downward into the empty space.
	// ───────────────────────────────────────────────────
	logCheckpoint('Waiting for assistant response to start streaming...');

	const assistantMessage = page.locator('.message-wrapper.assistant').last();
	await expect(assistantMessage).toBeVisible({ timeout: 45000 });

	// Record scroll position when streaming starts
	const scrollAtStreamStart = await chatContainer.evaluate((el: HTMLElement) => el.scrollTop);
	logCheckpoint('Scroll position at stream start', { scrollTop: scrollAtStreamStart });

	await takeStepScreenshot(page, 'streaming-started');

	// Wait for some content to stream in (multiple chunks)
	await page.waitForTimeout(3000);

	// Record scroll position after some streaming
	const scrollAfterStreaming = await chatContainer.evaluate((el: HTMLElement) => el.scrollTop);
	logCheckpoint('Scroll position after streaming', { scrollTop: scrollAfterStreaming });

	// Scroll position should be stable (not jumping around).
	// Allow a small tolerance for the spacer shrinking smoothly.
	const scrollDrift = Math.abs(scrollAfterStreaming - scrollAtStreamStart);
	logCheckpoint(`Scroll drift during streaming: ${scrollDrift}px`);
	// The scroll position should not jump significantly (< 50px drift is acceptable
	// since the spacer may cause minor adjustments)
	expect(scrollDrift).toBeLessThan(50);
	logCheckpoint('PASS: Scroll position is stable during streaming.');

	await takeStepScreenshot(page, 'streaming-in-progress');

	// ───────────────────────────────────────────────────
	// 7. Verify mate profile image and name remain stable
	//    The .mate-profile and .chat-mate-name elements should maintain
	//    consistent position throughout streaming.
	// ───────────────────────────────────────────────────
	const mateProfile = assistantMessage.locator('.mate-profile');
	const mateName = assistantMessage.locator('.chat-mate-name');

	const profilePosBefore = await mateProfile.boundingBox();
	const namePosBefore = await mateName.boundingBox();

	// Wait for more streaming content
	await page.waitForTimeout(2000);

	const profilePosAfter = await mateProfile.boundingBox();
	const namePosAfter = await mateName.boundingBox();

	if (profilePosBefore && profilePosAfter) {
		const profileYDrift = Math.abs(profilePosAfter.y - profilePosBefore.y);
		logCheckpoint(`Mate profile Y drift: ${profileYDrift}px`);
		// Profile image position should be completely stable during streaming
		expect(profileYDrift).toBeLessThan(5);
		logCheckpoint('PASS: Mate profile image position is stable during streaming.');
	}

	if (namePosBefore && namePosAfter) {
		const nameYDrift = Math.abs(namePosAfter.y - namePosBefore.y);
		logCheckpoint(`Mate name Y drift: ${nameYDrift}px`);
		expect(nameYDrift).toBeLessThan(5);
		logCheckpoint('PASS: Mate name position is stable during streaming.');
	}

	// ───────────────────────────────────────────────────
	// 8. Test user scroll-up during streaming (should not be interrupted)
	// ───────────────────────────────────────────────────
	logCheckpoint('Testing manual scroll during streaming...');

	// Scroll up manually
	await chatContainer.evaluate((el: HTMLElement) => {
		el.scrollTo({ top: 0, behavior: 'instant' });
	});
	await page.waitForTimeout(500);

	const scrollAfterManualScroll = await chatContainer.evaluate((el: HTMLElement) => el.scrollTop);
	logCheckpoint('Scroll position after manual scroll up', { scrollTop: scrollAfterManualScroll });

	// Wait a bit and verify scroll position stays where user put it
	await page.waitForTimeout(2000);

	const scrollAfterWait = await chatContainer.evaluate((el: HTMLElement) => el.scrollTop);
	const manualScrollDrift = Math.abs(scrollAfterWait - scrollAfterManualScroll);
	logCheckpoint(`Manual scroll drift after wait: ${manualScrollDrift}px`);

	// Scroll position should stay where the user put it, not jump back down
	expect(manualScrollDrift).toBeLessThan(30);
	logCheckpoint('PASS: User scroll position preserved during streaming.');

	await takeStepScreenshot(page, 'manual-scroll-preserved');

	// ───────────────────────────────────────────────────
	// 9. Wait for complete response and verify final state
	// ───────────────────────────────────────────────────
	logCheckpoint('Waiting for complete assistant response...');

	// Wait for the response to contain "Paris" (should be the answer about France's capital)
	await expect(assistantMessage).toContainText('Paris', { timeout: 45000 });
	logCheckpoint('PASS: Assistant response contains expected answer.');

	await takeStepScreenshot(page, 'response-complete');

	// Verify the mate-message-content bubble has proper dimensions
	const messageContent = assistantMessage.locator('.mate-message-content');
	const contentBox = await messageContent.boundingBox();
	if (contentBox) {
		logCheckpoint('Assistant message content dimensions', {
			width: contentBox.width,
			height: contentBox.height
		});
		// Content should have reasonable dimensions (not collapsed or infinitely tall)
		expect(contentBox.width).toBeGreaterThan(100);
		expect(contentBox.height).toBeGreaterThan(20);
	}

	// ───────────────────────────────────────────────────
	// 10. Cleanup: Delete the chat
	// ───────────────────────────────────────────────────
	logCheckpoint('Cleaning up: deleting test chat...');

	// Ensure sidebar is open
	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible();

	// Right-click to open context menu
	await activeChatItem.click({ button: 'right' });
	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click(); // First click: enter confirm mode
	await deleteButton.click(); // Second click: confirm deletion

	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'chat-deleted');
	logCheckpoint('Chat deleted successfully. Test complete.');
});
