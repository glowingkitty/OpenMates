/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const {
	email: TEST_EMAIL,
	password: TEST_PASSWORD,
	otpKey: TEST_OTP_KEY
} = getTestAccount();

test.describe('Workflow billing usage', () => {
	// contract-test: direct surface=gui.web assertions=workflows.billing.skill-usage
	test('overview and Apps show workflow run and node-test charges with readable labels', async ({ page }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const today = new Date().toISOString().slice(0, 10);
		const month = today.slice(0, 7);

		await page.route('**/v1/settings/usage/daily-overview**', async (route) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					days: [{
						date: today,
						total_credits: 12,
						items: [
							{ type: 'workflow', chat_id: null, api_key_hash: null, app_id: 'weather', skill_id: 'forecast', total_credits: 7, entry_count: 1, updated_at: 1_757_851_202 },
							{ type: 'workflow_test', chat_id: null, api_key_hash: null, app_id: 'web', skill_id: 'search', total_credits: 5, entry_count: 1, updated_at: 1_757_851_201 }
						]
					}],
					requested_days: 7,
					total_days: 1,
					has_more_days: false
				})
			});
		});
		await page.route('**/v1/settings/usage/summaries?**', async (route) => {
			const url = new URL(route.request().url());
			if (url.searchParams.get('type') !== 'apps') {
				await route.continue();
				return;
			}
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					summaries: [
						{ app_id: 'weather', year_month: month, total_credits: 7 },
						{ app_id: 'web', year_month: month, total_credits: 5 }
					],
					type: 'apps',
					months: 3,
					count: 2
				})
			});
		});

		await loginToTestAccount(page, () => {}, async () => {});
		await waitForChatReady(page, () => {});
		await page.locator('#settings-menu-toggle').click();
		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await settingsMenu.locator('[data-testid="menu-item"][role="menuitem"]').filter({ hasText: /billing/i }).click();

		const workflowRows = settingsMenu.getByTestId('usage-overview-workflow-row');
		await expect(workflowRows).toHaveCount(2);
		await expect(workflowRows.nth(0)).toContainText(/weather/i);
		await expect(workflowRows.nth(0)).toContainText(/workflow run/i);
		await expect(workflowRows.nth(0)).toContainText(/forecast/i);
		await expect(workflowRows.nth(1)).toContainText(/web/i);
		await expect(workflowRows.nth(1)).toContainText(/workflow test/i);
		await expect(workflowRows.nth(1)).toContainText(/search/i);
		await expect(settingsMenu.getByTestId('usage-overview-day-heading')).toContainText(/12\s*credits/i);

		await settingsMenu.getByTestId('settings-tab-apps').click();
		const appRows = settingsMenu.getByTestId('usage-app-summary-row');
		await expect(appRows).toHaveCount(2);
		await expect(appRows.nth(0)).toContainText(/weather/i);
		await expect(appRows.nth(1)).toContainText(/web/i);
	});
});
