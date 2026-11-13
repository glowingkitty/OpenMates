/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Default model settings E2E test.
 *
 * Tests the AI default model settings flow:
 *
 * 1. Login with test account + 2FA
 * 2. Navigate to Settings → AI
 * 3. Open the Simple requests tier editor → select "Mistral Small 4"
 * 4. Close settings, send "Capital of Germany?" and verify Mistral Small 4 is used
 * 5. Re-open settings, verify the selection persisted, switch back to Auto
 * 6. Start new chat, send same question, verify a different model is used (not Mistral Small 4)
 * 7. Cleanup: reset to auto-select, delete test chats
 *
 * This test validates:
 * - Choosing Auto or an exact model in the tier editor saves immediately
 * - Selecting a specific model in the tier editor persists and is used for the next message
 * - Switching back to auto-select uses a different (auto-selected) model
 * - The overview row shows the saved selection and keeps it after re-opening settings
 *
 * Architecture context: docs/architecture/ai_model_selection.md
 * Components: SettingsAI.svelte, AiTierSettings.svelte
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */
export {};

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
	deleteActiveChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const MISTRAL_MODEL_NAME = 'Mistral Small 4';

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Navigate to AI settings via the settings menu.
 * Path: Settings → AI (top-level)
 */
async function navigateToAiSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	// 1. Open settings menu
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	await settingsToggle.click();
	logCheckpoint('Opened settings menu.');

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(800);
	await takeStepScreenshot(page, `${stepLabel}-settings-open`);

	// 2. Click "AI" top-level menu item
	const aiMenuItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
	await expect(aiMenuItem).toBeVisible({ timeout: 5000 });
	await aiMenuItem.click();
	logCheckpoint('Clicked AI menu item.');
	await page.waitForTimeout(800);

	// 3. Verify AI Settings page loaded
	const aiSettings = page.getByTestId('ai-settings');
	await expect(aiSettings).toBeVisible({ timeout: 8000 });
	logCheckpoint('AI Settings page loaded.');
	await takeStepScreenshot(page, `${stepLabel}-ai-settings`);
}

/**
 * Close the settings panel by clicking the settings toggle again.
 */
async function closeSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	const isSettingsOpen = await settingsMenu.isVisible().catch(() => false);

	if (isSettingsOpen) {
		// Click the close button (data-testid="icon-button-close") inside the settings toggle.
		// Clicking #settings-menu-toggle directly fails because the close-icon-container
		// intercepts pointer events when settings are open.
		const closeButton = page.getByTestId('icon-button-close');
		await closeButton.click({ timeout: 5000 });
		logCheckpoint('Closed settings.');
		await page.waitForTimeout(500);
	} else {
		logCheckpoint('Settings already closed.');
	}
}

/**
 * Open the Simple requests tier editor from the AI settings overview.
 */
async function openSimpleTierEditor(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	const modifyButton = settingsMenu
		.getByTestId('ai-settings')
		.getByTestId('ai-tier-row-simple-modify-button');
	await modifyButton.scrollIntoViewIfNeeded();
	await modifyButton.click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'ai/tier/simple', {
		timeout: 10000
	});
	await expect(settingsMenu.getByTestId('ai-tier-provider-catalog')).toBeVisible({
		timeout: 10000
	});
	logCheckpoint('Opened Simple requests tier editor.');
}

/**
 * Go back through settings pages until the AI settings overview is visible.
 */
async function backToAiOverview(page: any): Promise<void> {
	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	for (let i = 0; i < 4; i += 1) {
		if (await settingsMenu.getByTestId('ai-settings').isVisible().catch(() => false)) return;
		await settingsMenu.getByTestId('banner-back-button').click({ timeout: 5000 });
		await page.waitForTimeout(500);
	}
	await expect(settingsMenu.getByTestId('ai-settings')).toBeVisible({ timeout: 5000 });
}

/**
 * Send a message and wait for the assistant response to complete.
 * Returns the "generated by" text which contains the model name.
 */
