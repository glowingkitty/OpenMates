/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: cli-no-credential-prompts
export {};
import type {TestInfo} from '@playwright/test';

/**
 * CLI Pair Login E2E Test
 *
 * Tests the full pair-auth login flow between the CLI (child process) and the
 * web app (Playwright browser). This mirrors the real user experience:
 *
 *   1. CLI runs `openmates login` → outputs a pair URL with a 6-char token
 *   2. User opens the URL on a logged-in device (the Playwright browser)
 *   3. Web app shows pair confirmation → user clicks Allow
 *   4. Web app shows a 6-char PIN
 *   5. User enters the PIN in the CLI → CLI completes login
 *   6. CLI can now run authenticated commands (whoami, chats list)
 *
 * Architecture doc: docs/architecture/openmates-cli.md
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL  (e.g. https://app.dev.openmates.org)
 */

const { test, expect } = require('./helpers/cookie-audit');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { createHash } = require('node:crypto');
const { runCli } = require('./helpers/cli-test-helpers');
const { recordPairLogin } = require('./helpers/cli-pair-terminal-helpers');
const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const {
	fillMessageEditor,
	loginToTestAccount,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * Resolve the CLI entry point. Inside the Playwright Docker container the CLI
 * dist is mounted at /workspace/cli/dist/cli.js. When running locally (e.g.
 * for development) the path resolves relative to the monorepo.
 */
const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function browserSessionUserId(page: any, apiUrl: string): Promise<string> {
	return page.evaluate(async (endpoint: string) => {
		const sessionId = sessionStorage.getItem('session_id');
		if (!sessionId) throw new Error('Browser session ID is missing');
		const response = await fetch(`${endpoint}/v1/auth/session`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ session_id: sessionId })
		});
		const body = await response.json().catch(() => ({}));
		if (!response.ok || body.success !== true || !body.user?.id) {
			throw new Error(`Browser session rejected with HTTP ${response.status}`);
		}
		return String(body.user.id);
	}, apiUrl);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Fixture keyring starts empty and accepts freshly paired keys. This exercises
// recovery for the same account without using the runner's real credential store.
function cliEnvironment(apiUrl: string, homeDir: string): Record<string, string | undefined> {
	return {
		...process.env,
		HOME: homeDir,
		OPENMATES_STATE_DIR: path.join(homeDir, '.openmates'),
		OPENMATES_PROFILE: undefined,
		OPENMATES_API_KEY: undefined,
		OPENMATES_API_URL: apiUrl,
		PATH: `${path.join(homeDir, 'bin')}:${process.env.PATH}`,
		NODE_PATH: path.join(path.dirname(path.dirname(CLI_DIST)), 'node_modules'),
		TERM: 'dumb'
	};
}

function seedUnavailableKeyringSession(apiUrl: string, homeDir: string): string {
	const stateDir = path.join(homeDir, '.openmates');
	const bin = path.join(homeDir, 'bin');
	const keyring = path.join(homeDir, 'keyring');
	for (const dir of [stateDir, bin, keyring]) fs.mkdirSync(dir, {recursive: true, mode: 0o700});
	const shim = `#!/usr/bin/env node
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const args = process.argv.slice(2), account = args[args.indexOf('account') + 1];
const file = path.join(${JSON.stringify(keyring)}, crypto.createHash('sha256').update(account).digest('hex'));
if (args[0] === 'store') fs.writeFileSync(file, fs.readFileSync(0), {mode: 0o600});
else if (args[0] === 'lookup') { if (!fs.existsSync(file)) process.exit(1); process.stdout.write(fs.readFileSync(file)); }
else if (args[0] === 'clear') fs.rmSync(file, {force: true});
else process.exit(1);
`;
	fs.writeFileSync(path.join(bin, 'secret-tool'), shim, {mode: 0o700});
	const session = JSON.stringify({
		apiUrl, sessionId: 'unavailable-keyring-fixture', wsToken: null,
		cookies: {auth_refresh_token: 'stale-fixture-cookie'},
		hashedEmail: createHash('sha256').update(TEST_EMAIL).digest('base64'),
		userEmailSalt: 'fixture-salt', createdAt: Date.now(),
		authorizerDeviceName: null, autoLogoutMinutes: null,
		masterKeyStorage: 'keychain', emailEncryptionKeyStorage: 'keychain'
	});
	fs.writeFileSync(path.join(stateDir, 'session.json'), session, {mode: 0o600});
	return session;
}


