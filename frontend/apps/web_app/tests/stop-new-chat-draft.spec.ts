/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Stop-new-chat draft restoration regression.
 *
 * Verifies that pressing Stop while the first message is still creating a new
 * chat reverses the optimistic chat creation UI and puts the message back into
 * the composer as a draft.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const { deleteActiveChat, loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test('stop during new chat creation restores the sent message as a draft', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(150000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('STOP_NEW_CHAT_DRAFT');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'stop-new-chat-draft'
	});
	await archiveExistingScreenshots(logCheckpoint);

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	let shouldTryCleanup = false;
	try {
		const visibleDraft = 'Please keep this exact draft text when I stop creating the new chat.';
		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toBeVisible({ timeout: 15000 });
		await messageEditor.click();
		await page.keyboard.type(withMockMarker(visibleDraft, 'chat_flow_capital', 'slow'));
		await takeStepScreenshot(page, 'draft-typed');

		const sendButton = page.locator('[data-action="send-message"]');
		await expect(sendButton).toBeVisible({ timeout: 15000 });
		await expect(sendButton).toBeEnabled({ timeout: 5000 });
		await sendButton.click();
		shouldTryCleanup = true;
		logCheckpoint('Sent fresh-chat message and waiting for creating-chat state.');

		const chatHeader = page.getByTestId('chat-header-banner');
		await expect(chatHeader).toContainText(/Creating new chat/i, { timeout: 15000 });
		const stopButton = page.getByTestId('stop-processing-button');
		await expect(stopButton).toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, 'creating-chat-before-stop');

		await stopButton.click();
		logCheckpoint('Clicked Stop while the new chat was still being created.');

		await expect(stopButton).not.toBeVisible({ timeout: 10000 });
		await expect(messageEditor).toContainText(visibleDraft, { timeout: 15000 });
		await expect(page.getByText(/Creating new chat/i)).toHaveCount(0, { timeout: 15000 });
		await expect(page.getByTestId('message-user')).toHaveCount(0, { timeout: 10000 });
		await takeStepScreenshot(page, 'draft-restored-after-stop');
	} finally {
		if (shouldTryCleanup) {
			await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup');
		}
	}
});
