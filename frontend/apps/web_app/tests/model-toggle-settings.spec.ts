/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Model enable/disable toggle persistence E2E test.
 *
 * Tests that toggling AI models on/off in Settings → AI → Ask is saved
 * and persists when closing and re-opening settings.
 *
 * 1. Login with test account + 2FA
 * 2. Navigate to Settings → App Store → AI → Ask
 * 3. Find the first model and toggle it OFF
 * 4. Close settings, re-open, navigate back to AI Ask
 * 5. Verify the model is still OFF (toggle persisted to IndexedDB)
 * 6. Toggle it back ON (cleanup)
 * 7. Verify the toggle is ON again
 *
 * Bug history this test suite guards against:
 * - OPE-53 (2026-03-28): disabled_ai_models and disabled_ai_servers were never
 *   written to or read from IndexedDB in userDB.ts, causing toggles to reset.
 *   Fix: added write handlers in updateUserData() and read handlers in getUserProfile().
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
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
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Navigate to AI Ask skill settings via the settings menu.
 * Path: Settings → App Store → AI → Ask
 */
async function navigateToAiAskSettings(
	page: any,
	logFn: (msg: string) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	// Dismiss any overlays (notifications, tooltips) that might block clicks
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);

	// Only click the settings toggle if the menu isn't already open
	const settingsMenu = page.getByTestId('settings-menu');
	const alreadyOpen = await settingsMenu.isVisible().catch(() => false);
	if (!alreadyOpen) {
		const settingsToggle = page.locator('#settings-menu-toggle');
		await expect(settingsToggle).toBeVisible({ timeout: 10000 });
		await settingsToggle.click({ timeout: 10000 });
	} else {
		logFn('Settings menu already open, skipping toggle click.');
	}

	const settingsMenuVisible = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenuVisible).toBeVisible({ timeout: 10000 });
	logFn('Opened settings menu.');
	await page.waitForTimeout(800);

	// Click "App Store" menu item
	const appStoreItem = settingsMenu.getByRole('menuitem', { name: /app store/i }).first();
	await expect(appStoreItem).toBeVisible({ timeout: 5000 });
	await appStoreItem.click();
	logFn('Clicked App Store.');
	await page.waitForTimeout(800);

	// Click the "AI" app
	const aiAppItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
	const aiAppVisible = await aiAppItem.isVisible({ timeout: 3000 }).catch(() => false);

	if (aiAppVisible) {
		await aiAppItem.click();
		logFn('Clicked AI app.');
	} else {
		// Try "Show all apps" first
		const showAllApps = settingsMenu
			.getByRole('menuitem', { name: /show all|all apps/i })
			.first();
		const showAllVisible = await showAllApps.isVisible({ timeout: 3000 }).catch(() => false);
		if (showAllVisible) {
			await showAllApps.click();
			logFn('Clicked "Show all apps".');
			await page.waitForTimeout(800);
		}
		const aiMenuItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
		await expect(aiMenuItem).toBeVisible({ timeout: 5000 });
		await aiMenuItem.click();
		logFn('Clicked AI app after showing all.');
	}

	await page.waitForTimeout(800);

	// Click "Ask" skill
	const askSkillItem = settingsMenu.getByRole('menuitem', { name: /ask/i }).first();
	await expect(askSkillItem).toBeVisible({ timeout: 5000 });
	await askSkillItem.click();
	logFn('Clicked Ask skill.');
	await page.waitForTimeout(800);

	// Verify AI Ask settings loaded
	const aiAskSettings = page.getByTestId('ai-ask-settings');
	await expect(aiAskSettings).toBeVisible({ timeout: 8000 });
	logFn('AI Ask Settings page loaded.');
	await takeStepScreenshot(page, `${stepLabel}-ai-ask-settings`);
}

/**
 * Close the settings panel.
 * Uses data-testid only (not the .visible CSS class) to avoid false negatives
 * when Svelte re-renders cause the class to flicker after model toggle interactions.
 */
async function closeSettings(page: any, logFn: (msg: string) => void): Promise<void> {
	// Check if the settings content is visible (more reliable than .visible CSS class)
	const settingsContent = page.getByTestId('settings-menu');
	const isOpen = await settingsContent.isVisible().catch(() => false);

	if (isOpen) {
		const settingsToggle = page.locator('#settings-menu-toggle');
		// Dismiss any potential overlays (notifications, tooltips) before clicking
		await page.keyboard.press('Escape');
		await page.waitForTimeout(300);
		await settingsToggle.click({ timeout: 10000 });
		logFn('Closed settings.');
		// Wait for close animation to complete
		await page.waitForTimeout(800);
	} else {
		logFn('Settings already closed (not detected as open).');
	}
}

