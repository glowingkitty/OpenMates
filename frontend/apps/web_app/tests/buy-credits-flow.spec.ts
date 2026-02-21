/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Buy Credits Flow Tests
 *
 * Tests the billing/credits purchase flow in Settings > Billing > Buy Credits:
 * 1. Navigate to Buy Credits, verify pricing tiers render, click a tier,
 *    and verify the payment form loads (Stripe iframe appears).
 * 2. Verify the credits balance is displayed in the settings menu.
 *
 * NOTE: No actual payment is made — tests only verify up to the payment form
 * rendering. This avoids real card charges while still testing the full
 * navigation and form-loading regression.
 *
 * Architecture:
 * - Settings opened via `.profile-container` click.
 * - Navigation: main settings → "billing" item → "buy-credits" item.
 * - SettingsBuyCredits shows a list of SettingsItem pricing tiers.
 * - Clicking a tier dispatches `openSettings` event → navigates to
 *   `billing/buy-credits/payment` → loads SettingsBuyCreditsPayment with
 *   Stripe Payment Element iframe.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

async function loginToTestAccount(
	page: any,
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		await submitLoginButton.click();
		try {
			await expect(otpInput).not.toBeVisible({ timeout: 8000 });
			loginSuccess = true;
		} catch {
			const hasError = await errorMessage.isVisible();
			if (hasError && attempt < 3) {
				await page.waitForTimeout(31000);
				await otpInput.fill('');
			} else if (!hasError) {
				loginSuccess = true;
			}
		}
	}
	await page.waitForURL(/chat/, { timeout: 20000 });
	logCheckpoint('Logged in.');
}

// ---------------------------------------------------------------------------
// Test 1: Navigate to Buy Credits → verify tiers → click tier → payment form
// ---------------------------------------------------------------------------

test('navigates to buy credits, shows pricing tiers, and loads payment form on selection', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(240000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('BUY_CREDITS');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	// Wait for app to fully initialize after login (auth state propagation + decryption)
	await page.waitForTimeout(4000);

	// Open settings
	const profileContainer = page.locator('.profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	log('Opened settings menu.');

	const settingsMenu = page.locator('.settings-menu.visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });

	// Wait for credits balance to appear — confirms authenticated state is loaded
	// before trying to click billing (which only appears when authenticated)
	await expect(page.locator('.settings-menu.visible .credits-container')).toBeVisible({
		timeout: 15000
	});
	await screenshot(page, 'settings-menu-open');

	// Click "billing" settings item (visible only for authenticated users)
	const billingItem = page
		.locator('.settings-menu.visible .menu-item[role="menuitem"]')
		.filter({ hasText: /billing/i });
	await expect(billingItem).toBeVisible({ timeout: 10000 });
	await billingItem.click();
	log('Navigated to Billing.');
	await screenshot(page, 'billing-page');

	// Click "Buy Credits" submenu item
	const buyCreditsItem = page
		.locator('.settings-menu.visible .menu-item[role="menuitem"]')
		.filter({ hasText: /buy credits/i });
	await expect(buyCreditsItem).toBeVisible({ timeout: 10000 });
	await buyCreditsItem.click();
	log('Navigated to Buy Credits.');
	await screenshot(page, 'buy-credits-page');

	// Verify pricing tiers are rendered as SettingsItem submenu elements
	// Each tier shows a credit amount (e.g. "1.000") and a price (e.g. "€9")
	// They render as .menu-item[role="menuitem"] with credit + price text
	await expect(async () => {
		const tierItems = page.locator('.settings-menu.visible .menu-item[role="menuitem"]');
		const count = await tierItems.count();
		log(`Pricing tier items visible: ${count}`);
		expect(count).toBeGreaterThanOrEqual(3); // Expect at least 3 pricing tiers
	}).toPass({ timeout: 15000 });

	await screenshot(page, 'pricing-tiers');
	log('At least 3 pricing tiers are visible.');

	// Click the first pricing tier
	const firstTier = page.locator('.settings-menu.visible .menu-item[role="menuitem"]').first();
	await expect(firstTier).toBeVisible({ timeout: 5000 });
	log('Clicking first pricing tier...');
	await firstTier.click();

	await screenshot(page, 'after-tier-click');
	await page.waitForTimeout(3000); // Allow payment form to initialize

	// Look for any Stripe iframe on the page
	// Stripe renders iframes for the payment element (title="Secure payment input frame" or __privateStripe*)
	const iframeCount = await page.locator('iframe').count();
	log(`Iframes on page: ${iframeCount}`);

	// Verify at least one iframe loaded (Stripe payment element)
	await expect(async () => {
		const frames = await page.locator('iframe').count();
		expect(frames).toBeGreaterThan(0);
	}).toPass({ timeout: 30000 });

	await screenshot(page, 'payment-form-loaded');
	log('Payment form (Stripe iframe) loaded successfully.');

	// Verify no missing translations
	await assertNoMissingTranslations(page);

	// Use the back button to go back without paying
	const backButton = page.locator('.settings-menu.visible .icon_back.visible, button.nav-button');
	if (await backButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await backButton.click();
		log('Navigated back from payment form.');
	}

	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 2: Credits balance is shown in the settings main menu
// ---------------------------------------------------------------------------

test('shows current credit balance in settings main menu', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('CREDITS_BALANCE');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(2000);

	// Open settings
	const profileContainer = page.locator('.profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();

	const settingsMenu = page.locator('.settings-menu.visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });
	await screenshot(page, 'settings-open');

	// Verify credits balance is shown
	// CurrentSettingsPage renders: div.credits-container > span.credits-amount > mark (balance)
	const creditsContainer = page.locator('.settings-menu.visible .credits-container');
	await expect(creditsContainer).toBeVisible({ timeout: 10000 });

	const creditsAmount = page.locator('.settings-menu.visible .credits-amount');
	const creditsText = await creditsAmount.textContent();
	log(`Credits balance shown: "${creditsText}"`);

	// Credits text should contain a number (balance)
	expect(creditsText).toBeTruthy();
	expect(creditsText!.trim()).not.toBe('');

	await screenshot(page, 'credits-visible');
	log('Credits balance confirmed visible in settings menu.');

	await assertNoMissingTranslations(page);
	log('Test complete.');
});
