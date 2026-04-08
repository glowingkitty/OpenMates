/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.

/**
 * Settings → Buy Credits — Stripe (EU card) flow test.
 *
 * WHAT THIS TESTS:
 * - Logs in with a pre-existing test account.
 * - Opens Settings → Billing → Buy Credits.
 * - Selects a credit tier (first available).
 * - Handles geo-detection: Playwright runs from a US IP → API returns provider=polar.
 *   When the Polar Checkout iframe appears, clicks "Pay with an EU card instead" to
 *   switch the backend to Stripe. When running from EU geo, Stripe loads directly.
 * - Verifies the Stripe Payment Element iframe loads.
 * - Fills in the Stripe EU test card (4000 0024 6000 0001 Finland — passes Radar EU rule).
 * - Submits the Stripe payment form.
 * - Verifies "purchase successful" message on the main page.
 *
 * ARCHITECTURE NOTES:
 * - The settings buy-credits flow uses SettingsBuyCreditsPayment.svelte.
 * - The default provider is Stripe (EU geo-detection or fallback).
 * - After consent, Payment.svelte renders a Stripe Payment Element iframe
 *   (title="Secure payment input frame").
 * - Clicking "Pay" triggers POST /create-order → Stripe charges the card.
 * - On success, ProcessingPayment polls /poll-order until SUCCEEDED, then
 *   dispatches purchaseCompleted → "purchase successful" is shown.
 *
 * STRIPE TEST CARD (used here):
 * - Card: 4000 0024 6000 0001 (Finland/EU card — required by Radar "block non-EU" rule) | Expiry: 12/34 | CVC: 123
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL (or slot-based variant)
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 *
 * SKIP CONDITIONS:
 * - Test account env vars are not set.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	fillStripeCardDetails,
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

// Stripe test card: Finland (FI) EU card — required because Radar blocks non-EU cards.
// See: https://docs.stripe.com/testing#international-cards
const STRIPE_TEST_CARD = '4000002460000001';

// ---------------------------------------------------------------------------
// Test: Settings → Buy Credits → Stripe (EU card) full checkout
// ---------------------------------------------------------------------------

test('settings buy credits: completes full Stripe (EU card) purchase flow', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	// Allow extra time for Stripe payment processing + polling loop.
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

	const log = createSignupLogger('SETTINGS_BUY_CREDITS_STRIPE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'settings-stripe' });
	await archiveExistingScreenshots(log);

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
	await expect(page.locator('[data-testid="settings-menu"].visible [data-testid="credits-row"]')).toBeVisible({
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

	// ─── Payment form ───────────────────────────────────────────────────────────
	// The Playwright Docker container runs from a US IP address. The API geo-detects
	// non-EU → sets provider=polar. We must force Stripe regardless of geo.
	//
	// Strategy:
	//   1. Click "Add Payment Method" (or wait for an iframe to appear).
	//   2. If the Polar Checkout iframe appears first, click the "Pay with an EU card
	//      instead" button inside it — this switches the flow to Stripe on the backend.
	//   3. Once the Stripe Payment Element iframe loads, fill the test card.
	//   4. Submit and wait for "purchase successful".
	//
	// We always use the new-card path (no saved method) to avoid saved-method Buy Now
	// triggering a Polar order via geo detection.

	// Click "Add Payment Method" to open the payment form.
	// From a US IP (geo=non-EU), this opens the Polar Checkout instead of Stripe.
	// The Polar Checkout renders over the right panel and exposes a "Pay with an EU
	// card instead" button in the main DOM (but visually covered by the Polar iframe).
	// We force-click that button to switch the backend order to Stripe.
	const addPaymentMethodBtn = page.getByRole('button', { name: /add payment method/i });
	await expect(addPaymentMethodBtn).toBeVisible({ timeout: 15000 });
	await addPaymentMethodBtn.click();
	log('Clicked Add Payment Method button.');
	await screenshot(page, 'payment-screen');

	// Wait for either Stripe or Polar to initialise (either way an iframe appears).
	await page.waitForSelector('iframe', { state: 'attached', timeout: 20000 });

	// If the "Pay with an EU card instead" button is present (Polar flow from US geo),
	// use JavaScript dispatchEvent to click it. The button is in the main DOM but is
	// visually covered by the Polar Checkout iframe, so Playwright's click (even with
	// force=true) doesn't trigger the Svelte event handler. A programmatic dispatchEvent
	// bypasses the iframe overlay and fires the handler correctly.
	const euCardBtn = page.getByRole('button', { name: /pay with.*eu card instead/i });
	const isPolarFlow = await euCardBtn.isVisible({ timeout: 5000 }).catch(() => false);
	if (isPolarFlow) {
		await page.evaluate(() => {
			const buttons = document.querySelectorAll('button');
			for (const btn of buttons) {
				if (btn.textContent?.includes('EU card instead')) {
					btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
					btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
					btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
					break;
				}
			}
		});
		log('Polar flow detected. Dispatched JS click on "Pay with an EU card instead".');
		await page.waitForTimeout(3000);
		await screenshot(page, 'after-eu-switch');
	}

	// Now the Stripe Payment Element iframe should be present in the DOM.
	await page.waitForSelector('iframe[title="Secure payment input frame"]', {
		state: 'attached',
		timeout: 30000
	});
	log('Stripe Payment Element iframe loaded.');

	// Wait for the card input fields to become interactive.
	await page.waitForTimeout(2000);
	await screenshot(page, 'stripe-payment-form');

	await fillStripeCardDetails(page, STRIPE_TEST_CARD);
	await screenshot(page, 'stripe-card-filled');
	log('Stripe test card details filled.');

	const paymentSubmittedAt = new Date().toISOString();
	// The submit button is "Buy for X EUR" (exact text varies by tier).
	// Use type="submit" to avoid matching "Pay with a non-EU card" or "Payment" header.
	const stripePayButton = page
		.locator(
			'button[type="submit"].buy-button, button[type="submit"]:has-text("Buy for"), button[type="submit"]:has-text("Pay")'
		)
		.first();
	await expect(stripePayButton).toBeVisible({ timeout: 15000 });
	await expect(stripePayButton).toBeEnabled({ timeout: 10000 });
	await stripePayButton.click();
	log('Clicked Stripe Pay button — waiting for success confirmation.', {
		paymentSubmittedAt
	});

	// ─── Verify purchase success ──────────────────────────────────────────────────
	// ProcessingPayment polls /poll-order until status=SUCCEEDED, then emits
	// purchaseCompleted → Payment.svelte shows "purchase successful".

	await expect(page.getByText(/purchase successful/i).first()).toBeVisible({ timeout: 120000 });
	await screenshot(page, 'purchase-success');
	log('Purchase confirmed successful.');

	await assertNoMissingTranslations(page);
	log('Test complete.');
});
