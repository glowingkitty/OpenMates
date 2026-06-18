/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * CLI embed diff version history E2E test.
 *
 * Verifies the CLI can use pair-auth, create a real code embed, receive a
 * diff-based update, locally reconstruct encrypted version rows, and restore a
 * previous version through client-side encrypted WebSocket writes.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect } = require('./helpers/cookie-audit');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);
const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log(
			'\n--- CLI EMBED DIFF VERSIONS DEBUG ---\n' +
				consoleLogs.slice(-80).join('\n') +
				'\n--- END DEBUG ---\n'
		);
	}
});

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') {
			return 'https://api.openmates.org';
		}
		if (url.hostname.startsWith('app.')) {
			return `${url.protocol}//api.${url.hostname.slice(4)}`;
		}
		if (url.hostname === 'localhost') {
			return 'http://localhost:8000';
		}
	} catch {
		// Fall through to production API default.
	}
	return 'https://api.openmates.org';
}

function spawnCliLogin(apiUrl: string): {
	waitForToken: () => Promise<string>;
	sendPin: (pin: string) => void;
	waitForExit: () => Promise<{ code: number | null; output: string }>;
	kill: () => void;
} {
	const stdout: string[] = [];
	const stderr: string[] = [];
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

	child.stdout.on('data', (data: Buffer) => {
		const line = data.toString();
		stdout.push(line);
		consoleLogs.push(`[CLI login stdout] ${line.trim()}`);
	});
	child.stderr.on('data', (data: Buffer) => {
		const line = data.toString();
		stderr.push(line);
		consoleLogs.push(`[CLI login stderr] ${line.trim()}`);
	});

	return {
		waitForToken(): Promise<string> {
			return new Promise((resolve, reject) => {
				const timeout = setTimeout(() => {
					reject(new Error(`No pair token in 15s. stdout: ${stdout.join('')}`));
				}, 15_000);
				const interval = setInterval(check, 300);

				function check() {
					const match = stdout.join('').match(/pair=([A-Z0-9]{6})/);
					if (match) {
						clearTimeout(timeout);
						clearInterval(interval);
						resolve(match[1]);
					}
				}

				child.stdout.on('data', check);
				check();
			});
		},
		sendPin(pin: string) {
			child.stdin.write(`${pin}\n`);
			consoleLogs.push('[CLI login stdin] sent PIN');
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
	timeoutMs = 120_000
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
		const stdout: string[] = [];
		const stderr: string[] = [];
		child.stdout.on('data', (data: Buffer) => stdout.push(data.toString()));
		child.stderr.on('data', (data: Buffer) => stderr.push(data.toString()));
		const timeout = setTimeout(() => {
			child.kill('SIGTERM');
			resolve({ code: null, stdout: stdout.join(''), stderr: stderr.join('') });
		}, timeoutMs);
		child.on('close', (code: number | null) => {
			clearTimeout(timeout);
			const out = stdout.join('');
			const err = stderr.join('');
			consoleLogs.push(`[CLI ${args.join(' ')}] code=${code} stdout=${out.slice(0, 800)} stderr=${err.slice(0, 400)}`);
			resolve({ code, stdout: out, stderr: err });
		});
	});
}

async function runCliJson(apiUrl: string, args: string[], timeoutMs = 120_000): Promise<any> {
	const result = await runCli(apiUrl, [...args, '--json'], timeoutMs);
	expect(result.code).toBe(0);
	try {
		return JSON.parse(result.stdout);
	} catch (_error) {
		throw new Error(`Expected JSON from openmates ${args.join(' ')} --json, got:\n${result.stdout}\nstderr:\n${result.stderr}`);
	}
}

function extractEmbedIdFromText(content: unknown): string | null {
	const text = String(content || '');
	for (const match of text.matchAll(/```(?:json_embed|json)\s*\n([\s\S]*?)\n```/gi)) {
		try {
			const parsed = JSON.parse(match[1].trim());
			if (typeof parsed?.embed_id === 'string' && parsed.embed_id.trim()) {
				return parsed.embed_id.trim();
			}
		} catch {
			// Ignore malformed model blocks and keep looking.
		}
	}

	const jsonFieldMatch = text.match(/"embed_id"\s*:\s*"([^"\s]+)"/i);
	if (jsonFieldMatch?.[1]) return jsonFieldMatch[1];

	const markdownMatch = text.match(/\[!\]\(embed:([a-f0-9-]+)\)/i);
	return markdownMatch?.[1] ?? null;
}

