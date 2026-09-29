import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Route } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview

function corsHeaders(origin: string) {
	return {
		'access-control-allow-origin': origin,
		'access-control-allow-credentials': 'true',
		'access-control-allow-methods': 'GET, POST, OPTIONS',
		'access-control-allow-headers': 'content-type'
	};
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
	const origin = route.request().headers().origin || 'http://localhost:5173';
	await route.fulfill({
		status,
		contentType: 'application/json',
		headers: corsHeaders(origin),
		body: JSON.stringify(body)
	});
}

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification
test('first-time 2FA setup accepts password plus one-use email proof without prior TOTP', async ({
	page
}) => {
	let verified = false;
	let emailRequests = 0;
	let setupRequests = 0;
	await page.route('**/v1/auth/methods', (route) =>
		fulfillJson(route, { has_password: true, has_passkey: false, has_2fa: false, credential_version: 2 })
	);
	await page.route('**/v1/auth/sensitive/email/**', async (route) => {
		const request = route.request();
		if (request.method() === 'OPTIONS') {
			await route.fulfill({
				status: 204,
				headers: corsHeaders(request.headers().origin || 'http://localhost:5173')
			});
			return;
		}
		const payload = request.postDataJSON();
		if (request.url().endsWith('/request')) {
			emailRequests++;
            expect(payload).toMatchObject({ purpose: 'factor_change', email: 'factor-preview@example.test' });
            expect(payload.session_id).toEqual(expect.any(String));
			await fulfillJson(route, {
				success: true,
				challenge_id: `preview-factor-challenge-${emailRequests}`,
                expires_in: 600,
                password_challenge_id: `password-factor-challenge-${emailRequests}`,
                password_nonce: 'ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8'
			});
			return;
		}
		expect(payload).toMatchObject({
			purpose: 'factor_change',
			challenge_id: `preview-factor-challenge-${emailRequests}`,
			code: '123456'
		});
		expect(payload.hashed_email).toEqual(expect.any(String));
        expect(payload.lookup_hash).toBeUndefined();
        expect(payload.password_challenge_id).toBe(`password-factor-challenge-${emailRequests}`);
        expect(payload.password_proof).toMatch(/^[A-Za-z0-9_-]{43}$/);
		expect(request.postData()).not.toContain('CurrentPassword!');
		verified = true;
		await fulfillJson(route, { success: true, expires_in: 300 });
	});
	await page.route('**/v1/auth/2fa/setup/initiate', async (route) => {
		if (route.request().method() === 'OPTIONS') {
			await route.fulfill({
				status: 204,
				headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173')
			});
			return;
		}
		setupRequests++;
		expect(verified).toBe(true);
		expect(route.request().postDataJSON().email_encryption_key).toEqual(expect.any(String));
		if (setupRequests === 1) {
			await fulfillJson(route, { detail: 'Recent verification required' }, 401);
			return;
		}
		await fulfillJson(route, {
			success: true,
			secret: 'JBSWY3DPEHPK3PXP',
			otpauth_url: 'otpauth://totp/OpenMates:preview?secret=JBSWY3DPEHPK3PXP&issuer=OpenMates'
		});
	});

	await page.goto('/dev/preview/settings/security/SettingsTwoFactorAuth?theme=light&chrome=0');
	await waitForComponentPreview(page);
	await page.getByTestId('tfa-enable-button').click();
	await expect(page.getByTestId('password-input')).toBeVisible();
	await page.getByTestId('password-input').fill('CurrentPassword!');
	await page.getByTestId('auth-btn').click();
	await expect(page.getByTestId('auth-email-otp')).toBeVisible();
	await page.getByTestId('auth-email-otp').locator('input').fill('123456');
	await expect(page.getByTestId('password-input')).toBeVisible();
	await page.getByTestId('password-input').fill('CurrentPassword!');
	await page.getByTestId('auth-btn').click();
	await expect(page.getByTestId('auth-email-otp')).toBeVisible();
	await page.getByTestId('auth-email-otp').locator('input').fill('123456');
	await expect(page.getByTestId('qr-code')).toBeVisible();
	await expect(page.getByTestId('secret-value')).toContainText('JBSWY3DPEHPK3PXP');
	expect(emailRequests).toBe(2);
	expect(setupRequests).toBe(2);
});

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification
test('backup regeneration and 2FA disable use distinct TOTP proof purposes', async ({ page }) => {
	const verifiedPurposes: string[] = [];
	let backupReset = 0;
	let disabled = 0;
	await page.route('**/v1/auth/methods', (route) =>
		fulfillJson(route, { has_password: true, has_passkey: false, has_2fa: true })
	);
	await page.route('**/v1/auth/sensitive/totp/verify', async (route) => {
		if (route.request().method() === 'OPTIONS') {
			await route.fulfill({
				status: 204,
				headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173')
			});
			return;
		}
		const payload = route.request().postDataJSON();
		expect(payload.code).toBe('123456');
		verifiedPurposes.push(payload.purpose);
		await fulfillJson(route, { success: true, expires_in: 300 });
	});
	await page.route('**/v1/auth/2fa/setup/reset-backup-codes', async (route) => {
		if (route.request().method() === 'OPTIONS') {
			await route.fulfill({
				status: 204,
				headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173')
			});
			return;
		}
		backupReset++;
		expect(verifiedPurposes).toContain('backup_codes');
		await fulfillJson(route, { success: true, backup_codes: ['ABCD-EFGH-JKLM'] });
	});
	await page.route('**/v1/settings/user/disable-2fa', async (route) => {
		if (route.request().method() === 'OPTIONS') {
			await route.fulfill({
				status: 204,
				headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173')
			});
			return;
		}
		disabled++;
		expect(verifiedPurposes).toContain('factor_change');
		expect(route.request().postDataJSON()).toEqual({ confirmed_less_secure: true });
		await fulfillJson(route, { success: true });
	});

	await page.goto(
		'/dev/preview/settings/security/SettingsTwoFactorAuth?theme=light&enabled=1&chrome=0'
	);
	await waitForComponentPreview(page);
	await page.getByTestId('tfa-reset-backup-codes-button').click();
	await page.getByTestId('tfa-input').fill('123456');
	await expect(page.getByTestId('tfa-backup-codes')).toBeVisible();
	await page.getByTestId('confirm-checkbox').locator('input').check();
	await page.getByTestId('tfa-backup-codes').getByRole('button', { name: /done/i }).click();
	await page.getByTestId('tfa-disable-button').click();
	await page.getByTestId('tfa-input').fill('123456');
	await expect(page.getByTestId('tfa-disable-confirm')).toBeVisible();
	await page.getByTestId('tfa-disable-confirm-button').click();
	await expect(page.getByTestId('tfa-enable-button')).toBeVisible();
	expect(verifiedPurposes).toEqual(['backup_codes', 'factor_change']);
	expect(backupReset).toBe(1);
	expect(disabled).toBe(1);
});
