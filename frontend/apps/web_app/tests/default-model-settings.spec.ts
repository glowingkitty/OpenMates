/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Default model settings E2E test.
 *
 * Tests the AI Ask default model settings flow:
 *
 * 1. Login with test account + 2FA
 * 2. Navigate to Settings → App Store → AI → Ask
 * 3. Toggle auto-select OFF → select "Mistral Small" for Simple requests
 * 4. Close settings, send "Capital of Germany?" and verify Mistral Small is used
 * 5. Re-open settings, toggle auto-select back ON
 * 6. Start new chat, send same question, verify a different model is used (not Mistral Small)
 * 7. Cleanup: reset to auto-select, delete test chats
 *
 * This test validates:
 * - The auto-select toggle saves immediately when switched on/off
 * - Selecting a specific model in the dropdown persists and is used for the next message
 * - Switching back to auto-select uses a different (auto-selected) model
 * - Notifications appear only for real value changes and include descriptive change text
 *
 * Architecture context: docs/architecture/ai_model_selection.md
 * Component: frontend/packages/ui/src/components/settings/AiAskSkillSettings.svelte
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
	generateTotp,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Navigate to AI Ask skill settings via the settings menu.
 * Path: Settings → App Store → AI → Ask
 */
async function navigateToAiAskSettings(
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

	const settingsMenu = page.locator('.settings-menu.visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(800);
	await takeStepScreenshot(page, `${stepLabel}-settings-open`);

	// 2. Click "App Store" menu item
	const appStoreItem = settingsMenu.getByRole('menuitem', { name: /app store/i }).first();
	await expect(appStoreItem).toBeVisible({ timeout: 5000 });
	await appStoreItem.click();
	logCheckpoint('Clicked App Store menu item.');
	await page.waitForTimeout(800);
	await takeStepScreenshot(page, `${stepLabel}-app-store`);

	// 3. Click the "AI" app
	// The AI app might be a card or a menu item depending on the layout.
	// Try finding it by text matching "AI" within the settings menu.
	const aiAppItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
	const aiAppVisible = await aiAppItem.isVisible({ timeout: 3000 }).catch(() => false);

	if (aiAppVisible) {
		await aiAppItem.click();
		logCheckpoint('Clicked AI app menu item.');
	} else {
		// Try the app card approach
		const aiCard = settingsMenu.locator('.app-card').filter({ hasText: /^AI$/i }).first();
		const aiCardVisible = await aiCard.isVisible({ timeout: 3000 }).catch(() => false);
		if (aiCardVisible) {
			await aiCard.click();
			logCheckpoint('Clicked AI app card.');
		} else {
			// Try "Show all apps" first
			const showAllApps = settingsMenu
				.getByRole('menuitem', { name: /show all|all apps/i })
				.first();
			const showAllVisible = await showAllApps.isVisible({ timeout: 3000 }).catch(() => false);
			if (showAllVisible) {
				await showAllApps.click();
				logCheckpoint('Clicked "Show all apps".');
				await page.waitForTimeout(800);
			}
			// Now find AI
			const aiMenuItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
			await expect(aiMenuItem).toBeVisible({ timeout: 5000 });
			await aiMenuItem.click();
			logCheckpoint('Clicked AI menu item after showing all apps.');
		}
	}

	await page.waitForTimeout(800);
	await takeStepScreenshot(page, `${stepLabel}-ai-app`);

	// 4. Click "Ask" skill
	const askSkillItem = settingsMenu.getByRole('menuitem', { name: /ask/i }).first();
	await expect(askSkillItem).toBeVisible({ timeout: 5000 });
	await askSkillItem.click();
	logCheckpoint('Clicked Ask skill menu item.');
	await page.waitForTimeout(800);

	// 5. Verify AI Ask Settings page loaded
	const aiAskSettings = page.locator('.ai-ask-settings');
	await expect(aiAskSettings).toBeVisible({ timeout: 8000 });
	logCheckpoint('AI Ask Settings page loaded.');
	await takeStepScreenshot(page, `${stepLabel}-ai-ask-settings`);
}

/**
 * Close the settings panel by clicking the settings toggle again.
 */
async function closeSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const settingsToggle = page.locator('#settings-menu-toggle');
	const settingsMenu = page.locator('.settings-menu.visible');
	const isSettingsOpen = await settingsMenu.isVisible().catch(() => false);

	if (isSettingsOpen) {
		await settingsToggle.click();
		logCheckpoint('Clicked settings toggle to close settings.');
		await page.waitForTimeout(500);
	} else {
		logCheckpoint('Settings already closed.');
	}
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
	stepLabel: string
): Promise<string> {
	// Type the question
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(withMockMarker(question, 'default_model_settings'));
	logCheckpoint(`Typed question: "${question}"`);
	await takeStepScreenshot(page, `${stepLabel}-question-typed`);

	// Click send button
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	logCheckpoint('Clicked send button.');
	await takeStepScreenshot(page, `${stepLabel}-message-sent`);

	// Wait for URL to update to new chat ID
	logCheckpoint('Waiting for URL to update to new chat ID...');
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatUrl = page.url();
	const chatIdMatch = chatUrl.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logCheckpoint(`Navigated to chat: ${chatId}`);

	// Wait for the assistant response to complete (generated-by element appears after streaming ends)
	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = page.locator('.message-wrapper.assistant').last();
	await expect(assistantMessage).toBeVisible({ timeout: 10000 });

	const generatedByElement = assistantMessage.locator('.generated-by-container .generated-by');
	await expect(generatedByElement).toBeVisible({ timeout: 90000 });
	logCheckpoint('Response complete - generated-by element visible.');
	await takeStepScreenshot(page, `${stepLabel}-response-complete`);

	const generatedByText = await generatedByElement.textContent();
	logCheckpoint(`Generated by text: "${generatedByText}"`);

	return generatedByText || '';
}

