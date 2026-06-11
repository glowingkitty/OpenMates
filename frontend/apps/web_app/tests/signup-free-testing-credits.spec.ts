/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Signup Free testing credits promotion contract.
 *
 * The backend service tests cover budget accounting and encrypted credit grants.
 * This spec verifies the public server-status metadata drives the signup copy
 * without exposing admin budget details to the browser.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { openSignupInterface } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

type FreeTestingPromotion = {
	active: boolean;
	grant_credits: number;
};

function serverStatusBody(freeTestingCredits: FreeTestingPromotion | null) {
	return {
		is_self_hosted: false,
		payment_enabled: true,
		server_edition: 'development',
		domain: 'app.dev.openmates.org',
		ai_models_configured: true,
		free_testing_credits: freeTestingCredits
	};
}

async function mockServerStatus(page: any, freeTestingCredits: FreeTestingPromotion | null) {
	await page.route('**/v1/settings/server-status', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(serverStatusBody(freeTestingCredits))
		});
	});
}

async function openSignupBasics(page: any, path: string = '/') {
    await page.goto(getE2EDebugUrl(path));
	await page.waitForLoadState('load');
	await openSignupInterface(page, 30000);

	const loginTabs = page.getByTestId('login-tabs');
	await expect(loginTabs).toBeVisible({ timeout: 10000 });
	await loginTabs.getByRole('button', { name: /sign up/i }).click();

	await expect(page.getByText('OpenMates is currently an alpha release for early testers.')).toBeVisible({ timeout: 10000 });
	await expect(page.getByRole('link', { name: /view openmates on github/i })).toBeVisible();
	await expect(page.getByRole('link', { name: /view openmates on instagram/i })).toBeVisible();

	await page.getByRole('button', { name: /continue/i }).click();
	await expect(page.getByRole('heading', { name: /sign up/i })).toBeVisible({ timeout: 10000 });
}

test('signup basics shows Free credits for testing while promotion is active', async ({ page }: { page: any }) => {
	await mockServerStatus(page, { active: true, grant_credits: 1000 });

	await openSignupBasics(page);

	await expect(page.getByText('Free credits for testing')).toBeVisible();
	await expect(page.getByText('Pay per use')).toHaveCount(0);
});

test('signup basics falls back to Pay per use when promotion is inactive', async ({ page }: { page: any }) => {
	await mockServerStatus(page, { active: false, grant_credits: 1000 });

	await openSignupBasics(page);

	await expect(page.getByText('Pay per use')).toBeVisible();
	await expect(page.getByText('Free credits for testing')).toHaveCount(0);
});

test('gift-card signup hides Free credits claim and sends pending code to password signup', async ({ page }: { page: any }) => {
	const giftCardCode = 'AB23-CDEF-4567';
	let setupPasswordPayload: Record<string, unknown> | null = null;

	await mockServerStatus(page, { active: true, grant_credits: 1000 });
	await page.route('**/v1/auth/check_username_valid', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ available: true })
		});
	});
	await page.route('**/v1/auth/request_confirm_email_code', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ success: true, message: 'Confirmation code sent' })
		});
	});
	await page.route('**/v1/auth/check_confirm_email_code', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ success: true, message: 'Email confirmed' })
		});
	});
	await page.route('**/v1/auth/setup_password', async (route: any) => {
		setupPasswordPayload = route.request().postDataJSON();
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				success: true,
				message: 'Password set up successfully. Account created.',
				user: { id: 'gift-card-signup-user', username: 'giftcard_e2e', is_admin: false }
			})
		});
	});

	await openSignupBasics(page, `/#gift-card=${giftCardCode}`);

	await expect(page.getByText('Pay per use')).toBeVisible();
	await expect(page.getByText('Free credits for testing')).toHaveCount(0);
	await expect
		.poll(() => page.evaluate(() => sessionStorage.getItem('pending_gift_card_code')), { timeout: 5000 })
		.toBe(giftCardCode);

	await page.locator('input[type="email"][autocomplete="email"]').fill('giftcard-e2e@example.com');
	await page.locator('input[autocomplete="username"]').fill('giftcard_e2e');
	await page.locator('#terms-agreed-toggle').check({ force: true });
	await page.locator('#privacy-agreed-toggle').check({ force: true });
	await page.getByRole('button', { name: /create new account/i }).click();

	await page.locator('input[inputmode="numeric"][maxlength="6"]').fill('123456');
	await expect(page.locator('#signup-password-option')).toBeVisible({ timeout: 10000 });
	await page.locator('#signup-password-option').click();

	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await passwordInputs.nth(0).fill('GiftcardTest!234');
	await passwordInputs.nth(1).fill('GiftcardTest!234');
	await page.locator('#signup-password-continue').click();

	await expect.poll(() => setupPasswordPayload).not.toBeNull();
	expect(setupPasswordPayload?.pending_gift_card_code).toBe(giftCardCode);
});
