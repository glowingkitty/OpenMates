/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * CLI File Upload E2E Test
 *
 * Tests the full file-via-@mention pipeline:
 *
 *   Text file:
 *   1. Login via pair auth
 *   2. Create a temp .ts file with a known secret (an OpenAI-format key)
 *   3. Send a chat message referencing it via @/path/to/file.ts
 *   4. Verify: the CLI output says "secrets redacted"
 *   5. Verify: the embed was created (chats show --json returns an embed reference)
 *   6. Verify: the embed content does NOT contain the raw secret value
 *
 *   Image file:
 *   7. Create a tiny valid PNG (1×1 pixel)
 *   8. Send a chat message with @/path/to/image.png
 *   9. Verify: CLI output shows the file was uploaded (✓ uploaded)
 *   10. Verify: the resulting message embed references an image
 *
 *   Share link:
 *   11. Create a share link for the chat (chats share)
 *   12. Verify: URL matches expected format
 *
 *   Cleanup:
 *   13. Delete the chat, logout
 *
 * Architecture doc: docs/architecture/openmates-cli.md
 *
 * REQUIRED ENV VARS:
 *   - OPENMATES_TEST_ACCOUNT_EMAIL
 *   - OPENMATES_TEST_ACCOUNT_PASSWORD
 *   - OPENMATES_TEST_ACCOUNT_OTP_KEY
 *   - PLAYWRIGHT_TEST_BASE_URL
 *
 * Run:
 *   npx playwright test frontend/apps/web_app/tests/cli-file-upload.spec.ts
 */

const { test, expect } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
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

test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		// eslint-disable-next-line no-console
		console.log(
			'\n--- CLI FILE UPLOAD DEBUG ---\n' +
				consoleLogs.slice(-80).join('\n') +
				'\n--- END DEBUG ---\n'
		);
	}
});

// ── Helpers (mirrors cli-images.spec.ts) ─────────────────────────────────────

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
					() => reject(new Error('login: timeout waiting for QR token')),
					30_000
				);
				const check = () => {
					const out = stdout.join('');
					const m = out.match(/openmates login confirm ([A-Z0-9]{6})/);
					if (m) {
						clearTimeout(timeout);
						resolve(m[1]);
					} else if (out.includes('Logged in')) {
						clearTimeout(timeout);
						resolve('already');
					} else {
						setTimeout(check, 300);
					}
				};
				check();
			});
		},
		waitForExit(): Promise<{ code: number | null; output: string }> {
			return new Promise((resolve) => {
				child.on('close', (code: number | null) => {
					resolve({ code, output: [...stdout, ...stderr].join('') });
				});
			});
		}
	};
}

async function runCli(
	apiUrl: string,
	args: string[],
	timeoutMs = 60_000
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
		child.stdout.on('data', (d: Buffer) => {
			const l = d.toString();
			out.push(l);
			consoleLogs.push(`[CLI stdout] ${l.trim()}`);
		});
		child.stderr.on('data', (d: Buffer) => {
			const l = d.toString();
			err.push(l);
			consoleLogs.push(`[CLI stderr] ${l.trim()}`);
		});
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

	const pwInput = page.locator('input[name="password"][type="password"]');
	await expect(pwInput).toBeVisible();
	await pwInput.fill(TEST_PASSWORD);
	await page.getByRole('button', { name: /continue|login|sign in/i }).click();

	// OTP
	let attempts = 0;
	while (attempts < 3) {
		try {
			const otpInput = page.locator('input[name="code"]');
			await expect(otpInput).toBeVisible({ timeout: 8000 });
			const totp = generateTotp(TEST_OTP_KEY);
			await otpInput.fill(totp);
			await page.getByRole('button', { name: /verify|continue/i }).click();
			await expect(page).toHaveURL(/chat|home|dashboard/, { timeout: 15000 });
			break;
		} catch {
			attempts++;
			if (attempts < 3) await page.waitForTimeout(31000);
			else throw new Error('OTP login failed after 3 attempts');
		}
	}

	logCheckpoint('Logged in via browser');

	// Pair auth: get the QR token from the CLI
	const cli = spawnCliLogin(apiUrl);
	let token: string;
	try {
		token = await cli.waitForToken();
	} catch (e) {
		consoleLogs.push(`[Login err] ${e}`);
		throw e;
	}

	if (token !== 'already') {
		// Confirm via web app
		await page.goto(`/pair-auth?token=${token}`);
		const confirmBtn = page.getByRole('button', { name: /confirm|approve|allow/i });
		await expect(confirmBtn).toBeVisible({ timeout: 10000 });
		await confirmBtn.click();
		logCheckpoint(`Pair-auth confirmed for token ${token}`);
	}

	const { code, output } = await cli.waitForExit();
	if (code !== 0 && !output.includes('Logged in')) {
		throw new Error(`CLI login failed (code=${code}): ${output.slice(0, 500)}`);
	}
	logCheckpoint('CLI login complete');
}