// ─── Test ────────────────────────────────────────────────────────────────────

test('change default model to Mistral Small, verify it is used, then switch back to auto', async ({
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

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting default model settings test.', { email: TEST_EMAIL });

	// =========================================================================
	// PHASE 1: Login
	// =========================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// =========================================================================
	// PHASE 2: Navigate to AI Ask settings and set Mistral Small as default
	// =========================================================================
	logCheckpoint('Phase 2: Navigating to AI Ask settings...');
	await navigateToAiAskSettings(page, logCheckpoint, takeStepScreenshot, '02');

	// Find the auto-select toggle in the AI Ask settings page.
	// The toggle wrapper is inside the settings-content of the Default Models section.
	const settingsMenu = page.locator('.settings-menu.visible');
	const aiAskSettings = settingsMenu.locator('.ai-ask-settings');

	// The auto-select toggle is a Toggle component wrapped in a clickable div.
	// The toggle's aria-label is the i18n text for "Auto-select model".
	// We target the outer clickable wrapper div (parent of the pointer-events:none div).
	const autoSelectRow = aiAskSettings.locator('.setting-row').first();
	await expect(autoSelectRow).toBeVisible({ timeout: 5000 });

	// Check if auto-select is currently ON (toggle is checked)
	const toggleInput = autoSelectRow.locator('input[type="checkbox"]');
	const isAutoOn = await toggleInput.evaluate((el: HTMLInputElement) => el.checked);
	logCheckpoint(`Auto-select toggle is currently: ${isAutoOn ? 'ON' : 'OFF'}`);

	if (isAutoOn) {
		// Click the toggle wrapper to turn auto-select OFF
		const toggleWrapper = autoSelectRow.locator('[role="button"]').first();
		await toggleWrapper.click();
		logCheckpoint('Toggled auto-select OFF.');
		await page.waitForTimeout(1000);
	}

	await takeStepScreenshot(page, '02-auto-select-off');

	// Toggling OFF auto-select without changing any values should NOT trigger save/notification
	const noChangeNotification = page.locator('.notification');
	await page.waitForTimeout(1200);
	await expect(noChangeNotification).toHaveCount(0);
	logCheckpoint('No notification after toggling auto-select OFF with unchanged values (expected).');

	// The model dropdowns should now be visible
	const simpleDropdown = aiAskSettings.locator('#default-simple-select');
	await expect(simpleDropdown).toBeVisible({ timeout: 5000 });
	logCheckpoint('Simple requests dropdown is visible.');

	// Select "Mistral Small" in the Simple requests dropdown.
	// The value format is "provider_id/model_id" = "mistral/mistral-small-latest"
	await simpleDropdown.selectOption({ label: 'Mistral Small' });
	logCheckpoint('Selected "Mistral Small" in Simple requests dropdown.');
	await page.waitForTimeout(1000);

	await takeStepScreenshot(page, '02-mistral-small-selected');

	// Verify success notification appears with descriptive change text
	const notification2 = page.locator('.notification');
	await expect(notification2).toBeVisible({ timeout: 5000 });
	await expect(notification2).toContainText(
		"Changed model for Simple requests from 'Auto' to 'Mistral Small'"
	);
	logCheckpoint('Descriptive success notification appeared after selecting Mistral Small.');

	// Wait for notification to disappear
	await page.waitForTimeout(3000);

	// Close settings
	await closeSettings(page, logCheckpoint);
	await page.waitForTimeout(500);

	// =========================================================================
	// PHASE 3: Send a message and verify Mistral Small is used
	// =========================================================================
	logCheckpoint('Phase 3: Sending message to verify Mistral Small is used...');

	// Start a new chat for a clean state
	await startNewChat(page, logCheckpoint);

	const generatedByText1 = await sendMessageAndGetModel(
		page,
		'Capital of Germany?',
		logCheckpoint,
		takeStepScreenshot,
		'03'
	);

	// Verify the response was generated by Mistral Small
	expect(generatedByText1.toLowerCase()).toContain('mistral small');
	logCheckpoint(`Verified: response was generated by Mistral Small. Text: "${generatedByText1}"`);

	// Verify the response contains the expected answer
	const assistantMessage1 = page.locator('.message-wrapper.assistant').last();
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
	await navigateToAiAskSettings(page, logCheckpoint, takeStepScreenshot, '04');

	// The auto-select toggle should be OFF now. Toggle it back ON.
	const autoSelectRow2 = aiAskSettings.locator('.setting-row').first();
	await expect(autoSelectRow2).toBeVisible({ timeout: 5000 });

	const toggleInput2 = autoSelectRow2.locator('input[type="checkbox"]');
	const isAutoOn2 = await toggleInput2.evaluate((el: HTMLInputElement) => el.checked);
	logCheckpoint(`Auto-select toggle is currently: ${isAutoOn2 ? 'ON' : 'OFF'}`);

	if (!isAutoOn2) {
		const toggleWrapper2 = autoSelectRow2.locator('[role="button"]').first();
		await toggleWrapper2.click();
		logCheckpoint('Toggled auto-select back ON.');
		await page.waitForTimeout(1000);
	}

	await takeStepScreenshot(page, '04-auto-select-on');

	// Wait for the success notification with descriptive change text
	const notification3 = page.locator('.notification');
	await expect(notification3).toBeVisible({ timeout: 5000 });
	await expect(notification3).toContainText(
		"Changed model for Simple requests from 'Mistral Small' to 'Auto'"
	);
	logCheckpoint('Descriptive success notification appeared after toggling auto-select ON.');

	// Wait for notification to dismiss
	await page.waitForTimeout(3000);

	// Verify the dropdowns are no longer visible (auto-select is ON)
	const simpleDropdown2 = aiAskSettings.locator('#default-simple-select');
	await expect(simpleDropdown2).not.toBeVisible({ timeout: 3000 });
	logCheckpoint('Dropdowns hidden - auto-select is ON.');

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
		'05'
	);

	// Verify the model used is NOT Mistral Small (auto-select should pick a different model)
	// Auto-select typically picks premium/standard models for simple requests, not economy tier Mistral Small.
	expect(generatedByText2.toLowerCase()).not.toContain('mistral small');
	logCheckpoint(
		`Verified: auto-select used a different model (not Mistral Small). Text: "${generatedByText2}"`
	);

	// Verify the response still contains the expected answer
	const assistantMessage2 = page.locator('.message-wrapper.assistant').last();
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
