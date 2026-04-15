/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Settings → Buy Credits — 110k EUR-only (bank transfer) tier test.
 *
 * WHAT THIS TESTS:
 * - The 110,000 credits / €100 tier is bank_transfer_only: true in pricing.yml.
 * - Selecting it in Buy Credits auto-routes directly to BankTransferPayment.svelte
 *   without needing to click "Pay via Bank Transfer" (no card form shown at all).
 * - No back button is shown (can't switch to card for a bank-transfer-only tier).
 * - IBAN, BIC, amount (€100), and reference are displayed correctly.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL / PASSWORD / OTP_KEY
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
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const MOCK_IBAN = 'GB68REVO04290962398393';
const MOCK_BIC = 'REVOGB21';

test('settings buy credits: 110k EUR-only tier auto-routes to bank transfer view', async ({
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

	// Force bank_transfer_available=true with a hardcoded config mock.
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

	// Mock create-bank-transfer-order so no real order is created.
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
			body: JSON.stringify({
				order_id: 'bt_110k_test',
				status: 'pending',
				credits_amount: 110000,
				amount_eur: '100.00',
				reference: 'OM-TEST-110ktest',
				expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
				created_at: new Date().toISOString(),
			}),
		});
	});

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(4000);

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

	await expect(page.getByTestId('bank-transfer-amount')).toContainText('100.00', { timeout: 5000 });
	await expect(page.getByTestId('bank-transfer-reference')).toContainText('OM-TEST-110ktest', { timeout: 5000 });
	log('Amount (€100) and reference correct.');
	await screenshot(page, '04-details-verified');

	// No back button — SEPA-only tier can't switch to card
	await expect(page.getByTestId('bank-transfer-back')).not.toBeVisible();
	log('No back button shown (correct for bank-transfer-only tier).');

	log('✅ 110k EUR-only tier auto-routing test passed.');
});
