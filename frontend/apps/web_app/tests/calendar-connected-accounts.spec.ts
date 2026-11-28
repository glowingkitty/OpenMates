/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Calendar connected-account deterministic settings coverage.
 *
 * The Calendar app page only lists the accounts Calendar may use and links to
 * Settings > Account > Connected accounts. Sign-in starts from that central page
 * in a popup (or a same-tab redirect when popups are blocked); the provider's
 * login UI is replaced by a stubbed authorization URL. Live provider coverage is
 * handled separately by the optional Google Calendar smoke tests.
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
const { openAppSettings, openConnectedAccountsSettings, startGoogleCalendarAdd } = require('./helpers/settings-readiness');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const HANDOFF_CLAIM = {
	provider_id: 'google_calendar',
	refresh_token_bundle: {
		provider: 'google_calendar',
		refresh_token: 'secret-refresh-token',
		scopes: ['https://www.googleapis.com/auth/calendar.events']
	},
	account_hint: {
		label: 'work@example.test',
		account_ref: 'calendar-work',
		provider_account_id: 'work@example.test',
		capabilities: ['read', 'write', 'delete'],
		scopes: ['https://www.googleapis.com/auth/calendar.events']
	}
};

/** Stubs the connected-account endpoints; returns accessors for what the app saved. */
async function stubConnectedAccountApi(page: any, handoffId: string, returnHash: string) {
	const state: { row: Record<string, unknown> | null; startBody: Record<string, unknown> | null } = { row: null, startBody: null };
	await page.route('**/v1/provider-oauth/google/calendar/start', async (route: any) => {
		state.startBody = route.request().postDataJSON();
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				authorization_url: getE2EDebugUrl(`/?oauth_handoff_id=${handoffId}${returnHash}`),
				state_expires_at: Math.floor(Date.now() / 1000) + 600,
				scopes: HANDOFF_CLAIM.refresh_token_bundle.scopes
			})
		});
	});
	await page.route(`**/v1/connected-account-oauth/handoffs/${handoffId}/claim`, async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ ...HANDOFF_CLAIM, expires_at: Math.floor(Date.now() / 1000) + 300 })
		});
	});
	await page.route('**/v1/connected-accounts', async (route: any) => {
		const request = route.request();
		if (request.method() === 'GET') {
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rows: state.row ? [state.row] : [] }) });
			return;
		}
		if (request.method() === 'POST') {
			state.row = request.postDataJSON() as Record<string, unknown>;
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: state.row.id, sync_version: Date.now() }) });
			return;
		}
		await route.continue();
	});
	return state;
}

