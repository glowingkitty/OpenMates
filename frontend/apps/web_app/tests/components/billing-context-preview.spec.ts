import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
test.describe('Billing context previews', () => {
	// contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing,teams.chat-billing.team-credit-boundary
	test('Team bank transfer tier opens the Team payment route', async ({ page }) => {
		const buyerAddress = {
			name: 'Preview Team GmbH',
			street_line_1: 'Main Street 1',
			postal_code: '10115',
			city: 'Berlin',
			country: 'DE'
		};
		let bankOrderPayload: Record<string, unknown> | null = null;
		const personalBillingRequests: string[] = [];
		const teamPaymentMethodRequests: string[] = [];
		page.on('request', (request) => {
			const path = new URL(request.url()).pathname;
			if (path === '/v1/teams/team-preview/billing/payment-methods') {
				teamPaymentMethodRequests.push(request.method());
			}
			if (
				path.startsWith('/v1/payments/buyer-address') ||
				path.startsWith('/v1/payments/payment-methods') ||
				path.startsWith('/v1/payments/create-bank-transfer-order')
			) {
				personalBillingRequests.push(`${request.method()} ${path}`);
			}
		});
		await page.route('**/v1/teams/team-preview/billing/buyer-address', (route) =>
			route.fulfill({ json: { buyer_address: buyerAddress } })
		);
		await page.route('**/v1/teams/team-preview/billing/payment-methods', (route) =>
			route.fulfill({ status: 503, json: { detail: 'Card methods unavailable' } })
		);
		await page.route('**/v1/teams/team-preview/billing/bank-transfer-orders', (route) => {
			bankOrderPayload = JSON.parse(route.request().postData() ?? '{}');
			return route.fulfill({
				json: {
					order_id: 'bt_team_preview',
					reference: 'OM-TEAM-PREVIEW',
					iban: 'DE02100100109307118603',
					bic: 'PBNKDEFF',
					bank_name: 'Preview Bank',
					account_holder_name: 'OpenMates',
					amount_eur: '100.00',
					credits_amount: 110000,
					expires_at: new Date(Date.now() + 86400000).toISOString()
				}
			});
		});
		await page.goto(
			'/dev/preview/settings/billing/SettingsTeamBillingNavigationHarness?chrome=0&theme=light&width=390'
		);
		await waitForComponentPreview(page);
		const navigation = page.getByTestId('team-billing-navigation-harness');
		await expect(navigation).toHaveAttribute(
			'data-active-view',
			'teams/team-preview/billing/buy-credits'
		);
		await page.getByRole('menuitem', { name: /110\.000 credits/i }).click();
		await expect(navigation).toHaveAttribute(
			'data-active-view',
			'teams/team-preview/billing/buy-credits/payment'
		);
		await expect(page.getByTestId('bank-transfer-details')).toBeVisible();
		await waitForComponentMotion(page.getByTestId('bank-transfer-details'));
		await expect(page.getByTestId('copy-account-holder-btn')).toBeVisible();
		await expect(page.getByTestId('team-billing-context-error')).toHaveCount(0);
		expect(bankOrderPayload).toMatchObject({
			credits_amount: 110000,
			buyer_address: buyerAddress
		});
		expect(personalBillingRequests).toEqual([]);
		expect(teamPaymentMethodRequests).toEqual([]);
	});

	// contract-test: supporting surface=gui.web assertions=teams.chat-billing.team-credit-boundary,billing.purchase.provider-routing
	test('Team SEPA checkout stops when its buyer address cannot be loaded', async ({ page }) => {
		let bankOrderRequests = 0;
		await page.route('**/v1/teams/team-preview/billing/buyer-address', (route) =>
			route.fulfill({ status: 503, json: { detail: 'Address unavailable' } })
		);
		await page.route('**/v1/teams/team-preview/billing/payment-methods', (route) =>
			route.fulfill({ status: 503, json: { detail: 'Card methods unavailable' } })
		);
		await page.route('**/v1/teams/team-preview/billing/bank-transfer-orders', (route) => {
			bankOrderRequests += 1;
			return route.fulfill({ status: 500, json: { detail: 'Unexpected order' } });
		});
		await page.goto(
			'/dev/preview/settings/billing/SettingsTeamBillingNavigationHarness?chrome=0&theme=light&width=390'
		);
		await waitForComponentPreview(page);
		await page.getByRole('menuitem', { name: /110\.000 credits/i }).click();
		await expect(page.getByTestId('team-billing-context-error')).toBeVisible();
		await expect(page.getByTestId('bank-transfer-details')).toHaveCount(0);
		expect(bankOrderRequests).toBe(0);
	});

	// contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing,billing.documents.visible-downloadable
	test('Team overview shows its own balance and billing actions at phone width', async ({
		page
	}) => {
		await page.goto(
			'/dev/preview/settings/billing/SettingsTeamBilling?chrome=0&theme=light&background=%23dbeafe&width=323'
		);
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-billing-page')).toBeVisible();
		await expect(page.getByTestId('team-settings-header').locator('.app-details-header')).toHaveCSS(
			'opacity',
			'1'
		);
		await expect(page.getByTestId('team-settings-header').locator('.app-details-header')).toHaveCSS(
			'background-image',
			/linear-gradient.*rgb\(72, 103, 205\)/
		);
		await expect(page.getByTestId('team-settings-header')).toContainText('Billing & usage');
		await expect(page.getByTestId('team-settings-header')).toContainText('xHain');
		await expect(page.getByTestId('team-billing-balance')).toContainText('0');
		await expect(page.getByTestId('team-billing-balance')).toContainText('remaining');
		await expect(page.getByTestId('team-billing-balance')).toContainText('without credits');
		await expect(
			page.getByTestId('team-billing-address').getByText('Billing address', { exact: true })
		).toHaveCSS('font-weight', '700');
		for (const id of [
			'team-billing-buy-credits',
			'team-billing-auto-topup',
			'team-billing-invoices',
			'team-billing-address',
			'team-usage-download'
		]) {
			await expect(page.getByTestId(id)).toBeVisible();
		}
		const geometry = await page.evaluate(() => {
			const frame = document
				.querySelector('[data-testid="team-billing-frame"]')!
				.getBoundingClientRect();
			const header = document
				.querySelector('[data-testid="team-settings-header"]')!
				.getBoundingClientRect();
			const card = document
				.querySelector('[data-testid="team-billing-balance"]')!
				.getBoundingClientRect();
			const rows = [
				'team-billing-buy-credits',
				'team-billing-auto-topup',
				'team-billing-invoices',
				'team-billing-address'
			].map((id) => document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect());
			const tabs = document
				.querySelector('.team-usage-tabs .settings-tabs-container')!
				.getBoundingClientRect();
			const day = document.querySelector('[data-testid="team-usage-day"]')!.getBoundingClientRect();
			return {
				frameHeight: frame.height,
				headerHeight: header.height,
				card: {
					x: card.x - frame.x,
					y: card.y - frame.y,
					width: card.width,
					height: card.height,
					background: getComputedStyle(
						document.querySelector('[data-testid="team-billing-balance"]')!
					).backgroundImage
				},
				rowTops: rows.map((row) => row.y - frame.y),
				tabs: { y: tabs.y - frame.y, height: tabs.height },
				dayY: day.y - frame.y
			};
		});
		expect(geometry.frameHeight).toBeGreaterThanOrEqual(719);
		expect(geometry.headerHeight).toBeCloseTo(227, 0);
		expect(geometry.card.x).toBeCloseTo(16, 0);
		expect(geometry.card.y).toBeCloseTo(238, 0);
		expect(geometry.card.width).toBeCloseTo(294, 0);
		expect(geometry.card.height).toBe(129);
		expect(geometry.card.background).toContain('gradient');
		expect(geometry.rowTops[1] - geometry.rowTops[0]).toBeCloseTo(54, 0);
		expect(geometry.tabs.y).toBeCloseTo(737, 0);
		expect(geometry.tabs.height).toBeCloseTo(37, 0);
		expect(geometry.dayY).toBeCloseTo(786, 0);
		await expect(
			page.getByTestId('team-billing-address').locator('.settings-icon')
		).toHaveAttribute('style', /--icon-url-maps/);
		for (const tab of ['overview', 'chats', 'apps', 'work']) {
			await expect(page.getByTestId(`team-usage-tab-${tab}`)).toBeVisible();
		}
		await expect(page.getByTestId('team-usage-day-heading')).toContainText('Today');
		await expect(page.getByTestId('team-usage-day-heading')).toContainText('25');
		await expect(page.getByTestId('team-usage-workspace')).toHaveCount(3);
		await expect(page.getByTestId('team-usage-ledger')).not.toContainText('01234567');
		await page.getByTestId('team-usage-tab-chats').click();
		await expect(page.getByTestId('team-usage-workspace')).toHaveCount(1);
		await expect(page.getByTestId('team-usage-day-heading')).toContainText('12');
		await page.getByTestId('team-usage-tab-apps').click();
		await expect(page.getByTestId('team-usage-day-heading')).toContainText('8');
		await page.getByTestId('team-usage-tab-work').click();
		await expect(page.getByTestId('team-usage-day-heading')).toContainText('5');
		await page.getByTestId('team-usage-tab-overview').click();
		await page.getByTestId('team-usage-download').click();
		await expect(page.getByTestId('team-usage-csv')).toBeVisible();
		await expect(page.getByTestId('team-usage-pdf')).toBeVisible();
		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth - document.documentElement.clientWidth
		);
		expect(overflow).toBeLessThanOrEqual(1);

		await page.goto(
			`/dev/preview/settings/billing/SettingsTeamBilling?chrome=0&theme=light&width=323&props=${encodeURIComponent(JSON.stringify({ previewBalance: 12000 }))}`
		);
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-billing-balance')).toContainText('12,000');
		await expect(page.getByTestId('team-billing-balance')).not.toContainText('without credits');
	});

	// contract-test: supporting surface=gui.web assertions=billing.documents.visible-downloadable
	test('Personal address starts collapsed, while Team address fields are visible and optional', async ({
		page
	}) => {
		const base =
			'/dev/preview/settings/billing/SettingsBillingAddress?chrome=0&theme=light&background=%23dbeafe&width=390';
		await page.goto(base);
		await waitForComponentPreview(page);
		await expect(page.getByTestId('billing-address-add')).toBeVisible();
		await expect(page.getByTestId('billing-address-form')).toHaveCount(0);
		await page.getByTestId('billing-address-add').click();
		await expect(page.getByTestId('billing-address-form')).toBeVisible();
		await page.getByTestId('billing-address-save').click();
		await expect(page.getByTestId('billing-address-saved')).toBeVisible();

		await page.goto(
			`${base}&props=${encodeURIComponent(JSON.stringify({ teamId: 'team-preview', preview: true }))}`
		);
		await waitForComponentPreview(page);
		await expect(page.getByTestId('billing-address-form')).toBeVisible();
		await page.getByTestId('billing-address-name').fill('Example GmbH');
		await page.getByTestId('billing-address-save').click();
		await expect(page.getByRole('alert')).toBeVisible();
		await page.getByTestId('billing-address-street').fill('Main Street 1');
		await page.getByTestId('billing-address-postal-code').fill('10115');
		await page.getByTestId('billing-address-city').fill('Berlin');
		await page.getByTestId('billing-address-country').fill('DE');
		await page.getByTestId('billing-address-save').click();
		await expect(page.getByTestId('billing-address-saved')).toBeVisible();
	});

	// contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing
	test('Team monthly auto top-up offers recurring tier and billing day controls', async ({
		page
	}) => {
		await page.goto(
			'/dev/preview/settings/billing/SettingsTeamMonthlyAutoTopup?chrome=0&theme=light&background=%23dbeafe&width=390'
		);
		await waitForComponentPreview(page);
		await expect(page.getByTestId('team-monthly-auto-topup')).toBeVisible();
		await expect(page.getByTestId('team-monthly-tier')).toBeVisible();
		await expect(page.getByTestId('team-monthly-currency')).toBeVisible();
		await expect(page.getByTestId('team-monthly-day')).toBeVisible();
		await expect(page.getByTestId('team-monthly-create')).toBeEnabled();
		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth - document.documentElement.clientWidth
		);
		expect(overflow).toBeLessThanOrEqual(1);
	});
});