async function sendMessageAndGetModel(
	page: any,
	question: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string,
	fixtureId: string
): Promise<string> {
	await sendMessage(
		page,
		withMockMarker(question, fixtureId),
		logCheckpoint,
		takeStepScreenshot,
		stepLabel
	);

	// Wait for URL to update to new chat ID
	logCheckpoint('Waiting for URL to update to new chat ID...');
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatUrl = page.url();
	const chatIdMatch = chatUrl.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logCheckpoint(`Navigated to chat: ${chatId}`);

	// Wait for the assistant response to complete (generated-by element appears after streaming ends)
	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = await waitForAssistantMessage(page, {
		which: 'last',
		logCheckpoint
	});

	// Wait for substantive content before checking for generated-by
	await expect(async () => {
		const msgText = await assistantMessage.textContent();
		expect((msgText || '').trim().length).toBeGreaterThan(5);
	}).toPass({ timeout: 60000, intervals: [2000, 3000, 5000] });

	const generatedByElement = assistantMessage.getByTestId('generated-by');
	await expect(generatedByElement).toBeVisible({ timeout: 90000 });
	logCheckpoint('Response complete - generated-by element visible.');
	await takeStepScreenshot(page, `${stepLabel}-response-complete`);

	const generatedByText = await generatedByElement.textContent();
	logCheckpoint(`Generated by text: "${generatedByText}"`);

	return generatedByText || '';
}

// ─── Test ────────────────────────────────────────────────────────────────────

