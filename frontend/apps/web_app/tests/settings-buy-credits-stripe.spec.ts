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
 * - Accepts payment consent toggle.
 * - Stays on the Stripe provider (default for EU — no provider switch).
 * - Verifies the Stripe Payment Element iframe loads.
 * - Fills in the Stripe EU test card (4000002500003155 — requires 3DS auth).
 *   Uses the simpler success card (4242 4242 4242 4242) for sandbox flow.
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
 * - Card: 4242 4242 4242 4242 (always succeeds, no 3DS) | Expiry: 12/34 | CVC: 123
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL (or slot-based variant)
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 *
 * SKIP CONDITIONS:
 * - Test account env vars are not set.
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	fillStripeCardDetails,
	getTestAccount
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

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// Stripe test card that always succeeds in sandbox (no 3DS required).
const STRIPE_TEST_CARD = '4242424242424242';

/**
 * Log in with the pre-existing test account.
 * Handles the OTP retry loop (up to 3 attempts) to tolerate TOTP window boundary.
 */
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
	await expect(emailInput).toBeVisible({ timeout: 10000 });
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
				await page.waitForTimeout(31000); // Wait for next TOTP window
				await otpInput.fill('');
			} else if (!hasError) {
				loginSuccess = true;
			}
		}
	}
	await page.waitForURL(/chat/, { timeout: 20000 });
	logCheckpoint('Logged in to test account.');
}

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

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('SETTINGS_BUY_CREDITS_STRIPE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'settings-stripe' });
	await archiveExistingScreenshots(log);

	// ─── Login ────────────────────────────────────────────────────────────────────

	await loginToTestAccount(page, log, screenshot);
	// Allow auth state + decryption to fully propagate before navigating to settings.
	await page.waitForTimeout(4000);

	// ─── Open Settings ───────────────────────────────────────────────────────────

	const profileContainer = page.locator('.profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	log('Opened settings menu.');

	const settingsMenu = page.locator('.settings-menu.visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });

	// Wait for credits balance — confirms authenticated state fully loaded.
	await expect(page.locator('.settings-menu.visible .credits-container')).toBeVisible({
		timeout: 15000
	});
	await screenshot(page, 'settings-menu-open');

	// ─── Navigate: Settings → Billing → Buy Credits ───────────────────────────────

	const billingItem = page
		.locator('.settings-menu.visible .menu-item[role="menuitem"]')
		.filter({ hasText: /billing/i });
	await expect(billingItem).toBeVisible({ timeout: 10000 });
	await billingItem.click();
	log('Navigated to Billing.');
	await screenshot(page, 'billing-page');

	const buyCreditsItem = page
		.locator('.settings-menu.visible .menu-item[role="menuitem"]')
		.filter({ hasText: /buy credits/i });
	await expect(buyCreditsItem).toBeVisible({ timeout: 10000 });
	await buyCreditsItem.click();
	log('Navigated to Buy Credits.');
	await screenshot(page, 'buy-credits-page');

	// Verify pricing tiers are rendered
	await expect(async () => {
		const tierItems = page.locator('.settings-menu.visible .menu-item[role="menuitem"]');
		const count = await tierItems.count();
		expect(count).toBeGreaterThanOrEqual(3);
	}).toPass({ timeout: 15000 });
	log('Pricing tiers visible.');
	await screenshot(page, 'pricing-tiers');

	// ─── Select first pricing tier ────────────────────────────────────────────────

	const firstTier = page.locator('.settings-menu.visible .menu-item[role="menuitem"]').first();
	await expect(firstTier).toBeVisible({ timeout: 5000 });
	await firstTier.click();
	log('Selected first pricing tier.');
	await screenshot(page, 'tier-selected');

	// ─── Payment form ───────────────────────────────────────────────────────────
	// Two possible states after tier selection:
	//
	// A) Saved Stripe payment methods exist (returning user):
	//    → Saved methods list is shown with a "Add payment method" button.
	//    → Click "Add payment method" to reveal the fresh Payment component.
	//
	// B) No saved payment methods (fresh account):
	//    → Stripe payment form is shown immediately (no consent screen — user
	//      already consented during signup).
	//
	// Note: The refund consent screen was removed from the credits purchase flow
	// because users already accept the refund policy during signup.

	const addPaymentMethodBtn = page.getByRole('button', { name: /add payment method/i });

	// Wait for either the Stripe iframe or the "Add payment method" button.
	await page.waitForSelector('iframe, button:has-text("Add payment method")', {
		state: 'visible',
		timeout: 20000
	});

	const addMethodVisible = await addPaymentMethodBtn.isVisible();
	if (addMethodVisible) {
		// Flow A: click "Add payment method" to get the fresh Stripe form
		await addPaymentMethodBtn.click();
		log('Saved payment methods detected — clicked "Add payment method" to show fresh form.');
		await screenshot(page, 'add-payment-method-clicked');
	}

	await assertNoMissingTranslations(page);

	// ─── Verify Stripe Payment Element iframe loaded ──────────────────────────────
	// We stay on Stripe (the default EU provider). The Stripe Payment Element renders
	// as an iframe with title="Secure payment input frame" (or similar).

	// Wait for at least one Stripe iframe to appear.
	await expect(async () => {
		const iframes = await page.locator('iframe').count();
		expect(iframes).toBeGreaterThan(0);
	}).toPass({ timeout: 30000 });
	log('Stripe payment iframe loaded.');
	await screenshot(page, 'stripe-payment-form');

	// ─── Fill Stripe card details ─────────────────────────────────────────────────
	// fillStripeCardDetails() handles both the unified Payment Element iframe and
	// the legacy split-frame (number/expiry/CVC) layout.

	await fillStripeCardDetails(page, STRIPE_TEST_CARD);
	await screenshot(page, 'stripe-card-filled');
	log('Stripe test card details filled.');

	// ─── Submit Stripe payment ────────────────────────────────────────────────────
	// The Pay button is outside the Stripe iframe in our Payment.svelte component.
	// Button text comes from i18n key signup.buy_for → "Buy for {amount} {currency}"
	// e.g. "Buy for 2 EUR". Match broadly to handle any amount/currency combination.

	const paymentSubmittedAt = new Date().toISOString();
	const stripePayButton = page.getByRole('button', { name: /buy for|pay/i });
	await expect(stripePayButton).toBeVisible({ timeout: 15000 });
	await stripePayButton.click();
	log('Clicked Stripe Pay button — waiting for success confirmation.');

	// ─── Verify purchase success ──────────────────────────────────────────────────
	// ProcessingPayment polls /poll-order until status=SUCCEEDED, then emits
	// purchaseCompleted → Payment.svelte shows "purchase successful".

	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 120000 });
	await screenshot(page, 'purchase-success');
	log('Stripe purchase confirmed successful.', { paymentSubmittedAt });

	await assertNoMissingTranslations(page);
	log('Test complete.');
});
