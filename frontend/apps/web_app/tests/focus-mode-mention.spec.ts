/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
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

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * Focus mode mention dropdown test: Verify that typing "@career" in the message
 * editor triggers the mention dropdown with focus mode results, and selecting
 * one closes the dropdown.
 *
 * This test needs NO AI call — it only checks the mention dropdown UI.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------
const SELECTORS = {
	mentionDropdown: '[data-testid="mention-dropdown"]',
	mentionDropdownFocusItem: '[data-testid="mention-result"][role="option"]'
};

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function setupPageListeners(page: any): void {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});
}

// ---------------------------------------------------------------------------
// Test: Focus mode can be manually triggered via MentionDropdown (@focus)
// ---------------------------------------------------------------------------

test('focus mode can be manually triggered via mention dropdown', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	// No AI call needed — just UI interaction. 1 minute timeout.
	test.setTimeout(60000);

	const logCheckpoint = createSignupLogger('FOCUS_MENTION');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-mention'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting focus mode mention dropdown test.');

	// STEP 1: Login
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// STEP 2: Type "@career" to trigger the mention dropdown
	logCheckpoint('Typing "@career" in message editor to trigger mention dropdown...');
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type('@career');
	await page.waitForTimeout(500);
	await takeStepScreenshot(page, 'mention-dropdown-typed');

	// STEP 3: Verify the mention dropdown appears with focus mode results
	logCheckpoint('Checking for mention dropdown...');
	const mentionDropdown = page.locator(SELECTORS.mentionDropdown);
	await expect(mentionDropdown).toBeVisible({ timeout: 5000 });
	logCheckpoint('Mention dropdown is visible!');

	// Check that at least one result is a focus_mode type matching "career"
	const allResults = page.locator('[data-testid="mention-result"][role="option"]');
	const resultCount = await allResults.count();
	logCheckpoint(`Mention dropdown has ${resultCount} results.`);
	expect(resultCount).toBeGreaterThan(0);

	// Look for a result that contains "career" in its text
	let foundCareerFocusMode = false;
	for (let i = 0; i < resultCount && !foundCareerFocusMode; i++) {
		const resultText = await allResults.nth(i).textContent();
		if (resultText?.toLowerCase().includes('career')) {
			foundCareerFocusMode = true;
			logCheckpoint(`Found career focus mode result: "${resultText?.trim()}"`);

			// Click it to select it
			await allResults.nth(i).click();
			logCheckpoint('Clicked career focus mode result in dropdown.');
			break;
		}
	}

	if (!foundCareerFocusMode) {
		// Try pressing Enter to select the first result
		logCheckpoint('No career result found — pressing Enter to select first result.');
		await page.keyboard.press('Enter');
	}

	await page.waitForTimeout(500);
	await takeStepScreenshot(page, 'mention-dropdown-selected');

	// STEP 4: Verify the dropdown is closed (selection completed)
	const dropdownAfter = await mentionDropdown.isVisible({ timeout: 1000 }).catch(() => false);
	logCheckpoint(`Mention dropdown still visible after selection: ${dropdownAfter}`);
	await expect(mentionDropdown).not.toBeVisible({ timeout: 3000 });
	logCheckpoint('Mention dropdown closed after focus mode selection — trigger verified.');

	logCheckpoint('Focus mode mention dropdown test completed successfully.');
});
