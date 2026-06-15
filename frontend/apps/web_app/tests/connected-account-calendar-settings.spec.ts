/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Google Calendar connected-account settings flow.
 *
 * Verifies the user-facing Apps settings path can start OAuth, finalize an
 * opaque handoff after redirect, and persist only encrypted connected-account
 * fields before showing the account as connected.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount,
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Calendar connected-account settings', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('shows a safe error when connected accounts cannot be loaded', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CONNECTED_ACCOUNT_CALENDAR_SETTINGS_LOAD_FAILURE');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'connected-account-calendar-settings-load-failure',
		});

		await archiveExistingScreenshots(logCheckpoint);
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await page.route('**/v1/connected-accounts', async (route: any) => {
			if (route.request().method() === 'GET') {
				await route.abort('failed');
				return;
			}
			await route.continue();
		});

		await page.goto(getE2EDebugUrl('/#settings/apps/calendar'), { waitUntil: 'domcontentloaded' });
		const settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/calendar"]');
		await expect(settingsMenu).toBeVisible({ timeout: 15000 });

		const accountSection = settingsMenu.getByTestId('calendar-connected-accounts-section');
		await expect(accountSection).toBeVisible({ timeout: 15000 });
		await expect(accountSection).toContainText('Could not load connected accounts.', { timeout: 15000 });
		await expect(accountSection).not.toContainText(/Load failed|Failed to fetch|TypeError/i);
		await takeStepScreenshot(page, 'connected-account-load-failure-safe-error');
	});

	test('connects Google Calendar through settings using encrypted OAuth handoff storage', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CONNECTED_ACCOUNT_CALENDAR_SETTINGS');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'connected-account-calendar-settings',
		});
		let savedConnectedAccountRow: Record<string, unknown> | null = null;
		let startRequestBody: Record<string, unknown> | null = null;

		await archiveExistingScreenshots(logCheckpoint);
		await page.route('**/v1/provider-oauth/google/calendar/start', async (route: any) => {
			startRequestBody = route.request().postDataJSON();
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					authorization_url: getE2EDebugUrl('/?oauth_handoff_id=handoff-test-1#settings/apps/calendar'),
					state_expires_at: Math.floor(Date.now() / 1000) + 600,
					scopes: ['https://www.googleapis.com/auth/calendar.events']
				})
			});
		});
		await page.route('**/v1/connected-account-oauth/handoffs/handoff-test-1/claim', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					provider_id: 'google_calendar',
					refresh_token_bundle: {
						provider: 'google_calendar',
						refresh_token: 'secret-refresh-token',
						scopes: ['https://www.googleapis.com/auth/calendar.events']
					},
					account_hint: {
						label: 'Work Calendar',
						account_ref: 'calendar-work',
						provider_account_id: 'work@example.test',
						capabilities: ['read', 'write', 'delete'],
						scopes: ['https://www.googleapis.com/auth/calendar.events']
					},
					expires_at: Math.floor(Date.now() / 1000) + 300
				})
			});
		});
		await page.route('**/v1/connected-accounts', async (route: any) => {
			const request = route.request();
			if (request.method() === 'GET') {
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ rows: savedConnectedAccountRow ? [savedConnectedAccountRow] : [] })
				});
				return;
			}
			if (request.method() === 'POST') {
				const row = request.postDataJSON() as Record<string, unknown>;
				savedConnectedAccountRow = row;
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ id: row.id, sync_version: Date.now() })
				});
				return;
			}
			await route.continue();
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await page.goto(getE2EDebugUrl('/#settings/apps/calendar'), { waitUntil: 'domcontentloaded' });
		const settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/calendar"]');
		await expect(settingsMenu).toBeVisible({ timeout: 15000 });

		const accountSection = settingsMenu.getByTestId('calendar-connected-accounts-section');
		await expect(accountSection).toBeVisible({ timeout: 15000 });
		await expect(accountSection).toContainText('Not connected', { timeout: 15000 });
		await settingsMenu.getByTestId('connect-google-calendar-button').click();
		logCheckpoint('Clicked Google Calendar connect button.');

		await expect.poll(() => savedConnectedAccountRow, {
			message: 'encrypted connected-account row was created from OAuth handoff',
			timeout: 15000
		}).not.toBeNull();
		await expect(accountSection).toContainText('1 connected', { timeout: 15000 });
		await expect(page).not.toHaveURL(/oauth_handoff_id=/, { timeout: 15000 });

		expect(startRequestBody).toEqual({
			capabilities: ['read', 'write', 'delete'],
			return_path: '/#settings/apps/calendar'
		});
		expect(savedConnectedAccountRow).toBeTruthy();
		const finalConnectedAccountRow: Record<string, unknown> = savedConnectedAccountRow ?? {};
		expect(finalConnectedAccountRow.provider_type_hash).toBeTruthy();
		const savedRowJson = JSON.stringify(finalConnectedAccountRow);
		expect(savedRowJson).not.toContain('secret-refresh-token');
		expect(savedRowJson).not.toContain('work@example.test');
		expect(savedRowJson).not.toContain('google_calendar"');
		expect(savedRowJson).not.toContain('"refresh_token"');
		await takeStepScreenshot(page, 'connected-account-stored');
	});
});