async function loginCliViaPair(page: any, apiUrl: string, baseUrl: string, log: (message: string) => void) {
	const cli = spawnCliLogin(apiUrl);
	let token: string;
	try {
		token = await cli.waitForToken();
	} catch (error) {
		cli.kill();
		throw error;
	}
	log(`CLI pair token: ${token}`);

	await page.goto(`${baseUrl}/#pair=${token}`);
	const allowButton = page.getByTestId('pair-allow-button');
	await expect(allowButton).toBeVisible({ timeout: 15000 });
	await allowButton.click();

	const pinDisplay = page.getByTestId('pair-pin-display');
	await expect(pinDisplay).toBeVisible({ timeout: 15000 });
	const pinText = await pinDisplay.textContent();
	const pin = (pinText || '').replace(/\s/g, '').trim();
	expect(pin).toMatch(/^[A-Z0-9]{6}$/);

	cli.sendPin(pin);
	const { code, output } = await cli.waitForExit();
	expect(output).toContain('Login successful');
	expect(code).toBe(0);
}

test.describe('CLI Embed Diff Versions', () => {
	test.setTimeout(360_000);

	test('code embed version history can be listed, shown, and restored through encrypted CLI flow', async ({ page }) => {
		test.slow();
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const log = createSignupLogger('CLI_EMBED_DIFF');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'cli-embed-diff' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		page.on('console', (message: any) => consoleLogs.push(`[browser] ${message.type()}: ${message.text()}`));

		await loginToTestAccount(page, log, screenshot);
		await screenshot(page, '01-web-logged-in');
		await loginCliViaPair(page, apiUrl, baseUrl, log);

		const turn1 = await runCliJson(
			apiUrl,
			[
				'chats',
				'new',
				'Create a code embed with a Python function named calculate_average that returns the average of a list of numbers. Use a code artifact/embed, not inline prose.'
			],
			150_000
		);
		expect(turn1.chatId).toBeTruthy();
		const embedId = extractEmbedIdFromText(turn1.assistant);
		expect(embedId, `assistant response should reference a code embed: ${turn1.assistant}`).toBeTruthy();

		const turn2 = await runCliJson(
			apiUrl,
			[
				'chats',
				'send',
				'--chat',
				turn1.chatId,
				'Edit the existing code artifact from the previous turn only. Rename calculate_average to compute_mean and add a -> float return type hint. Do not create a new code artifact or new JSON embed block; preserve the same artifact by applying a diff to it.'
			],
			150_000
		);
		const updatedEmbedId = extractEmbedIdFromText(turn2.assistant);
		expect(updatedEmbedId).toBe(embedId);

		const versions = await runCliJson(apiUrl, ['embeds', 'versions', 'list', embedId], 60_000);
		expect(versions.embed_id).toBe(embedId);
		expect(versions.current_version).toBeGreaterThanOrEqual(2);
		expect(versions.versions.map((version: any) => version.version_number)).toEqual(
			expect.arrayContaining([1, 2])
		);

		const version1 = await runCliJson(
			apiUrl,
			['embeds', 'versions', 'show', embedId, '--version', '1'],
			60_000
		);
		expect(version1.content).toContain('calculate_average');
		expect(version1.content).not.toContain('compute_mean');

		const restored = await runCliJson(
			apiUrl,
			['embeds', 'versions', 'restore', embedId, '--version', '1', '--yes'],
			60_000
		);
		expect(restored.embed_id).toBe(embedId);
		expect(restored.restored_from_version).toBe(1);
		expect(restored.version_number).toBeGreaterThan(versions.current_version);

		const afterRestore = await runCliJson(apiUrl, ['embeds', 'versions', 'list', embedId], 60_000);
		expect(afterRestore.current_version).toBe(restored.version_number);
		expect(afterRestore.versions.map((version: any) => version.version_number)).toContain(
			restored.version_number
		);
	});
});
