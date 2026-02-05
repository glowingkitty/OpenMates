/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
const { test, expect } = require('@playwright/test');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter
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
		consoleLogs.slice(-30).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

/**
 * Shared chat opening test
 *
 * Tests that shared chat links redirect to the main app with the chat loaded
 * and display the correct content including:
 * - Chat title with correct icon and category colors
 * - User message with expected text
 * - Assistant response with expected text
 *
 * ARCHITECTURE:
 * The shared chat flow works as follows:
 * 1. User visits /share/chat/{chatId}#key={encryptedBlob}
 * 2. The share page extracts the chat encryption key from the URL fragment
 * 3. It fetches encrypted chat data from the API
 * 4. Decrypts and stores the chat in IndexedDB
 * 5. Redirects to the main app with the chat loaded
 */
test('opens shared chat and loads content correctly', async ({ page }: { page: any }) => {
	// Listen for console logs - helpful for debugging decryption issues
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	// Listen for network requests
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});

	// Listen for network responses
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	// Allow extra time for shared chat loading and decryption
	test.setTimeout(120000);

	// Setup logging and screenshots
	const logCheckpoint = createSignupLogger('SHARED_CHAT');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'shared-chat'
	});

	await archiveExistingScreenshots(logCheckpoint);

	// The shared chat URL with encryption key in the fragment
	// This is a test chat with known content about web app security
	const sharedChatUrl =
		'https://app.dev.openmates.org/share/chat/87f1da2f-1814-4a36-a375-c718fa946922#key=X4Tz9wamfp_uPngBF3Z_imlm7t9eelWvSwPauIpcAy8z8qHi9A0Nu4uS-ZhfKBdF2462Qc0gJQZFHINe0L_iqwCUfvtjsY7eDrAAVsEuQUaCmUo-KZK1PslohdOMfg_xRvKUbGW-lh1mi6NrCz7pOur8ojLhxuT-lfsHIoHMEQPHuFb6AsDW5s-ZGSdHcTsQp3ue&messageid=ffcc180d-a0aa-4fc0-9c44-be39064122b8';
	const expectedChatId = '87f1da2f-1814-4a36-a375-c718fa946922';

	logCheckpoint('Starting shared chat test', { chatId: expectedChatId });

	// Step 1: Navigate to the shared chat URL
	logCheckpoint('Navigating to shared chat URL...');
	await page.goto(sharedChatUrl);

	// Step 2: Wait for redirect to main app (should redirect to /#chat-id=...)
	// The shared chat page will redirect to the main app once loaded
	// The redirect happens very fast, so we don't take a screenshot until after
	try {
		await page.waitForURL(
			(url: URL) => {
				return url.hash.includes(`chat-id=${expectedChatId}`);
			},
			{ timeout: 60000 }
		);
		logCheckpoint('Successfully redirected to main app (via waitForURL)');
	} catch {
		// Sometimes the redirect happens before waitForURL starts monitoring
		// Check if we're already on the main app
		const currentUrl = page.url();
		if (currentUrl.includes(`chat-id=${expectedChatId}`)) {
			logCheckpoint('Already redirected to main app (redirect was fast)');
		} else {
			// Wait for URL to contain the chat ID using a poll
			await expect(async () => {
				const url = page.url();
				expect(url).toContain(`chat-id=${expectedChatId}`);
			}).toPass({ timeout: 30000 });
			logCheckpoint('Successfully redirected to main app (via polling)');
		}
	}

	await takeStepScreenshot(page, 'redirected-to-main-app');

	// Step 3: Wait for the chat history container to be visible
	await expect(page.locator('.chat-history-container')).toBeVisible({ timeout: 30000 });
	logCheckpoint('Chat history container visible');
	await takeStepScreenshot(page, 'chat-history-visible');

	// Step 4: Verify chat title appears in the sidebar
	// There may be multiple elements with the title (sidebar + active chat header)
	const chatTitle = page
		.locator('.chat-title')
		.filter({ hasText: 'Explain web app security essentials' })
		.first();
	await expect(chatTitle).toBeVisible({ timeout: 15000 });
	logCheckpoint('Chat title verified', { title: 'Explain web app security essentials' });
	await takeStepScreenshot(page, 'chat-title-visible');

	// Step 5: Find the specific chat item in the sidebar and verify its category icon and circle
	const chatItem = page
		.locator('.chat-with-profile')
		.filter({ hasText: 'Explain web app security essentials' })
		.first();
	await expect(chatItem).toBeVisible();

	// Verify the shield icon (security category) within this specific chat item
	const categoryIcon = chatItem.locator('.category-icon');
	await expect(categoryIcon).toBeVisible();
	const iconSvg = categoryIcon.locator('svg');
	await expect(iconSvg).toBeVisible();
	const iconPath = iconSvg.locator('path');
	await expect(iconPath).toBeVisible();
	logCheckpoint('Security category shield icon verified');

	// Verify the category circle has the correct gradient (security blue colors)
	const categoryCircle = chatItem.locator('.category-circle');
	await expect(categoryCircle).toBeVisible();
	const circleStyle = await categoryCircle.getAttribute('style');
	expect(circleStyle).toMatch(/linear-gradient.*rgb\(21.*93.*145\).*rgb\(66.*171.*244\)/);
	logCheckpoint('Security category gradient colors verified');
	await takeStepScreenshot(page, 'category-icon-verified');

	// Step 6: Wait for messages to be present and decrypt
	// Messages are rendered in .message-wrapper elements
	const userMessageWrapper = page.locator('.message-wrapper.user').first();
	const assistantMessageWrapper = page.locator('.message-wrapper.assistant').first();

	await expect(userMessageWrapper).toBeVisible({ timeout: 20000 });
	await expect(assistantMessageWrapper).toBeVisible({ timeout: 20000 });

	const userMessageCount = await page.locator('.message-wrapper.user').count();
	const assistantMessageCount = await page.locator('.message-wrapper.assistant').count();

	logCheckpoint('Messages loaded', {
		userCount: userMessageCount,
		assistantCount: assistantMessageCount
	});
	expect(userMessageCount).toBe(1);
	expect(assistantMessageCount).toBe(1);

	await takeStepScreenshot(page, 'messages-loaded');

	// Step 7: Wait for message decryption to complete
	// The content is rendered via TipTap's ProseMirror editor inside .read-only-message
	// We need to wait for the actual text content to appear
	logCheckpoint('Waiting for message content to decrypt and render...');

	// Wait for user message content to render inside ProseMirror
	const userMessageProseMirror = userMessageWrapper.locator('.read-only-message .ProseMirror');
	await expect(userMessageProseMirror).toBeVisible({ timeout: 15000 });

	// Wait for the actual text to appear (decryption complete)
	// Use a polling approach to wait for content
	await page.waitForFunction(
		([selector, expectedText]: [string, string]) => {
			const el = document.querySelector(selector);
			return el && el.textContent && el.textContent.includes(expectedText);
		},
		[
			'.message-wrapper.user .read-only-message .ProseMirror',
			'Explain web app security essentials'
		],
		{ timeout: 20000 }
	);

	const userMessageText = await userMessageProseMirror.textContent();
	logCheckpoint('User message content loaded', { content: userMessageText?.substring(0, 100) });
	expect(userMessageText).toContain('Explain web app security essentials');
	logCheckpoint('User message content verified');

	await takeStepScreenshot(page, 'user-message-decrypted');

	// Step 8: Wait for assistant message content to render
	const assistantMessageProseMirror = assistantMessageWrapper.locator(
		'.read-only-message .ProseMirror'
	);
	await expect(assistantMessageProseMirror).toBeVisible({ timeout: 15000 });

	// Wait for the actual text to appear (decryption complete)
	await page.waitForFunction(
		([selector, expectedText]: [string, string]) => {
			const el = document.querySelector(selector);
			return el && el.textContent && el.textContent.includes(expectedText);
		},
		[
			'.message-wrapper.assistant .read-only-message .ProseMirror',
			'Web application security is crucial'
		],
		{ timeout: 20000 }
	);

	const assistantMessageText = await assistantMessageProseMirror.textContent();
	logCheckpoint('Assistant message content loaded', {
		contentLength: assistantMessageText?.length
	});
	expect(assistantMessageText).toContain('Web application security is crucial');
	logCheckpoint('Assistant response content verified');

	await takeStepScreenshot(page, 'assistant-message-decrypted');

	// Step 9: Final verification and screenshot
	await takeStepScreenshot(page, 'test-complete');
	logCheckpoint('Shared chat test completed successfully');
});