test.describe('Calendar connected accounts', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	// contract-test: direct surface=gui.web assertions=connected-accounts.connection.private-reusable
	test('Calendar app page lists no account, offers no connect buttons and links to Connected accounts', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CALENDAR_CONNECTED_ACCOUNTS');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'calendar-connected-accounts' });
		await archiveExistingScreenshots(logCheckpoint);
		await stubConnectedAccountApi(page, 'handoff-unused', '#settings/account/connected-accounts');

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		const settingsMenu = await openAppSettings(page, getE2EDebugUrl('/#apps/calendar'), 'calendar');

		const section = settingsMenu.getByTestId('calendar-connected-accounts-section');
		await expect(section).toBeVisible({ timeout: 15000 });
		await expect(section).toContainText('No account connected', { timeout: 15000 });
		await expect(section.getByTestId('app-connected-accounts-manage-link')).toContainText('Add account in Connected accounts');
		for (const gone of ['connect-google-calendar-button', 'connected-account-manage', 'connected-account-reconnect', 'connected-account-disconnect', 'calendar-capability-toggles']) {
			await expect(settingsMenu.getByTestId(gone)).toHaveCount(0);
		}
		await takeStepScreenshot(page, 'calendar-app-page-no-account');

		await section.getByTestId('app-connected-accounts-manage-link').click();
		await expect(page.locator('[data-testid="settings-menu"][data-active-view="account/connected-accounts"]')).toBeVisible({ timeout: 15000 });
	});

	// contract-test: direct surface=gui.web assertions=connected-accounts.connection.private-reusable,connected-accounts.connection.popup-sign-in
	test('signs in through a popup, keeps OpenMates open and lists the new account', async ({ page, context }: { page: any; context: any }) => {
		const logCheckpoint = createSignupLogger('CALENDAR_CONNECTED_ACCOUNTS_POPUP');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'calendar-connected-accounts-popup' });
		await archiveExistingScreenshots(logCheckpoint);
		const api = await stubConnectedAccountApi(page, 'handoff-popup', '#settings/account/connected-accounts');

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await openConnectedAccountsSettings(page, getE2EDebugUrl('/#settings/account/connected-accounts'));
		const central = page.locator('[data-testid="settings-menu"][data-active-view="account/connected-accounts"]');
		const popupPromise = context.waitForEvent('page');
		await startGoogleCalendarAdd(central);
		const popup = await popupPromise;
		await popup.waitForEvent('close', { timeout: 30000 });

		await expect.poll(() => api.row, { message: 'encrypted row saved by the opener', timeout: 15000 }).not.toBeNull();
		await expect(central.getByTestId('connected-account-oauth-success')).toBeVisible({ timeout: 15000 });
		expect(api.startBody).toMatchObject({ app_id: 'calendar' });
		expect(JSON.stringify(api.row)).not.toContain('secret-refresh-token');
		expect(JSON.stringify(api.row)).not.toContain('work@example.test');
		await takeStepScreenshot(page, 'calendar-popup-connected');

		const appMenu = await openAppSettings(page, getE2EDebugUrl('/#apps/calendar'), 'calendar');
		await expect(appMenu.getByTestId('app-connected-account-item')).toHaveCount(1, { timeout: 15000 });
		await expect(appMenu.getByTestId('app-connected-account-item')).toContainText('work@example.test');
	});

	// contract-test: direct surface=gui.web assertions=connected-accounts.connection.popup-sign-in
	test('blocked popup falls back to a same-tab redirect and returns to the same settings page with a success message', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CALENDAR_CONNECTED_ACCOUNTS_BLOCKED_POPUP');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'calendar-connected-accounts-blocked-popup' });
		await archiveExistingScreenshots(logCheckpoint);
		await page.addInitScript(() => { window.open = () => null; });
		const api = await stubConnectedAccountApi(page, 'handoff-redirect', '#settings/account/connected-accounts');

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await openConnectedAccountsSettings(page, getE2EDebugUrl('/#settings/account/connected-accounts'));
		const central = page.locator('[data-testid="settings-menu"][data-active-view="account/connected-accounts"]');
		await startGoogleCalendarAdd(central);

		await expect.poll(() => api.row, { timeout: 30000 }).not.toBeNull();
		await expect(page).toHaveURL(/#settings\/account\/connected-accounts/, { timeout: 15000 });
		await expect(page).not.toHaveURL(/oauth_handoff_id=/, { timeout: 15000 });
		await expect(page.locator('[data-testid="settings-menu"][data-active-view="account/connected-accounts"]').getByTestId('connected-account-oauth-success')).toBeVisible({ timeout: 15000 });
		await takeStepScreenshot(page, 'calendar-blocked-popup-return');
	});

	// contract-test: direct surface=gui.web assertions=connected-accounts.connection.popup-sign-in
	test('a provider error on return shows an error message instead of failing silently', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CALENDAR_CONNECTED_ACCOUNTS_PROVIDER_ERROR');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'calendar-connected-accounts-provider-error' });
		await archiveExistingScreenshots(logCheckpoint);
		await page.addInitScript(() => { window.open = () => null; });
		await page.route('**/v1/provider-oauth/google/calendar/start', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					authorization_url: getE2EDebugUrl('/?error=access_denied#settings/account/connected-accounts'),
					state_expires_at: Math.floor(Date.now() / 1000) + 600,
					scopes: []
				})
			});
		});
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await openConnectedAccountsSettings(page, getE2EDebugUrl('/#settings/account/connected-accounts'));
		const central = page.locator('[data-testid="settings-menu"][data-active-view="account/connected-accounts"]');
		await startGoogleCalendarAdd(central);
		await expect(page.locator('[data-testid="settings-menu"][data-active-view="account/connected-accounts"]').getByTestId('connected-account-oauth-error')).toBeVisible({ timeout: 20000 });
		await takeStepScreenshot(page, 'calendar-provider-error');
	});
});
