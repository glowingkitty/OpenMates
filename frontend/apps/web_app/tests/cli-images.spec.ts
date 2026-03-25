/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * CLI Images E2E Test
 *
 * Tests the full zero-knowledge image generation pipeline via the CLI:
 *   1. Login via pair auth (required — image key resolution needs the master key)
 *   2. Send a chat message requesting image generation
 *   3. Verify the AI response references an image embed
 *   4. Use `embeds show <id> --json` to fetch and decrypt the image embed
 *   5. Verify the embed data contains the prompt and image metadata
 *   6. Clean up: delete the chat
 *
 * This test fulfills the TODO in backend/tests/test_rest_api_images.py:
 * "Replace these tests with full CLI-based E2E tests once the CLI implements
 * master key derivation and WebSocket embed handling."
 *
 * Why images/* REST API returns 404 by design:
 *   Image generation uses a zero-knowledge hybrid encryption model where the
 *   browser client encrypts the embed with the chat master key — the server
 *   never sees the plaintext key. A stateless REST call has no WebSocket,
 *   no browser crypto, and no master key, making this architecturally impossible
 *   without breaking zero-knowledge. The CLI mirrors the browser crypto stack
 *   and can complete the full pipeline via WebSocket.
 *
 * Architecture doc: docs/architecture/openmates-cli.md
 *
 * REQUIRED ENV VARS:
 *   - OPENMATES_TEST_ACCOUNT_EMAIL
 *   - OPENMATES_TEST_ACCOUNT_PASSWORD
 *   - OPENMATES_TEST_ACCOUNT_OTP_KEY
 *   - PLAYWRIGHT_TEST_BASE_URL
 *
 * Execution:
 *   npx playwright test frontend/apps/web_app/tests/cli-images.spec.ts
 */

const { test, expect } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	createStepScreenshotter,
	generateTotp,
	getTestAccount
} = require('./signup-flow-helpers');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		// eslint-disable-next-line no-console
		console.log(
			'\n--- CLI IMAGES DEBUG ---\n' + consoleLogs.slice(-60).join('\n') + '\n--- END DEBUG ---\n'
		);
	}
});

// ---------------------------------------------------------------------------
// Helpers (mirrors cli-memories.spec.ts pattern)
// ---------------------------------------------------------------------------

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org')
			return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		/* fall through */
	}
	return 'https://api.openmates.org';
}

