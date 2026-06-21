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
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { openSignupInterface } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, setToggleChecked } = require('./signup-flow-helpers');

const SELFHOST_API_URL = process.env.SELFHOST_API_URL || 'http://localhost:8000';
const SELFHOST_APP_URL = process.env.SELFHOST_APP_URL || 'http://localhost:5173';
const SELFHOST_INSTALL_PATH = process.env.SELFHOST_INSTALL_PATH || '/tmp/openmates-selfhost';
const OPENMATES_CLI_PATH = process.env.OPENMATES_CLI_PATH || '';

test.describe.configure({ retries: 0 });

function readInstallEnv(name: string): string {
 const envPath = path.join(SELFHOST_INSTALL_PATH, '.env');
 const content = fs.readFileSync(envPath, 'utf-8');
 const line = content.split('\n').find((entry: string) => entry.startsWith(`${name}=`));
 return line ? line.slice(name.length + 1).trim() : '';
}

function runOpenMatesServer(args: string[], options: any = {}): string {
 const serverArgs = ['server', ...args, '--path', SELFHOST_INSTALL_PATH];
 if (OPENMATES_CLI_PATH) {
  return execFileSync(process.execPath, [OPENMATES_CLI_PATH, ...serverArgs], {
   encoding: options.stdio ? undefined : 'utf-8',
   maxBuffer: 64 * 1024 * 1024,
   ...options
  });
 }
 return execFileSync('openmates', serverArgs, {
  encoding: options.stdio ? undefined : 'utf-8',
  maxBuffer: 64 * 1024 * 1024,
  ...options
 });
}

function sqlString(value: string): string {
 return `'${value.replace(/'/g, "''")}'`;
}

function runDatabaseSql(sql: string): string {
 const databaseUser = readInstallEnv('DATABASE_USERNAME') || 'directus';
 const databaseName = readInstallEnv('DATABASE_NAME') || 'directus';
 return execFileSync(
  'docker',
  ['exec', 'cms-database', 'psql', '-U', databaseUser, '-d', databaseName, '-tAc', sql],
  { encoding: 'utf-8' }
 ).trim();
}

function assertCliDefaultsToInstalledSelfHost(): void {
 const serverConfigPath = path.join(os.homedir(), '.openmates', 'server.json');
 expect(fs.existsSync(serverConfigPath), 'server install should persist ~/.openmates/server.json').toBe(true);

 const serverConfig = JSON.parse(fs.readFileSync(serverConfigPath, 'utf-8'));
 expect(serverConfig.installPath).toBe(SELFHOST_INSTALL_PATH);
 expect(serverConfig.apiUrl).toBe(SELFHOST_API_URL);
 expect(serverConfig.appUrl).toBe(SELFHOST_APP_URL);

 const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-selfhost-cli-'));
 try {
  const tempStateDir = path.join(tempHome, '.openmates');
  fs.mkdirSync(tempStateDir, { recursive: true });
  fs.copyFileSync(serverConfigPath, path.join(tempStateDir, 'server.json'));

  const repoRoot = path.resolve(process.cwd(), '../../..');
  const cliIndexUrl = pathToFileURL(path.join(repoRoot, 'frontend/packages/openmates-cli/dist/index.js')).href;
  const script = `
    import { OpenMatesClient, deriveAppUrl } from ${JSON.stringify(cliIndexUrl)};
    const client = OpenMatesClient.load();
    console.log(JSON.stringify({ apiUrl: client.apiUrl, appUrl: deriveAppUrl(client.apiUrl) }));
  `;
  const env = { ...process.env, HOME: tempHome, USERPROFILE: tempHome };
  delete env.OPENMATES_API_URL;
  delete env.OPENMATES_APP_URL;

  const output = execFileSync(process.execPath, ['--input-type=module', '-e', script], {
   encoding: 'utf-8',
   env
  });
  const detected = JSON.parse(output);
  expect(detected.apiUrl).toBe(SELFHOST_API_URL);
  expect(detected.appUrl).toBe(SELFHOST_APP_URL);
 } finally {
  fs.rmSync(tempHome, { recursive: true, force: true });
 }
}

