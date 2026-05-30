/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Interactive Questions Chat Flow Spec
 *
 * Verifies that the assistant can embed interactive question blocks,
 * which are parsed as Svelte widgets. Interacting with the choices and
 * clicking "Send" dispatches the response as a user message, locking
 * the container's interactive elements.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, waitForAssistantMessage } = require('./helpers/chat-test-helpers');

test('triggers interactive questions, handles selections, submissions, and state locking', async ({ page }) => {
	const log = createSignupLogger('INTERACTIVE_QUESTIONS');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	// Start a new chat
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		await page.waitForTimeout(1500);
	}
	await screenshot(page, 'new-chat-ready');

	// Ask for a quiz to trigger the interactive question block
	const message = 'Quiz me on Python slicing syntax';
	log(`Sending: "${message}"`);
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await messageEditor.click();
	await page.keyboard.type(withMockMarker(message, 'interactive_questions_quiz'));

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	log('Message sent.');

	// Wait for the assistant's message containing the interactive question
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	await page.waitForTimeout(1000);
	await screenshot(page, 'assistant-quiz-received');

	// Verify the interactive question card is mounted inside the message bubble
	const questionCard = page.locator('.interactive-question-card');
	await expect(questionCard).toBeVisible({ timeout: 15000 });

	// Assert the question heading title is parsed and rendered correctly
	const title = questionCard.locator('.question-title');
	await expect(title).toBeVisible();

	// Verify the option items list renders correctly
	const options = questionCard.locator('.option-item');
	await expect(options).toHaveCount(2);

	// Verify "Send" and "Clear" buttons exist in the card footer
	const clearBtn = questionCard.locator('.btn-clear');
	const submitBtn = questionCard.locator('.btn-send');
	await expect(clearBtn).toBeVisible();
	await expect(submitBtn).toBeVisible();

	// Send button should be disabled until a choice is selected
	await expect(submitBtn).toHaveClass(/disabled/);

	// Select the first option
	await options.first().click();
	await expect(submitBtn).not.toHaveClass(/disabled/);

	// Click "Send" inside the question card container to submit the response
	await submitBtn.click();
	log('Interactive answer submitted.');

	// Wait for our answered response summary message to be appended to the chat
	const userResponseMsg = page.locator('.chat-message-body').last();
	await expect(userResponseMsg).toContainText('I selected:');

	// Verify that the interactive question card has transitioned to its locked/answered state
	await expect(questionCard).toHaveClass(/locked/);
	await expect(questionCard.locator('.answered-badge')).toBeVisible();

	// Confirm that the Clear and Send buttons are unmounted after the question is locked
	await expect(clearBtn).not.toBeVisible();
	await expect(submitBtn).not.toBeVisible();

	await screenshot(page, 'quiz-completed-and-locked');
});
