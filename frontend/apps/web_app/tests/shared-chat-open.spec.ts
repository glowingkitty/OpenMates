/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations
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
test('stale shared chat link shows invalid-link error instead of decrypted dummy content', async ({
	page
}: {
	page: any;
}) => {
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

	// This legacy shared-chat fixture points at a chat that no longer exists in
	// Directus. The API intentionally returns dummy ciphertext for missing chats;
	// the share page must reject that payload instead of importing dummy messages
	// that later render "[Content decryption failed]".
	const sharedChatUrl =
		'https://app.dev.openmates.org/share/chat/87f1da2f-1814-4a36-a375-c718fa946922#key=X4Tz9wamfp_uPngBF3Z_imlm7t9eelWvSwPauIpcAy8z8qHi9A0Nu4uS-ZhfKBdF2462Qc0gJQZFHINe0L_iqwCUfvtjsY7eDrAAVsEuQUaCmUo-KZK1PslohdOMfg_xRvKUbGW-lh1mi6NrCz7pOur8ojLhxuT-lfsHIoHMEQPHuFb6AsDW5s-ZGSdHcTsQp3ue&messageid=ffcc180d-a0aa-4fc0-9c44-be39064122b8';
	const expectedChatId = '87f1da2f-1814-4a36-a375-c718fa946922';

	logCheckpoint('Starting shared chat test', { chatId: expectedChatId });

	// Step 1: Navigate to the shared chat URL
	logCheckpoint('Navigating to shared chat URL...');
	await page.goto(sharedChatUrl);

	// Step 2: The stale link should be rejected on the share page, before the
	// dummy encrypted payload is persisted to IndexedDB or rendered as messages.
	await expect(page.getByText(/shared chat is no longer available|link is invalid/i)).toBeVisible({
		timeout: 30000
	});
	await expect(page.getByText('[Content decryption failed]')).not.toBeVisible();
	await expect(page).not.toHaveURL(new RegExp(`chat-id=${expectedChatId}`));
	await takeStepScreenshot(page, 'invalid-link-error');

	// Step 3: Verify no missing translations on the shared chat page
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// Step 4: Final verification and screenshot
	await takeStepScreenshot(page, 'test-complete');
	logCheckpoint('Stale shared chat link rejected successfully');
});
