/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Chat error report consent E2E test.
 *
 * Verifies that an authenticated user who has a chat open gets the automatic
 * chat-error report notification, and that no issue details are submitted until
 * the user presses the notification action button.
 */
export {};

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners,
} = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount,
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Chat Error Report Consent', () => {
	test.describe.configure({ timeout: 120000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('shows notification and submits details only after user confirmation', async ({ page }) => {
		const logCheckpoint = createSignupLogger('CHAT_ERROR_REPORT');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'chat-error-report-consent',
		});
		await archiveExistingScreenshots(logCheckpoint);
		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);

		let submittedIssuePayload: Record<string, any> | null = null;
		let issuePostCount = 0;
		await page.route('**/v1/settings/issues', async (route: any) => {
			issuePostCount += 1;
			submittedIssuePayload = route.request().postDataJSON();
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					success: true,
					issue_id: 'OPE-E2E-CHAT-ERROR',
					screenshot_uploaded: false,
				}),
			});
		});
		await page.route('**/v1/settings/issue-logs', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ success: true }),
			});
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 20000 });
		await page.getByTestId('daily-inspiration-banner').click();
		await page.waitForFunction(async () => {
			const debug = (window as any).debug;
			const state = await debug?.state?.();
			return typeof state?.activeChat === 'string' && state.activeChat.length > 0;
		}, null, { timeout: 30000 });
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 20000 });
		await takeStepScreenshot(page, '01-authenticated-chat-open');

		const simulated = await page.evaluate(async () => {
			const debug = (window as any).debug;
			if (!debug?.simulateChatError) throw new Error('window.debug.simulateChatError is unavailable');
			return debug.simulateChatError({
				source: 'e2e-simulated-chat-error',
				message: 'E2E simulated chat failure details',
			});
		});
		expect(simulated?.source).toBe('e2e-simulated-chat-error');
		expect(simulated?.chatId, 'simulated chat error should include active chat context').toBeTruthy();
		logCheckpoint(`Triggered simulated chat error for chat ${simulated?.chatId ?? 'unknown'}.`);

		const notification = page.getByTestId('notification').filter({ hasText: /Chat response failed/i });
		await expect(notification).toBeVisible({ timeout: 10000 });
		await expect(notification).toContainText('OpenMates can send a technical issue report');
		await expect(notification).toContainText('only if you choose to report it');
		await expect(notification.getByTestId('notification-action')).toContainText(/Report issue/i);
		await takeStepScreenshot(page, '02-consent-notification-visible');

		expect(issuePostCount, 'issue report should not be submitted before confirmation').toBe(0);
		expect(submittedIssuePayload).toBeNull();

		const issueResponsePromise = page.waitForResponse(
			(response: any) => response.url().includes('/v1/settings/issues') && response.request().method() === 'POST',
			{ timeout: 15000 },
		);
		await notification.getByTestId('notification-action').click();
		const issueResponse = await issueResponsePromise;
		expect(issueResponse.status()).toBe(200);

		await expect(page.getByTestId('notification').filter({ hasText: /OPE-E2E-CHAT-ERROR/i })).toBeVisible({ timeout: 10000 });
		expect(issuePostCount).toBe(1);
		expect(submittedIssuePayload?.title).toBe('Chat response failed');
		expect(submittedIssuePayload?.description).toContain('A chat processing error happened');
		expect(submittedIssuePayload?.description).toContain('Source: e2e-simulated-chat-error');
		expect(submittedIssuePayload?.description).toContain('Error: E2E simulated chat failure details');
		expect(submittedIssuePayload?.chat_or_embed_url, 'current chat context should be included after consent').toBeTruthy();
		expect(submittedIssuePayload?.runtime_debug_state).toBeTruthy();
		expect(submittedIssuePayload?.add_to_linear).toBe(true);
		await takeStepScreenshot(page, '03-report-submitted');
	});
});
