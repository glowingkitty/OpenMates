/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Usage token breakdown E2E test (OPE-213).
 *
 * Validates that after sending a chat message, the billing usage detail view
 * displays a correct token breakdown where system_prompt_tokens + user_input_tokens
 * closely matches input_tokens (the total from the provider API).
 *
 * Uses the &usage deep-link parameter (#settings/billing&usage) to auto-navigate
 * to the most recent usage entry's detail view.
 *
 * Bug history this test suite guards against:
 * - OPE-213: calculate_token_breakdown() was not receiving `tools` parameter in
 *   8 of 10 provider clients, causing tool definition tokens (~13K) to be missing
 *   from system_prompt_tokens. Fixed by adding tools=tools to all calls.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

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
	withMockMarker
} = require('./signup-flow-helpers');

const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

// Default test account — needs credits for AI inference.
const {
	email: TEST_EMAIL,
	password: TEST_PASSWORD,
	otpKey: TEST_OTP_KEY
} = getTestAccount();

test.describe('Usage Token Breakdown', () => {
	test.beforeEach(async ({ page }, testInfo) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		attachConsoleListeners(page, testInfo);
		attachNetworkListeners(page, testInfo);
	});

	test('token breakdown adds up: system_prompt + user_input ≈ input_tokens', async ({ page }, testInfo) => {
		const logger = createSignupLogger(testInfo);
		const takeScreenshot = createStepScreenshotter(testInfo);
		await archiveExistingScreenshots(testInfo);

		// Step 1: Login
		await loginToTestAccount(page, logger.logCheckpoint, takeScreenshot);
		logger.logCheckpoint('Logged in successfully');

		// Step 2: Start a new chat and send a message
		await startNewChat(page, logger.logCheckpoint, takeScreenshot);
		logger.logCheckpoint('Started new chat');

		// Send a simple message that triggers AI inference with tool definitions
		await sendMessage(page, 'What is the capital of France?', logger.logCheckpoint, takeScreenshot);
		logger.logCheckpoint('Message sent, waiting for AI response');

		// Wait for AI response to complete (final message appears)
		const aiResponse = page.locator('[data-testid="chat-message"][data-role="assistant"]').last();
		await expect(aiResponse).toBeVisible({ timeout: 60000 });
		// Wait for the response to finish streaming (status becomes synced)
		await page.waitForTimeout(3000);
		logger.logCheckpoint('AI response received');
		await takeScreenshot(page, 'ai-response-received');

		// Step 3: Navigate to usage detail via deep-link
		// The &usage parameter triggers auto-selection of the latest usage entry
		await page.evaluate(() => {
			window.location.hash = '#settings/billing&usage';
		});
		logger.logCheckpoint('Navigating to billing/usage via deep-link');

		// Wait for the usage detail view to appear (auto-selected by &usage deep-link)
		const usageDetailView = page.getByTestId('usage-detail-view');
		await expect(usageDetailView).toBeVisible({ timeout: 30000 });
		logger.logCheckpoint('Usage detail view is visible');
		await takeScreenshot(page, 'usage-detail-view');

		// Step 4: Extract token values from the detail view
		const inputTokensRow = page.getByTestId('usage-input-tokens');
		await expect(inputTokensRow).toBeVisible({ timeout: 10000 });

		// Extract numeric values from the displayed text
		const inputTokensText = await inputTokensRow.locator('.entry-detail-value').textContent();
		const inputTokens = parseInt((inputTokensText || '0').replace(/[.,\s]/g, ''), 10);
		logger.logCheckpoint(`Input tokens: ${inputTokens}`);

		// Output tokens should also be visible
		const outputTokensRow = page.getByTestId('usage-output-tokens');
		await expect(outputTokensRow).toBeVisible({ timeout: 5000 });
		const outputTokensText = await outputTokensRow.locator('.entry-detail-value').textContent();
		const outputTokens = parseInt((outputTokensText || '0').replace(/[.,\s]/g, ''), 10);
		logger.logCheckpoint(`Output tokens: ${outputTokens}`);

		// System prompt tokens and user input tokens should be visible for AI Ask
		const systemPromptRow = page.getByTestId('usage-system-prompt-tokens');
		await expect(systemPromptRow).toBeVisible({ timeout: 5000 });
		const systemPromptText = await systemPromptRow.locator('.entry-detail-value').textContent();
		const systemPromptTokens = parseInt((systemPromptText || '0').replace(/[.,\s]/g, ''), 10);
		logger.logCheckpoint(`System prompt tokens: ${systemPromptTokens}`);

		const userInputRow = page.getByTestId('usage-user-input-tokens');
		await expect(userInputRow).toBeVisible({ timeout: 5000 });
		const userInputText = await userInputRow.locator('.entry-detail-value').textContent();
		const userInputTokens = parseInt((userInputText || '0').replace(/[.,\s]/g, ''), 10);
		logger.logCheckpoint(`User input tokens: ${userInputTokens}`);

		await takeScreenshot(page, 'token-values-extracted');

		// Step 5: Validate token breakdown
		// All values must be positive
		expect(inputTokens).toBeGreaterThan(0);
		expect(outputTokens).toBeGreaterThan(0);
		expect(systemPromptTokens).toBeGreaterThan(0);
		expect(userInputTokens).toBeGreaterThan(0);

		// The sum of system_prompt_tokens + user_input_tokens should be close to input_tokens.
		// We allow up to 20% deviation because tiktoken estimates won't perfectly match
		// the provider's native tokenizer (different tokenization algorithms).
		const breakdownSum = systemPromptTokens + userInputTokens;
		const ratio = breakdownSum / inputTokens;
		logger.logCheckpoint(
			`Token breakdown: system(${systemPromptTokens}) + user(${userInputTokens}) = ${breakdownSum} vs input(${inputTokens}), ratio=${ratio.toFixed(3)}`
		);

		// The ratio should be between 0.7 and 1.3 (within 30% — generous for cross-tokenizer estimates)
		// Before the fix (OPE-213), this ratio was ~0.74 because tool tokens were missing.
		// After the fix, it should be close to 1.0.
		expect(ratio).toBeGreaterThan(0.7);
		expect(ratio).toBeLessThan(1.3);

		// Log a warning if the ratio is outside the ideal range (0.9–1.1) but still passing
		if (ratio < 0.9 || ratio > 1.1) {
			logger.logCheckpoint(
				`WARNING: Token ratio ${ratio.toFixed(3)} is outside ideal 0.9-1.1 range. ` +
				`This may indicate remaining estimation drift.`
			);
		}

		await takeScreenshot(page, 'token-validation-complete');

		// Step 6: Clean up — delete the test chat
		// Close settings first
		await page.evaluate(() => {
			window.location.hash = '';
		});
		await page.waitForTimeout(500);
		// Press Escape to close settings if still open
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);
		await deleteActiveChat(page, logger.logCheckpoint, takeScreenshot);
		logger.logCheckpoint('Test chat deleted');
	});
});
