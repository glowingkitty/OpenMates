/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.

/**
 * Settings → Buy Credits — Polar (non-EU card) flow test.
 *
 * WHAT THIS TESTS:
 * - Logs in with a pre-existing test account.
 * - Opens Settings → Billing → Buy Credits.
 * - Selects a credit tier (first available).
 * - Accepts payment consent toggle.
 * - Clicks "Pay with a non-EU card" to switch from Stripe to Polar.
 * - Verifies the Polar pay button appears.
 * - Clicks the Polar pay button → Polar checkout overlay (iframe) loads.
 * - Fills in the Polar sandbox test card (4242 4242 4242 4242).
 * - Submits the Polar checkout form.
 * - Verifies "purchase successful" message on the main page.
 *
 * ARCHITECTURE NOTES:
 * - The settings buy-credits flow uses SettingsBuyCreditsPayment.svelte which has
 *   a "Pay with a non-EU card" button that triggers provider override to Polar.
 * - After switching, Payment.svelte renders a single .polar-pay-button.
 * - Clicking it calls PolarEmbedCheckout.create() → appends a full-screen iframe.
 * - Polar uses Stripe's test infrastructure in sandbox, so Stripe test cards work.
 *
 * POLAR SANDBOX TEST CARD:
 * - Card: 4242 4242 4242 4242 | Expiry: 12/34 | CVC: 123
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL (or slot-based variant)
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL (base URL of the deployed dev web app)
 *
 * POLAR VAULT PREREQUISITE:
 * - Polar secrets must be in Vault at kv/data/providers/polar.
 * - Without these, ?provider_override=polar falls back to 'stripe' and this test skips.
 *
 * SKIP CONDITIONS:
 * - Test account env vars are not set.
 * - Polar is not configured in Vault on this environment.
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

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

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const PLAYWRIGHT_TEST_BASE_URL =
	process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';

// Polar uses Stripe's test infrastructure in sandbox mode — Stripe test cards work.
const POLAR_SANDBOX_TEST_CARD = '4242424242424242';

/**
 * Check whether the Polar payment provider is active on this environment.
 * Calls /v1/payments/config?provider_override=polar and checks the response.
 * Returns true only when provider === 'polar' (not the Stripe fallback).
 */
async function isPolarConfigured(baseUrl: string): Promise<boolean> {
	try {
		const apiBaseUrl = baseUrl.replace('app.', 'api.').replace(/\/$/, '');
		const response = await fetch(`${apiBaseUrl}/v1/payments/config?provider_override=polar`, {
			headers: { 'Content-Type': 'application/json' }
		});
		if (!response.ok) return false;
		const data = await response.json();
		return data?.provider === 'polar';
	} catch {
		return false;
	}
}

// ---------------------------------------------------------------------------
// Test: Settings → Buy Credits → Polar (non-EU card) full checkout
// ---------------------------------------------------------------------------

