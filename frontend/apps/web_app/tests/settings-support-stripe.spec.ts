/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.

/**
 * Settings → Support → One-Time — Stripe card payment flow test.
 *
 * WHAT THIS TESTS:
 * - Logs in with a pre-existing test account.
 * - Opens Settings → Support → One-Time.
 * - Selects a donation amount (€5 — smallest available, fastest to process).
 * - Verifies the Stripe Payment Element iframe loads correctly.
 * - Fills in a Stripe EU test card (Finland 4000 0024 6000 0001 — required
 *   by Radar "block non-EU cards" rule).
 * - Submits the payment form.
 * - Verifies the success confirmation screen appears.
 *
 * ARCHITECTURE NOTES:
 * - Support payments use POST /v1/payments/create-support-order (Stripe always).
 *   The Payment.svelte component handles the Stripe element.
 * - geo-detection: GHA runners have US IPs → API may return managed payments by default.
 *   We use page.route() to force provider=stripe so the EU Stripe form loads.
 * - No credits are granted (credits_amount=0), no invoice PDF generated.
 *   A receipt email is sent to the support_email address.
 *
 * STRIPE TEST CARD (EU card — required by Radar rule):
 *   4000 0024 6000 0001 | Finland | Expiry: 12/34 | CVC: 123
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL / PASSWORD / OTP_KEY
 *
 * SKIP CONDITIONS:
 * - Test account env vars not set.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	fillStripeCardDetails,
	getTestAccount,
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
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const STRIPE_TEST_CARD = '4000002460000001'; // Finland EU card

// ─────────────────────────────────────────────────────────────────────────────
// Test: Settings → Support → One-Time → Stripe card donation
// ─────────────────────────────────────────────────────────────────────────────

test('settings support: completes one-time donation via Stripe card', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
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

	// ─── Skip guards ──────────────────────────────────────────────────────────

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SETTINGS_SUPPORT_STRIPE');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'support-stripe' });
	await archiveExistingScreenshots(log);

	// ─── Force Stripe EU provider (GHA has US IPs → defaults to Managed Payments) ────
	// Hardcoded response to avoid route.fetch() HTML error from GHA's IP.
	// The Stripe publishable key is intentionally public (pk_test_* prefix).
	await page.route('**/v1/payments/config', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				provider: 'stripe',
				public_key: 'pk_test_51RG0OnRxFvyhqY5pj03qMj6CnWrmI2Thcm8RkEBo7zHIJ7bobKs9jCwcbF0tcNUcP9fcswKSYs01kTqyIJsFMkMr00k9PWB2ZP',
				environment: 'sandbox',
				bank_transfer_available: false,
			}),
		});
	});

	// ─── Login ────────────────────────────────────────────────────────────────

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(4000);

	// ─── Open Settings ────────────────────────────────────────────────────────

	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	log('Opened settings menu.');

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });
	await expect(
		page.locator('[data-testid="settings-menu"].visible [data-testid="credits-row"]')
	).toBeVisible({ timeout: 15000 });
	await screenshot(page, '01-settings-menu-open');

	// ─── Navigate: Support → One-Time ────────────────────────────────────────

	const supportItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /support/i });
	await expect(supportItem).toBeVisible({ timeout: 10000 });
	await supportItem.click();
	log('Navigated to Support.');
	await screenshot(page, '02-support-page');

	const oneTimeItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /one.time|one time/i });
	await expect(oneTimeItem).toBeVisible({ timeout: 10000 });
	await oneTimeItem.click();
	log('Navigated to Support → One-Time.');
	await screenshot(page, '03-support-one-time');

	// ─── Select €5 tier ──────────────────────────────────────────────────────

	const fiveEurItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.getByText('€5', { exact: true });
	await expect(fiveEurItem).toBeVisible({ timeout: 10000 });
	await fiveEurItem.click();
	log('Selected €5 donation tier.');
	await screenshot(page, '04-tier-selected');

	// ─── Wait for Stripe Payment Element iframe ───────────────────────────────

	// For authenticated users, payment form auto-starts.
	const stripeIframe = page.frameLocator('iframe[title="Secure payment input frame"]');
	await expect(
		stripeIframe.locator('input[name="number"], input[name="cardNumber"], input[autocomplete="cc-number"]').first()
	).toBeVisible({ timeout: 30000 });
	log('Stripe Payment Element iframe loaded.');
	await screenshot(page, '05-stripe-form-loaded');

	// ─── Fill Stripe card details ─────────────────────────────────────────────

	await fillStripeCardDetails(page, STRIPE_TEST_CARD);
	log('Filled Stripe card details.');
	await screenshot(page, '06-card-filled');

	// ─── Submit payment ───────────────────────────────────────────────────────

	// Find and click the submit button (PaymentForm renders "Send X EUR" for support contributions)
	const submitButton = page.locator('button[type="submit"], button').filter({ hasText: /send|pay/i }).last();
	await expect(submitButton).toBeEnabled({ timeout: 10000 });
	await submitButton.click();
	log('Submitted payment form.');
	await screenshot(page, '07-payment-submitted');

	// ─── Wait for success ─────────────────────────────────────────────────────

	// Success: confirmation screen or "purchase successful" text
	const successIndicator = page.locator('text=/thank|success|received|support.*received|confirmation/i').first();
	await expect(successIndicator).toBeVisible({ timeout: 60000 });
	log('Success confirmation shown.');
	await screenshot(page, '08-success');

	log('✅ Support Stripe card donation test passed.');
});
