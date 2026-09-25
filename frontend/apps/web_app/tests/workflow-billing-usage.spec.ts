/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Billing usage landing page', () => {
	// contract-test: direct surface=gui.web assertions=billing.usage.landing-complete,workflows.billing.skill-usage
	test('overview shows every billed context once with readable labels and a reconciled total', async ({
		page
	}) => {
		test.slow();
		test.setTimeout(120_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const today = new Date().toISOString().slice(0, 10);
		const month = today.slice(0, 7);

		await page.route('**/v1/settings/server-status**', async (route) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					is_self_hosted: false,
					payment_enabled: true,
					server_edition: 'development'
				})
			});
		});

		await page.route('**/v1/settings/usage/daily-overview**', async (route) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					days: [
						{
							date: today,
							total_credits: 38,
							items: [
								{
									type: 'incognito',
									chat_id: 'incognito',
									api_key_hash: null,
									app_id: 'ai',
									skill_id: 'ask',
									total_credits: 3,
									entry_count: 1,
									updated_at: 1_757_851_208
								},
								{
									type: 'app',
									chat_id: null,
									api_key_hash: null,
									app_id: 'audio',
									skill_id: 'transcribe',
									usage_type: 'realtime_transcription_interrupted',
									started_minutes: 1,
									total_credits: 8,
									entry_count: 1,
									updated_at: 1_757_851_207
								},
								{
									type: 'api_key',
									chat_id: null,
									api_key_hash: 'api-hash',
									app_id: 'web',
									skill_id: 'search',
									total_credits: 3,
									entry_count: 1,
									updated_at: 1_757_851_206
								},
								{
									type: 'device',
									chat_id: null,
									api_key_hash: 'cli:device-hash',
									app_id: 'code',
									skill_id: 'run',
									total_credits: 4,
									entry_count: 1,
									updated_at: 1_757_851_205
								},
								{
									type: 'workflow',
									chat_id: null,
									api_key_hash: null,
									app_id: 'weather',
									skill_id: 'forecast',
									total_credits: 7,
									entry_count: 1,
									updated_at: 1_757_851_202
								},
								{
									type: 'workflow_test',
									chat_id: null,
									api_key_hash: null,
									app_id: 'web',
									skill_id: 'search',
									total_credits: 5,
									entry_count: 1,
									updated_at: 1_757_851_201
								},
								{
									type: 'benchmark',
									chat_id: null,
									api_key_hash: null,
									app_id: 'ai',
									skill_id: 'ask',
									total_credits: 6,
									entry_count: 1,
									updated_at: 1_757_851_200
								},
								{
									type: 'unattributed',
									chat_id: null,
									api_key_hash: null,
									app_id: 'ai',
									skill_id: 'ask',
									total_credits: 2,
									entry_count: 1,
									updated_at: 1_757_851_199
								}
							]
						}
					],
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

		await loginToTestAccount(
			page,
			() => {},
			async () => {}
		);
		await waitForChatReady(page, () => {});
		await page.locator('#settings-menu-toggle').click();
		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 8_000 });
		const billingItem = settingsMenu.getByRole('button', { name: /billing/i });
		await expect(billingItem).toBeEnabled({ timeout: 15_000 });
		await billingItem.click();
		await expect(settingsMenu.getByText(/^usage$/i).first()).toBeVisible({ timeout: 15_000 });

		const workflowRows = settingsMenu.getByTestId('usage-overview-workflow-row');
		await expect(workflowRows).toHaveCount(2);
		await expect(workflowRows.nth(0)).toContainText(/weather/i);
		await expect(workflowRows.nth(0)).toContainText(/workflow run/i);
		await expect(workflowRows.nth(0)).toContainText(/forecast/i);
		await expect(workflowRows.nth(1)).toContainText(/web/i);
		await expect(workflowRows.nth(1)).toContainText(/workflow test/i);
		await expect(workflowRows.nth(1)).toContainText(/search/i);
		await expect(workflowRows.nth(0)).toContainText(/1 request/i);

		const appRow = settingsMenu.getByTestId('usage-overview-app-row');
		await expect(appRow).toContainText(/audio/i);
		await expect(appRow).toContainText(/transcript/i);
		await expect(appRow).toContainText(/interrupted recording/i);
		await expect(appRow).toContainText(/1 started minute/i);
		await expect(appRow).toContainText(/8\s*credits/i);

		const apiDeviceRows = settingsMenu.getByTestId('usage-overview-api-device-row');
		await expect(apiDeviceRows).toHaveCount(2);
		await expect(apiDeviceRows.nth(0)).toContainText(/api key activity/i);
		await expect(apiDeviceRows.nth(1)).toContainText(/device activity/i);

		const otherRows = settingsMenu.getByTestId('usage-overview-other-row');
		await expect(otherRows).toHaveCount(2);
		await expect(otherRows.nth(0)).toContainText(/benchmark/i);
		await expect(otherRows.nth(1)).toContainText(/original context unavailable/i);
		await expect(settingsMenu.getByTestId('usage-overview-chat-row')).toContainText(/incognito/i);
		await expect(settingsMenu.getByTestId('usage-overview-day-heading')).toContainText(
			/38\s*credits/i
		);

		await settingsMenu.getByTestId('settings-tab-apps').click();
		const appRows = settingsMenu.getByTestId('usage-app-summary-row');
		await expect(appRows).toHaveCount(2);
		await expect(appRows.nth(0)).toContainText(/weather/i);
		await expect(appRows.nth(1)).toContainText(/web/i);
	});
});