test('settings buy credits: completes full Polar (non-EU card) purchase flow', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	// Allow extra time for Polar checkout overlay + payment processing.
	test.setTimeout(300000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	// ─── Skip guards ─────────────────────────────────────────────────────────────

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	// Skip if Polar is not configured in Vault on this environment.
	const polarReady = await isPolarConfigured(PLAYWRIGHT_TEST_BASE_URL);
	if (!polarReady) {
		test.skip(
			true,
			'Polar is not configured in Vault — add polar secrets to kv/data/providers/polar in Vault.'
		);
		return;
	}

	const log = createSignupLogger('SETTINGS_BUY_CREDITS_POLAR');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'settings-polar' });
	await archiveExistingScreenshots(log);

	log('Polar provider confirmed active in environment.');

	// ─── Login ────────────────────────────────────────────────────────────────────

	await loginToTestAccount(page, log, screenshot);
	// Allow auth state + decryption to fully propagate before navigating to settings.
	await page.waitForTimeout(4000);

	// ─── Open Settings ───────────────────────────────────────────────────────────

	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	log('Opened settings menu.');

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });

	// Wait for credits balance — confirms authenticated state fully loaded.
	await expect(page.locator('[data-testid="settings-menu"].visible [data-testid="credits-container"]')).toBeVisible({
		timeout: 15000
	});
	await screenshot(page, 'settings-menu-open');

	// ─── Navigate: Settings → Billing → Buy Credits ───────────────────────────────

	const billingItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /billing/i });
	await expect(billingItem).toBeVisible({ timeout: 10000 });
	await billingItem.click();
	log('Navigated to Billing.');
	await screenshot(page, 'billing-page');

	const buyCreditsItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /buy credits/i });
	await expect(buyCreditsItem).toBeVisible({ timeout: 10000 });
	await buyCreditsItem.click();
	log('Navigated to Buy Credits.');
	await screenshot(page, 'buy-credits-page');

	// Verify pricing tiers are rendered
	await expect(async () => {
		const tierItems = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]');
		const count = await tierItems.count();
		expect(count).toBeGreaterThanOrEqual(3);
	}).toPass({ timeout: 15000 });
	log('Pricing tiers visible.');
	await screenshot(page, 'pricing-tiers');

	// ─── Select first pricing tier ────────────────────────────────────────────────

	const firstTier = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]').first();
	await expect(firstTier).toBeVisible({ timeout: 5000 });
	await firstTier.click();
	log('Selected first pricing tier.');
	await screenshot(page, 'tier-selected');

	// ─── Switch to Polar ────────────────────────────────────────────────────────
	// Two possible states after tier selection:
	//
	// A) Saved Stripe payment methods exist (returning user):
	//    → Saved methods list is shown with a "Pay with a non-EU card" button.
	//    → Click the button directly to switch to Polar.
	//
	// B) No saved payment methods (fresh account / new card flow):
	//    → Stripe payment form is shown immediately (no consent screen — user
	//      already consented during signup). Click "Pay with a non-EU card".
	//
	// Note: The refund consent screen was removed from the credits purchase flow
	// because users already accept the refund policy during signup.

	const switchToPolarButton = page.getByRole('button', { name: /pay with a non-eu card/i });

	// Wait for the "Pay with a non-EU card" button to appear (present in both flows).
	await expect(switchToPolarButton).toBeVisible({ timeout: 20000 });

	await assertNoMissingTranslations(page);

	await switchToPolarButton.click();
	await screenshot(page, 'switch-to-polar-clicked');
	log('Clicked "Pay with a non-EU card" button — Polar provider activated.');

	// ─── Polar pay button ─────────────────────────────────────────────────────────
	// After switching, Payment.svelte renders a .polar-pay-button (no Stripe fields).

	const polarBuyButton = page.getByTestId('polar-pay-button');
	await expect(polarBuyButton).toBeVisible({ timeout: 20000 });
	await screenshot(page, 'polar-pay-button-visible');
	log('Polar pay button visible.');

	await assertNoMissingTranslations(page);

	const paymentSubmittedAt = new Date().toISOString();
	await polarBuyButton.click();
	log('Clicked Polar pay button — waiting for Polar checkout overlay iframe.');

	// ─── Polar checkout overlay (iframe) ─────────────────────────────────────────
	// PolarEmbedCheckout.create() appends a full-screen iframe to document.body.
	// Src matches polar.sh or sandbox.polar.sh checkout URLs.

	const polarIframe = page.frameLocator('iframe[src*="polar.sh"], iframe[src*="sandbox.polar.sh"]');

	// Wait for the card input inside the iframe to become visible.
	// Polar uses Stripe's payment form internally in sandbox mode.
	const polarCardInput = polarIframe
		.locator('input[name="cardNumber"], input[autocomplete="cc-number"], [placeholder*="1234"]')
		.first();
	await expect(polarCardInput).toBeVisible({ timeout: 60000 });
	await screenshot(page, 'polar-checkout-overlay-visible');
	log('Polar checkout overlay visible with card input.');

	// ─── Fill Polar checkout card details ─────────────────────────────────────────

	await polarCardInput.fill(POLAR_SANDBOX_TEST_CARD);

	const polarExpiryInput = polarIframe
		.locator('input[name="cardExpiry"], input[autocomplete="cc-exp"], [placeholder*="MM"]')
		.first();
	await polarExpiryInput.fill('12/34');

	const polarCvcInput = polarIframe
		.locator(
			'input[name="cardCvc"], input[autocomplete="cc-csc"], [placeholder*="CVC"], [placeholder*="123"]'
		)
		.first();
	await polarCvcInput.fill('123');

	await screenshot(page, 'polar-card-filled');
	log('Polar sandbox card details filled.');

	// ─── Submit Polar checkout ────────────────────────────────────────────────────

	const polarSubmitButton = polarIframe
		.getByRole('button', { name: /pay|subscribe|complete/i })
		.first();
	await expect(polarSubmitButton).toBeVisible({ timeout: 15000 });
	await polarSubmitButton.click();
	log('Submitted Polar checkout form — waiting for success confirmation.');

	// ─── Verify purchase success ──────────────────────────────────────────────────
	// After Polar processes the payment, our Payment.svelte → ProcessingPayment
	// transitions to the success state and shows "purchase successful".

	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 120000 });
	await screenshot(page, 'purchase-success');
	log('Polar purchase confirmed successful.', { paymentSubmittedAt });

	await assertNoMissingTranslations(page);
	log('Test complete.');
});
