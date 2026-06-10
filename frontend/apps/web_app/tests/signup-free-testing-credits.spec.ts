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

async function openSignupBasics(page: any) {
	await page.goto(getE2EDebugUrl('/'));
	await page.waitForLoadState('load');
	await openSignupInterface(page, 30000);

	const loginTabs = page.getByTestId('login-tabs');
	await expect(loginTabs).toBeVisible({ timeout: 10000 });
	await loginTabs.getByRole('button', { name: /sign up/i }).click();

	await expect(page.getByText('OpenMates is currently an alpha release for early testers.')).toBeVisible({ timeout: 10000 });
	await expect(page.locator('a[href*="github.com/glowingkitty/OpenMates"]')).toBeVisible();
	await expect(page.locator('a[href*="instagram.com/openmates_official"]')).toBeVisible();

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
