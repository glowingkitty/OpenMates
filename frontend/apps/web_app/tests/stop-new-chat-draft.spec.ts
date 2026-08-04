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

async function insertComposerText(page: any, messageEditor: any, text: string, visibleText: string): Promise<void> {
	await messageEditor.click({ position: { x: 12, y: 12 }, force: true });
	await expect
		.poll(
			async () => messageEditor.evaluate((element: HTMLElement) => {
				const activeElement = document.activeElement;
				return Boolean(
					activeElement instanceof HTMLElement &&
					element.contains(activeElement) &&
					activeElement.isContentEditable
				);
			}),
			{ timeout: 5000 }
		)
		.toBeTruthy();

	await page.keyboard.insertText(text);
	const keyboardInserted = await expect
		.poll(
			async () => (await messageEditor.textContent().catch(() => '')) ?? '',
			{ timeout: 2000 }
		)
		.toContain(visibleText)
		.then(() => true)
		.catch(() => false);

	if (!keyboardInserted) {
		await messageEditor.evaluate((element: HTMLElement, insertedText: string) => {
			const editableElement = element.isContentEditable
				? element
				: element.querySelector<HTMLElement>('[contenteditable="true"]');
			if (!editableElement) {
				throw new Error('Message editor contenteditable target was not found.');
			}
			editableElement.focus();
			const range = document.createRange();
			range.selectNodeContents(editableElement);
			range.collapse(false);
			const selection = window.getSelection();
			selection?.removeAllRanges();
			selection?.addRange(range);

			const inserted = document.execCommand('insertText', false, insertedText);
			if (!inserted || !editableElement.textContent?.includes(insertedText)) {
				editableElement.textContent = insertedText;
				editableElement.dispatchEvent(new InputEvent('input', {
					bubbles: true,
					cancelable: true,
					data: insertedText,
					inputType: 'insertText'
				}));
			}
		}, text);
	}

	await expect
		.poll(
			async () => (await messageEditor.textContent().catch(() => '')) ?? '',
			{ timeout: 10000 }
		)
		.toContain(visibleText);
}

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
		await insertComposerText(page, messageEditor, withMockMarker(visibleDraft, 'chat_flow_capital', 'slow'), visibleDraft);
		await page.getByTestId('input-dismiss-button').click();
		await expect(page.getByTestId('chat-header-banner')).toHaveCount(0, { timeout: 10000 });
		await messageEditor.click({ position: { x: 12, y: 12 }, force: true });
		await takeStepScreenshot(page, 'draft-typed');
		await page.route(/\/v1\/user-(tasks|plans)(\?|$)/, async (route: any) => {
			await page.waitForTimeout(1500);
			await route.continue();
		});

		const sendButton = page.locator('[data-action="send-message"]');
		await expect(sendButton).toBeVisible({ timeout: 15000 });
		await expect(sendButton).toBeEnabled({ timeout: 5000 });
		await sendButton.click();
		const taskLoadingAppeared = page
			.getByTestId('active-chat-task-preview-loading')
			.waitFor({ state: 'visible', timeout: 2500 })
			.then(() => true)
			.catch(() => false);
		shouldTryCleanup = true;
		logCheckpoint('Sent fresh-chat message and waiting for creating-chat state.');

		const chatHeader = page.getByTestId('chat-header-banner');
		await expect(chatHeader).toContainText(/Creating new chat/i, { timeout: 15000 });
		expect(await taskLoadingAppeared).toBe(false);
		const stopButton = page.getByTestId('stop-processing-button');
		await expect(stopButton).toBeVisible({ timeout: 10000 });
		await stopButton.click();
		logCheckpoint('Clicked Stop while the new chat was still being created.');
		await takeStepScreenshot(page, 'creating-chat-stop-clicked');

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