async function getBrowserSession(page: any): Promise<any> {
 return page.evaluate(async (apiUrl: string) => {
  const sessionId = sessionStorage.getItem('session_id');
  const response = await fetch(`${apiUrl}/v1/auth/session`, {
   method: 'POST',
   headers: {
    'Content-Type': 'application/json'
   },
   body: JSON.stringify({ session_id: sessionId }),
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
	const installEnvPath = path.join(SELFHOST_INSTALL_PATH, '.env');
	test.skip(
		!fs.existsSync(installEnvPath),
		`self-hosted install fixture is not provisioned at ${installEnvPath}`
	);

	const firstInviteCode = readInstallEnv('SELF_HOST_FIRST_INVITE_CODE');
  expect(firstInviteCode, 'first signup invite code should be generated during install').toMatch(
   /^[0-9]{4}-[0-9]{4}-[0-9]{4}$/
  );

 assertCliDefaultsToInstalledSelfHost();

  const signupEmail = `selfhost-${Date.now()}@example.test`;
 const signupUsername = `selfhost_${Date.now().toString(36).slice(-8)}`;
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
	expect(status).not.toHaveProperty('payment_enabled');
	expect(status).not.toHaveProperty('free_testing_credits');
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
	expect(browserStatus.json).not.toHaveProperty('free_testing_credits');

 await openSignupInterface(page, 30000);

 const loginTabs = page.getByTestId('login-tabs');
 await expect(loginTabs).toBeVisible({ timeout: 15000 });
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await page.getByRole('button', { name: /continue/i }).click();
	await expect(page.getByText('Free credits for testing')).toHaveCount(0);

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
	// docAssert('invite signup creates a normal user and make-admin promotes that user')
	expect(signedUpSession.ok, `session after signup failed with ${signedUpSession.status}`).toBe(true);
	expect(signedUpSession.json.success).toBe(true);
	expect(signedUpSession.json.user?.is_admin).toBe(false);

 runOpenMatesServer(['make-admin', signupEmail], { stdio: 'inherit' });

	const adminSession = await waitForAdminStatus(page, true);
	// docAssert('openmates server make-admin promotes a self-hosted signup user to admin')
	expect(adminSession.json.success).toBe(true);
	expect(adminSession.json.user?.is_admin).toBe(true);

 const userId = adminSession.json.user?.id;
 expect(userId, 'admin session should expose restored user id').toBeTruthy();

 const repoRoot = process.env.GITHUB_WORKSPACE || path.resolve(process.cwd(), '../../..');
 const backupPath = path.join(repoRoot, 'test-results', 'selfhost-user-data-backup.tar.gz');
 fs.mkdirSync(path.dirname(backupPath), { recursive: true });
 const backup = JSON.parse(runOpenMatesServer(['backup', '--output', backupPath, '--json']));
 expect(backup.status).toBe('success');
 expect(backup.file).toBe(backupPath);
 expect(fs.existsSync(backupPath), 'server backup should write an archive').toBe(true);
 expect(fs.statSync(backupPath).mode & 0o777, 'backup archive should be owner-readable only').toBe(0o600);

 runDatabaseSql(`UPDATE directus_users SET is_admin = false WHERE id = ${sqlString(userId)}`);
 expect(runDatabaseSql(`SELECT is_admin::text FROM directus_users WHERE id = ${sqlString(userId)}`)).toBe('false');

 runOpenMatesServer(['restore', '--file', backupPath, '--yes'], { stdio: 'inherit' });
 expect(runDatabaseSql(`SELECT is_admin::text FROM directus_users WHERE id = ${sqlString(userId)}`)).toBe('true');
 await page.goto(getE2EDebugUrl('/'));
 const restoredSession = await waitForAdminStatus(page, true);
 expect(restoredSession.json.user?.id).toBe(userId);

	const selfHostedCloudOnlyStatuses = await page.evaluate(async (apiUrl: string) => {
		const requests = [
			{ method: 'GET', path: '/v1/admin/free-testing-credits-budget' },
			{
				method: 'PUT',
				path: '/v1/admin/free-testing-credits-budget',
				body: { enabled: true, total_budget_credits: 1000, per_user_grant_credits: 1000 }
			},
			{
				method: 'POST',
				path: '/v1/admin/generate-gift-cards',
				body: { credits_value: 1000, count: 1 }
			},
			{ method: 'GET', path: '/v1/admin/gift-cards' },
			{
				method: 'POST',
				path: '/v1/payments/redeem-gift-card',
				body: { code: 'ABCD-EFGH-IJKL' }
			},
			{
				method: 'POST',
				path: '/v1/payments/buy-gift-card',
				body: { credits_amount: 1000, currency: 'eur', email_encryption_key: 'test-key' }
			},
			{
				method: 'POST',
				path: '/v1/payments/create-gift-card-bank-transfer-order',
				body: { credits_amount: 1000, currency: 'eur', email_encryption_key: 'test-key' }
			},
			{ method: 'GET', path: '/v1/payments/gift-card-purchase-status/selfhost-test-order' },
			{ method: 'GET', path: '/v1/payments/redeemed-gift-cards' }
		];

		return Promise.all(
			requests.map(async ({ method, path, body }) => {
				const response = await fetch(`${apiUrl}${path}`, {
					method,
					headers: body ? { 'Content-Type': 'application/json' } : undefined,
					body: body ? JSON.stringify(body) : undefined,
					credentials: 'include'
				});
				return { path, status: response.status };
			})
		);
	}, SELFHOST_API_URL);

	for (const endpointStatus of selfHostedCloudOnlyStatuses) {
		expect(endpointStatus.status, `${endpointStatus.path} should be hidden on self-hosted`).toBe(404);
	}
});