// ─── Test ────────────────────────────────────────────────────────────────────

test.describe('Model toggle persistence (OPE-53)', () => {
	test.describe.configure({ timeout: 120000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('disabling a model persists after closing and re-opening settings', async ({ page }) => {
		const logCheckpoint = createSignupLogger('MODEL_TOGGLE');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'model-toggle'
		});

		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);
		await archiveExistingScreenshots(logCheckpoint);

		// ── Step 1: Login ──────────────────────────────────────────────
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		logCheckpoint('Login complete.');

		// ── Step 2: Navigate to AI Ask settings ────────────────────────
		await navigateToAiAskSettings(page, logCheckpoint, takeStepScreenshot, '02');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		const aiAskSettings = settingsMenu.getByTestId('ai-ask-settings');

		// ── Step 3: Find the first model toggle and record initial state ─
		// Each model in the list has a .model-toggle wrapper containing a Toggle checkbox
		const modelItems = aiAskSettings.getByTestId('model-item');
		const firstModelItem = modelItems.first();
		await expect(firstModelItem).toBeVisible({ timeout: 5000 });

		// Get the model name for logging
		const modelName = await firstModelItem.getByTestId('model-name').textContent();
		logCheckpoint(`Target model: "${modelName}"`);

		// Get initial toggle state
		const firstToggle = firstModelItem.locator('input[type="checkbox"]');
		const wasEnabled = await firstToggle.evaluate((el: HTMLInputElement) => el.checked);
		logCheckpoint(`Initial state: ${wasEnabled ? 'enabled' : 'disabled'}`);

		// Ensure the model starts as enabled (if not, toggle it on first)
		if (!wasEnabled) {
			// model-toggle div itself has role="button" and onclick — click it directly
			const toggleWrapper = firstModelItem.getByTestId('model-toggle');
			await toggleWrapper.click();
			logCheckpoint('Pre-toggled model ON so we can test disabling it.');
			await page.waitForTimeout(1000);
		}

		await takeStepScreenshot(page, '03-before-toggle');

		// ── Step 4: Toggle the model OFF ───────────────────────────────
		// model-toggle div itself has role="button" and onclick — click it directly
		const toggleWrapper = firstModelItem.getByTestId('model-toggle');
		await toggleWrapper.click();
		logCheckpoint('Toggled model OFF.');
		await page.waitForTimeout(1000);

		// Verify toggle is now unchecked
		const isNowOff = await firstToggle.evaluate((el: HTMLInputElement) => !el.checked);
		expect(isNowOff).toBe(true);
		logCheckpoint('Verified toggle is OFF in UI.');

		// Verify the model item has the disabled class
		await expect(firstModelItem).toHaveClass(/disabled/);
		logCheckpoint('Model item has disabled class.');
		await takeStepScreenshot(page, '04-toggled-off');

		// ── Step 5: Close settings, re-open, verify persistence ───────
		await closeSettings(page, logCheckpoint);
		await page.waitForTimeout(1000);

		await navigateToAiAskSettings(page, logCheckpoint, takeStepScreenshot, '05');

		// Re-locate the model by name (DOM was destroyed and recreated)
		const modelItemsAfter = settingsMenu.getByTestId('ai-ask-settings').getByTestId('model-item');
		const targetModelAfter = modelItemsAfter.filter({ hasText: modelName! });
		await expect(targetModelAfter).toBeVisible({ timeout: 5000 });

		// Verify the toggle persisted as OFF
		const toggleAfter = targetModelAfter.locator('input[type="checkbox"]');
		const isStillOff = await toggleAfter.evaluate((el: HTMLInputElement) => !el.checked);
		expect(isStillOff).toBe(true);
		logCheckpoint(`Persistence verified: "${modelName}" is still OFF after re-opening settings.`);

		// Verify the model item still has the disabled class
		await expect(targetModelAfter).toHaveClass(/disabled/);
		await takeStepScreenshot(page, '05-persisted-off');

		// ── Step 6: Cleanup — toggle the model back ON ────────────────
		// model-toggle div itself has role="button" and onclick — click it directly
		const cleanupToggle = targetModelAfter.getByTestId('model-toggle');
		await cleanupToggle.click();
		logCheckpoint('Cleanup: toggled model back ON.');
		await page.waitForTimeout(1000);

		// Verify it's back on
		const isBackOn = await toggleAfter.evaluate((el: HTMLInputElement) => el.checked);
		expect(isBackOn).toBe(true);
		logCheckpoint('Verified model is back ON.');
		await takeStepScreenshot(page, '06-cleanup-on');

		// Close settings
		await closeSettings(page, logCheckpoint);
		logCheckpoint('Model toggle persistence test completed successfully.');
	});
});
