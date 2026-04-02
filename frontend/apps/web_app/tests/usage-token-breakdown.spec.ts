/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Usage token breakdown E2E test (OPE-213, OPE-257).
 *
 * Validates that after sending a chat message, the billing usage detail view
 * displays a correct receipt-style token breakdown where:
 *   - Without app skills: system_prompt + user_input ≈ total input
 *   - With app skills: system_prompt + user_input + app_skills = total input
 *
 * Uses the &usage deep-link parameter (#settings/billing&usage) to auto-navigate
 * to the most recent usage entry's detail view.
 *
 * Bug history this test suite guards against:
 * - OPE-213: calculate_token_breakdown() was not receiving `tools` parameter in
 *   8 of 10 provider clients, causing tool definition tokens (~13K) to be missing
 *   from system_prompt_tokens. Fixed by adding tools=tools to all calls.
 * - OPE-257: Token breakdown displayed cumulative input_tokens (across all LLM
 *   iterations) alongside last-iteration-only system_prompt/user_input, making
 *   the numbers not add up. Fixed with receipt-style layout: sub-items + computed
 *   "App skills (×N)" row always sum to the total.
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

	test('receipt-style breakdown: sub-items sum to total input', async ({ page }, testInfo) => {
		test.setTimeout(120000); // 2 minutes — AI inference + usage fetch
		const logStep = createSignupLogger('USAGE_TOKENS');
		const takeScreenshot = createStepScreenshotter(logStep, { filenamePrefix: 'usage-token-breakdown' });
		await archiveExistingScreenshots(logStep);

		// Step 1: Login
		await loginToTestAccount(page, logStep, takeScreenshot);
		logStep('Logged in successfully');

		// Step 2: Start a new chat and send a message
		await startNewChat(page, logStep, takeScreenshot);
		logStep('Started new chat');

		// Send a simple message that triggers AI inference with tool definitions
		await sendMessage(page, 'What is the capital of France?', logStep, takeScreenshot);
		logStep('Message sent, waiting for AI response');

		// Wait for AI response to complete (final message appears)
		const aiResponse = page.getByTestId('message-assistant').last();
		await expect(aiResponse).toBeVisible({ timeout: 60000 });
		// Wait for the response to finish streaming (status becomes synced)
		await page.waitForTimeout(5000);
		logStep('AI response received');
		await takeScreenshot(page, 'ai-response-received');

		// Step 3: Navigate to billing settings via UI
		const settingsToggle = page.locator('#settings-menu-toggle');
		await expect(settingsToggle).toBeVisible({ timeout: 10000 });
		await settingsToggle.click();
		logStep('Opened settings menu');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 8000 });

		// Wait for menu items to load
		await expect(
			settingsMenu.locator('[data-testid="menu-item"][role="menuitem"]').first()
		).toBeVisible({ timeout: 15000 });

		// Click billing
		const billingItem = settingsMenu
			.locator('[data-testid="menu-item"][role="menuitem"]')
			.filter({ hasText: /billing/i });
		await expect(billingItem).toBeVisible({ timeout: 10000 });
		await billingItem.click();
		logStep('Navigated to Billing');
		await takeScreenshot(page, 'billing-page');

		// Wait for usage overview to load (the "Usage" section in billing)
		// The overview shows daily items — wait for at least one entry to appear
		await page.waitForTimeout(3000); // Allow API fetch to complete

		// Click the first usage item in the overview (most recent chat)
		// These are SettingsItem components rendered as clickable menu items
		const firstUsageEntry = settingsMenu
			.locator('[data-testid="menu-item"][role="menuitem"]')
			.filter({ hasText: /request/ })
			.first();
		await expect(firstUsageEntry).toBeVisible({ timeout: 15000 });
		await firstUsageEntry.click();
		logStep('Clicked first usage entry (drill into chat entries)');
		await takeScreenshot(page, 'chat-entries-list');

		// Wait for chat entries to load, then click the first entry to see detail
		await page.waitForTimeout(2000);
		const firstChatEntry = settingsMenu.locator('button.detail-entry.clickable').first();
		await expect(firstChatEntry).toBeVisible({ timeout: 10000 });
		await firstChatEntry.click();
		logStep('Clicked first chat entry to see detail view');

		// Wait for usage detail view to appear
		const usageDetailView = page.getByTestId('usage-detail-view');
		await expect(usageDetailView).toBeVisible({ timeout: 10000 });
		logStep('Usage detail view is visible');
		await takeScreenshot(page, 'usage-detail-view');

		// Step 4: Extract token values from the receipt-style breakdown
		// All rows use data-testid on the row and data-testid="entry-value" on the value span

		// Total input tokens (bold row with separator)
		const inputTokensRow = page.getByTestId('usage-input-tokens');
		await expect(inputTokensRow).toBeVisible({ timeout: 10000 });
		const inputTokensText = await inputTokensRow.getByTestId('entry-value').textContent();
		const inputTokens = parseInt((inputTokensText || '0').replace(/[.,\s]/g, ''), 10);
		logStep(`Total input tokens: ${inputTokens}`);

		// Output tokens (AI response)
		const outputTokensRow = page.getByTestId('usage-output-tokens');
		await expect(outputTokensRow).toBeVisible({ timeout: 5000 });
		const outputTokensText = await outputTokensRow.getByTestId('entry-value').textContent();
		const outputTokens = parseInt((outputTokensText || '0').replace(/[.,\s]/g, ''), 10);
		logStep(`Output tokens (AI response): ${outputTokens}`);

		// System prompt tokens
		const systemPromptRow = page.getByTestId('usage-system-prompt-tokens');
		await expect(systemPromptRow).toBeVisible({ timeout: 5000 });
		const systemPromptText = await systemPromptRow.getByTestId('entry-value').textContent();
		const systemPromptTokens = parseInt((systemPromptText || '0').replace(/[.,\s]/g, ''), 10);
		logStep(`System prompt tokens: ${systemPromptTokens}`);

		// User input tokens (your input)
		const userInputRow = page.getByTestId('usage-user-input-tokens');
		await expect(userInputRow).toBeVisible({ timeout: 5000 });
		const userInputText = await userInputRow.getByTestId('entry-value').textContent();
		const userInputTokens = parseInt((userInputText || '0').replace(/[.,\s]/g, ''), 10);
		logStep(`User input tokens: ${userInputTokens}`);

		// App skill tokens (optional — only shown when tool iterations > 0)
		const appSkillRow = page.getByTestId('usage-app-skill-tokens');
		let appSkillTokens = 0;
		const appSkillVisible = await appSkillRow.isVisible().catch(() => false);
		if (appSkillVisible) {
			const appSkillText = await appSkillRow.getByTestId('entry-value').textContent();
			appSkillTokens = parseInt((appSkillText || '0').replace(/[.,\s]/g, ''), 10);
			logStep(`App skill tokens: ${appSkillTokens}`);

			// When app skills row is visible, the hint should also be visible
			const appSkillsHint = page.getByTestId('usage-app-skills-hint');
			await expect(appSkillsHint).toBeVisible({ timeout: 3000 });
			logStep('App skills hint is visible');
		} else {
			logStep('No app skill tokens row (no tool iterations — expected for simple queries)');
		}

		await takeScreenshot(page, 'token-values-extracted');

		// Step 5: Validate receipt-style breakdown
		// All base values must be positive
		expect(inputTokens).toBeGreaterThan(0);
		expect(outputTokens).toBeGreaterThan(0);
		expect(systemPromptTokens).toBeGreaterThan(0);
		expect(userInputTokens).toBeGreaterThan(0);

		// Receipt validation: sub-items must sum to the total input.
		// system_prompt + user_input + app_skills = total_input
		// We allow up to 30% deviation because tiktoken estimates won't perfectly
		// match the provider's native tokenizer (different tokenization algorithms).
		// The app_skills row is computed as: total - system - user, so when it's
		// present the sum is exact. When absent (no tool iterations), we compare
		// system + user against total directly.
		const breakdownSum = systemPromptTokens + userInputTokens + appSkillTokens;
		const ratio = breakdownSum / inputTokens;
		logStep(
			`Receipt breakdown: system(${systemPromptTokens}) + user(${userInputTokens}) + app_skills(${appSkillTokens}) = ${breakdownSum} vs total_input(${inputTokens}), ratio=${ratio.toFixed(3)}`
		);

		if (appSkillTokens > 0) {
			// When app skills row is present, the sum must be exact (it's computed as the difference)
			expect(breakdownSum).toBe(inputTokens);
			logStep('App skills present — breakdown sums exactly to total (computed row)');
		} else {
			// Without app skills: system + user ≈ input (within 30% for tiktoken estimation drift)
			expect(ratio).toBeGreaterThan(0.7);
			expect(ratio).toBeLessThan(1.3);

			if (ratio < 0.9 || ratio > 1.1) {
				logStep(
					`WARNING: Token ratio ${ratio.toFixed(3)} is outside ideal 0.9-1.1 range. ` +
					`This may indicate remaining estimation drift.`
				);
			}
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
		await deleteActiveChat(page, logStep, takeScreenshot);
		logStep('Test chat deleted');
	});
});
