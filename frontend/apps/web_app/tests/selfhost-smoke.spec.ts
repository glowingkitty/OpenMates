/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Self-hosted install smoke test.
 *
 * Runs against a GitHub Actions-provisioned local self-hosted stack. This test
 * intentionally avoids chat, LLM calls, provider APIs, and app skills so the
 * minimum installer can be verified without secrets or paid external services.
 */

const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { openSignupInterface } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, setToggleChecked } = require('./signup-flow-helpers');

const SELFHOST_API_URL = process.env.SELFHOST_API_URL || 'http://localhost:8000';
const SELFHOST_INSTALL_PATH = process.env.SELFHOST_INSTALL_PATH || '/tmp/openmates-selfhost';

function readInstallEnv(name: string): string {
 const envPath = path.join(SELFHOST_INSTALL_PATH, '.env');
 const content = fs.readFileSync(envPath, 'utf-8');
 const line = content.split('\n').find((entry: string) => entry.startsWith(`${name}=`));
 return line ? line.slice(name.length + 1).trim() : '';
}

async function getBrowserSession(page: any): Promise<any> {
 return page.evaluate(async (apiUrl: string) => {
  const response = await fetch(`${apiUrl}/v1/auth/session`, {
   method: 'POST',
   credentials: 'include'
  });
  return {
   ok: response.ok,
   status: response.status,
   json: await response.json()
  };
 }, SELFHOST_API_URL);
}

async function waitForAdminStatus(page: any, expected: boolean): Promise<any> {
 let latestSession: any = null;
 await expect
  .poll(
   async () => {
    latestSession = await getBrowserSession(page);
    return latestSession.json?.user?.is_admin === expected;
   },
   { timeout: 30000, intervals: [1000, 2000, 3000] }
  )
  .toBe(true);
 return latestSession;
}

test('self-hosted install starts, signs up a user, and promotes admin', async ({ page, request }) => {
 test.slow();
 test.setTimeout(180000);

 const firstInviteCode = readInstallEnv('SELF_HOST_FIRST_INVITE_CODE');
 expect(firstInviteCode, 'first signup invite code should be generated during install').toMatch(
  /^[0-9]{4}-[0-9]{4}-[0-9]{4}$/
 );

 const signupEmail = `selfhost-${Date.now()}@example.test`;
 const signupUsername = signupEmail.split('@')[0].replace(/[^a-zA-Z0-9._]/g, '_');
 const signupPassword = 'SelfHostSmoke!234Secure';

 const pageResponse = await page.goto(getE2EDebugUrl('/'));
 expect(pageResponse?.ok(), 'web app root should respond successfully').toBe(true);

	await page.waitForLoadState('networkidle');
	const bodyText = await page.evaluate(() => document.body.textContent || '');
	expect(bodyText.length, 'web app should render visible content').toBeGreaterThan(20);

	const apiResponse = await request.get(`${SELFHOST_API_URL}/v1/settings/server-status`);
	expect(apiResponse.ok(), 'backend server status endpoint should respond').toBe(true);

	const status = await apiResponse.json();
	expect(status.is_self_hosted).toBe(true);
	expect(status.payment_enabled).toBe(false);
	expect(status.ai_models_configured).toBe(false);

 const sessionResponse = await request.post(`${SELFHOST_API_URL}/v1/auth/session`);
 expect(sessionResponse.ok(), 'unauthenticated session endpoint should respond').toBe(true);
 const session = await sessionResponse.json();
	expect(session.success).toBe(false);
	expect(session.require_invite_code).toBe(true);

	const browserStatus = await page.evaluate(async (apiUrl: string) => {
		const response = await fetch(`${apiUrl}/v1/settings/server-status`);
		return {
			ok: response.ok,
			status: response.status,
			json: await response.json()
		};
	}, SELFHOST_API_URL);

 expect(browserStatus.ok, `browser fetch failed with ${browserStatus.status}`).toBe(true);
 expect(browserStatus.json.is_self_hosted).toBe(true);

 await openSignupInterface(page, 30000);

 const loginTabs = page.getByTestId('login-tabs');
 await expect(loginTabs).toBeVisible({ timeout: 15000 });
 await loginTabs.getByRole('button', { name: /sign up/i }).click();
 await page.getByRole('button', { name: /continue/i }).click();

 const inviteInput = page.locator('input[maxlength="14"]').first();
 await expect(inviteInput).toBeVisible({ timeout: 10000 });
 await inviteInput.fill(firstInviteCode);
 await expect(page.locator('input[autocomplete="email"]')).toBeVisible({ timeout: 15000 });

 await page.locator('input[autocomplete="email"]').fill(signupEmail);
 await page.locator('input[autocomplete="username"]').fill(signupUsername);
 await setToggleChecked(page.locator('#terms-agreed-toggle'), true);
 await setToggleChecked(page.locator('#privacy-agreed-toggle'), true);
 await page.getByRole('button', { name: /create new account/i }).click();

 const passwordOption = page.locator('#signup-password-option');
 await expect(passwordOption).toBeVisible({ timeout: 15000 });
 await passwordOption.click();

 const passwordInputs = page.locator('input[autocomplete="new-password"]');
 await expect(passwordInputs).toHaveCount(2, { timeout: 10000 });
 await passwordInputs.nth(0).fill(signupPassword);
 await passwordInputs.nth(1).fill(signupPassword);
 await page.locator('#signup-password-continue').click();

 await expect(page.getByRole('button', { name: /logout/i }).or(page.getByTestId('profile-container'))).toBeVisible({
  timeout: 45000
 });

 const signedUpSession = await waitForAdminStatus(page, false);
 expect(signedUpSession.ok, `session after signup failed with ${signedUpSession.status}`).toBe(true);
 expect(signedUpSession.json.success).toBe(true);
 expect(signedUpSession.json.user?.is_admin).toBe(false);

 execFileSync('openmates', ['server', 'make-admin', signupEmail, '--path', SELFHOST_INSTALL_PATH], {
  stdio: 'inherit'
 });

 const adminSession = await waitForAdminStatus(page, true);
 expect(adminSession.json.success).toBe(true);
 expect(adminSession.json.user?.is_admin).toBe(true);
});
