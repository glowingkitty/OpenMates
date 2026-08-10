/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Proton local connector settings contract.
 *
 * Verifies the web settings surface can show Proton Mail Bridge local connector
 * status from non-secret connector metadata, without exposing Bridge credentials,
 * and can revoke the connector metadata through the connected-account API.
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

const FORBIDDEN_SECRET_TEXT = /bridge-password|imap-password|smtp-password|proton-password|secret-bridge-pass|secret-smtp-pass/i;

function buildLocalConnectorRow(status: 'online' | 'offline' | 'revoked') {
	return {
		id: 'proton-local-connector-e2e',
		hashed_user_id: 'hash-only-user-id',
		encrypted_provider_type: 'not-valid-test-ciphertext',
		provider_type_hash: 'hash-only-provider-id',
		encrypted_account_label: 'not-valid-test-ciphertext',
		encrypted_refresh_token_bundle: 'not-valid-test-ciphertext',
		encrypted_capabilities: 'not-valid-test-ciphertext',
		encrypted_app_permissions: 'not-valid-test-ciphertext',
		encrypted_account_directory_hint: 'not-valid-test-ciphertext',
		execution_mode: 'local_connector',
		connector_provider_id: 'protonmail_bridge',
		connector_status: status,
		connector_public_metadata: {
			bridge_host: 'localhost',
			bridge_transport: 'imap_smtp',
			capabilities: ['read', 'write'],
			label: 'Proton Mail Local',
		},
		updated_at: Date.now(),
	};
}

test.describe('Proton local connector settings', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('shows status without secrets and revokes local connector metadata', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('PROTON_LOCAL_CONNECTOR_SETTINGS');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'proton-local-connector-settings',
		});
		let connectorStatus: 'online' | 'offline' | 'revoked' = 'online';
		let revokePatchBody: Record<string, unknown> | null = null;

		await archiveExistingScreenshots(logCheckpoint);
		await page.route('**/v1/connected-accounts', async (route: any) => {
			const request = route.request();
			if (request.method() !== 'GET') {
				await route.continue();
				return;
			}
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ rows: [buildLocalConnectorRow(connectorStatus)] }),
			});
		});
		await page.route('**/v1/connected-accounts/proton-local-connector-e2e', async (route: any) => {
			const request = route.request();
			if (request.method() !== 'PATCH') {
				await route.continue();
				return;
			}
			revokePatchBody = request.postDataJSON();
			expect(JSON.stringify(revokePatchBody)).not.toMatch(FORBIDDEN_SECRET_TEXT);
			expect(revokePatchBody).toEqual({ connector_status: 'revoked' });
			connectorStatus = 'revoked';
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ id: 'proton-local-connector-e2e', sync_version: Date.now() }),
			});
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await page.goto(getE2EDebugUrl('/#settings/privacy/connected-accounts'), { waitUntil: 'domcontentloaded' });
		const settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="privacy/connected-accounts"]');
		await expect(settingsMenu).toBeVisible({ timeout: 15000 });

		const connectedAccountsPage = settingsMenu.getByTestId('privacy-connected-accounts-page');
		await expect(connectedAccountsPage).toBeVisible({ timeout: 15000 });
		const accountItem = connectedAccountsPage.getByTestId('privacy-connected-account-item');
		await expect(accountItem).toContainText('Proton Mail Local', { timeout: 15000 });
		await expect(accountItem).toContainText('Proton Mail Bridge');
		await expect(accountItem).toContainText('Online via CLI');

		const details = connectedAccountsPage.getByTestId('privacy-connected-account-detail');
		await expect(details).toContainText('Mail');
		await expect(details).toContainText('Read events, Write events');
		await expect(connectedAccountsPage).not.toContainText(FORBIDDEN_SECRET_TEXT);
		await takeStepScreenshot(page, 'proton-local-connector-online');

		await connectedAccountsPage.getByTestId('privacy-connected-account-revoke-button').click();
		await expect.poll(() => revokePatchBody, {
			message: 'local connector revoke PATCH was sent',
			timeout: 15000,
		}).not.toBeNull();
		await expect(connectedAccountsPage).toContainText('Local connector revoked.', { timeout: 15000 });
		await expect(connectedAccountsPage).toContainText('Revoked');
		await expect(connectedAccountsPage.getByTestId('privacy-connected-account-revoke-button')).toHaveCount(0);
		await expect(connectedAccountsPage).not.toContainText(FORBIDDEN_SECRET_TEXT);
		await takeStepScreenshot(page, 'proton-local-connector-revoked');
	});
});
