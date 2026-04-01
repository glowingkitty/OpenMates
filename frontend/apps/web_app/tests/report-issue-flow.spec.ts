/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Report Issue E2E test.
 *
 * Validates the issue reporting flow end-to-end:
 *
 * 1. Login with test account + 2FA
 * 2. Open Settings menu → navigate to "Report Issue"
 * 3. Verify the report issue form is visible with required elements
 * 4. Attempt to submit with empty title — verify validation error
 * 5. Fill in the title field with a valid test issue
 * 6. Submit the form — verify the API call succeeds (200 + success: true)
 * 7. Verify the confirmation page appears with an issue ID
 * 8. Click "Submit another report" — verify form resets
 *
 * Bug history this test suite guards against:
 * - 6b082ce08 (2026-03-31): OPE-221 added prompt injection detection to report_issue
 *   endpoint — need to verify the sanitization layer doesn't break normal submissions
 * - CMS outage (2026-04-01): Directus downtime caused 500s on /v1/settings/issues
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
 */
export {};

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Open the settings menu and navigate to the Report Issue page.
 * Path: Settings toggle → Report Issue menu item
 */
async function navigateToReportIssue(
	page: any,
	logFn: (msg: string) => void
): Promise<void> {
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	await settingsToggle.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logFn('Opened settings menu.');

	// Click "Report Issue" menu item — matches the i18n label via regex
	const reportItem = settingsMenu.getByRole('menuitem', { name: /report.*issue|issue.*report|problem.*melden/i }).first();
	await expect(reportItem).toBeVisible({ timeout: 5000 });
	await reportItem.click();
	logFn('Navigated to Report Issue settings.');

	// Wait for the report issue form to render
	await page.waitForTimeout(1000);
}

/**
 * Close the settings panel by clicking the settings toggle close icon.
 */
async function closeSettings(page: any): Promise<void> {
	const closeIcon = page.locator('#settings-menu-toggle .close-icon-container.visible').first();
	try {
		await closeIcon.click({ timeout: 3000 });
	} catch {
		const settingsToggle = page.locator('#settings-menu-toggle');
		await settingsToggle.click();
	}
	await page.waitForTimeout(500);
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test.describe('Report Issue Flow', () => {
	// Login + settings navigation + form submission needs time
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('Report issue form submits successfully and shows confirmation', async ({ page }) => {
		const logCheckpoint = createSignupLogger('REPORT_ISSUE');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'report-issue-flow'
		});

		// Archive old screenshots
		await archiveExistingScreenshots(logCheckpoint);

		// Attach console/network monitors
		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);

		// ── Step 1: Login ──────────────────────────────────────────────
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		logCheckpoint('Login complete.');
		await takeStepScreenshot(page, '01-logged-in');

		// ── Step 2: Navigate to Report Issue ───────────────────────────
		await navigateToReportIssue(page, logCheckpoint);
		await takeStepScreenshot(page, '02-report-issue-form');

		// ── Step 3: Verify form elements are visible ───────────────────
		const reportForm = page.getByTestId('report-issue-form');
		await expect(reportForm).toBeVisible({ timeout: 10000 });
		logCheckpoint('Report issue form visible.');

		const titleField = page.getByTestId('report-issue-title');
		await expect(titleField).toBeVisible({ timeout: 5000 });
		logCheckpoint('Title field visible.');

		const submitButton = page.getByTestId('report-issue-submit');
		await expect(submitButton).toBeVisible({ timeout: 5000 });
		logCheckpoint('Submit button visible.');

		// ── Step 4: Attempt empty submit — verify validation ───────────
		// The submit button should be disabled when the form is invalid
		await expect(submitButton).toBeDisabled();
		logCheckpoint('Submit button correctly disabled with empty title.');
		await takeStepScreenshot(page, '03-submit-disabled');

		// ── Step 5: Fill in the title ──────────────────────────────────
		const testTitle = `[E2E Test] Report issue flow validation — ${new Date().toISOString()}`;
		await titleField.fill(testTitle);
		logCheckpoint(`Filled title: "${testTitle}"`);

		// Wait for validation to enable the button
		await page.waitForTimeout(500);
		await expect(submitButton).toBeEnabled({ timeout: 5000 });
		logCheckpoint('Submit button enabled after filling title.');
		await takeStepScreenshot(page, '04-title-filled');

		// ── Step 6: Submit and intercept API response ──────────────────
		// Set up a response listener for the API call
		const responsePromise = page.waitForResponse(
			(response: any) =>
				response.url().includes('/v1/settings/issues') &&
				response.request().method() === 'POST',
			{ timeout: 30000 }
		);

		await submitButton.click();
		logCheckpoint('Clicked submit button.');

		// Wait for the API response
		const apiResponse = await responsePromise;
		const statusCode = apiResponse.status();
		logCheckpoint(`API response status: ${statusCode}`);

		// Parse response body
		let responseBody: any;
		try {
			responseBody = await apiResponse.json();
			logCheckpoint(`API response body: ${JSON.stringify(responseBody)}`);
		} catch {
			logCheckpoint('Could not parse API response as JSON.');
		}

		// Verify success
		expect(statusCode).toBe(200);
		expect(responseBody?.success).toBe(true);
		expect(responseBody?.issue_id).toBeTruthy();
		logCheckpoint(`Issue created with ID: ${responseBody?.issue_id}`);
		await takeStepScreenshot(page, '05-submitted');

		// ── Step 7: Verify confirmation page ───────────────────────────
		const confirmation = page.getByTestId('report-issue-confirmation');
		await expect(confirmation).toBeVisible({ timeout: 10000 });
		logCheckpoint('Confirmation page visible.');

		// Verify the issue ID is displayed on the confirmation page
		const issueIdElement = confirmation.locator('code');
		await expect(issueIdElement).toBeVisible({ timeout: 5000 });
		const displayedIssueId = await issueIdElement.textContent();
		expect(displayedIssueId).toBe(responseBody?.issue_id);
		logCheckpoint(`Confirmation shows issue ID: ${displayedIssueId}`);
		await takeStepScreenshot(page, '06-confirmation');

		// ── Step 8: Submit another report — verify form resets ──────────
		const submitAnotherButton = confirmation.locator('button:has-text("report"), button:has-text("Report"), button:has-text("melden"), button:has-text("another")');
		await expect(submitAnotherButton).toBeVisible({ timeout: 5000 });
		await submitAnotherButton.click();
		logCheckpoint('Clicked "Submit another report" button.');

		// Wait for navigation back to the form
		await page.waitForTimeout(1000);

		// Verify the form is shown again with an empty title
		const titleFieldAfterReset = page.getByTestId('report-issue-title');
		await expect(titleFieldAfterReset).toBeVisible({ timeout: 10000 });
		const titleValue = await titleFieldAfterReset.inputValue();
		expect(titleValue).toBe('');
		logCheckpoint('Form reset — title field is empty.');
		await takeStepScreenshot(page, '07-form-reset');

		// Clean up: close settings
		await closeSettings(page);
		logCheckpoint('Report issue flow complete — all assertions passed.');
	});
});
