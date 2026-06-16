/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Calendar connected-account deterministic settings coverage.
 *
 * Exercises capability selection before Google OAuth handoff without driving the
 * live Google login UI. Live provider coverage is handled separately by the
 * optional Google Calendar smoke tests when credentials are available.
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

test.describe('Calendar connected accounts', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('shows Calendar OAuth capability toggles and sends only selected capabilities', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CALENDAR_CONNECTED_ACCOUNTS');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'calendar-connected-accounts',
		});
		let startRequestBody: Record<string, unknown> | null = null;

		await archiveExistingScreenshots(logCheckpoint);
		await page.route('**/v1/connected-accounts', async (route: any) => {
			if (route.request().method() === 'GET') {
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ rows: [] })
				});
				return;
			}
			await route.continue();
		});
		await page.route('**/v1/provider-oauth/google/calendar/start', async (route: any) => {
			startRequestBody = route.request().postDataJSON();
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					authorization_url: getE2EDebugUrl('/#settings/apps/calendar'),
					state_expires_at: Math.floor(Date.now() / 1000) + 600,
					scopes: ['https://www.googleapis.com/auth/calendar.events']
				})
			});
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await page.goto(getE2EDebugUrl('/#settings/apps/calendar'), { waitUntil: 'domcontentloaded' });
		const settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/calendar"]');
		await expect(settingsMenu).toBeVisible({ timeout: 15000 });

		const capabilityToggles = settingsMenu.getByTestId('calendar-capability-toggles');
		await expect(capabilityToggles).toBeVisible({ timeout: 15000 });
		await expect(capabilityToggles.getByLabel('Read events')).toBeChecked();
		await expect(capabilityToggles.getByLabel('Write events')).toBeChecked();
		await expect(capabilityToggles.getByLabel('Delete events')).toBeChecked();

		const summary = settingsMenu.getByTestId('calendar-oauth-capability-summary');
		await expect(summary).toContainText('Read events');
		await expect(summary).toContainText('Write events');
		await expect(summary).toContainText('Delete events');

		await capabilityToggles.getByLabel('Delete events').click();
		await expect(capabilityToggles.getByLabel('Delete events')).not.toBeChecked();
		await expect(summary).toContainText('Read events');
		await expect(summary).toContainText('Write events');
		await expect(summary).not.toContainText('Delete events');

		await settingsMenu.getByTestId('connect-google-calendar-button').click();
		await expect.poll(() => startRequestBody, {
			message: 'Google Calendar OAuth start request was captured',
			timeout: 10000
		}).not.toBeNull();

		expect(startRequestBody).toEqual({
			capabilities: ['read', 'write'],
			return_path: '/#settings/apps/calendar'
		});
		await takeStepScreenshot(page, 'calendar-capability-summary');
	});

	test('opens shared Privacy account details and updates only missing Calendar write access', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CALENDAR_PRIVACY_CONNECTED_ACCOUNTS');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'calendar-privacy-connected-accounts',
		});
		let savedConnectedAccountRow: Record<string, unknown> | null = null;
		let firstStartRequestBody: Record<string, unknown> | null = null;
		let updateStartRequestBody: Record<string, unknown> | null = null;
		let patchRequestBody: Record<string, unknown> | null = null;

		await archiveExistingScreenshots(logCheckpoint);
		await page.route('**/v1/provider-oauth/google/calendar/start', async (route: any) => {
			const body = route.request().postDataJSON();
			if (body.return_path === '/#settings/privacy/connected-accounts') {
				updateStartRequestBody = body;
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({
						authorization_url: getE2EDebugUrl('/?oauth_handoff_id=handoff-write#settings/privacy/connected-accounts'),
						state_expires_at: Math.floor(Date.now() / 1000) + 600,
						scopes: ['https://www.googleapis.com/auth/calendar.events']
					})
				});
				return;
			}
			firstStartRequestBody = body;
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					authorization_url: getE2EDebugUrl('/?oauth_handoff_id=handoff-read#settings/apps/calendar'),
					state_expires_at: Math.floor(Date.now() / 1000) + 600,
					scopes: ['https://www.googleapis.com/auth/calendar.readonly']
				})
			});
		});
		await page.route('**/v1/connected-account-oauth/handoffs/handoff-read/claim', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					provider_id: 'google_calendar',
					refresh_token_bundle: {
						provider: 'google_calendar',
						refresh_token: 'secret-read-refresh-token',
						scopes: ['https://www.googleapis.com/auth/calendar.readonly']
					},
					account_hint: {
						label: 'Work Calendar',
						account_ref: 'calendar-work',
						provider_account_id: 'work@example.test',
						capabilities: ['read'],
						scopes: ['https://www.googleapis.com/auth/calendar.readonly']
					},
					expires_at: Math.floor(Date.now() / 1000) + 300
				})
			});
		});
		await page.route('**/v1/connected-account-oauth/handoffs/handoff-write/claim', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					provider_id: 'google_calendar',
					refresh_token_bundle: {
						provider: 'google_calendar',
						refresh_token: 'secret-write-refresh-token',
						scopes: ['https://www.googleapis.com/auth/calendar.events']
					},
					account_hint: {
						label: 'Work Calendar',
						account_ref: 'calendar-work',
						provider_account_id: 'work@example.test',
						capabilities: ['write'],
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
				savedConnectedAccountRow = request.postDataJSON() as Record<string, unknown>;
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ id: savedConnectedAccountRow.id, sync_version: Date.now() })
				});
				return;
			}
			await route.continue();
		});
		await page.route('**/v1/connected-accounts/*', async (route: any) => {
			const request = route.request();
			if (request.method() === 'PATCH') {
				patchRequestBody = request.postDataJSON() as Record<string, unknown>;
				savedConnectedAccountRow = { ...(savedConnectedAccountRow ?? {}), ...patchRequestBody };
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ id: savedConnectedAccountRow.id, sync_version: Date.now() })
				});
				return;
			}
			await route.continue();
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await page.goto(getE2EDebugUrl('/#settings/apps/calendar'), { waitUntil: 'domcontentloaded' });
		let settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/calendar"]');
		await expect(settingsMenu).toBeVisible({ timeout: 15000 });

		const capabilityToggles = settingsMenu.getByTestId('calendar-capability-toggles');
		await capabilityToggles.getByLabel('Write events').click();
		await capabilityToggles.getByLabel('Delete events').click();
		await settingsMenu.getByTestId('connect-google-calendar-button').click();

		await expect.poll(() => savedConnectedAccountRow, {
			message: 'read-only encrypted connected-account row was created',
			timeout: 15000
		}).not.toBeNull();
		expect(firstStartRequestBody).toEqual({
			capabilities: ['read'],
			return_path: '/#settings/apps/calendar'
		});

		settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/calendar"]');
		await settingsMenu.getByTestId(/^calendar-connected-account-detail-/).click();
		const privacySettingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="privacy/connected-accounts"]');
		await expect(privacySettingsMenu).toBeVisible({ timeout: 15000 });
		const details = privacySettingsMenu.getByTestId('privacy-connected-account-detail');
		await expect(details).toContainText('Work Calendar', { timeout: 15000 });
		await expect(details).toContainText('Google Calendar');
		await expect(details).toContainText('Read events');
		await expect(details).not.toContainText('secret-read-refresh-token');
		await expect(details).not.toContainText('work@example.test');

		await privacySettingsMenu.getByTestId('privacy-connected-account-add-write-button').click();
		await expect.poll(() => updateStartRequestBody, {
			message: 'Calendar update OAuth start request was captured',
			timeout: 10000
		}).not.toBeNull();
		expect(updateStartRequestBody).toEqual({
			capabilities: ['write'],
			return_path: '/#settings/privacy/connected-accounts'
		});
		await expect.poll(() => patchRequestBody, {
			message: 'connected-account update PATCH was captured',
			timeout: 15000
		}).not.toBeNull();
		expect(JSON.stringify(patchRequestBody)).not.toContain('secret-write-refresh-token');
		expect(JSON.stringify(patchRequestBody)).not.toContain('work@example.test');

		await page.goto(getE2EDebugUrl('/#settings/privacy/connected-accounts'), { waitUntil: 'domcontentloaded' });
		const updatedPrivacySettingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="privacy/connected-accounts"]');
		await expect(updatedPrivacySettingsMenu).toBeVisible({ timeout: 15000 });
		const updatedDetails = updatedPrivacySettingsMenu.getByTestId('privacy-connected-account-detail');
		await expect(updatedDetails).toContainText('Read events', { timeout: 15000 });
		await expect(updatedDetails).toContainText('Write events', { timeout: 15000 });
		await expect(updatedPrivacySettingsMenu.getByTestId('privacy-connected-account-add-write-button')).toHaveCount(0);
		await takeStepScreenshot(page, 'privacy-connected-account-updated');
	});
});