/**
 * Derive the API URL from the Playwright base URL.
 * e.g. https://app.dev.openmates.org → https://api.dev.openmates.org
 *      https://openmates.org         → https://api.openmates.org
 */
function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') {
			return 'https://api.openmates.org';
		}
		if (url.hostname.startsWith('app.')) {
			// app.dev.openmates.org → api.dev.openmates.org
			return `${url.protocol}//api.${url.hostname.slice(4)}`;
		}
		if (url.hostname === 'localhost') {
			return 'http://localhost:8000';
		}
	} catch {
		// fall through
	}
	return 'https://api.openmates.org';
}

/** Pair in a real terminal so successful login must exit with stdin still open. */
function spawnCliLogin(apiUrl: string, homeDir: string, testInfo: TestInfo) {
	return recordPairLogin(CLI_DIST, cliEnvironment(apiUrl, homeDir), apiUrl, testInfo);
}

/**
 * Spawn a CLI command that uses the existing session and return its output.
 */
async function runCliCommand(
	apiUrl: string,
	homeDir: string,
	args: string[],
	timeoutMs = 20_000
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	return runCli(apiUrl, args, timeoutMs, {
		useApiKey: false,
		env: cliEnvironment(apiUrl, homeDir)
	});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('CLI Pair Login', () => {
	test.setTimeout(240_000); // Includes account login, encrypted draft sync, and PAKE exchange

	// contract-test: direct surface=cli assertions=auth.pair-login.single-use-zk,auth.pair-login.session-grant,auth.session.isolation,cli.credentials.storage-mode
	test('full pair-auth flow recovers an unavailable keyring session: CLI login → web approve → PIN → whoami', async ({
		page
	}: {
		page: any;
	}, testInfo: TestInfo) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('CLI_PAIR');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'cli-pair'
		});
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const cliHome = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-pair-e2e-'));
		let draftChatId: string | null = null;
		let cli: ReturnType<typeof spawnCliLogin> | null = null;
		const pairRequests: Array<{ url: string; body: string }> = [];
		page.on('request', (request: any) => {
			if (request.url().includes('/v1/auth/pair/')) {
				pairRequests.push({ url: request.url(), body: request.postData() || '' });
			}
		});
		logCheckpoint(`Using API URL: ${apiUrl} (derived from ${baseUrl})`);

		try {
			const preservedSession = seedUnavailableKeyringSession(apiUrl, cliHome);
			const sessionFile = path.join(cliHome, '.openmates', 'session.json');
			for (const args of [['version'], ['--help'], ['chats', '--help'], ['update', '--dry-run', '--version', '99.0.0', '--json']]) {
				const result = await runCliCommand(apiUrl, cliHome, args);
				expect(result.code, result.stderr + result.stdout).toBe(0);
				expect(fs.readFileSync(sessionFile, 'utf8')).toBe(preservedSession);
			}
			const blocked = await runCliCommand(apiUrl, cliHome, ['whoami', '--json']);
			expect(blocked.code).not.toBe(0);
			expect(blocked.stderr + blocked.stdout).toContain('Existing OS keyring entry is unavailable');
			expect(fs.readFileSync(sessionFile, 'utf8')).toBe(preservedSession);

			// ---------------------------------------------------------------
			// Step 1: Log in to the test account in the browser
			// ---------------------------------------------------------------
			logCheckpoint('Step 1: Logging in to test account via browser...');
			await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
			await takeStepScreenshot(page, 'logged-in');
			const browserUserId = await browserSessionUserId(page, apiUrl);
			const draftMarker = `Pair key transfer ${Date.now().toString(36)}`;
			await startNewChat(page, () => undefined);
			draftChatId = await page
				.locator('[data-action="message-input"]')
				.last()
				.getAttribute('data-current-chat-id');
			expect(draftChatId).toMatch(/^[0-9a-f-]{36}$/i);
			await fillMessageEditor(page, page.getByTestId('message-editor'), draftMarker);
			await expect(page.getByTestId('message-editor')).toContainText(draftMarker);
			await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', draftChatId!);
			await expect(page.getByTestId('chat-header-banner')).toHaveCount(0);
			await expect
				.poll(
					async () =>
						page.evaluate(
							async ({ endpoint, chatId }: { endpoint: string; chatId: string }) => {
								const response = await fetch(
									`${endpoint}/v1/drafts/${encodeURIComponent(chatId)}`,
									{
										credentials: 'include'
									}
								);
								const data = await response.json().catch(() => ({}));
								return response.ok && typeof data.draft?.encrypted_draft_md === 'string';
							},
							{ endpoint: apiUrl, chatId: draftChatId! }
						),
					{ timeout: 30_000 }
				)
				.toBe(true);

			// ---------------------------------------------------------------
			// Step 2: Start CLI login in background → capture pair token
			// ---------------------------------------------------------------
			logCheckpoint('Step 2: Starting CLI login process...');
			cli = spawnCliLogin(apiUrl, cliHome, testInfo);

			const token = await cli.waitForToken();
			logCheckpoint('CLI received a pair token.');
			expect(fs.readFileSync(sessionFile, 'utf8')).toBe(preservedSession);
			await takeStepScreenshot(page, 'cli-token-received');

			// ---------------------------------------------------------------
			// Step 3: Navigate to the pair URL in the browser
			// ---------------------------------------------------------------
			const pairUrl = `${baseUrl}/#pair=${token}`;
			logCheckpoint('Step 3: Opening the pairing URL.');
			await page.goto(pairUrl);

			// Wait for the pair confirmation page to load (Allow/Deny buttons)
			const allowButton = page.getByTestId('pair-allow-button');
			await expect(allowButton).toBeVisible({ timeout: 15000 });
			logCheckpoint('Pair confirmation page visible — Allow button found.');
			await takeStepScreenshot(page, 'pair-confirm');

			// ---------------------------------------------------------------
			// Step 4: Click Allow to authorize the CLI device
			// ---------------------------------------------------------------
			logCheckpoint('Step 4: Clicking Allow...');
			await allowButton.click();

			// Wait for PIN display to appear
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 15000 });
			logCheckpoint('PIN display visible.');
			// The PIN is local to the sender; do not include it in screenshots or logs.

			// ---------------------------------------------------------------
			// Step 5: Read the PIN and send it to the CLI
			// ---------------------------------------------------------------
			const pinText = await pinDisplay.textContent();
			// PIN is displayed as "ABC DEF" (with space), strip to get raw 6-char PIN
			const pin = (pinText || '').replace(/\s/g, '').trim();
			logCheckpoint('Step 5: Read the locally displayed PIN.');
			expect(pin).toMatch(/^[A-Z0-9]{6}$/);
			expect(
				pairRequests.some((request) => request.url.includes('/v1/auth/pair/v2/approve/'))
			).toBe(true);
			expect(pairRequests.some((request) => request.url.includes('/v1/auth/pair/authorize/'))).toBe(
				false
			);

			// Send PIN to CLI stdin
			await cli.sendPin(pin);
			logCheckpoint('Sent PIN to CLI.');

			// ---------------------------------------------------------------
			// Step 6: Wait for CLI to complete login
			// ---------------------------------------------------------------
			logCheckpoint('Step 6: Waiting for CLI to complete login...');
			const { code: loginCode, output: loginOutput } = await cli.waitForExit();
			logCheckpoint(`CLI exited with code ${loginCode}.`);

			expect(loginOutput).toContain('Login successful');
			expect(loginOutput).toContain('Run `openmates` to start chatting.');
			expect(loginCode).toBe(0);
			const recovered = JSON.parse(fs.readFileSync(sessionFile, 'utf8'));
			expect(recovered.masterKeyStorage).toBe('keychain');
			expect(recovered.emailEncryptionKeyStorage).toBe('keychain');
			expect(recovered.masterKeyExportedB64).toBeUndefined();
			expect(recovered.sessionId).not.toBe('unavailable-keyring-fixture');
			logCheckpoint('CLI login completed successfully.');
			await takeStepScreenshot(page, 'cli-login-done');

			// ---------------------------------------------------------------
			// Step 7: Verify session works with whoami
			// ---------------------------------------------------------------
			logCheckpoint('Step 7: Running whoami to verify session...');
			const whoami = await runCliCommand(apiUrl, cliHome, ['whoami', '--json']);
			logCheckpoint(`whoami exit=${whoami.code}`);

			expect(whoami.code).toBe(0);
			const whoamiData = JSON.parse(whoami.stdout);
			expect(whoamiData).toHaveProperty('username');
			expect(String(whoamiData.id)).toBe(browserUserId);

			// The authorizer's logical session must survive minting the receiver session.
			expect(await browserSessionUserId(page, apiUrl)).toBe(browserUserId);
			for (const request of pairRequests) {
				expect(request.body, `Raw PIN leaked in ${new URL(request.url).pathname}`).not.toContain(
					pin
				);
			}
			expect(
				pairRequests.some((request) => request.url.includes('/v1/auth/pair/v2/authorize/'))
			).toBe(true);

			// This draft existed before the CLI had a session. Its plaintext must
			// decrypt after a fresh receiver sync, without calling an AI provider.
			await expect
				.poll(
					async () => {
						const result = await runCliCommand(
							apiUrl,
							cliHome,
							['drafts', 'get', draftChatId!, '--refresh'],
							30_000
						);
						if (result.code !== 0) return null;
						try {
							return JSON.parse(result.stdout).draft?.markdown ?? null;
						} catch {
							return null;
						}
					},
					{ timeout: 60_000, intervals: [1_000, 2_000, 5_000] }
				)
				.toBe(draftMarker);
			const clearDraft = await runCliCommand(
				apiUrl,
				cliHome,
				['drafts', 'clear', draftChatId!],
				10_000
			);
			expect(clearDraft.code).toBe(0);
			draftChatId = null;

			// ---------------------------------------------------------------
			// Step 8: Clean up — logout
			// ---------------------------------------------------------------
			logCheckpoint('Step 8: Running logout to clean up...');
			const logout = await runCliCommand(apiUrl, cliHome, ['logout']);
			logCheckpoint(`logout exit=${logout.code}`);
			expect(logout.code).toBe(0);
		} finally {
			await cli?.dispose();
			if (draftChatId) {
				await runCliCommand(apiUrl, cliHome, ['drafts', 'clear', draftChatId], 10_000).catch(
					() => undefined
				);
			}
			fs.rmSync(cliHome, { recursive: true, force: true });
		}
	});

	// contract-test: direct surface=cli assertions=auth.pair-login.single-use-zk,auth.pair-login.session-grant,auth.session.isolation
	test('wrong local PIN fails before bundle release and preserves the sender session', async ({
		page
	}: {
		page: any;
	}, testInfo: TestInfo) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const cliHome = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-pair-wrong-pin-'));
		const pairPaths: string[] = [];
		page.on('request', (request: any) => {
			if (request.url().includes('/v1/auth/pair/')) {
				pairPaths.push(new URL(request.url()).pathname);
			}
		});
		let cli: ReturnType<typeof spawnCliLogin> | null = null;
		try {
			await loginToTestAccount(
				page,
				() => undefined,
				async () => undefined
			);
			const senderId = await browserSessionUserId(page, apiUrl);
			cli = spawnCliLogin(apiUrl, cliHome, testInfo);
			const token = await cli.waitForToken();
			await page.goto(`${baseUrl}/#pair=${token}`);
			await page.getByTestId('pair-allow-button').click();
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
			const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '').trim();
			expect(pin).toMatch(/^[A-Z0-9]{6}$/);
			const wrongPin = `${pin[0] === 'A' ? 'B' : 'A'}${pin.slice(1)}`;
			await cli.sendPin(wrongPin);
			const result = await cli.waitForExit();
			expect(result.code).toBe(1);
			expect(result.output).toContain('Pairing authentication failed');
			expect(
				pairPaths.some((path) => path.includes('/v1/auth/pair/v2/authorize/')),
				'No encrypted master bundle should be released after a wrong PIN'
			).toBe(false);
			expect(await browserSessionUserId(page, apiUrl)).toBe(senderId);
		} finally {
			await cli?.dispose();
			fs.rmSync(cliHome, { recursive: true, force: true });
		}
	});
});
