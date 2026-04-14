/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.

/**
 * Settings → Support → One-Time — SEPA Bank Transfer flow test.
 *
 * WHAT THIS TESTS:
 * - Logs in with a pre-existing test account.
 * - Opens Settings → Support → One-Time.
 * - Selects a donation amount (€10).
 * - Clicks "Pay via Bank Transfer".
 * - Verifies bank details screen: IBAN, BIC, amount, reference, warning text.
 * - Verifies copy buttons function (text changes to "Copied!").
 * - Simulates transfer receipt by mocking the status polling endpoint to return
 *   { status: "completed" }, which exercises the polling→success path.
 * - Verifies success state is shown.
 *
 * MOCKING STRATEGY:
 * - POST /v1/payments/create-support-bank-transfer-order → mocked to return
 *   predictable bank details without needing Revolut Business Vault secrets.
 * - GET /v1/payments/bank-transfer-status/* → mocked to return "completed"
 *   on the second poll, triggering the success transition.
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

// Sandbox bank details returned by the mocked create-support-bank-transfer-order endpoint.
const MOCK_ORDER_ID = 'bt_test1234567890';
const MOCK_REFERENCE = 'OM-SUP-test1234';
const MOCK_IBAN = 'GB68REVO04290962398393';
const MOCK_BIC = 'REVOGB21';
const MOCK_AMOUNT_EUR = '10.00';

// ─────────────────────────────────────────────────────────────────────────────
// Test: Settings → Support → One-Time → SEPA bank transfer flow
// ─────────────────────────────────────────────────────────────────────────────

test('settings support: shows SEPA bank transfer details and transitions to success on receipt', async ({
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

	// ─── Skip guards ─────────────────────────────────────────────────────────

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SETTINGS_SUPPORT_BANK_TRANSFER');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'support-bank-transfer' });
	await archiveExistingScreenshots(log);

	// ─── Mock endpoints ───────────────────────────────────────────────────────

	// Mock: /config — return polar provider (no Stripe key needed) + bank_transfer_available=true.
	// Using polar avoids the "Stripe Public Key not found" error that would occur with an empty key.
	// We don't use route.fetch() because GHA's outbound IP may get an HTML error page from the
	// dev server's rate limiter, causing a JSON parse failure.
	await page.route('**/v1/payments/config', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				provider: 'polar',
				public_key: '',
				environment: 'sandbox',
				bank_transfer_available: true,
			}),
		});
	});

	// Mock: create-support-order (called by Payment.svelte when provider=polar).
	// Prevents network errors in the console while we wait for the bank transfer button.
	await page.route('**/v1/payments/create-support-order', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ provider: 'polar', order_id: 'mock_support_order', client_secret: '', checkout_url: '' }),
		});
	});

	// Mock: create order — returns predictable sandbox bank details.
	await page.route('**/v1/payments/create-support-bank-transfer-order', async (route: any) => {
		log('Intercepted create-support-bank-transfer-order request.');
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				order_id: MOCK_ORDER_ID,
				reference: MOCK_REFERENCE,
				iban: MOCK_IBAN,
				bic: MOCK_BIC,
				bank_name: 'Revolut Bank UAB',
				amount_eur: MOCK_AMOUNT_EUR,
				credits_amount: 0,
				expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
			}),
		});
	});

	// Mock: status polling — returns "pending" on first call, "completed" on second.
	// This exercises the polling→success transition without waiting for a real transfer.
	let statusPollCount = 0;
	await page.route(`**/v1/payments/bank-transfer-status/${MOCK_ORDER_ID}`, async (route: any) => {
		statusPollCount++;
		const status = statusPollCount >= 2 ? 'completed' : 'pending';
		log(`Status poll #${statusPollCount}: returning status="${status}"`);
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				order_id: MOCK_ORDER_ID,
				status,
				credits_amount: 0,
				amount_eur: MOCK_AMOUNT_EUR,
				reference: MOCK_REFERENCE,
				expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
				created_at: new Date().toISOString(),
			}),
		});
	});

	// ─── Login ────────────────────────────────────────────────────────────────

	await loginToTestAccount(page, log, screenshot);
	// Allow auth state + decryption to fully propagate before navigating to settings.
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

	// ─── Select €10 donation tier ─────────────────────────────────────────────

	// Use exact: true to avoid matching €100 (bank-transfer-only tier also shows in support).
	const tenEurItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.getByText('€10', { exact: true });
	await expect(tenEurItem).toBeVisible({ timeout: 10000 });
	await tenEurItem.click();
	log('Selected €10 donation tier.');
	await screenshot(page, '04-tier-selected');

	// For authenticated users, payment form auto-starts.
	// Wait for the "Pay via Bank Transfer" button to appear.
	const bankTransferBtn = page.getByTestId('support-switch-to-bank-transfer');
	await expect(bankTransferBtn).toBeVisible({ timeout: 15000 });
	await screenshot(page, '05-payment-form-with-bank-transfer-btn');
	log('Bank transfer button is visible alongside the payment form.');

	// ─── Switch to bank transfer ──────────────────────────────────────────────

	await bankTransferBtn.click();
	log('Clicked "Pay via Bank Transfer".');

	// ─── Verify bank transfer details screen ─────────────────────────────────

	const detailsContainer = page.getByTestId('bank-transfer-details');
	await expect(detailsContainer).toBeVisible({ timeout: 10000 });
	log('Bank transfer details screen is visible.');
	await screenshot(page, '06-bank-transfer-details');

	// IBAN row
	const ibanRow = page.getByTestId('bank-transfer-iban');
	await expect(ibanRow).toBeVisible({ timeout: 5000 });
	await expect(ibanRow).toContainText(MOCK_IBAN);
	log(`IBAN displayed: ${MOCK_IBAN}`);

	// BIC row
	const bicRow = page.getByTestId('bank-transfer-bic');
	await expect(bicRow).toBeVisible({ timeout: 5000 });
	await expect(bicRow).toContainText(MOCK_BIC);
	log(`BIC displayed: ${MOCK_BIC}`);

	// Amount row
	const amountRow = page.getByTestId('bank-transfer-amount');
	await expect(amountRow).toBeVisible({ timeout: 5000 });
	await expect(amountRow).toContainText(MOCK_AMOUNT_EUR);
	log(`Amount displayed: €${MOCK_AMOUNT_EUR}`);

	// Reference row — most critical field
	const referenceRow = page.getByTestId('bank-transfer-reference');
	await expect(referenceRow).toBeVisible({ timeout: 5000 });
	await expect(referenceRow).toContainText(MOCK_REFERENCE);
	log(`Reference displayed: ${MOCK_REFERENCE}`);

	// Reference warning must be present
	const referenceWarning = page.getByTestId('reference-warning');
	await expect(referenceWarning).toBeVisible({ timeout: 5000 });
	log('Reference warning is visible.');

	// Awaiting status indicator
	const awaitingStatus = page.getByTestId('bank-transfer-awaiting');
	await expect(awaitingStatus).toBeVisible({ timeout: 5000 });
	log('Awaiting transfer status indicator is visible.');
	await screenshot(page, '07-all-details-verified');

	// ─── Test copy buttons ────────────────────────────────────────────────────

	// Copy reference button (most important — user must include this)
	const copyReferenceBtn = page.getByTestId('copy-reference-btn');
	await expect(copyReferenceBtn).toBeVisible({ timeout: 5000 });
	await copyReferenceBtn.click();
	// Button text should briefly change to "Copied!"
	await expect(copyReferenceBtn).toContainText(/copied/i, { timeout: 3000 });
	log('Copy reference button works — shows "Copied!" feedback.');
	await screenshot(page, '08-copy-reference-clicked');

	// Copy IBAN button
	const copyIbanBtn = page.getByTestId('copy-iban-btn');
	await expect(copyIbanBtn).toBeVisible({ timeout: 5000 });
	await copyIbanBtn.click();
	await expect(copyIbanBtn).toContainText(/copied/i, { timeout: 3000 });
	log('Copy IBAN button works.');

	// ─── Wait for success state (mocked polling) ──────────────────────────────
	// The component polls /bank-transfer-status/<id> every 30 seconds.
	// Poll #1 (t=30s) → pending. Poll #2 (t=60s) → completed.
	// On completed, BankTransferPayment dispatches paymentStateChange {state:'success'}
	// → the parent (SettingsSupportOneTime) immediately navigates to the confirmation screen.
	// We assert the confirmation screen, not the intermediate BankTransferPayment text
	// (which is unmounted as soon as the parent navigates).

	log('Waiting for mock polling to trigger success and confirmation screen...');
	await screenshot(page, '09-waiting-for-success');

	// Confirmation screen shows "Payment successful! Thank you for your support."
	// Allow 90s for 2 poll cycles (30s each) + GHA runner overhead.
	const successText = page.locator('text=/payment successful|thank you|support.*received/i').first();
	await expect(successText).toBeVisible({ timeout: 90000 });
	log('Confirmation screen shown — donation completed successfully.');
	await screenshot(page, '10-success-state');

	log('✅ SEPA bank transfer support flow test passed.');
});

