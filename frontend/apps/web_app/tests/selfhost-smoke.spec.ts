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
const { openSignupInterface, loginToTestAccount } = require('./helpers/chat-test-helpers');
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

function readRecoveryCode(email: string): string {
 const password = readInstallEnv('DRAGONFLY_PASSWORD');
 expect(password, 'installed cache must have a password').toBeTruthy();
 // Pass the cache password through the docker client's environment so it never
 // appears in the command arguments, test output, or Playwright traces.
 return execFileSync('docker', [
  'exec', '-e', 'REDISCLI_AUTH', 'cache', 'redis-cli', '--raw', 'GET', `account_recovery:${email}`
 ], {
  encoding: 'utf-8',
  env: { ...process.env, REDISCLI_AUTH: password },
  stdio: ['ignore', 'pipe', 'ignore']
 }).trim();
}

async function completeRequiredInvite(page: any, inviteCode: string): Promise<void> {
 const inviteInput = page.locator('input[maxlength="14"]').first();
 const signupForm = page.locator('form').filter({ has: page.locator('input[autocomplete="username"]') });
 // The self-host fixture stays in invite_only mode after admin promotion.
 // Its form can briefly appear before the session response supplies that rule.
 await expect(inviteInput).toBeVisible({ timeout: 15000 });
 await inviteInput.fill(inviteCode);
 // The invite screen also renders a newsletter email input; wait for the
 // account form after real invite validation.
 await expect(signupForm.locator('input[autocomplete="email"]')).toBeVisible({ timeout: 15000 });
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

async function waitForUserSession(page: any, userId?: string): Promise<any> {
 let latestSession: any = null;
 await expect.poll(async () => {
  latestSession = await getBrowserSession(page);
  return latestSession.ok && latestSession.json?.success &&
   (!userId || latestSession.json?.user?.id === userId);
 }, { timeout: 45000, intervals: [500, 1000, 2000] }).toBe(true);
 return latestSession;
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

// contract-test: supporting surface=cli assertions=server-management.update.safety-sequence
test('self-hosted install starts, signs up a user, and promotes admin', async ({ page, request, browser }) => {
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
 // Verify the running image-mode CMS, not merely the source Compose file.
 const cacheSettings = execFileSync('docker', ['exec', 'cms', 'printenv',
  'CACHE_SKIP_ALLOWED', 'CACHE_AUTO_PURGE'], { encoding: 'utf-8' }).trim().split('\n');
 expect(cacheSettings, 'installed CMS must honor fresh reads and invalidate cached writes').toEqual(['true', 'true']);


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
	await expect(page.getByTestId('tab-signup')).toHaveClass(/active/);
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

	const authMethodRoutes = await page.evaluate(async (apiUrl: string) => {
		const [authResponse, legacyPaymentResponse] = await Promise.all([
			fetch(`${apiUrl}/v1/auth/methods`, { credentials: 'include' }),
			fetch(`${apiUrl}/v1/payments/user-auth-methods`, { credentials: 'include' })
		]);
		return {
			authStatus: authResponse.status,
			authBody: await authResponse.json(),
			legacyPaymentStatus: legacyPaymentResponse.status
		};
	}, SELFHOST_API_URL);
	expect(authMethodRoutes.authStatus).toBe(200);
	expect(authMethodRoutes.authBody.has_password).toBe(true);
	expect(authMethodRoutes.legacyPaymentStatus).toBe(404);

	await page.getByTestId('profile-container').click();
	await expect(page.getByTestId('settings-menu')).toBeVisible();
	await page.getByRole('menuitem', { name: /account/i }).click();
	await page.getByRole('menuitem', { name: /security/i }).click();
	await page.getByRole('menuitem', { name: /^password/i }).click();
	await expect(page.getByTestId('password-settings-container')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('password-settings-error')).toHaveCount(0);

	runOpenMatesServer(['make-admin', signupEmail], { stdio: 'inherit' });

	const adminSession = await waitForAdminStatus(page, true);
	// docAssert('openmates server make-admin promotes a self-hosted signup user to admin')
	expect(adminSession.json.success).toBe(true);
	expect(adminSession.json.user?.is_admin).toBe(true);

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

 // This backup is deliberately scoped to database/runtime state and cannot
 // safely serve as a complete core restore. Verify that refusal before
 // restoring the test account's admin flag through the supported command.
 expect(() => runOpenMatesServer(['restore', '--file', backupPath, '--yes']))
  .toThrow(/refusing unsafe full core restore/);
 expect(runDatabaseSql(`SELECT is_admin::text FROM directus_users WHERE id = ${sqlString(userId)}`)).toBe('false');
 // The first make-admin above already covers the supported promotion command.
 // Restore only the test fixture flag after verifying that unsafe restore
 // refused to touch the database.
 runDatabaseSql(`UPDATE directus_users SET is_admin = true WHERE id = ${sqlString(userId)}`);
 expect(runDatabaseSql(`SELECT is_admin::text FROM directus_users WHERE id = ${sqlString(userId)}`)).toBe('true');
 await page.goto(getE2EDebugUrl('/'));
 const rePromotedSession = await waitForAdminStatus(page, true);
 expect(rePromotedSession.json.user?.id).toBe(userId);

 // The account created above must remain accessible from fresh devices. The
 // first new browser encrypts a canary with the unwrapped account key; after
 // logout, a second new browser must independently unwrap and decrypt it.
 const originalLogout = await page.evaluate(async (apiUrl: string) => {
  const response = await fetch(`${apiUrl}/v1/auth/logout`, { method: 'POST', credentials: 'include' });
  return response.ok;
 }, SELFHOST_API_URL);
 expect(originalLogout, 'signup browser logout should succeed').toBe(true);

 const firstContext = await browser.newContext();
 let encryptedCanary = '';
 try {
  const firstPage = await firstContext.newPage();
  await loginToTestAccount(firstPage, () => {}, async () => {}, {
   waitForEditor: false,
   credentials: { email: signupEmail, password: signupPassword, otpKey: '' }
  });
  const firstSession = await getBrowserSession(firstPage);
  expect(firstSession.json.success).toBe(true);
  expect(firstSession.json.user?.id).toBe(userId);
  encryptedCanary = await firstPage.evaluate(async () => {
   const key = await new Promise<CryptoKey>((resolve, reject) => {
    const dbRequest = indexedDB.open('openmates_crypto');
    dbRequest.onerror = () => reject(dbRequest.error);
    dbRequest.onsuccess = () => {
     const db = dbRequest.result;
     const keyRequest = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
     keyRequest.onerror = () => reject(keyRequest.error);
     keyRequest.onsuccess = () => { db.close(); resolve(keyRequest.result); };
    };
   });
   if (!key) throw new Error('Fresh login did not persist an unwrapped account key');
   const iv = crypto.getRandomValues(new Uint8Array(12));
   const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv }, key, new TextEncoder().encode('selfhost-auth-canary-v1')
   ));
   return JSON.stringify({ iv: Array.from(iv), ciphertext: Array.from(ciphertext) });
  });
  const logout = await firstPage.evaluate(async (apiUrl: string) => {
   const response = await fetch(`${apiUrl}/v1/auth/logout`, { method: 'POST', credentials: 'include' });
   return response.ok;
  }, SELFHOST_API_URL);
  expect(logout, 'fresh browser logout should succeed').toBe(true);
 } finally {
  await firstContext.close();
 }

 const secondContext = await browser.newContext();
 try {
  const secondPage = await secondContext.newPage();
  await loginToTestAccount(secondPage, () => {}, async () => {}, {
   waitForEditor: false,
   credentials: { email: signupEmail, password: signupPassword, otpKey: '' }
  });
  const secondSession = await getBrowserSession(secondPage);
  expect(secondSession.json.success).toBe(true);
  expect(secondSession.json.user?.id).toBe(userId);
  const decrypted = await secondPage.evaluate(async (serialized: string) => {
   const key = await new Promise<CryptoKey>((resolve, reject) => {
    const dbRequest = indexedDB.open('openmates_crypto');
    dbRequest.onerror = () => reject(dbRequest.error);
    dbRequest.onsuccess = () => {
     const db = dbRequest.result;
     const keyRequest = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
     keyRequest.onerror = () => reject(keyRequest.error);
     keyRequest.onsuccess = () => { db.close(); resolve(keyRequest.result); };
    };
   });
   if (!key) throw new Error('Second fresh login did not unwrap account key');
   const artifact = JSON.parse(serialized);
   const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: new Uint8Array(artifact.iv) },
    key, new Uint8Array(artifact.ciphertext)
   );
   return new TextDecoder().decode(plaintext);
  }, encryptedCanary);
  expect(decrypted).toBe('selfhost-auth-canary-v1');
 } finally {
  await secondContext.close();
 }
});

