/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Live Google Calendar connected-account OAuth E2E coverage.
 *
 * Runs only when Google test-user credentials are configured in CI. The spec
 * lets the backend OAuth broker and Google consent flow run live, while
 * intercepting the final connected-account POST to prove no plaintext provider
 * secrets or account identifiers leave the browser storage boundary.
 *
 * Spec: docs/specs/calendar-permission-management/spec.yml
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount,
	generateTotp,
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const GOOGLE_TEST_EMAIL = process.env.GOOGLE_CALENDAR_TEST_EMAIL ?? process.env.GOOGLE_TEST_EMAIL;
const GOOGLE_TEST_PASSWORD = process.env.GOOGLE_CALENDAR_TEST_PASSWORD ?? process.env.GOOGLE_TEST_PASSWORD;
const GOOGLE_TEST_TOTP_KEY = process.env.GOOGLE_CALENDAR_TEST_TOTP_KEY ?? process.env.GOOGLE_TEST_TOTP_KEY;

function skipWithoutGoogleOAuthCredentials(): void {
	test.skip(
		!GOOGLE_TEST_EMAIL || !GOOGLE_TEST_PASSWORD,
		'GOOGLE_CALENDAR_TEST_EMAIL/GOOGLE_TEST_EMAIL and GOOGLE_CALENDAR_TEST_PASSWORD/GOOGLE_TEST_PASSWORD are required for live Google OAuth.'
	);
}

async function clickFirstVisible(locator: any, timeout = 2500): Promise<boolean> {
	const count = await locator.count().catch(() => 0);
	for (let index = 0; index < count; index += 1) {
		const candidate = locator.nth(index);
		if (await candidate.isVisible({ timeout }).catch(() => false)) {
			await candidate.click();
			return true;
		}
	}
	return false;
}

async function fillFirstVisible(locator: any, value: string, timeout = 2500): Promise<boolean> {
	const count = await locator.count().catch(() => 0);
	for (let index = 0; index < count; index += 1) {
		const candidate = locator.nth(index);
		if (await candidate.isVisible({ timeout }).catch(() => false)) {
			await candidate.fill(value);
			return true;
		}
	}
	return false;
}

async function clickGoogleNext(page: any): Promise<void> {
	const explicitNext = page.locator('#identifierNext, #passwordNext, #totpNext');
	if (await clickFirstVisible(explicitNext, 1500)) return;
	await clickFirstVisible(page.getByRole('button', { name: /next|continue|allow/i }), 3000);
}

async function checkVisibleGoogleScopes(page: any): Promise<void> {
	const checkboxes = page.locator('input[type="checkbox"]');
	const count = await checkboxes.count().catch(() => 0);
	for (let index = 0; index < count; index += 1) {
		const checkbox = checkboxes.nth(index);
		if (await checkbox.isVisible().catch(() => false)) {
			await checkbox.check({ force: true }).catch(() => undefined);
		}
	}
}

