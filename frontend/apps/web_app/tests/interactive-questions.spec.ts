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
const { getTestAccount } = require('./signup-flow-helpers');

const MIN_WCAG_AA_NORMAL_TEXT_CONTRAST = 4.5;

function parseRgbColor(color: string): [number, number, number] {
	const match = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
	if (!match) {
		throw new Error(`Unsupported color format: ${color}`);
	}
	return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function relativeLuminance([red, green, blue]: [number, number, number]) {
	const [r, g, b] = [red, green, blue].map((value) => {
		const channel = value / 255;
		return channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4);
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(foreground: string, background: string) {
	const foregroundLuminance = relativeLuminance(parseRgbColor(foreground));
	const backgroundLuminance = relativeLuminance(parseRgbColor(background));
	const lighter = Math.max(foregroundLuminance, backgroundLuminance);
	const darker = Math.min(foregroundLuminance, backgroundLuminance);
	return (lighter + 0.05) / (darker + 0.05);
}

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

	test('keeps selected choice text readable in dark mode', async ({ page }) => {
		await page.evaluate(() => {
			document.documentElement.setAttribute('data-theme', 'dark');
		});

		const option = page.getByTestId('interactive-question-option-opt_reverse');
		await option.click();

		const colors = await option.evaluate((element) => {
			const textElement = Array.from(element.querySelectorAll<HTMLElement>('*')).find((child) =>
				child.textContent?.includes('Reverses the direction of slicing')
			);
			if (!textElement) {
				throw new Error('Selected option text element was not found');
			}
			const optionStyles = window.getComputedStyle(element);
			const textStyles = window.getComputedStyle(textElement);
			return {
				background: optionStyles.backgroundColor,
				foreground: textStyles.color
			};
		});

		expect(contrastRatio(colors.foreground, colors.background)).toBeGreaterThanOrEqual(
			MIN_WCAG_AA_NORMAL_TEXT_CONTRAST
		);
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

	test('shows and requires a text input for custom choice answers', async ({ page }) => {
		await page.getByRole('button', { name: 'choice_custom' }).click();
		await page.waitForTimeout(500);

		const sendBtn = page.getByTestId('interactive-question-send');
		await expect(sendBtn).toBeDisabled();

		await page.getByTestId('interactive-question-option-own_answer').click();
		const customInput = page.getByTestId('interactive-question-custom-answer');
		await expect(customInput).toBeVisible();
		await expect(sendBtn).toBeDisabled();

		await customInput.fill('Let users type a custom response');
		await expect(sendBtn).toBeEnabled();

		await page.getByTestId('interactive-question-clear').click();
		await expect(customInput).not.toBeVisible();
		await expect(sendBtn).toBeDisabled();
	});

	test('renders embed previews inside choice options', async ({ page }) => {
		await page.getByRole('button', { name: 'choice_with_embeds' }).click();
		await page.waitForTimeout(500);

		await expect(page.getByTestId('interactive-question-title')).toContainText('Which implementation should we use?');
		await expect(page.getByTestId('interactive-question-embed')).toHaveCount(2);

		const sendBtn = page.getByTestId('interactive-question-send');
		await expect(sendBtn).toBeDisabled();
		await page.getByText('More robust implementation').click();
		await expect(sendBtn).toBeEnabled();
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

	test('renders embed previews inside swipe cards', async ({ page }) => {
		await page.getByRole('button', { name: 'swipe_with_embeds' }).click();
		await page.waitForTimeout(500);

		await expect(page.getByTestId('interactive-question-title')).toContainText('Review these generated assets');
		await expect(page.getByTestId('interactive-question-embed').first()).toBeVisible();

		const sendBtn = page.getByTestId('interactive-question-send');
		await expect(sendBtn).toBeDisabled();
		await page.getByTestId('interactive-question-swipe-like').click();
		await page.getByTestId('interactive-question-swipe-dislike').click();
		await expect(sendBtn).toBeEnabled();
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

		const account = getTestAccount();
		test.skip(!account.email || !account.password || !account.otpKey, 'Test account credentials not configured');

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
		const questionCard = page.getByTestId('interactive-question-card');
		await expect(questionCard).toBeVisible({ timeout: 15000 });

		// Assert the question heading title is parsed and rendered correctly
		const title = questionCard.getByTestId('interactive-question-title');
		await expect(title).toBeVisible();

		// Verify the option items list renders correctly
		const options = questionCard.locator('[data-testid^="interactive-question-option-"]');
		await expect(options).toHaveCount(2);

		// Verify "Send" and "Clear" buttons exist in the card footer
		const clearBtn = questionCard.getByTestId('interactive-question-clear');
		const submitBtn = questionCard.getByTestId('interactive-question-send');
		await expect(clearBtn).toBeVisible();
		await expect(submitBtn).toBeVisible();

		// Send button should be disabled until a choice is selected
		await expect(submitBtn).toHaveClass(/disabled/);

		// Select the first option
		await options.first().click();
		await expect(submitBtn).not.toHaveClass(/disabled/);

		await screenshot(page, 'quiz-option-selected');

		await submitBtn.click();
		const latestUserMessage = page.getByTestId('user-message-content').last();
		await expect(latestUserMessage).toBeVisible({ timeout: 10000 });
		await expect(latestUserMessage).not.toContainText('I selected');
		await expect(latestUserMessage).not.toContainText('Selected:');
		await expect(latestUserMessage).not.toContainText('interactive_response');
		await expect(questionCard).toHaveClass(/locked/, { timeout: 10000 });
		await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
		const latestAssistantMessage = page.getByTestId('mate-message-content').last();
		await expect(latestAssistantMessage).not.toContainText('The AI service encountered an error while processing your request', { timeout: 15000 });
		await screenshot(page, 'quiz-answer-submitted-answer-only');
	});
});
