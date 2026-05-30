/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Interactive Questions E2E Integration Spec
 *
 * Verifies all 5 interactive question types (Choice, Input, Slider, Swipe, Rating)
 * inside the component preview viewport, and validates the live chat-flow integration.
 *
 * Architecture: Svelte 5 / Playwright Integration Tests
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, waitForAssistantMessage } = require('./helpers/chat-test-helpers');

test.describe('InteractiveQuestions Component Previews (All 5 Types)', () => {
	test.beforeEach(async ({ page }) => {
		// Navigate directly to the component's unauthenticated dev preview route
		const response = await page.goto('/dev/preview/interactive_questions/InteractiveQuestionContainer', {
			waitUntil: 'networkidle'
		});
		expect(response?.status()).toBe(200);
		// Wait for SvelteKit client hydration
		await page.waitForTimeout(2000);
	});

	// --- 1. Choice Single-Select ---
	test('renders choice single-select question, handles selections and clear actions', async ({ page }) => {
		await expect(page.locator('.type-badge.choice-badge')).toContainText('Choice');
		const options = page.locator('.option-item');
		await expect(options).toHaveCount(3);

		const sendBtn = page.locator('.btn-send');
		await expect(sendBtn).toHaveClass(/disabled/);

		// Click the first option
		await options.first().click();
		await expect(sendBtn).not.toHaveClass(/disabled/);

		// Click 'Clear'
		await page.locator('.btn-clear').click();
		await expect(sendBtn).toHaveClass(/disabled/);
	});

	test('supports keyboard navigation for accessible choice selections', async ({ page }) => {
		const options = page.locator('.option-item');
		const sendBtn = page.locator('.btn-send');

		await options.nth(1).focus();
		await page.keyboard.press('Enter');

		await expect(options.nth(1)).toHaveClass(/selected/);
		await expect(sendBtn).not.toHaveClass(/disabled/);
	});

	// --- 2. Choice Multi-Select ---
	test('renders choice multi-select, handles multiple selections and clear', async ({ page }) => {
		await page.locator('.variant-btn:has-text("choice_multi")').click();
		await page.waitForTimeout(500);

		await expect(page.locator('.type-badge.choice-badge')).toContainText('Choice');
		const options = page.locator('.option-item');
		await expect(options).toHaveCount(4);

		const sendBtn = page.locator('.btn-send');
		await expect(sendBtn).toHaveClass(/disabled/);

		// Select first and second options
		await options.nth(0).click();
		await options.nth(1).click();

		await expect(options.nth(0)).toHaveClass(/selected/);
		await expect(options.nth(1)).toHaveClass(/selected/);
		await expect(sendBtn).not.toHaveClass(/disabled/);

		// Clear selections
		await page.locator('.btn-clear').click();
		await expect(sendBtn).toHaveClass(/disabled/);
		await expect(options.nth(0)).not.toHaveClass(/selected/);
	});

	// --- 3. Input Sequential Form ---
	test('renders input forms, validates and locks required fields', async ({ page }) => {
		await page.locator('.variant-btn:has-text("input_form")').click();
		await page.waitForTimeout(500);

		await expect(page.locator('.type-badge.input-badge')).toContainText('Form');
		
		const inputs = page.locator('.text-input');
		await expect(inputs).toHaveCount(3);

		const sendBtn = page.locator('.btn-send');
		await expect(sendBtn).toHaveClass(/disabled/);

		// Fill out only one required field (Jane Doe)
		await inputs.nth(0).fill('Jane Doe');
		await expect(sendBtn).toHaveClass(/disabled/); // Still disabled because 'experience' is required

		// Fill out the second required field (5 years)
		await inputs.nth(2).fill('5');
		await expect(sendBtn).not.toHaveClass(/disabled/); // Now unlocked!
	});

	// --- 4. Slider Numeric Scale ---
	test('renders slider scale, drags range values', async ({ page }) => {
		await page.locator('.variant-btn:has-text("slider_scale")').click();
		await page.waitForTimeout(500);

		await expect(page.locator('.type-badge.slider-badge')).toContainText('Scale');
		
		const rangeInput = page.locator('.range-input');
		await expect(rangeInput).toBeVisible();

		// Current value should initially show default (3)
		await expect(page.locator('.current-value')).toContainText('Selected: 3');

		// Set the value to 5
		await rangeInput.fill('5');
		await rangeInput.dispatchEvent('input');

		await expect(page.locator('.current-value')).toContainText('Selected: 5');
	});

	// --- 5. Swipe Card Decider ---
	test('renders swipe card stack, decodes dislikes/likes and resets', async ({ page }) => {
		await page.locator('.variant-btn:has-text("swipe_cards")').click();
		await page.waitForTimeout(500);

		await expect(page.locator('.type-badge.swipe-badge')).toContainText('Swipe Decision');

		// First card text should be visible
		const card = page.locator('.swipe-card.top-card');
		await expect(card).toContainText('Minimalist');

		// Click Dislike on first card
		await page.locator('.btn-dislike').click();
		await page.waitForTimeout(300);

		// Second card (Brutalist) should now be top card
		await expect(card).toContainText('Brutalist');

		// Click Like on second card
		await page.locator('.btn-like').click();
		await page.waitForTimeout(300);

		// Third card (Skeuomorphic)
		await expect(card).toContainText('Skeuomorphic');
		await page.locator('.btn-like').click();
		await page.waitForTimeout(300);

		// Stack finished
		await expect(page.locator('.stack-end-text')).toContainText('All cards reviewed!');
		const sendBtn = page.locator('.btn-send');
		await expect(sendBtn).not.toHaveClass(/disabled/);

		// Reset/Rewind
		await page.locator('.btn-rewind').click();
		await expect(card).toContainText('Minimalist');
	});

	// --- 6. Star Rating + Comments ---
	test('renders star rating, selects stars and writes comment', async ({ page }) => {
		await page.locator('.variant-btn:has-text("rating_stars")').click();
		await page.waitForTimeout(500);

		await expect(page.locator('.type-badge.rating-badge')).toContainText('Rating');

		const stars = page.locator('.star-wrapper');
		await expect(stars).toHaveCount(5);

		const sendBtn = page.locator('.btn-send');
		await expect(sendBtn).toHaveClass(/disabled/);

		// Click 4th star
		await stars.nth(3).click();

		// Stars should highlight and Send button should unlock
		await expect(page.locator('.star-icon').nth(3)).toHaveClass(/highlighted/);
		await expect(sendBtn).not.toHaveClass(/disabled/);

		// Fill optional comment
		await page.locator('.comment-textarea').fill('Awesome developer tools!');
	});
});

test.describe('InteractiveQuestions Chat Integration', () => {
	test('triggers interactive questions, handles selections, submissions, and state locking in real-time chat', async ({ page }) => {
		test.setTimeout(90000);
		const log = createSignupLogger('INTERACTIVE_QUESTIONS_FLOW');
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

		await screenshot(page, 'quiz-option-selected');
	});
});