// ── 1×1 pixel PNG (smallest valid PNG) ─────────────────────────────────────
// Hex bytes of a 1×1 transparent PNG — always passes MIME validation
const TINY_PNG_HEX =
	'89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
	'0000000a49444154789c6260000000020001e221bc330000000049454e44ae426082';

function writeTinyPng(destPath: string): void {
	const buf = Buffer.from(TINY_PNG_HEX, 'hex');
	fs.writeFileSync(destPath, buf);
}

// ── Main test ───────────────────────────────────────────────────────────────

test('CLI file upload — text file with secret + image file', async ({ page }: any) => {
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://openmates.org';
	const apiUrl = deriveApiUrl(baseUrl);

	const logCheckpoint = createSignupLogger(consoleLogs);
	const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-e2e-'));

	try {
		// ── Login ────────────────────────────────────────────────────────
		await loginViaPair(page, apiUrl, logCheckpoint);

		// ── Create test files ────────────────────────────────────────────

		// Text file containing a fake OpenAI-format key (will be auto-redacted)
		const FAKE_KEY = 'sk-proj-TestSecretKeyForE2ETesting123456789abcdef';
		const textFilePath = path.join(tmpDir, 'config.ts');
		fs.writeFileSync(
			textFilePath,
			`// Test config\nexport const OPENAI_API_KEY = "${FAKE_KEY}";\nexport const DEBUG = true;\n`
		);
		logCheckpoint(`Created text file: ${textFilePath}`);

		// Tiny valid PNG for image upload
		const imagePath = path.join(tmpDir, 'test-image.png');
		writeTinyPng(imagePath);
		logCheckpoint(`Created image file: ${imagePath}`);

		// ── Text file upload ─────────────────────────────────────────────

		logCheckpoint('Sending message with @text-file reference...');
		const textSendResult = await runCli(
			apiUrl,
			[
				'chats',
				'new',
				`Analyse this code snippet @${textFilePath} and tell me what you see. Reply in one sentence.`
			],
			90_000 // longer timeout: AI needs to respond + file processed
		);

		logCheckpoint(`Text send exit code: ${textSendResult.code}`);
		consoleLogs.push(`Text send stdout: ${textSendResult.stdout.slice(0, 2000)}`);
		consoleLogs.push(`Text send stderr: ${textSendResult.stderr.slice(0, 1000)}`);

		// Verify the CLI acknowledged secret redaction
		const combinedTextOutput = textSendResult.stdout + textSendResult.stderr;
		expect(
			combinedTextOutput.toLowerCase(),
			'Expected "secrets redacted" in CLI output for text file'
		).toMatch(/secrets redacted|zero-knowledge/i);

		// Verify the raw secret never appeared in CLI output
		expect(
			combinedTextOutput,
			'Raw secret key must never appear in CLI output'
		).not.toContain(FAKE_KEY);

		// Verify the send succeeded (exit code 0) and got an AI response
		expect(textSendResult.code).toBe(0);
		expect(textSendResult.stdout.length).toBeGreaterThan(10);

		// Get the chat ID from the most recent chat
		const listResult = await runCli(apiUrl, ['chats', 'list', '--json', '--limit', '1'], 20_000);
		expect(listResult.code).toBe(0);
		const listData = JSON.parse(listResult.stdout);
		const chatId: string = listData.chats?.[0]?.id ?? listData[0]?.id;
		expect(chatId).toBeTruthy();
		logCheckpoint(`Chat ID: ${chatId}`);

		// Show the chat and verify it has an embed reference (the code-code embed)
		const showResult = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
		expect(showResult.code).toBe(0);
		const showData = JSON.parse(showResult.stdout);
		const messages: any[] = showData.messages ?? [];
		const userMessages = messages.filter((m: any) => m.role === 'user');
		expect(userMessages.length).toBeGreaterThan(0);

		// The user message content should contain an embed reference block (```json with embed_id)
		const lastUserMsg = userMessages[userMessages.length - 1];
		const userContent: string = lastUserMsg.content ?? '';
		expect(userContent).toContain('embed_id');
		expect(userContent).toContain('"type": "code"');
		logCheckpoint('Text file embed reference found in message content');

		// Verify the embed content does NOT contain the raw secret
		const embedIdMatch = userContent.match(/"embed_id":\s*"([^"]+)"/);
		if (embedIdMatch) {
			const embedId = embedIdMatch[1];
			const embedResult = await runCli(apiUrl, ['embeds', 'show', embedId, '--json'], 20_000);
			if (embedResult.code === 0 && embedResult.stdout.trim()) {
				const embedData = JSON.parse(embedResult.stdout);
				const embedContent = JSON.stringify(embedData);
				expect(
					embedContent,
					'Raw secret must not appear in embed content'
				).not.toContain(FAKE_KEY);
				// Should contain a placeholder like [OPENAI_KEY_...]
				expect(embedContent).toMatch(/\[OPENAI_KEY_/);
				logCheckpoint('Embed content verified: secret redacted, placeholder present');
			}
		}

		// ── Image file upload ─────────────────────────────────────────────

		logCheckpoint('Sending message with @image-file reference...');
		const imageSendResult = await runCli(
			apiUrl,
			[
				'chats',
				'send',
				'--chat',
				chatId,
				`What colour is this image? @${imagePath}`
			],
			90_000 // longer: upload + AI response
		);

		logCheckpoint(`Image send exit code: ${imageSendResult.code}`);
		consoleLogs.push(`Image send stdout: ${imageSendResult.stdout.slice(0, 1000)}`);
		consoleLogs.push(`Image send stderr: ${imageSendResult.stderr.slice(0, 1000)}`);

		const combinedImageOutput = imageSendResult.stdout + imageSendResult.stderr;

		// Verify upload acknowledgment
		expect(
			combinedImageOutput,
			'Expected upload confirmation in CLI output'
		).toMatch(/uploaded|uploading|✓/i);

		// Verify successful exit
		expect(imageSendResult.code).toBe(0);

		// Verify the message contains an image embed reference
		const showAfterImage = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
		expect(showAfterImage.code).toBe(0);
		const showAfterData = JSON.parse(showAfterImage.stdout);
		const allMessages: any[] = showAfterData.messages ?? [];
		const allContent = allMessages.map((m: any) => m.content ?? '').join('\n');
		expect(allContent).toContain('"type": "image"');
		logCheckpoint('Image embed reference found in message content');

		// ── Share link ────────────────────────────────────────────────────

		logCheckpoint('Creating share link...');
		const shareResult = await runCli(apiUrl, ['chats', 'share', chatId, '--json'], 20_000);
		expect(shareResult.code).toBe(0);
		const shareData = JSON.parse(shareResult.stdout);

		expect(shareData.url).toBeTruthy();
		expect(shareData.url).toMatch(/\/share\/chat\//);
		expect(shareData.url).toContain('#key=');
		logCheckpoint(`Share URL generated: ${shareData.url.slice(0, 80)}...`);

		// ── Cleanup ────────────────────────────────────────────────────────

		await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 20_000);
		logCheckpoint('Chat deleted');
		await runCli(apiUrl, ['logout'], 10_000);
		logCheckpoint('Logged out');
	} finally {
		// Clean up temp files
		try {
			fs.rmSync(tmpDir, { recursive: true, force: true });
		} catch {
			/* non-fatal */
		}
	}
});