async function completeGoogleCalendarOAuth(page: any, logCheckpoint: (message: string) => void): Promise<void> {
	await page.waitForURL(/accounts\.google\.com|\/v1\/provider-oauth\/google\/calendar/, { timeout: 30000 });

	for (let attempt = 0; attempt < 30; attempt += 1) {
		const url = page.url();
		if (url.includes('oauth_handoff_id=') || url.includes('/#settings/apps/calendar')) {
			logCheckpoint('Returned from Google OAuth to OpenMates.');
			return;
		}

		if (GOOGLE_TEST_EMAIL) {
			if (await clickFirstVisible(page.getByText(GOOGLE_TEST_EMAIL, { exact: false }), 1000)) {
				logCheckpoint('Selected existing Google test account.');
				await page.waitForTimeout(1000);
				continue;
			}

			if (await fillFirstVisible(page.locator('input[type="email"], input[name="identifier"]'), GOOGLE_TEST_EMAIL, 1000)) {
				logCheckpoint('Entered Google test account email.');
				await clickGoogleNext(page);
				await page.waitForTimeout(1500);
				continue;
			}
		}

		if (GOOGLE_TEST_PASSWORD && await fillFirstVisible(page.locator('input[type="password"], input[name="Passwd"]'), GOOGLE_TEST_PASSWORD, 1000)) {
			logCheckpoint('Entered Google test account password.');
			await clickGoogleNext(page);
			await page.waitForTimeout(2000);
			continue;
		}

		if (GOOGLE_TEST_TOTP_KEY && await fillFirstVisible(page.locator('input[type="tel"], input[type="number"]'), generateTotp(GOOGLE_TEST_TOTP_KEY), 1000)) {
			logCheckpoint('Entered Google test account TOTP.');
			await clickGoogleNext(page);
			await page.waitForTimeout(2000);
			continue;
		}

		if (await clickFirstVisible(page.getByRole('button', { name: /advanced/i }), 1000)) {
			logCheckpoint('Opened Google unverified-app advanced section.');
			await page.waitForTimeout(500);
			continue;
		}

		if (await clickFirstVisible(page.getByRole('link', { name: /go to .*unsafe/i }), 1000)) {
			logCheckpoint('Continued through Google unverified-app warning.');
			await page.waitForTimeout(1500);
			continue;
		}

		await checkVisibleGoogleScopes(page);
		if (await clickFirstVisible(page.getByRole('button', { name: /continue|allow/i }), 1000)) {
			logCheckpoint('Accepted Google Calendar consent prompt.');
			await page.waitForTimeout(2000);
			continue;
		}

		await page.waitForTimeout(1000);
	}

	throw new Error(`Google OAuth did not return to OpenMates. Current URL: ${page.url()}`);
}

test.describe('Calendar connected-account live Google OAuth', () => {
	test.describe.configure({ timeout: 300000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	skipWithoutGoogleOAuthCredentials();

	test('connects Google Calendar through the live OAuth broker', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CONNECTED_ACCOUNT_CALENDAR_LIVE_OAUTH');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'connected-account-calendar-live-oauth',
		});
		let savedConnectedAccountRow: Record<string, unknown> | null = null;

		await archiveExistingScreenshots(logCheckpoint);
		await page.route('**/v1/connected-accounts', async (route: any) => {
			if (route.request().method() === 'POST') {
				savedConnectedAccountRow = route.request().postDataJSON() as Record<string, unknown>;
			}
			await route.continue();
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await page.goto(getE2EDebugUrl('/#settings/apps/calendar'), { waitUntil: 'domcontentloaded' });
		const settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/calendar"]');
		await expect(settingsMenu).toBeVisible({ timeout: 20000 });

		const accountSection = settingsMenu.getByTestId('calendar-connected-accounts-section');
		await expect(accountSection).toBeVisible({ timeout: 20000 });
		await settingsMenu.getByTestId('connect-google-calendar-button').click();
		logCheckpoint('Clicked Google Calendar connect button for live OAuth.');

		await completeGoogleCalendarOAuth(page, logCheckpoint);
		await expect.poll(() => savedConnectedAccountRow, {
			message: 'live OAuth created an encrypted connected-account row',
			timeout: 45000
		}).not.toBeNull();
		await expect(accountSection).toContainText(/\d+ connected/, { timeout: 30000 });
		await expect(page).not.toHaveURL(/oauth_handoff_id=/, { timeout: 30000 });

		const finalConnectedAccountRow: Record<string, unknown> = savedConnectedAccountRow ?? {};
		const savedRowJson = JSON.stringify(finalConnectedAccountRow);
		expect(finalConnectedAccountRow.provider_type_hash).toBeTruthy();
		expect(savedRowJson).not.toContain(GOOGLE_TEST_EMAIL ?? '<missing-google-email>');
		expect(savedRowJson).not.toContain(GOOGLE_TEST_PASSWORD ?? '<missing-google-password>');
		expect(savedRowJson).not.toContain('refresh_token');
		expect(savedRowJson).not.toContain('google_calendar"');
		await takeStepScreenshot(page, 'live-google-calendar-connected');
	});
});
