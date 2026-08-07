/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed Deep research end-to-end proof.
 *
 * Selects the real focus mention, delegates three bounded child chats through
 * live inference, and verifies the final parent synthesis without route mocks.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { dismissVisibleNotifications } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function sendDeepResearchMessage(
	page: any,
	prompt: string,
	log: (message: string, metadata?: Record<string, unknown>) => void,
	screenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	const messageField = page.getByTestId('message-field').last();
	const editor = messageField.getByTestId('message-editor');
	await expect(editor).toBeVisible();
	await dismissVisibleNotifications(page);
	await editor.click();
	await page.keyboard.type('@deep', { delay: 50 });
	await expect(editor).toContainText('@deep', { timeout: 5_000 });

	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown).toBeVisible({ timeout: 10_000 });
	const focusResult = dropdown.getByTestId('mention-result').filter({ hasText: 'Deep research' }).first();
	await expect(focusResult).toBeVisible({ timeout: 10_000 });
	await focusResult.click();
	await expect(dropdown).not.toBeVisible({ timeout: 5_000 });
	await page.keyboard.insertText(` ${prompt}`);
	await screenshot(page, 'deep-research-request-typed');

	const userMessages = page.getByTestId('message-user');
	const userCount = await userMessages.count();
	const sendButton = messageField.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 10_000 });
	await sendButton.click();
	await expect(userMessages).toHaveCount(userCount + 1, { timeout: 30_000 });
	log('Sent explicit Deep research focus mention request.');
}

test('Deep research delegates three angles and renders the final parent synthesis', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(900_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('deep-research-real-inference');
	await archiveExistingScreenshots(log);
	const screenshot = createStepScreenshotter(log);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const prompt =
		'Investigate how the EU AI Act general-purpose AI obligations affect open-source model providers, cloud hosts, and downstream startups. ' +
		'Delegate exactly three distinct regulatory, market-incentive, and counterargument/source-quality angles, use current sources, and synthesize what is confirmed, likely, plausible, and uncertain.';

	await sendDeepResearchMessage(page, prompt, log, screenshot);

	const focusBar = page.getByTestId('focus-mode-bar').filter({ hasText: 'Deep research' }).first();
	await expect(focusBar).toBeVisible({ timeout: 120_000 });
	await screenshot(page, 'deep-research-activated');

	const carousel = page.getByTestId('sub-chats-carousel');
	await expect(carousel).toBeVisible({ timeout: 240_000 });
	const subChatCards = page.getByTestId('sub-chat-card');
	await expect(subChatCards).toHaveCount(3, { timeout: 240_000 });
	await screenshot(page, 'deep-research-three-children');

	const finalAssistant = page.getByTestId('message-assistant').last();
	await expect(finalAssistant).toHaveAttribute('data-streaming', 'false', { timeout: 600_000 });
	await expect(finalAssistant).toContainText('Short Answer');
	await expect(finalAssistant).toContainText('Surface Explanation');
	await expect(finalAssistant).toContainText('What Else May Be Going On');
	await expect(finalAssistant).toContainText('Evidence');
	await expect(finalAssistant).toContainText('Counterarguments');
	await expect(finalAssistant).toContainText('Bottom Line');
	await expect(finalAssistant).not.toContainText('The AI service encountered an error');
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible();
	await screenshot(page, 'deep-research-final-synthesis');

	await deleteActiveChat(page, log, screenshot, 'deep-research-cleanup');
	log('Deep research completed with three children and a final parent synthesis.');
});