// NOTE: The 110k EUR-only tier test was moved to settings-buy-credits-bank-transfer.spec.ts
// to avoid shared browser state issues when tests run sequentially in the same spec.

// Placeholder to satisfy the linter (file must export something)
if (false) test('settings buy credits: 110k EUR-only tier auto-routes to bank transfer view', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('BUY_CREDITS_110K_BANK_TRANSFER');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'buy-credits-110k' });
	await archiveExistingScreenshots(log);

	// Mock: /config — force bank_transfer_available=true. Hardcoded (no route.fetch) because
	// GHA's IP may receive an HTML error page from the dev server's rate limiter.
	await page.route('**/v1/payments/config', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				provider: 'polar',
				public_key: '',
				environment: 'sandbox',
				bank_transfer_available: true,
			}),
		});
	});

	// Mock the bank transfer order creation
	await page.route('**/v1/payments/create-bank-transfer-order', async (route: any) => {
		log('Intercepted create-bank-transfer-order request.');
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				order_id: 'bt_110k_test',
				reference: 'OM-TEST-110ktest',
				iban: MOCK_IBAN,
				bic: MOCK_BIC,
				bank_name: 'Revolut Bank UAB',
				amount_eur: '100.00',
				credits_amount: 110000,
				expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
			}),
		});
	});

	await page.route('**/v1/payments/bank-transfer-status/bt_110k_test', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ order_id: 'bt_110k_test', status: 'pending',
				credits_amount: 110000, amount_eur: '100.00', reference: 'OM-TEST-110ktest',
				expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
				created_at: new Date().toISOString() }),
		});
	});

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(4000);

	// Navigate to Settings → Billing → Buy Credits
	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 8000 });
	await expect(
		page.locator('[data-testid="settings-menu"].visible [data-testid="credits-row"]')
	).toBeVisible({ timeout: 15000 });

	const billingItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /billing/i });
	await billingItem.click();

	const buyCreditsItem = page
		.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
		.filter({ hasText: /buy credits/i });
	await expect(buyCreditsItem).toBeVisible({ timeout: 10000 });
	await buyCreditsItem.click();
	log('Navigated to Buy Credits.');
	await screenshot(page, '01-buy-credits-page');

	// Select the 110k tier (bank_transfer_only — shows "Bank transfer only" tag)
	const tierItems = page.locator(
		'[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]'
	);
	const bankTransferTier = tierItems.filter({ hasText: /110.*credits|110\.000/i });
	await expect(bankTransferTier).toBeVisible({ timeout: 10000 });
	log('110k credits bank-transfer-only tier is visible.');
	await screenshot(page, '02-110k-tier-visible');
	await bankTransferTier.click();
	log('Selected 110k tier.');

	// Bank transfer view should auto-load (no manual switch button needed)
	const detailsContainer = page.getByTestId('bank-transfer-details');
	await expect(detailsContainer).toBeVisible({ timeout: 15000 });
	log('Bank transfer details auto-loaded for 110k tier.');
	await screenshot(page, '03-auto-routed-to-bank-transfer');

	// Verify amount shows €100.00
	const amountRow = page.getByTestId('bank-transfer-amount');
	await expect(amountRow).toBeVisible({ timeout: 5000 });
	await expect(amountRow).toContainText('100.00');
	log('Amount shows €100.00 correctly.');

	// Verify reference is present
	const referenceRow = page.getByTestId('bank-transfer-reference');
	await expect(referenceRow).toBeVisible({ timeout: 5000 });
	await expect(referenceRow).toContainText('OM-TEST-110ktest');
	log('Reference is shown correctly.');
	await screenshot(page, '04-details-verified');

	// No back button (SEPA-only tier — can't go back to card payment)
	const backBtn = page.getByTestId('bank-transfer-back');
	await expect(backBtn).not.toBeVisible();
	log('No back button shown for bank-transfer-only tier (correct).');

	log('✅ 110k EUR-only tier auto-routing test passed.');
});
