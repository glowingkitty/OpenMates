import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

function corsHeaders(origin: string) {
	return {
		'access-control-allow-origin': origin,
		'access-control-allow-credentials': 'true',
		'access-control-allow-methods': 'GET, POST, OPTIONS',
		'access-control-allow-headers': 'content-type'
	};
}

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification
test('changing a password without enrolled TOTP uses password and one-use email proof', async ({
	page
}) => {
	let emailRequests = 0;
	let emailVerifications = 0;
	let passwordUpdates = 0;
	let proofVerified = false;
	const challengeId = 'preview-password-change-challenge';
	await page.route('**/v1/auth/methods', async (route) => {
		const origin = route.request().headers().origin || 'http://localhost:5173';
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
			body: JSON.stringify({ has_password: true, has_passkey: false, has_2fa: false, credential_version: 2 })
		});
	});
	await page.route('**/v1/auth/sensitive/email/**', async (route) => {
		const request = route.request();
		const origin = request.headers().origin || 'http://localhost:5173';
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers: corsHeaders(origin) });
			return;
		}
		const payload = request.postDataJSON();
		if (request.url().endsWith('/request')) {
			emailRequests++;
            expect(payload).toMatchObject({
                purpose: 'credential_change',
                email: 'password-preview@example.test'
            });
            expect(payload.session_id).toEqual(expect.any(String));
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				headers: corsHeaders(origin),
                body: JSON.stringify({ success: true, challenge_id: challengeId, expires_in: 600,
                    password_challenge_id: 'password-challenge-id', password_nonce: 'ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8' })
			});
			return;
		}
		emailVerifications++;
		expect(payload).toMatchObject({
			purpose: 'credential_change',
			challenge_id: challengeId,
			code: '123456'
		});
		expect(payload.hashed_email).toEqual(expect.any(String));
        expect(payload.lookup_hash).toBeUndefined();
        expect(payload.password_challenge_id).toBe('password-challenge-id');
        expect(payload.password_proof).toMatch(/^[A-Za-z0-9_-]{43}$/);
		expect(request.postData()).not.toContain('CurrentPassword!');
		proofVerified = true;
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
			body: JSON.stringify({ success: true, expires_in: 300 })
		});
	});
	await page.route('**/v1/settings/update-password', async (route) => {
		const request = route.request();
		const origin = request.headers().origin || 'http://localhost:5173';
		if (request.method() === 'OPTIONS') {
			await route.fulfill({ status: 204, headers: corsHeaders(origin) });
			return;
		}
		passwordUpdates++;
		expect(proofVerified).toBe(true);
		const payload = request.postDataJSON();
		expect(payload).toMatchObject({ is_new_password: false });
        expect(payload.credential_version).toBe(2);
        expect(payload.password_auth_key).toMatch(/^[A-Za-z0-9_-]{43}$/);
        expect(payload.lookup_hash).toBeUndefined();
		expect(payload.encrypted_master_key).toEqual(expect.any(String));
		expect(request.postData()).not.toContain('NextPassword2!');
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: corsHeaders(origin),
            body: JSON.stringify({ success: true, message: 'Password changed successfully', legacy_password_retained: false })
		});
	});

	await page.goto('/dev/preview/settings/security/SettingsPassword?theme=light&chrome=0');
	await waitForComponentPreview(page);
	await expect(page.getByTestId('password-input')).toBeVisible();
	await page.getByTestId('password-input').fill('CurrentPassword!');
	await page.getByTestId('auth-btn').click();
	await expect(page.getByTestId('auth-email-otp')).toBeVisible();
	await page.getByTestId('auth-email-otp').locator('input').fill('123456');
	await expect(page.locator('#new-password')).toBeVisible();
	await expect(page.getByText('2FA setup', { exact: false })).toHaveCount(0);
	await page.locator('#new-password').fill('NextPassword2!');
	await page.locator('#confirm-password').fill('NextPassword2!');
	await page.getByRole('button', { name: /change password/i }).click();
    await expect(page.getByText(/password has been changed successfully/i)).toBeVisible();
	expect(emailRequests).toBe(1);
	expect(emailVerifications).toBe(1);
	expect(passwordUpdates).toBe(1);
});

// contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection
test('ambiguous legacy password change is deferred without claiming success', async ({ page }) => {
    await page.route('**/v1/auth/methods', async (route) => {
        if (route.request().method() === 'OPTIONS') {
            await route.fulfill({ status: 204, headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173') });
            return;
        }
        await route.fulfill({ status: 200, contentType: 'application/json',
            headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173'),
            body: JSON.stringify({ has_password: true, has_passkey: false, has_2fa: false, credential_version: 1 }) });
    });
    await page.route('**/v1/auth/sensitive/email/**', async (route) => {
        if (route.request().method() === 'OPTIONS') {
            await route.fulfill({ status: 204, headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173') });
            return;
        }
        if (route.request().url().endsWith('/request')) {
            await route.fulfill({ status: 200, contentType: 'application/json',
                headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173'),
                body: JSON.stringify({ success: true, challenge_id: 'legacy-password-change', expires_in: 600 }) });
        } else {
            await route.fulfill({ status: 200, contentType: 'application/json',
                headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173'),
                body: JSON.stringify({ success: true }) });
        }
    });
    await page.route('**/v1/settings/update-password', async (route) => {
        if (route.request().method() === 'OPTIONS') {
            await route.fulfill({ status: 204, headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173') });
            return;
        }
        await route.fulfill({ status: 409, contentType: 'application/json',
            headers: corsHeaders(route.request().headers().origin || 'http://localhost:5173'),
            body: JSON.stringify({ detail: { error: 'legacy_credential_binding_required', migration_status: 'deferred_legacy_credentials' } }) });
    });
    await page.goto('/dev/preview/settings/security/SettingsPassword?theme=light&chrome=0');
    await waitForComponentPreview(page);
    await page.getByTestId('password-input').fill('CurrentPassword!');
    await page.getByTestId('auth-btn').click();
    await page.getByTestId('auth-email-otp').locator('input').fill('123456');
    await expect(page.locator('#new-password')).toBeVisible();
    await page.locator('#new-password').fill('NextPassword2!');
    await page.locator('#confirm-password').fill('NextPassword2!');
    await page.getByRole('button', { name: /change password/i }).click();
    await expect(page.getByText(/current password still works/i)).toBeVisible();
    await expect(page.getByText(/password has been changed successfully/i)).toHaveCount(0);
});
