/* eslint-disable @typescript-eslint/no-require-imports */
/* eslint-disable no-console */
export {};

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
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const {
	createSignupLogger,
	createStepScreenshotter,
	generateTotp,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * Resolve the CLI entry point. Inside the Playwright Docker container the CLI
 * dist is mounted at /workspace/cli/dist/cli.js. When running locally (e.g.
 * for development) the path resolves relative to the monorepo.
 */
const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log(
			'\n--- CLI PAIR LOGIN DEBUG ---\n' +
				consoleLogs.slice(-40).join('\n') +
				'\n--- END DEBUG ---\n'
		);
	}
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

/**
 * Spawn the CLI login command and return helpers to interact with it.
 * The process runs with OPENMATES_API_URL pointing at the same backend
 * as the Playwright web app.
 */
function spawnCliLogin(apiUrl: string): {
	process: any;
	stdout: string[];
	stderr: string[];
	waitForToken: () => Promise<string>;
	sendPin: (pin: string) => void;
	waitForExit: () => Promise<{ code: number | null; output: string }>;
	kill: () => void;
} {
	const stdout: string[] = [];
	const stderr: string[] = [];

	// Resolve the CLI's node_modules so `ws` and `qrcode-terminal` are found.
	const cliDir = path.dirname(path.dirname(CLI_DIST)); // …/cli
	const child = spawn('node', [CLI_DIST, 'login'], {
		env: {
			...process.env,
			OPENMATES_API_URL: apiUrl,
			NODE_PATH: path.join(cliDir, 'node_modules'),
			// Force non-TTY so stdin.setRawMode is skipped (the E key listener)
			TERM: 'dumb'
		},
		stdio: ['pipe', 'pipe', 'pipe']
	});

	child.stdout.on('data', (data: Buffer) => {
		const line = data.toString();
		stdout.push(line);
		consoleLogs.push(`[CLI stdout] ${line.trim()}`);
	});

	child.stderr.on('data', (data: Buffer) => {
		const line = data.toString();
		stderr.push(line);
		consoleLogs.push(`[CLI stderr] ${line.trim()}`);
	});

	return {
		process: child,
		stdout,
		stderr,

		/** Wait for the pair token to appear in CLI stdout (up to 15s). */
		waitForToken(): Promise<string> {
			return new Promise((resolve, reject) => {
				const timeout = setTimeout(() => {
					reject(
						new Error(`CLI did not output a pair token within 15s. stdout: ${stdout.join('')}`)
					);
				}, 15_000);

				const check = () => {
					const combined = stdout.join('');
					const match = combined.match(/pair=([A-Z0-9]{6})/);
					if (match) {
						clearTimeout(timeout);
						resolve(match[1]);
					}
				};

				// Check periodically
				const interval = setInterval(check, 300);
				child.stdout.on('data', () => check());

				// Clean up on timeout/resolve
				const origResolve = resolve;
				resolve = ((val: string) => {
					clearInterval(interval);
					origResolve(val);
				}) as any;
			});
		},

		/** Write the PIN to the CLI's stdin. */
		sendPin(pin: string) {
			child.stdin.write(pin + '\n');
			consoleLogs.push(`[CLI stdin] sent PIN: ${pin}`);
		},

		/** Wait for the CLI process to exit (up to 30s). */
		waitForExit(): Promise<{ code: number | null; output: string }> {
			return new Promise((resolve) => {
				const timeout = setTimeout(() => {
					child.kill('SIGTERM');
					resolve({ code: null, output: stdout.join('') + stderr.join('') });
				}, 30_000);

				child.on('close', (code: number | null) => {
					clearTimeout(timeout);
					resolve({ code, output: stdout.join('') + stderr.join('') });
				});
			});
		},

		kill() {
			child.kill('SIGTERM');
		}
	};
}

/**
 * Spawn a CLI command that uses the existing session and return its output.
 */