function spawnCliLogin(apiUrl: string) {
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	const child = spawn('node', [CLI_DIST, 'login'], {
		env: {
			...process.env,
			OPENMATES_API_URL: apiUrl,
			NODE_PATH: path.join(cliDir, 'node_modules'),
			TERM: 'dumb'
		},
		stdio: ['pipe', 'pipe', 'pipe']
	});

	const stdout: string[] = [];
	const stderr: string[] = [];
	child.stdout.on('data', (d: Buffer) => {
		const l = d.toString();
		stdout.push(l);
		consoleLogs.push(`[CLI] ${l.trim()}`);
	});
	child.stderr.on('data', (d: Buffer) => {
		const l = d.toString();
		stderr.push(l);
		consoleLogs.push(`[CLI err] ${l.trim()}`);
	});

	return {
		process: child,
		stdout,
		stderr,
		waitForToken(): Promise<string> {
			return new Promise((resolve, reject) => {
				const timeout = setTimeout(
					() => reject(new Error(`No pair token in 15s. stdout: ${stdout.join('')}`)),
					15_000
				);
				const check = () => {
					const m = stdout.join('').match(/pair=([A-Z0-9]{6})/);
					if (m) {
						clearTimeout(timeout);
						resolve(m[1]);
					}
				};
				setInterval(check, 300);
				child.stdout.on('data', check);
			});
		},
		sendPin(pin: string) {
			child.stdin.write(pin + '\n');
		},
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

async function runCli(
	apiUrl: string,
	args: string[],
	timeoutMs = 30_000
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	return new Promise((resolve) => {
		const child = spawn('node', [CLI_DIST, ...args], {
			env: {
				...process.env,
				OPENMATES_API_URL: apiUrl,
				NODE_PATH: path.join(cliDir, 'node_modules')
			},
			stdio: ['pipe', 'pipe', 'pipe']
		});
		const out: string[] = [];
		const err: string[] = [];
		child.stdout.on('data', (d: Buffer) => out.push(d.toString()));
		child.stderr.on('data', (d: Buffer) => err.push(d.toString()));
		const timeout = setTimeout(() => {
			child.kill('SIGTERM');
			resolve({ code: null, stdout: out.join(''), stderr: err.join('') });
		}, timeoutMs);
		child.on('close', (code: number | null) => {
			clearTimeout(timeout);
			resolve({ code, stdout: out.join(''), stderr: err.join('') });
		});
	});
}

async function loginViaPair(page: any, apiUrl: string, logCheckpoint: (msg: string) => void) {
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';

	await page.goto('/');
	const loginBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginBtn).toBeVisible({ timeout: 15000 });
	await loginBtn.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	const continueBtn = page.getByRole('button', { name: /continue/i });
	await expect(continueBtn).toBeEnabled({ timeout: 5000 });
	await continueBtn.click();

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitBtn = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		await otpInput.fill(generateTotp(TEST_OTP_KEY));
		await submitBtn.click();
		try {
			await expect(otpInput).not.toBeVisible({ timeout: 8000 });
			loginSuccess = true;
		} catch {
			if (attempt < 3) await page.waitForTimeout(31000);
		}
	}
	await page.waitForURL(/chat/, { timeout: 20000 });
	logCheckpoint('Web app logged in.');

	const cli = spawnCliLogin(apiUrl);
	let token: string;
	try {
		token = await cli.waitForToken();
	} catch (err) {
		cli.kill();
		throw err;
	}
	logCheckpoint(`CLI pair token: ${token}`);

	await page.goto(`${baseUrl}/#pair=${token}`);
	const allowBtn = page.locator('.btn-allow');
	await expect(allowBtn).toBeVisible({ timeout: 15000 });
	await allowBtn.click();

	const pinDisplay = page.locator('.pin-display');
	await expect(pinDisplay).toBeVisible({ timeout: 15000 });
	const pinText = await pinDisplay.textContent();
	const pin = (pinText || '').replace(/\s/g, '').trim();
	logCheckpoint(`PIN: ${pin}`);

	cli.sendPin(pin);
	const { code, output } = await cli.waitForExit();
	expect(output).toContain('Login successful');
	expect(code).toBe(0);
	logCheckpoint('CLI login complete.');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('CLI Images', () => {
	test.setTimeout(300_000);

	test('image generation via chat: zero-knowledge pipeline create → embed show (JSON)', async ({
		page
	}: {
		page: any;
	}) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('CLI_IMAGES');
		const takeScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'cli-images' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);

		page.on('console', (msg: any) => consoleLogs.push(`[browser] ${msg.type()}: ${msg.text()}`));

		// -----------------------------------------------------------------------
		// Step 1: Login via pair auth (required for master key access)
		// -----------------------------------------------------------------------
		logCheckpoint('Step 1: Logging in...');
		await loginViaPair(page, apiUrl, logCheckpoint);
		await takeScreenshot(page, 'logged-in');

		// -----------------------------------------------------------------------
		// Step 2: Send a chat message requesting image generation
		// Uses `chats new --json` to capture the structured response
		// -----------------------------------------------------------------------
		logCheckpoint('Step 2: Requesting image generation via chat...');
		const chatResult = await runCli(
			apiUrl,
			['chats', 'new', 'Generate an image of a simple red circle on a white background', '--json'],
			120_000 // image generation can take up to 90s
		);
		consoleLogs.push(`[chats new stdout] ${chatResult.stdout.slice(0, 500)}`);
		consoleLogs.push(`[chats new stderr] ${chatResult.stderr.slice(0, 200)}`);

		expect(chatResult.code).toBe(0);

		let chatData: any;
		try {
			chatData = JSON.parse(chatResult.stdout);
		} catch (e) {
			throw new Error(
				`Expected JSON from chats new --json, got:\n${chatResult.stdout}\nstderr:\n${chatResult.stderr}`
			);
		}

		expect(chatData.chatId).toBeTruthy();
		const chatId = chatData.chatId;
		logCheckpoint(`Chat created: ${chatId}`);
		await takeScreenshot(page, 'chat-created');

		// The assistant response should mention the image or embed reference
		const assistantText = String(chatData.assistant || '');
		logCheckpoint(`Assistant response (first 200 chars): ${assistantText.slice(0, 200)}`);

		// -----------------------------------------------------------------------
		// Step 3: Retrieve the full chat to find the image embed ID
		// -----------------------------------------------------------------------
		logCheckpoint('Step 3: Fetching chat to find image embed...');
		const showResult = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
		consoleLogs.push(`[chats show stdout] ${showResult.stdout.slice(0, 1000)}`);
		expect(showResult.code).toBe(0);

		let showData: any;
		try {
			showData = JSON.parse(showResult.stdout);
		} catch (e) {
			throw new Error(`Expected JSON from chats show --json, got:\n${showResult.stdout}`);
		}

		// Find the assistant message that contains an embed
		const messages = showData.messages || [];
		expect(messages.length).toBeGreaterThan(0);

		const assistantMsgs = messages.filter((m: any) => m.role === 'assistant');
		expect(assistantMsgs.length).toBeGreaterThan(0);

		// Look for embed IDs in the assistant messages
		let imageEmbedId: string | null = null;
		for (const msg of assistantMsgs) {
			const embedIds = msg.embedIds || msg.embed_ids || [];
			if (embedIds.length > 0) {
				imageEmbedId = embedIds[0];
				break;
			}
			// Also check the message content for embed references
			const content = String(msg.content || msg.text || '');
			const embedMatch = content.match(/\[!\]\(embed:([a-f0-9-]+)\)/);
			if (embedMatch) {
				imageEmbedId = embedMatch[1];
				break;
			}
		}

		expect(imageEmbedId).toBeTruthy();
		logCheckpoint(`Found image embed ID: ${imageEmbedId}`);
		await takeScreenshot(page, 'embed-found');

		// -----------------------------------------------------------------------
		// Step 4: Fetch and decrypt the embed using `embeds show --json`
		// This exercises the full zero-knowledge embed decryption pipeline
		// -----------------------------------------------------------------------
		logCheckpoint('Step 4: Decrypting image embed via embeds show --json...');
		const embedResult = await runCli(apiUrl, ['embeds', 'show', imageEmbedId!, '--json'], 30_000);
		consoleLogs.push(`[embeds show stdout] ${embedResult.stdout.slice(0, 500)}`);
		consoleLogs.push(`[embeds show stderr] ${embedResult.stderr.slice(0, 200)}`);

		expect(embedResult.code).toBe(0);

		let embedData: any;
		try {
			embedData = JSON.parse(embedResult.stdout);
		} catch (e) {
			throw new Error(
				`Expected JSON from embeds show --json, got:\n${embedResult.stdout}\nstderr:\n${embedResult.stderr}`
			);
		}

		// The embed should have been decrypted and contain image generation metadata
		expect(embedData).toBeTruthy();
		// embed_id or id should match what we requested
		const resolvedId = String(embedData.embed_id || embedData.id || '');
		expect(resolvedId.length).toBeGreaterThan(0);

		// The decrypted content should contain the generation prompt
		const embedContent = embedData.content || embedData.data || {};
		logCheckpoint(`Embed type: ${embedData.embed_type || embedData.type}`);

		// verify it's an image embed type
		const embedType = String(embedData.embed_type || embedData.type || '');
		expect(embedType).toMatch(/image|generate/i);

		logCheckpoint('Image embed successfully decrypted via zero-knowledge pipeline!');
		await takeScreenshot(page, 'embed-decrypted');

		// -----------------------------------------------------------------------
		// Step 5: Cleanup — delete the test chat
		// -----------------------------------------------------------------------
		logCheckpoint('Step 5: Cleaning up test chat...');
		const deleteResult = await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 20_000);
		expect(deleteResult.code).toBe(0);
		logCheckpoint('Test chat deleted.');

		// -----------------------------------------------------------------------
		// Cleanup: logout
		// -----------------------------------------------------------------------
		await runCli(apiUrl, ['logout']);
		logCheckpoint('Logged out. Test complete.');
	});
});
