/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * AI settings breadcrumb + model/provider detail E2E test.
 *
 * Verifies the fixes for the AI settings page after it was moved to the
 * top-level settings section:
 *
 * 1. Clicking a model under "Available models" opens a detail page that
 *    uses the standard settings-banner-shell (same gradient header as
 *    Privacy / Billing / etc.).
 * 2. The back button from the model detail page returns to the AI
 *    settings page (not an intermediate "ai/model" route).
 * 3. Clicking a server provider under "Available providers" opens a
 *    provider detail page that lists the models hosted by that provider
 *    — informational only (no toggles, no nested links).
 * 4. Provider display names are simplified ("Anthropic" / "OpenAI",
 *    not "Anthropic API" / "OpenAI API").
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

async function navigateToAiSettings(
	page: any,
	logFn: (msg: string) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);

	const settingsMenu = page.getByTestId('settings-menu');
	const alreadyOpen = await settingsMenu.isVisible().catch(() => false);
	if (!alreadyOpen) {
		const settingsToggle = page.locator('#settings-menu-toggle');
		await expect(settingsToggle).toBeVisible({ timeout: 10000 });
		await settingsToggle.click({ timeout: 10000 });
	}

	const settingsMenuVisible = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenuVisible).toBeVisible({ timeout: 10000 });
	logFn('Opened settings menu.');
	await page.waitForTimeout(800);

	const aiMenuItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
	await expect(aiMenuItem).toBeVisible({ timeout: 5000 });
	await aiMenuItem.click();
	logFn('Clicked AI menu item.');
	await page.waitForTimeout(800);

	const aiSettings = page.getByTestId('ai-settings');
	await expect(aiSettings).toBeVisible({ timeout: 8000 });
	logFn('AI Settings page loaded.');
	await takeStepScreenshot(page, `${stepLabel}-ai-settings`);
}

test.describe('AI settings breadcrumb & detail pages', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('model and provider detail pages use banner shell and back returns to AI settings', async ({ page }) => {
		const logCheckpoint = createSignupLogger('AI_SETTINGS_BREADCRUMB');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'ai-settings-breadcrumb'
		});

		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);
		await archiveExistingScreenshots(logCheckpoint);

		// ── Step 1: Login ──────────────────────────────────────────────
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		logCheckpoint('Login complete.');

		// ── Step 2: Navigate to AI settings ────────────────────────────
		await navigateToAiSettings(page, logCheckpoint, takeStepScreenshot, '02');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		const aiSettings = settingsMenu.getByTestId('ai-settings');

		// ── Step 3: Verify section order (models before providers) ────
		// The Available models section should appear above the Available providers section
		// Grab bounding boxes of the first model-item and first provider-item and compare y.
		const firstModelItem = aiSettings.getByTestId('model-item').first();
		const firstProviderItem = aiSettings.getByTestId('provider-item').first();
		await expect(firstModelItem).toBeVisible({ timeout: 5000 });
		await expect(firstProviderItem).toBeVisible({ timeout: 5000 });
		const modelBox = await firstModelItem.boundingBox();
		const providerBox = await firstProviderItem.boundingBox();
		expect(modelBox).not.toBeNull();
		expect(providerBox).not.toBeNull();
		expect(modelBox!.y).toBeLessThan(providerBox!.y);
		logCheckpoint('Available models section is rendered above Available providers.');
		await takeStepScreenshot(page, '03-section-order');

		// ── Step 4: Provider names should not contain " API" ──────────
		const providerNames = await aiSettings
			.getByTestId('provider-item')
			.getByTestId('provider-name')
			.allTextContents();
		logCheckpoint(`Provider names rendered: ${JSON.stringify(providerNames)}`);
		for (const name of providerNames) {
			expect(name).not.toMatch(/\bAPI$/);
		}

		// ── Step 5: Click a model → should open detail page with banner-shell ─
		const modelName = await firstModelItem.getByTestId('model-name').textContent();
		logCheckpoint(`Opening model detail for "${modelName}"`);
		await firstModelItem.click();
		await page.waitForTimeout(800);

		// The settings-menu data-active-view attribute should now match ai/model/<id>
		await expect(settingsMenu).toHaveAttribute('data-active-view', /^ai\/model\//, { timeout: 5000 });
		logCheckpoint('Active view switched to ai/model/<id>.');

		// The banner shell should be rendered (same as standard sub-pages)
		const bannerShell = settingsMenu.getByTestId('settings-banner-shell');
		await expect(bannerShell.first()).toBeVisible({ timeout: 5000 });
		logCheckpoint('settings-banner-shell is visible on model detail page.');
		await takeStepScreenshot(page, '04-model-detail-banner');

		// ── Step 6: Back button returns to AI settings ────────────────
		const backButton = page.locator('#settings-back-button');
		await expect(backButton).toBeVisible();
		await backButton.click();
		await page.waitForTimeout(800);

		await expect(settingsMenu).toHaveAttribute('data-active-view', 'ai', { timeout: 5000 });
		await expect(aiSettings).toBeVisible({ timeout: 5000 });
		logCheckpoint('Back from model detail lands on AI settings page.');
		await takeStepScreenshot(page, '05-back-to-ai');

		// ── Step 7: Click a provider → should open provider detail ───
		const firstProvider = aiSettings.getByTestId('provider-item').first();
		const providerName = await firstProvider.getByTestId('provider-name').textContent();
		logCheckpoint(`Opening provider detail for "${providerName}"`);
		await firstProvider.click();
		await page.waitForTimeout(800);

		await expect(settingsMenu).toHaveAttribute('data-active-view', /^ai\/provider\//, { timeout: 5000 });
		const providerDetails = settingsMenu.getByTestId('ai-provider-details');
		await expect(providerDetails).toBeVisible({ timeout: 5000 });
		logCheckpoint('AI provider details page rendered.');

		// Banner shell visible on provider detail
		await expect(settingsMenu.getByTestId('settings-banner-shell').first()).toBeVisible();

		// Provider detail lists models (at least one)
		const providerModelItems = providerDetails.getByTestId('provider-model-item');
		await expect(providerModelItems.first()).toBeVisible({ timeout: 5000 });
		const count = await providerModelItems.count();
		expect(count).toBeGreaterThan(0);
		logCheckpoint(`Provider detail shows ${count} model(s).`);

		// Model entries on the provider page must be informational — no toggles
		const togglesInProviderDetail = await providerDetails.getByTestId('model-toggle').count();
		expect(togglesInProviderDetail).toBe(0);
		logCheckpoint('Provider detail models have no toggles (informational only).');
		await takeStepScreenshot(page, '06-provider-detail');

		// ── Step 8: Back from provider detail returns to AI settings ─
		await backButton.click();
		await page.waitForTimeout(800);
		await expect(settingsMenu).toHaveAttribute('data-active-view', 'ai', { timeout: 5000 });
		await expect(aiSettings).toBeVisible({ timeout: 5000 });
		logCheckpoint('Back from provider detail lands on AI settings page.');
		await takeStepScreenshot(page, '07-back-to-ai-from-provider');
	});
});