// contract-test: supporting surface=gui.web assertions=ai-model-routing.preferences.exclusive-tier-defaults,ai-model-routing.precedence.chat-over-tier-over-auto
test('change default model to Mistral Small 4, verify it is used, then switch back to auto', async ({
	page
}: {
	page: any;
}) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	test.slow();
	test.setTimeout(300000); // 5 minutes: covers settings navigation + two chat rounds + cleanup

	const logCheckpoint = createSignupLogger('DEFAULT_MODEL_SETTINGS');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'default-model'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting default model settings test.', { email: TEST_EMAIL });

	// =========================================================================
	// PHASE 1: Login
	// =========================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// =========================================================================
	// PHASE 2: Navigate to AI Ask settings and set Mistral Small 4 as default
	// =========================================================================
	logCheckpoint('Phase 2: Navigating to AI settings...');
	await navigateToAiSettings(page, logCheckpoint, takeStepScreenshot, '02');

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	const aiSettings = settingsMenu.getByTestId('ai-settings');
	const simpleRow = aiSettings.getByTestId('ai-tier-row-simple');
	await expect(simpleRow).toBeVisible({ timeout: 5000 });
	await expect(simpleRow).toContainText('Auto');
	logCheckpoint('Simple requests default starts as Auto.');

	await openSimpleTierEditor(page, logCheckpoint);
	const tierCatalog = settingsMenu.getByTestId('ai-tier-provider-catalog');
	await tierCatalog.getByTestId('ai-provider-family-card').filter({ hasText: /Mistral/i }).click();
	await expect(settingsMenu).toHaveAttribute(
		'data-active-view',
		'ai/tier/simple/provider/mistral',
		{ timeout: 10000 }
	);

	// Older models are collapsed behind a button; expand it if the model is not listed yet.
	const mistralOption = settingsMenu
		.getByTestId('ai-model-option-exact')
		.filter({ hasText: MISTRAL_MODEL_NAME });
	const showOld = settingsMenu.getByTestId('ai-tier-show-old-models');
	if (!(await mistralOption.isVisible().catch(() => false)) && (await showOld.isVisible().catch(() => false))) {
		await showOld.click();
	}
	await expect(mistralOption).toBeVisible({ timeout: 10000 });
	await mistralOption.getByTestId('ai-model-option-exact-toggle').click();
	await expect(mistralOption.locator('input[type="checkbox"]')).toBeChecked({ timeout: 5000 });
	logCheckpoint('Selected "Mistral Small 4" for Simple requests.');
	await takeStepScreenshot(page, '02-mistral-small-selected');

	// The overview row shows the saved selection.
	await backToAiOverview(page);
	await expect(aiSettings.getByTestId('ai-tier-row-simple')).toContainText(MISTRAL_MODEL_NAME, {
		timeout: 5000
	});
	logCheckpoint('Simple requests row shows Mistral Small 4.');

	// Close settings
	await closeSettings(page, logCheckpoint);
	await page.waitForTimeout(500);

	// =========================================================================
	// PHASE 3: Send a message and verify Mistral Small 4 is used
	// =========================================================================
	logCheckpoint('Phase 3: Sending message to verify Mistral Small 4 is used...');

	// Start a new chat for a clean state
	await startNewChat(page, logCheckpoint);

	const generatedByText1 = await sendMessageAndGetModel(
		page,
		'Capital of Germany?',
		logCheckpoint,
		takeStepScreenshot,
		'03',
		'default_model_mistral'
	);

	// Verify the response was generated by Mistral Small 4
	expect(generatedByText1.toLowerCase()).toContain('mistral small 4');
	logCheckpoint(`Verified: response was generated by Mistral Small 4. Text: "${generatedByText1}"`);

	// Verify the response contains the expected answer
	const assistantMessage1 = page.getByTestId('message-assistant').last();
	await expect(assistantMessage1).toContainText('Berlin', { timeout: 15000 });
	logCheckpoint('Verified response contains "Berlin".');

	// Remember this chat for later cleanup
	const chatUrl1 = page.url();
	const chatId1Match = chatUrl1.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId1 = chatId1Match ? chatId1Match[1] : 'unknown';
	logCheckpoint(`Chat 1 ID: ${chatId1}`);

	// =========================================================================
	// PHASE 4: Switch back to auto-select
	// =========================================================================
	logCheckpoint('Phase 4: Switching back to auto-select...');
	await navigateToAiSettings(page, logCheckpoint, takeStepScreenshot, '04');
	const settingsMenu2 = page.locator('[data-testid="settings-menu"].visible');
	const aiSettings2 = settingsMenu2.getByTestId('ai-settings');

	// The selection persisted across closing and re-opening settings.
	await expect(aiSettings2.getByTestId('ai-tier-row-simple')).toContainText(MISTRAL_MODEL_NAME, {
		timeout: 5000
	});
	logCheckpoint('Mistral Small 4 selection persisted after re-opening settings.');

	await openSimpleTierEditor(page, logCheckpoint);
	const autoOption = settingsMenu2.getByTestId('ai-model-option-auto');
	await autoOption.getByTestId('ai-model-option-auto-toggle').click();
	await expect(autoOption.locator('input[type="checkbox"]')).toBeChecked({ timeout: 5000 });
	logCheckpoint('Switched Simple requests back to Auto.');
	await takeStepScreenshot(page, '04-auto-select-on');

	await backToAiOverview(page);
	await expect(aiSettings2.getByTestId('ai-tier-row-simple')).not.toContainText(
		MISTRAL_MODEL_NAME,
		{ timeout: 5000 }
	);
	await expect(aiSettings2.getByTestId('ai-tier-row-simple')).toContainText('Auto');
	logCheckpoint('Simple requests row shows Auto again.');

	// Close settings
	await closeSettings(page, logCheckpoint);
	await page.waitForTimeout(500);

	// =========================================================================
	// PHASE 5: Send another message and verify auto-select uses a DIFFERENT model
	// =========================================================================
	logCheckpoint('Phase 5: Sending message to verify auto-select uses a different model...');

	// Start a new chat
	await startNewChat(page, logCheckpoint);

	const generatedByText2 = await sendMessageAndGetModel(
		page,
		'Capital of Germany?',
		logCheckpoint,
		takeStepScreenshot,
		'05',
		'default_model_auto'
	);

	// Verify the model used is NOT Mistral Small 4 (auto-select should pick a different model)
	// Auto-select typically picks premium/standard models for simple requests, not economy tier Mistral Small 4.
	expect(generatedByText2.toLowerCase()).not.toContain('mistral small 4');
	logCheckpoint(
		`Verified: auto-select used a different model (not Mistral Small 4). Text: "${generatedByText2}"`
	);

	// Verify the response still contains the expected answer
	const assistantMessage2 = page.getByTestId('message-assistant').last();
	await expect(assistantMessage2).toContainText('Berlin', { timeout: 15000 });
	logCheckpoint('Verified response contains "Berlin".');

	// =========================================================================
	// PHASE 6: Cleanup - delete both test chats
	// =========================================================================
	logCheckpoint('Phase 6: Cleaning up test chats...');

	// Delete the second chat (currently active)
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup');

	// Navigate back to the first chat and delete it
	if (chatId1 !== 'unknown') {
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
		await page.goto(`${baseUrl}/#chat-id=${chatId1}`);
		await page.waitForTimeout(3000);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup');
	}

	logCheckpoint('Default model settings test completed successfully.');
});
