/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Focused code-file upload regression test.
 * Verifies authenticated .py uploads render as code-code embeds immediately.
 * Guards against leaking internal JSON embed reference blocks to users.
 * Uses the deployed dev app through the standard Playwright CI workflow.
 * Keep this separate from file-attachment-flow.spec.ts image/vision cases.
 */

const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { loginToTestAccount, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const SAMPLE_PY = path.join(__dirname, 'fixtures', 'sample.py');
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openNewChat(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		await page.waitForTimeout(1500);
	}
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	logCheckpoint('New chat opened and editor ready.');
}

async function attachFiles(
	page: any,
	filePaths: string[],
	logCheckpoint: (msg: string) => void
): Promise<void> {
	const fileInput = page.locator('input[type="file"][multiple]');
	await expect(fileInput).toBeAttached({ timeout: 10000 });

	logCheckpoint(`Attaching ${filePaths.length} file(s): ${filePaths.join(', ')}`);
	await fileInput.setInputFiles(filePaths);
	logCheckpoint('Files attached via setInputFiles().');
}

test('uploaded Python file renders as code embed without JSON leakage', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('FILE_ATTACH_CODE_ONLY');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'file-attach-code-only' });
	await archiveExistingScreenshots(log);

	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	await openNewChat(page, log);
	await screenshot(page, 'new-chat-ready');

	await attachFiles(page, [SAMPLE_PY], log);
	await page.waitForTimeout(5000);
	await screenshot(page, 'after-code-attach');

	const editor = page.getByTestId('message-editor');
	const editorCodeEmbed = editor.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	);
	await expect(editorCodeEmbed).toBeVisible({ timeout: 20000 });
	await expect(editor).not.toContainText('```json');
	await expect(editor).not.toContainText('"embed_id"');
	log('Code embed rendered in editor without raw JSON reference.');

	await editor.click();
	await page.keyboard.type('Please review this Python code:');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	log('Message with Python file sent.');

	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toBeVisible({ timeout: 20000 });
	await screenshot(page, 'code-message-in-chat');

	const chatCodeEmbed = userMessage.locator(
		'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
	);
	await expect(chatCodeEmbed).toBeVisible({ timeout: 20000 });

	const visibleTextOutsideEmbeds = await userMessage.evaluate((el: HTMLElement) => {
		const clone = el.cloneNode(true) as HTMLElement;
		clone.querySelectorAll('[data-testid="embed-full-width-wrapper"]').forEach((embed) => embed.remove());
		return clone.textContent || '';
	});
	expect(visibleTextOutsideEmbeds).not.toContain('```json');
	expect(visibleTextOutsideEmbeds).not.toContain('"embed_id"');
	log('Code embed rendered in sent message without raw JSON leakage.');

	await deleteActiveChat(page, log, screenshot, 'cleanup');
});
