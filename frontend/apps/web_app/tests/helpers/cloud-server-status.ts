// contract-test-file: infrastructure
/**
 * Browser route fixture presenting the official-cloud server status.
 *
 * Isolated CI serves the stack from localhost, so the backend reports
 * self-hosted and Settings hides Billing. Billing browser fixtures call this
 * before login so the payment UI is reachable; the payment endpoints
 * themselves are mocked by each spec.
 */
import type { Page, Route } from '@playwright/test';

export async function mockCloudServerStatus(page: Page): Promise<void> {
	await page.route('**/v1/settings/server-status', (route: Route) =>
		route.fulfill({
			json: {
				is_self_hosted: false,
				payment_enabled: true,
				server_edition: 'development',
				ai_models_configured: true,
			},
		})
	);
}

/**
 * Billing profile GET with no saved buyer address. SettingsBuyCreditsPayment
 * treats any failure of this call as a billing-context error and renders
 * nothing else, so the bank-transfer view needs it to answer. The address is
 * incidental to what these specs assert (bank details, switch button).
 */
export async function mockEmptyBuyerAddress(page: Page): Promise<void> {
	await page.route('**/v1/payments/buyer-address', (route: Route) =>
		route.request().method() === 'GET'
			? route.fulfill({ json: { buyer_address: null } })
			: route.continue()
	);
}