async function runCliCommand(
	apiUrl: string,
	args: string[],
	timeoutMs = 20_000
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	return new Promise((resolve) => {
		const cliDir = path.dirname(path.dirname(CLI_DIST));
		const child = spawn('node', [CLI_DIST, ...args], {
			env: {
				...process.env,
				OPENMATES_API_URL: apiUrl,
				NODE_PATH: path.join(cliDir, 'node_modules')
			},
			stdio: ['pipe', 'pipe', 'pipe']
		});

		const stdoutChunks: string[] = [];
		const stderrChunks: string[] = [];

		child.stdout.on('data', (d: Buffer) => stdoutChunks.push(d.toString()));
		child.stderr.on('data', (d: Buffer) => stderrChunks.push(d.toString()));

		const timeout = setTimeout(() => {
			child.kill('SIGTERM');
			resolve({ code: null, stdout: stdoutChunks.join(''), stderr: stderrChunks.join('') });
		}, timeoutMs);

		child.on('close', (code: number | null) => {
			clearTimeout(timeout);
			resolve({ code, stdout: stdoutChunks.join(''), stderr: stderrChunks.join('') });
		});
	});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('CLI Pair Login', () => {
	test.setTimeout(120_000); // Allow 2 min for the full flow including OTP retries

	test('full pair-auth flow: CLI login → web approve → PIN → whoami', async ({
		page
	}: {
		page: any;
	}) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('CLI_PAIR');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'cli-pair'
		});
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		logCheckpoint(`Using API URL: ${apiUrl} (derived from ${baseUrl})`);

		// Capture browser console logs for debugging
		page.on('console', (msg: any) => {
			consoleLogs.push(`[browser] ${msg.type()}: ${msg.text()}`);
		});

		// ---------------------------------------------------------------
		// Step 1: Log in to the test account in the browser
		// ---------------------------------------------------------------
		logCheckpoint('Step 1: Logging in to test account via browser...');
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await takeStepScreenshot(page, 'logged-in');

		// ---------------------------------------------------------------
		// Step 2: Start CLI login in background → capture pair token
		// ---------------------------------------------------------------
		logCheckpoint('Step 2: Starting CLI login process...');
		const cli = spawnCliLogin(apiUrl);

		let token: string;
		try {
			token = await cli.waitForToken();
		} catch (err) {
			cli.kill();
			throw err;
		}
		logCheckpoint(`Got pair token: ${token}`);
		await takeStepScreenshot(page, 'cli-token-received');

		// ---------------------------------------------------------------
		// Step 3: Navigate to the pair URL in the browser
		// ---------------------------------------------------------------
		const pairUrl = `${baseUrl}/#pair=${token}`;
		logCheckpoint(`Step 3: Navigating to pair URL: ${pairUrl}`);
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
		await takeStepScreenshot(page, 'pair-pin-shown');

		// ---------------------------------------------------------------
		// Step 5: Read the PIN and send it to the CLI
		// ---------------------------------------------------------------
		const pinText = await pinDisplay.textContent();
		// PIN is displayed as "ABC DEF" (with space), strip to get raw 6-char PIN
		const pin = (pinText || '').replace(/\s/g, '').trim();
		logCheckpoint(`Step 5: Read PIN from web app: "${pin}" (raw from "${pinText}")`);
		expect(pin).toMatch(/^[A-Z0-9]{6}$/);

		// Send PIN to CLI stdin
		cli.sendPin(pin);
		logCheckpoint('Sent PIN to CLI.');

		// ---------------------------------------------------------------
		// Step 6: Wait for CLI to complete login
		// ---------------------------------------------------------------
		logCheckpoint('Step 6: Waiting for CLI to complete login...');
		const { code: loginCode, output: loginOutput } = await cli.waitForExit();
		logCheckpoint(`CLI exited with code ${loginCode}. Output: ${loginOutput.slice(-200)}`);
		consoleLogs.push(`[CLI full output] ${loginOutput}`);

		expect(loginOutput).toContain('Login successful');
		expect(loginCode).toBe(0);
		logCheckpoint('CLI login completed successfully.');
		await takeStepScreenshot(page, 'cli-login-done');

		// ---------------------------------------------------------------
		// Step 7: Verify session works with whoami
		// ---------------------------------------------------------------
		logCheckpoint('Step 7: Running whoami to verify session...');
		const whoami = await runCliCommand(apiUrl, ['whoami', '--json']);
		logCheckpoint(`whoami exit=${whoami.code} stdout=${whoami.stdout.slice(0, 200)}`);
		consoleLogs.push(`[whoami stdout] ${whoami.stdout}`);
		consoleLogs.push(`[whoami stderr] ${whoami.stderr}`);

		expect(whoami.code).toBe(0);
		const whoamiData = JSON.parse(whoami.stdout);
		expect(whoamiData).toHaveProperty('username');
		logCheckpoint(`whoami returned username: ${whoamiData.username}`);

		// ---------------------------------------------------------------
		// Step 8: Clean up — logout
		// ---------------------------------------------------------------
		logCheckpoint('Step 8: Running logout to clean up...');
		const logout = await runCliCommand(apiUrl, ['logout']);
		logCheckpoint(`logout exit=${logout.code}`);
		expect(logout.code).toBe(0);
	});
});
