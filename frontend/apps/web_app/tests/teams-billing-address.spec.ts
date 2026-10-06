/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Team billing address boundary', () => {
	// contract-test: direct surface=gui.web assertions=teams.chat-billing.team-credit-boundary,billing.documents.visible-downloadable,billing.access.authenticated-first-party
	test('owner saves an optional Team invoice address without touching Personal billing', async ({
		page
	}: {
		page: Page;
	}) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await page.getByTestId('profile-container').click();
		await page.getByTestId('settings-teams-item').click();
		await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30000 });

		const teamName = `Billing proof ${Date.now()}`;
		await page.getByTestId('team-create-open').click();
		await page.getByTestId('team-name-input').fill(teamName);
		await page.getByTestId('team-create-continue').click();
		await expect(page.getByTestId('team-avatar-preview')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('team-create-submit').click();
		await expect(page.getByTestId('team-settings-header')).toContainText(teamName, {
			timeout: 30000
		});

		const personalBillingRequests: string[] = [];
		page.on('request', (request) => {
			const path = new URL(request.url()).pathname;
			if (
				path.startsWith('/v1/payments/buyer-address') ||
				path.startsWith('/v1/payments/invoices') ||
				path.startsWith('/v1/payments/create-order') ||
				path.startsWith('/v1/payments/create-bank-transfer-order')
			) {
				personalBillingRequests.push(`${request.method()} ${path}`);
			}
		});

		await page.getByTestId('team-billing-open').click();
		await expect(page.getByTestId('team-billing-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('team-billing-address')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('team-billing-address').click();
		await expect(page.getByTestId('billing-address-form')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('billing-address-name').fill('Example Team GmbH');
		await page.getByTestId('billing-address-street').fill('Main Street 1');
		await page.getByTestId('billing-address-postal-code').fill('10115');
		await page.getByTestId('billing-address-city').fill('Berlin');
		await page.getByTestId('billing-address-country').fill('DE');
		const saved = page.waitForResponse(
			(response) =>
				response.request().method() === 'PUT' &&
				/\/v1\/teams\/[^/]+\/billing\/buyer-address$/.test(new URL(response.url()).pathname)
		);
		await page.getByTestId('billing-address-save').click();
		expect((await saved).ok()).toBe(true);
		await expect(page.getByTestId('billing-address-saved')).toBeVisible();

		let bankPayload: Record<string, unknown> | null = null;
		await page.route('**/v1/teams/*/billing/bank-transfer-orders', async (route) => {
			bankPayload = JSON.parse(route.request().postData() ?? '{}');
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					order_id: 'bt_team_billing_proof',
					reference: 'OM-TEAM-PROOF',
					iban: 'DE02100100109307118603',
					bic: 'PBNKDEFF',
					bank_name: 'Proof Bank',
					account_holder_name: 'OpenMates',
					amount_eur: '100.00',
					credits_amount: 110000,
					expires_at: new Date(Date.now() + 86400000).toISOString()
				})
			});
		});
		await page.getByTestId('banner-back-button').click();
		await expect(page.getByTestId('team-billing-buy-credits')).toBeVisible();
		await page.getByTestId('team-billing-buy-credits').click();
		await page
			.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
			.filter({ hasText: /110.*credits|110\.000/i })
			.click();
		await expect(page.getByTestId('bank-transfer-details')).toBeVisible({ timeout: 30000 });
		expect(bankPayload).toMatchObject({
			credits_amount: 110000,
			buyer_address: { name: 'Example Team GmbH', street_line_1: 'Main Street 1', country: 'DE' }
		});
		expect(personalBillingRequests).toEqual([]);
	});
});