// contract-test: direct surface=gui.web assertions=auth.signup.current-flow,auth.signup.transaction-bound,auth.passkey.origin-prf-bound,auth.keys.independent-unlock
test('self-hosted passkey signup and fresh local passkey login unwrap the same account key', async ({ page, context }) => {
 test.slow();
 test.setTimeout(180000);
 test.skip(!fs.existsSync(path.join(SELFHOST_INSTALL_PATH, '.env')), 'Self-hosted install fixture is required.');

 const timestamp = Date.now();
 const signupEmail = `selfhost-passkey-${timestamp}@example.test`;
 const signupUsername = `pk_${timestamp.toString(36).slice(-8)}`;
 const inviteCode = `${String(timestamp).slice(-4)}-${String(timestamp + 1).slice(-4)}-${String(timestamp + 2).slice(-4)}`;
 runDatabaseSql(`INSERT INTO invite_codes (id, code, remaining_uses) VALUES (gen_random_uuid(), ${sqlString(inviteCode)}, 1)`);

 const pageResponse = await page.goto(getE2EDebugUrl('/'));
 expect(pageResponse?.ok()).toBe(true);
 const client = await context.newCDPSession(page);
 await client.send('WebAuthn.enable');
 let virtualCredentialsAdded = 0;
 client.on('WebAuthn.credentialAdded', () => { virtualCredentialsAdded += 1; });
 const { authenticatorId } = await client.send('WebAuthn.addVirtualAuthenticator', {
  options: {
   protocol: 'ctap2', transport: 'usb', hasResidentKey: true,
   hasUserVerification: true, isUserVerified: true,
   automaticPresenceSimulation: true, hasPrf: true
  }
 });
 try {
  await openSignupInterface(page, 30000);
  await page.getByTestId('tab-signup').click();
  await expect(page.getByTestId('tab-signup')).toHaveClass(/active/);
  const basicsStatusResponse = page.waitForResponse((response: any) =>
   response.url().endsWith('/v1/settings/server-status') && response.request().method() === 'GET'
  );
  await page.getByRole('button', { name: /continue/i }).click();
  expect((await basicsStatusResponse).ok()).toBe(true);
  await completeRequiredInvite(page, inviteCode);
  const emailInput = page.locator('input[autocomplete="email"]');
  await emailInput.fill(signupEmail);
  await expect(emailInput).toHaveValue(signupEmail);
  const usernameCheck = page.waitForResponse((response: any) =>
   response.url().endsWith('/v1/auth/check_username_valid') && response.request().method() === 'POST'
  );
  await page.locator('input[autocomplete="username"]').fill(signupUsername);
  const usernameResponse = await usernameCheck;
  expect(usernameResponse.ok()).toBe(true);
  expect((await usernameResponse.json()).available).toBe(true);
  await expect(emailInput).toHaveValue(signupEmail);
  await setToggleChecked(page.locator('#terms-agreed-toggle'), true);
  await expect(emailInput).toHaveValue(signupEmail);
  await setToggleChecked(page.locator('#privacy-agreed-toggle'), true);
  await expect(emailInput).toHaveValue(signupEmail);
  await setToggleChecked(page.locator('#stayLoggedIn'), true);
  await expect(emailInput).toHaveValue(signupEmail);
  await expect(page.locator('input[autocomplete="username"]')).toHaveValue(signupUsername);
  const createAccountButton = page.getByRole('button', { name: /create new account/i });
  await expect(createAccountButton).toBeEnabled({ timeout: 20000 });
  await createAccountButton.click();
  const passkeyOption = page.locator('#signup-passkey-option');
  await expect(passkeyOption).toBeVisible({ timeout: 15000 });
  const passkeyBrowserErrors: string[] = [];
  page.on('console', (message: any) => {
   if (message.type() === 'error' || /Clearing signup data|Missing required signup data/i.test(message.text())) {
    passkeyBrowserErrors.push(message.text().slice(0, 300));
   }
  });
  page.on('pageerror', (error: Error) => passkeyBrowserErrors.push(`${error.name}: ${error.message.slice(0, 300)}`));
  const passkeyRequests: string[] = [];
  let initiation: any = null;
  let registration: any = null;
  page.on('request', (request: any) => {
   if (request.method() === 'POST' && /\/passkey\/registration\/(initiate|complete)$/.test(request.url())) {
    passkeyRequests.push(request.url().split('/').at(-1));
   }
  });
  page.on('response', (response: any) => {
   if (response.request().method() !== 'POST') return;
   if (response.url().endsWith('/v1/auth/passkey/registration/initiate')) initiation = response;
   if (response.url().endsWith('/v1/auth/passkey/registration/complete')) registration = response;
  });
  await passkeyOption.click({ timeout: 10000 });
  await expect.poll(() => Boolean(initiation), { timeout: 30000 }).toBe(true).catch(() => {
   throw new Error(`Passkey registration did not initiate (requests: ${passkeyRequests.join(', ') || 'none'}). Browser errors: ${passkeyBrowserErrors.join(' | ') || 'none'}`);
  });
  expect(initiation.ok(), 'passkey registration initiation must succeed').toBe(true);
  const initiationBody = await initiation.json();
  expect(initiationBody.success).toBe(true);
  await expect.poll(() => Boolean(registration), { timeout: 70000 }).toBe(true).catch(() => {
   throw new Error(`Passkey registration did not complete (RP ${initiationBody.rp?.id}, virtual credentials ${virtualCredentialsAdded}, requests: ${passkeyRequests.join(', ')}). Browser errors: ${passkeyBrowserErrors.join(' | ') || 'none'}`);
  });
  const body = await registration.json();
  expect(body.success, JSON.stringify(body)).toBe(true);
  await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 45000 });
  const signedUp = await waitForUserSession(page);
  const userId = signedUp.json.user?.id;
  expect(userId).toBeTruthy();

  // The canary is encrypted before logout with the signup key. A later passkey
  // login must recover that same key; merely receiving an auth cookie cannot pass.
  const encryptedCanary = await page.evaluate(async () => {
   const key = await new Promise<CryptoKey>((resolve, reject) => {
    const request = indexedDB.open('openmates_crypto');
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
     const db = request.result;
     const lookup = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
     lookup.onerror = () => { db.close(); reject(lookup.error); };
     lookup.onsuccess = () => { db.close(); resolve(lookup.result); };
    };
   });
   if (!key) throw new Error('Passkey signup did not store an unwrapped account key');
   const iv = crypto.getRandomValues(new Uint8Array(12));
   const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv }, key, new TextEncoder().encode('selfhost-passkey-canary-v1')
   ));
   return JSON.stringify({ iv: Array.from(iv), ciphertext: Array.from(ciphertext) });
  });

  const logout = await page.evaluate(async (apiUrl: string) => {
   const response = await fetch(`${apiUrl}/v1/auth/logout`, { method: 'POST', credentials: 'include' });
   if (!response.ok) return false;
   const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open('openmates_crypto');
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
   });
   await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction('keys', 'readwrite');
    transaction.objectStore('keys').delete('master_key');
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
   });
   db.close();
   sessionStorage.clear();
   localStorage.clear();
   return true;
  }, SELFHOST_API_URL);
  expect(logout, 'passkey signup session should log out').toBe(true);
  await page.goto(getE2EDebugUrl('/'));
  const loggedOut = await getBrowserSession(page);
  expect(loggedOut.json.success, 'logout must leave no authenticated session').toBe(false);
  const keyAfterLogout = await page.evaluate(async () => {
   return new Promise<boolean>((resolve, reject) => {
    const request = indexedDB.open('openmates_crypto');
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
     const db = request.result;
     const lookup = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
     lookup.onerror = () => { db.close(); reject(lookup.error); };
     lookup.onsuccess = () => { db.close(); resolve(Boolean(lookup.result)); };
    };
   });
  });
  expect(keyAfterLogout, 'no local master key may remain before passkey login').toBe(false);

  await openSignupInterface(page, 30000);
  await page.getByTestId('tab-login').click();
  await setToggleChecked(page.locator('#stayLoggedIn'), true);
  let passkeyLoginResponse: any = null;
  page.on('response', (response: any) => {
   if (response.url().endsWith('/v1/auth/login') && response.request().method() === 'POST') {
    passkeyLoginResponse = response;
   }
  });
  const assertionResponse = page.waitForResponse((response: any) =>
   response.url().includes('/passkey/assertion/verify') && response.request().method() === 'POST'
  );
  await page.getByTestId('login-passkey-button').click();
  const assertion = await assertionResponse;
  expect(assertion.ok(), 'server must verify a genuine passkey assertion').toBe(true);
  const assertionBody = await assertion.json();
  expect(assertionBody.success).toBe(true);
  expect(assertionBody.user_id).toBe(userId);
  await waitForUserSession(page, userId).catch(async () => {
   const loginResult = passkeyLoginResponse ? await passkeyLoginResponse.json().then((body: any) => ({
    status: passkeyLoginResponse.status(), success: body.success, message: body.message
   })).catch(() => ({ status: passkeyLoginResponse.status() })) : 'not requested';
   const clientFailure = await page.evaluate(() => {
    try {
     const stored = localStorage.getItem('openmates_last_login_error');
     if (!stored) return null;
     const parsed = JSON.parse(stored);
     return { path: parsed.path, error: String(parsed.error || '').slice(0, 200) };
    } catch { return 'unavailable'; }
   });
   throw new Error(`Passkey assertion verified but no user session. Login result: ${JSON.stringify(loginResult)}. Client failure: ${JSON.stringify(clientFailure)}. Browser errors: ${passkeyBrowserErrors.join(' | ') || 'none'}`);
  });
  await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 45000 });
  const decrypted = await page.evaluate(async (serialized: string) => {
   const key = await new Promise<CryptoKey>((resolve, reject) => {
    const request = indexedDB.open('openmates_crypto');
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
     const db = request.result;
     const lookup = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
     lookup.onerror = () => { db.close(); reject(lookup.error); };
     lookup.onsuccess = () => { db.close(); resolve(lookup.result); };
    };
   });
   if (!key) throw new Error('Passkey login did not store an unwrapped account key');
   const artifact = JSON.parse(serialized);
   const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: new Uint8Array(artifact.iv) },
    key, new Uint8Array(artifact.ciphertext)
   );
   return new TextDecoder().decode(plaintext);
  }, encryptedCanary);
  expect(decrypted).toBe('selfhost-passkey-canary-v1');
 } finally {
  if (!page.isClosed()) {
   await client.send('WebAuthn.removeVirtualAuthenticator', { authenticatorId });
   await client.send('WebAuthn.disable');
  }
 }
});

