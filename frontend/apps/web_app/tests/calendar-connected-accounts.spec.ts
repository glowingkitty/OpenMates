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
});
