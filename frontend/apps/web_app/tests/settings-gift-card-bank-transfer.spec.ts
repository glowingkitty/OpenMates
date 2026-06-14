/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Settings → Gift Cards — SEPA bank transfer purchase contract.
 *
 * Verifies that gift-card purchases using the generic bank-transfer payment UI
 * mark the pending SEPA order as a gift-card purchase. The backend webhook test
 * covers the confirmed-transfer side effects: create gift card, email the code,
 * and avoid granting credits to the buyer.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	setToggleChecked,
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const MOCK_IBAN = 'GB68REVO04290962398393';
const MOCK_BIC = 'REVOGB21';
const MOCK_REFERENCE = 'OM-GIFT-btgift01';

test('settings gift cards: bank transfer order is created as gift-card purchase', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('GIFT_CARD_BANK_TRANSFER');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'gift-card-bank-transfer' });
	await archiveExistingScreenshots(log);

	let createBankTransferBody: Record<string, unknown> | null = null;

	await page.route('**/v1/payments/config', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				provider: 'stripe',
				public_key: 'pk_test_placeholder_gift_card_bank_transfer',
				environment: 'sandbox',
				bank_transfer_available: true,
				is_eu: true,
				use_managed_payments: false,
			}),
		});
	});

	await page.route('**/v1/payments/payment-methods', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ payment_methods: [] }),
		});
	});

	await page.route('**/v1/payments/buy-gift-card', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				provider: 'stripe',
				order_id: 'pi_gift_card_test',
				client_secret: 'pi_gift_card_test_secret_mock',
			}),
		});
	});

	await page.route('**/v1/payments/create-bank-transfer-order', async (route: any) => {
		createBankTransferBody = route.request().postDataJSON();
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				order_id: 'bt_gift01',
				reference: MOCK_REFERENCE,
				iban: MOCK_IBAN,
				bic: MOCK_BIC,
				bank_name: 'Revolut Bank UAB',
				account_holder_name: 'OpenMates',
				account_holder_address_line1: 'Sorauer Str. 19',
				account_holder_address_line2: '',
				account_holder_postal_code: '10997',
				account_holder_city: 'Berlin',
				account_holder_country: 'Germany',
				amount_eur: '20.00',
				credits_amount: 21000,
				expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
			}),
		});
	});

	await page.route('**/v1/payments/bank-transfer-status/bt_gift01', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				order_id: 'bt_gift01',
				status: 'pending',
				credits_amount: 21000,
				amount_eur: '20.00',
				reference: MOCK_REFERENCE,
				expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
				created_at: new Date().toISOString(),
			}),
		});
	});

	await loginToTestAccount(page, log, screenshot);

	await page.evaluate(() => {
		window.dispatchEvent(new CustomEvent('openSettingsMenu', { detail: { returnTo: 'billing/gift-cards/buy' } }));
	});

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'billing/gift-cards/buy', { timeout: 10000 });
	await page.getByTestId('menu-item').filter({ hasText: '21.000' }).click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'billing/gift-cards/buy/payment', { timeout: 10000 });

	const limitedRefundHeading = page.getByRole('heading', { name: /Limited refund/i });
	await expect(limitedRefundHeading).toBeVisible({ timeout: 15000 });
	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await setToggleChecked(consentToggle, true);
	await expect(limitedRefundHeading).toBeHidden({ timeout: 10000 });

	const bankTransferButton = page.getByTestId('switch-to-bank-transfer');
	await expect(bankTransferButton).toBeVisible({ timeout: 15000 });
	await screenshot(page, '01-gift-card-payment-bank-transfer-button');
	await bankTransferButton.click();

	await expect(page.getByTestId('bank-transfer-details')).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('bank-transfer-reference')).toContainText(MOCK_REFERENCE, { timeout: 5000 });
	await expect(page.getByTestId('bank-transfer-iban')).toContainText(MOCK_IBAN, { timeout: 5000 });
	await expect(page.getByTestId('bank-transfer-bic')).toContainText(MOCK_BIC, { timeout: 5000 });
	await screenshot(page, '02-gift-card-bank-transfer-details');

	expect(createBankTransferBody).toMatchObject({
		credits_amount: 21000,
		currency: 'eur',
		is_gift_card: true,
	});
});