// contract-test: direct surface=gui.web assertions=auth.signup.current-flow,auth.recovery.email-delay,auth.session.lifecycle,auth.keys.independent-unlock
test('self-hosted account recovery schedules and cancels a reset while the old password still unlocks data', async ({ page, browser }: { page: any; browser: any }) => {
 test.slow();
 // Includes signup, recovery, a fresh-device password login, key decryption,
 // and cancellation on a resource-limited self-hosted CI runner.
 test.setTimeout(480000);
 test.skip(!fs.existsSync(path.join(SELFHOST_INSTALL_PATH, '.env')), 'Self-hosted install fixture is required.');

 const timestamp = Date.now();
 const email = `selfhost-recovery-${timestamp}@example.test`;
 const username = `rc_${timestamp.toString(36).slice(-8)}`;
 const password = 'SelfHostRecovery!234Secure';
 const inviteCode = `${String(timestamp).slice(-4)}-${String(timestamp + 1).slice(-4)}-${String(timestamp + 2).slice(-4)}`;
 runDatabaseSql(`INSERT INTO invite_codes (id, code, remaining_uses) VALUES (gen_random_uuid(), ${sqlString(inviteCode)}, 1)`);
 const signupBrowserErrors: string[] = [];
 page.on('console', (message: any) => {
  if (message.type() === 'error' || /Clearing signup data|Missing required signup data/i.test(message.text())) {
   signupBrowserErrors.push(message.text().slice(0, 300));
  }
 });
 page.on('pageerror', (error: Error) => signupBrowserErrors.push(`${error.name}: ${error.message.slice(0, 300)}`));

 await page.goto(getE2EDebugUrl('/'));
 await openSignupInterface(page, 30000);
 await page.getByTestId('tab-signup').click();
 await expect(page.getByTestId('tab-signup')).toHaveClass(/active/);
 const basicsStatusResponse = page.waitForResponse((response: any) =>
  response.url().endsWith('/v1/settings/server-status') && response.request().method() === 'GET'
 );
 await page.getByRole('button', { name: /continue/i }).click();
 expect((await basicsStatusResponse).ok()).toBe(true);
 await completeRequiredInvite(page, inviteCode);
 const basicsEmailInput = page.locator('input[autocomplete="email"]');
 await basicsEmailInput.fill(email);
 await expect(basicsEmailInput).toHaveValue(email);
 const usernameCheck = page.waitForResponse((response: any) =>
  response.url().endsWith('/v1/auth/check_username_valid') && response.request().method() === 'POST'
 );
 await page.locator('input[autocomplete="username"]').fill(username);
 const usernameResponse = await usernameCheck;
 expect(usernameResponse.ok()).toBe(true);
 expect((await usernameResponse.json()).available).toBe(true);
 await expect(basicsEmailInput).toHaveValue(email);
 await setToggleChecked(page.locator('#terms-agreed-toggle'), true);
 await expect(basicsEmailInput).toHaveValue(email);
 await setToggleChecked(page.locator('#privacy-agreed-toggle'), true);
 await expect(basicsEmailInput).toHaveValue(email);
 await setToggleChecked(page.locator('#stayLoggedIn'), true);
 await expect(basicsEmailInput).toHaveValue(email);
 await expect(page.locator('input[autocomplete="username"]')).toHaveValue(username);
 const createAccountButton = page.getByRole('button', { name: /create new account/i });
 await expect(createAccountButton).toBeEnabled({ timeout: 20000 });
 await createAccountButton.click();
 await expect(page.locator('#signup-password-option')).toBeVisible({ timeout: 15000 });
 await page.locator('#signup-password-option').click();
 const passwordInputs = page.locator('input[autocomplete="new-password"]');
 await expect(passwordInputs).toHaveCount(2, { timeout: 10000 });
 await passwordInputs.nth(0).fill(password);
 await passwordInputs.nth(1).fill(password);
 let passwordSetupRequested = false;
 let setup: any = null;
 page.on('request', (request: any) => {
  if (request.url().endsWith('/v1/auth/setup_password') && request.method() === 'POST') passwordSetupRequested = true;
 });
 page.on('response', (response: any) => {
  if (response.url().endsWith('/v1/auth/setup_password') && response.request().method() === 'POST') setup = response;
 });
 await page.locator('#signup-password-continue').click({ timeout: 10000 });
 await expect.poll(() => passwordSetupRequested, { timeout: 30000 }).toBe(true).catch(() => {
  throw new Error(`Password signup never requested setup_password. Browser errors: ${signupBrowserErrors.join(' | ') || 'none'}`);
 });
 await expect.poll(() => Boolean(setup), { timeout: 60000 }).toBe(true).catch(() => {
  throw new Error(`Password signup request had no response. Browser errors: ${signupBrowserErrors.join(' | ') || 'none'}`);
 });
 expect(setup.ok(), 'password signup request must succeed').toBe(true);
 const setupBody = await setup.json();
 expect(setupBody.success, JSON.stringify(setupBody)).toBe(true);
 const userId = setupBody.user?.id;
 expect(userId).toBeTruthy();
 await waitForUserSession(page, userId);
 await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 45000 });

 // Encrypt with the signup key before recovery. A fresh login must unwrap that
 // exact key; an authentication cookie alone cannot decrypt this canary.
 const encryptedCanary = await page.evaluate(async () => {
  const key = await new Promise<CryptoKey>((resolve, reject) => {
   const request = indexedDB.open('openmates_crypto');
   request.onerror = () => reject(request.error);
   request.onsuccess = () => {
    const db = request.result;
    const lookup = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
    lookup.onerror = () => { db.close(); reject(lookup.error); };
    lookup.onsuccess = () => { db.close(); resolve(lookup.result); };
   };
  });
  if (!key) throw new Error('Password signup did not store an unwrapped account key');
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
   { name: 'AES-GCM', iv }, key, new TextEncoder().encode('selfhost-recovery-canary-v1')
  ));
  return JSON.stringify({ iv: Array.from(iv), ciphertext: Array.from(ciphertext) });
 });

 const recoveryContext = await browser.newContext();
 try {
  const recoveryPage = await recoveryContext.newPage();
  await recoveryPage.goto(getE2EDebugUrl('/'));
  await openSignupInterface(recoveryPage, 30000);
  await recoveryPage.getByTestId('tab-login').click();
  const emailInput = recoveryPage.getByTestId('login-email-input');
  await expect(emailInput).toBeVisible({ timeout: 15000 });
  await emailInput.fill(email);
  await recoveryPage.getByRole('button', { name: /continue/i }).click();
  await expect(recoveryPage.locator('#login-password-input')).toBeVisible({ timeout: 15000 });

  const codeRequest = recoveryPage.waitForResponse((response: any) =>
   response.url().endsWith('/v1/auth/recovery/request-code') && response.request().method() === 'POST'
  );
  await recoveryPage.getByTestId('cant-login-button').click();
  expect((await codeRequest).ok()).toBe(true);
  const codeInput = recoveryPage.locator('#verification-code');
  await expect(codeInput).toBeVisible({ timeout: 15000 });
  await expect(codeInput).toBeEnabled();
  let recoveryCode = '';
  await expect.poll(() => {
   recoveryCode = readRecoveryCode(email);
   return /^[0-9]{6}$/.test(recoveryCode);
  }, { timeout: 60000, intervals: [500, 1000, 2000] }).toBe(true);
  await setToggleChecked(recoveryPage.locator('#acknowledge-data-loss'), true);
  await codeInput.fill(recoveryCode);
  await expect(recoveryPage.getByRole('button', { name: /password/i })).toBeVisible({ timeout: 15000 });
  recoveryCode = '';
  await recoveryPage.getByRole('button', { name: /password/i }).click();
  const newPasswordInputs = recoveryPage.locator('input[autocomplete="new-password"]');
  await expect(newPasswordInputs).toHaveCount(2, { timeout: 10000 });
  await newPasswordInputs.nth(0).fill(password);
  await newPasswordInputs.nth(1).fill(password);
  const scheduleResponse = recoveryPage.waitForResponse((response: any) =>
   response.url().endsWith('/v1/auth/recovery/reset-account') && response.request().method() === 'POST'
  );
  await recoveryPage.getByRole('button', { name: /complete reset/i }).click();
  const scheduled = await scheduleResponse;
  expect(scheduled.ok()).toBe(true);
  const scheduledBody = await scheduled.json();
  expect(scheduledBody.success).toBe(true);
  expect(scheduledBody.state).toBe('pending');
  const dueAt = Date.parse(scheduledBody.pending_until);
  expect(dueAt - Date.now()).toBeGreaterThan(23 * 60 * 60 * 1000);
  expect(dueAt - Date.now()).toBeLessThanOrEqual(24 * 60 * 60 * 1000);
  await expect(recoveryPage.getByRole('heading', { name: 'Account reset pending' })).toBeVisible();
  await expect(recoveryPage.getByText(/existing login methods and encrypted history remain available/i)).toBeVisible();
  expect(runDatabaseSql(`SELECT state FROM account_recovery_resets WHERE user_id = ${sqlString(userId)} ORDER BY requested_at DESC LIMIT 1`)).toBe('pending');

  const loginContext = await browser.newContext();
  try {
   const loginPage = await loginContext.newPage();
   await loginToTestAccount(loginPage, () => {}, async () => {}, {
    waitForEditor: false,
    credentials: { email, password, otpKey: '' }
   });
   const session = await getBrowserSession(loginPage);
   expect(session.json.success).toBe(true);
   expect(session.json.user?.id).toBe(userId);
   const decrypted = await loginPage.evaluate(async (serialized: string) => {
    const key = await new Promise<CryptoKey>((resolve, reject) => {
     const request = indexedDB.open('openmates_crypto');
     request.onerror = () => reject(request.error);
     request.onsuccess = () => {
      const db = request.result;
      const lookup = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
      lookup.onerror = () => { db.close(); reject(lookup.error); };
      lookup.onsuccess = () => { db.close(); resolve(lookup.result); };
     };
    });
    if (!key) throw new Error('Old password did not unwrap the account key during pending recovery');
    const artifact = JSON.parse(serialized);
    const plaintext = await crypto.subtle.decrypt(
     { name: 'AES-GCM', iv: new Uint8Array(artifact.iv) },
     key, new Uint8Array(artifact.ciphertext)
    );
    return new TextDecoder().decode(plaintext);
   }, encryptedCanary);
   expect(decrypted).toBe('selfhost-recovery-canary-v1');

   let cancelRequested = false;
   let cancelled: any = null;
   const cancelBrowserErrors: string[] = [];
   recoveryPage.on('request', (request: any) => {
    if (request.url().endsWith('/v1/auth/recovery/cancel-reset') && request.method() === 'POST') {
     cancelRequested = true;
    }
   });
   recoveryPage.on('response', (response: any) => {
    if (response.url().endsWith('/v1/auth/recovery/cancel-reset') && response.request().method() === 'POST') {
     cancelled = response;
    }
   });
   recoveryPage.on('pageerror', (error: Error) => cancelBrowserErrors.push(error.message.slice(0, 200)));
   const cancelButton = recoveryPage.getByRole('button', { name: 'Cancel account reset' });
   await expect(cancelButton).toBeEnabled();
   await cancelButton.click({ timeout: 15000 });
   await expect.poll(() => Boolean(cancelled), { timeout: 30000 }).toBe(true).catch(() => {
    throw new Error(`Account-reset cancellation had no response (requested: ${cancelRequested}). Browser errors: ${cancelBrowserErrors.join(' | ') || 'none'}`);
   });
   expect(cancelled.ok()).toBe(true);
   const cancelledBody = await cancelled.json();
   expect(cancelledBody.success).toBe(true);
   expect(cancelledBody.state).toBe('cancelled');
   await expect(recoveryPage.getByTestId('login-password-input')).toBeVisible({ timeout: 15000 });
   expect(runDatabaseSql(`SELECT state FROM account_recovery_resets WHERE user_id = ${sqlString(userId)} ORDER BY requested_at DESC LIMIT 1`)).toBe('cancelled');
   const sessionAfterCancel = await getBrowserSession(loginPage);
   expect(sessionAfterCancel.json.success).toBe(true);
   expect(sessionAfterCancel.json.user?.id).toBe(userId);
  } finally {
   await loginContext.close();
  }
 } finally {
  await recoveryContext.close();
 }
});
