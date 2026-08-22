/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Settings gift-card redemption E2E smoke.
 *
 * The unified test runner seeds OPENMATES_E2E_GIFT_CARD_CODE in dev Directus
 * immediately before dispatch. This spec must not mock the redemption route:
 * it verifies the deployed browser calls the real authenticated payment API and
 * the user sees the redemption in billing settings.
 *
 * Tests: python3 scripts/tests.py run --spec settings-gift-card-redemption.spec.ts
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SEEDED_GIFT_CARD_CODE = process.env.OPENMATES_E2E_GIFT_CARD_CODE;
const EXPECTED_CREDITS_ADDED = 321;
const EXPECTED_CREDITS_TEXT = `${EXPECTED_CREDITS_ADDED} credits`;

test.describe.configure({ retries: 0 });

// contract-test: direct surface=gui.web assertions=billing.purchase.provider-routing,billing.access.authenticated-first-party
test('settings gift cards: seeded code redeems through real payment API', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.skip(!SEEDED_GIFT_CARD_CODE, 'OPENMATES_E2E_GIFT_CARD_CODE is seeded by scripts/run_tests.py for this spec.');

	if (!SEEDED_GIFT_CARD_CODE) {
		throw new Error('OPENMATES_E2E_GIFT_CARD_CODE missing after skip guard.');
	}

	const log = createSignupLogger('GIFT_CARD_REDEMPTION');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'gift-card-redemption' });
	await archiveExistingScreenshots(log);

	const redemptionResponses: Array<{ status: number; payload: Record<string, unknown> }> = [];
	page.on('response', async (response: any) => {
		const url = response.url();
		if (!url.includes('/v1/payments/redeem-gift-card')) return;
		let payload: Record<string, unknown> = {};
		try {
			payload = await response.json();
		} catch {
			payload = {};
		}
		redemptionResponses.push({ status: response.status(), payload });
	});

	await loginToTestAccount(page, log, screenshot);

	await page.evaluate(() => {
		window.dispatchEvent(new CustomEvent('openSettingsMenu', { detail: { returnTo: 'billing/gift-cards/redeem' } }));
	});

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'billing/gift-cards/redeem', { timeout: 10000 });

	const codeInput = page.getByTestId('gift-card-code-input');
	await expect(codeInput).toBeVisible({ timeout: 10000 });
	await codeInput.fill(SEEDED_GIFT_CARD_CODE);
	await screenshot(page, '01-code-entered');

	const redeemButton = page.getByTestId('gift-card-redeem-submit');
	await expect(redeemButton).toBeEnabled({ timeout: 10000 });
	await redeemButton.click();

	await expect.poll(() => redemptionResponses.length, { timeout: 30000 }).toBeGreaterThan(0);
	const redemption = redemptionResponses.at(-1);
	expect(redemption?.status, `redeem-gift-card response: ${JSON.stringify(redemption?.payload)}`).toBe(200);
	expect(redemption?.payload).toMatchObject({
		success: true,
		credits_added: EXPECTED_CREDITS_ADDED
	});
	log('Real gift-card redemption endpoint returned success.', {
		credits_added: redemption?.payload?.credits_added
	});

	await expect(settingsMenu).toHaveAttribute('data-active-view', 'billing/gift-cards/redeemed', { timeout: 15000 });
	const redeemedCardRow = settingsMenu.getByTestId('redeemed-gift-card-row').filter({ hasText: SEEDED_GIFT_CARD_CODE });
	await expect(redeemedCardRow).toBeVisible({ timeout: 15000 });
	await expect(redeemedCardRow).toContainText(EXPECTED_CREDITS_TEXT);
	await screenshot(page, '02-redeemed-list');
});
