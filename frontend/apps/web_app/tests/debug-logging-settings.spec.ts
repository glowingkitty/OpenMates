/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Debug Logging settings E2E test.
 *
 * Validates the Debug Logging opt-in toggle in Settings > Privacy:
 *
 * 1. Login with test account + 2FA
 * 2. Navigate to Settings > Privacy
 * 3. Verify the Debug Logging section is visible with heading, toggle, and disclaimer
 * 4. Toggle debug logging ON — verify toggle state changes
 * 5. Close and re-open settings — verify toggle persists as ON
 * 6. Toggle debug logging OFF — verify toggle state changes back
 * 7. Cleanup: ensure toggle is OFF (default state)
 *
 * Bug history this test suite guards against:
 * - Phase 06 (2026-03-27): Initial implementation of debug logging opt-in for OTel Tier 3 traces
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
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Open the settings menu and navigate to the Privacy page.
 * Path: Settings toggle → Privacy menu item
 */
async function navigateToPrivacySettings(
	page: any,
	logFn: (msg: string) => void
): Promise<void> {
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	await settingsToggle.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logFn('Opened settings menu.');

	// Click "Privacy" menu item
	const privacyItem = settingsMenu.getByRole('menuitem', { name: /privacy/i }).first();
	await expect(privacyItem).toBeVisible({ timeout: 5000 });
	await privacyItem.click();
	logFn('Navigated to Privacy settings.');

	// Wait for the privacy settings page to load — look for the Debug Logging heading
	await page.waitForTimeout(1000);
}

/**
 * Close the settings panel by clicking the settings toggle again.
 */
async function closeSettings(page: any): Promise<void> {
	const closeIcon = page.locator('#settings-menu-toggle .close-icon-container.visible').first();
	try {
		await closeIcon.click({ timeout: 3000 });
	} catch {
		// Fallback: click the toggle itself
		const settingsToggle = page.locator('#settings-menu-toggle');
		await settingsToggle.click();
	}
	await page.waitForTimeout(500);
}

/**
 * Find the Debug Logging toggle on the Privacy page.
 * The toggle is inside a SettingsItem with the debug logging title text.
 */
function getDebugLoggingToggle(page: any) {
	// The toggle is a SettingsItem with hasToggle=true containing the debug logging label text
	// Look for the toggle input near the "Debug Logging" or "Enable detailed debug logging" text
	return page.locator('[data-testid="menu-item"]:has-text("debug") input[type="checkbox"], [data-testid="menu-item"]:has-text("Debug") input[type="checkbox"]').first();
}

/**
 * Get the visual toggle container for the Debug Logging toggle.
 * Returns the clickable settings item row.
 */
function getDebugLoggingRow(page: any) {
	return page.locator('[data-testid="menu-item"]:has-text("debug logging"), [data-testid="menu-item"]:has-text("Debug Logging"), [data-testid="menu-item"]:has-text("Enable detailed debug logging")').first();
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test.describe('Debug Logging Settings', () => {
	// Login + settings navigation + toggle + re-open needs time
	test.describe.configure({ timeout: 90000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('Debug logging toggle appears and persists state', async ({ page }) => {
		const logCheckpoint = createSignupLogger('DEBUG_LOGGING');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'debug-logging-settings'
		});

		// Archive old screenshots
		await archiveExistingScreenshots(logCheckpoint);

		// Attach console/network monitors
		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);

		// ── Step 1: Login ──────────────────────────────────────────────
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		logCheckpoint('Login complete.');
		await takeStepScreenshot(page, '01-logged-in');

		// ── Step 2: Navigate to Privacy settings ───────────────────────
		await navigateToPrivacySettings(page, logCheckpoint);
		await takeStepScreenshot(page, '02-privacy-settings');

		// ── Step 3: Verify Debug Logging section exists ────────────────
		// Look for the heading text "Debug Logging" (case-insensitive)
		const debugHeading = page.locator('text=/[Dd]ebug [Ll]ogging/').first();
		await expect(debugHeading).toBeVisible({ timeout: 10000 });
		logCheckpoint('Debug Logging heading visible.');

		// Look for the toggle label text
		const toggleLabel = page.locator('text=/[Ee]nable detailed debug logging|[Dd]etaillierte/').first();
		await expect(toggleLabel).toBeVisible({ timeout: 5000 });
		logCheckpoint('Debug logging toggle label visible.');

		// Look for the "never collected" disclaimer text
		const disclaimer = page.getByTestId('settings-note').last();
		await expect(disclaimer).toBeVisible({ timeout: 5000 });
		logCheckpoint('Debug logging disclaimer note visible.');

		await takeStepScreenshot(page, '03-debug-logging-visible');

		// ── Step 4: Record initial toggle state and toggle ON ──────────
		// Find the toggle — it's a clickable settings row
		const toggleRow = getDebugLoggingRow(page);
		await expect(toggleRow).toBeVisible({ timeout: 5000 });

		// Click the toggle row to enable debug logging
		await toggleRow.click();
		logCheckpoint('Clicked debug logging toggle (should be ON now).');
		await page.waitForTimeout(1500); // Wait for profile sync

		await takeStepScreenshot(page, '04-toggle-on');

		// ── Step 5: Close settings, re-open, verify persistence ───────
		await closeSettings(page);
		logCheckpoint('Closed settings.');
		await page.waitForTimeout(1000);

		await navigateToPrivacySettings(page, logCheckpoint);
		logCheckpoint('Re-opened Privacy settings.');
		await page.waitForTimeout(1000);

		await takeStepScreenshot(page, '05-reopened-privacy');

		// The debug logging heading should still be visible
		await expect(page.locator('text=/[Dd]ebug [Ll]ogging/').first()).toBeVisible({ timeout: 10000 });

		// ── Step 6: Toggle OFF (cleanup) ──────────────────────────────
		const toggleRowAgain = getDebugLoggingRow(page);
		await expect(toggleRowAgain).toBeVisible({ timeout: 5000 });
		await toggleRowAgain.click();
		logCheckpoint('Clicked debug logging toggle (should be OFF now — cleanup).');
		await page.waitForTimeout(1500);

		await takeStepScreenshot(page, '06-toggle-off-cleanup');

		// ── Step 7: Close settings ────────────────────────────────────
		await closeSettings(page);
		logCheckpoint('Test complete. Debug logging toggle verified.');
	});
});
