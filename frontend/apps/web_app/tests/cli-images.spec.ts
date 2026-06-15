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

const { test, expect } = require('./helpers/cookie-audit');
const { spawn } = require('child_process');
const https = require('https');
const os = require('os');
const path = require('path');
const fs = require('fs');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { submitPasswordAndHandleOtp, waitForChatReady } = require('./helpers/chat-test-helpers');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const CLI_SYNC_CACHE_FILE = path.join(os.homedir(), '.openmates', 'sync_cache.json');
const REVERSE_SEARCH_CAR_IMAGE_URL =
	'https://upload.wikimedia.org/wikipedia/commons/thumb/3/31/Mercedes-Benz_300_SL_Gullwing.jpg/960px-Mercedes-Benz_300_SL_Gullwing.jpg';
const REVERSE_SEARCH_CAR_FILENAME = 'mercedes-300-sl-gullwing.jpg';
const REVERSE_SEARCH_EXPECTED_MODEL = /Mercedes(?:-Benz)?\s+300\s*SL|300\s*SL\s+Gullwing|Gullwing/i;

const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
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

function extractEmbedIdFromText(content: unknown): string | null {
	const text = String(content || '');
	if (!text) return null;

	const jsonBlockMatches = text.matchAll(/```(?:json_embed|json)\s*\n([\s\S]*?)\n```/gi);
	for (const match of jsonBlockMatches) {
		try {
			const parsed = JSON.parse(match[1].trim());
			if (typeof parsed?.embed_id === 'string' && parsed.embed_id.trim()) {
				return parsed.embed_id.trim();
			}
		} catch {
			// Ignore malformed blocks and continue checking other candidates.
		}
	}

	const jsonFieldMatch = text.match(/"embed_id"\s*:\s*"([^"\s]+)"/i);
	if (jsonFieldMatch?.[1]) return jsonFieldMatch[1];

	const markdownMatch = text.match(/\[!\]\(embed:([a-f0-9-]+)\)/i);
	if (markdownMatch?.[1]) return markdownMatch[1];

	return null;
}

function extractEmbedIdsFromText(content: unknown): string[] {
	const text = String(content || '');
	if (!text) return [];

	const ids = new Set<string>();
	for (const match of text.matchAll(/"embed_id"\s*:\s*"([^"\s]+)"/gi)) {
		ids.add(match[1]);
	}
	for (const match of text.matchAll(/\[!\]\(embed:([a-f0-9-]+)\)/gi)) {
		ids.add(match[1]);
	}
	return [...ids];
}

function readEmbedContent(embedData: any): Record<string, unknown> {
	const rawContent = embedData?.content || embedData?.data || {};
	if (typeof rawContent === 'string') {
		try {
			return JSON.parse(rawContent);
		} catch {
			return {};
		}
	}
	return rawContent && typeof rawContent === 'object' ? rawContent : {};
}

function clearCliSyncCache(): void {
	if (fs.existsSync(CLI_SYNC_CACHE_FILE)) {
		fs.unlinkSync(CLI_SYNC_CACHE_FILE);
	}
}

async function downloadFile(url: string, destination: string): Promise<void> {
	await fs.promises.mkdir(path.dirname(destination), { recursive: true });

	await new Promise<void>((resolve, reject) => {
		const request = https.get(url, {
			headers: {
				'User-Agent': 'OpenMates-E2E/1.0 (https://openmates.org)'
			}
		}, (response: any) => {
			if ([301, 302, 303, 307, 308].includes(response.statusCode) && response.headers.location) {
				response.resume();
				downloadFile(new URL(response.headers.location, url).toString(), destination).then(resolve, reject);
				return;
			}

			if (response.statusCode !== 200) {
				response.resume();
				reject(new Error(`Download failed with HTTP ${response.statusCode} for ${url}`));
				return;
			}

			const file = fs.createWriteStream(destination);
			response.pipe(file);
			file.on('finish', () => file.close(resolve));
			file.on('error', reject);
		});

		request.on('error', reject);
		request.setTimeout(30_000, () => {
			request.destroy(new Error(`Download timed out for ${url}`));
		});
	});
}

async function collectChatEmbedIds(apiUrl: string, chatId: string): Promise<string[]> {
	clearCliSyncCache();
	let showResult = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
	for (let _r = 0; _r < 3 && showResult.code !== 0; _r++) {
		await new Promise((r) => setTimeout(r, 5000));
		clearCliSyncCache();
		showResult = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
	}
	expect(showResult.code).toBe(0);

	let showData: any;
	try {
		showData = JSON.parse(showResult.stdout);
	} catch (_e) {
		throw new Error(`Expected JSON from chats show --json, got:\n${showResult.stdout}`);
	}

	const ids = new Set<string>();
	for (const msg of showData.messages || []) {
		for (const id of msg.embedIds || msg.embed_ids || []) ids.add(id);
		for (const id of extractEmbedIdsFromText(msg.content || msg.text || '')) ids.add(id);
	}
	return [...ids];
}

async function expectImagesSearchEmbed(apiUrl: string, embedIds: string[]): Promise<void> {
	for (const embedId of embedIds) {
		const embedResult = await runCli(apiUrl, ['embeds', 'show', embedId, '--json'], 30_000);
		if (embedResult.code !== 0) continue;

		let embedData: any;
		try {
			embedData = JSON.parse(embedResult.stdout);
		} catch (_e) {
			continue;
		}

		const content = readEmbedContent(embedData);
		if (content.app_id === 'images' && content.skill_id === 'search') {
			return;
		}
	}

	throw new Error(`Expected at least one images/search embed, checked ${embedIds.length} embed(s).`);
}

async function loginViaPair(page: any, apiUrl: string, logCheckpoint: (msg: string) => void) {
	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';

	await page.goto('/');
	const loginBtn = page.getByTestId('header-login-signup-btn');
	await expect(loginBtn).toBeVisible({ timeout: 15000 });
	await loginBtn.click();

	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	const continueBtn = page.getByRole('button', { name: /continue/i });
	await expect(continueBtn).toBeEnabled({ timeout: 5000 });
	await continueBtn.click();

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	await submitPasswordAndHandleOtp(page, TEST_OTP_KEY, logCheckpoint);

	await waitForChatReady(page, logCheckpoint, 30000);
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
	const allowBtn = page.getByTestId('pair-allow-button');
	await expect(allowBtn).toBeVisible({ timeout: 15000 });
	await allowBtn.click();

	const pinDisplay = page.getByTestId('pair-pin-display');
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
		} catch (_e) {
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
		let imageEmbedId: string | null = extractEmbedIdFromText(assistantText);

		// -----------------------------------------------------------------------
		// Step 3: Retrieve the full chat to find the image embed ID
		// -----------------------------------------------------------------------
		logCheckpoint('Step 3: Fetching chat to find image embed...');
		// `chats show` reuses the local CLI sync cache when it is still considered
		// fresh, which can hide the just-created image embed from this test.
		clearCliSyncCache();
		let showResult = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
		// chats show may fail transiently if the chat data is still being persisted.
		for (let _r = 0; _r < 3 && showResult.code !== 0; _r++) {
			await new Promise((r) => setTimeout(r, 5000));
			clearCliSyncCache();
			showResult = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
		}
		consoleLogs.push(`[chats show stdout] ${showResult.stdout.slice(0, 1000)}`);

		if (showResult.code === 0) {
			let showData: any;
			try {
				showData = JSON.parse(showResult.stdout);
			} catch (_e) {
				throw new Error(`Expected JSON from chats show --json, got:\n${showResult.stdout}`);
			}

			// Image-generation embeds are resolved from chat history, but they are not
			// guaranteed to be attached to the assistant message specifically.
			const messages = showData.messages || [];
			expect(messages.length).toBeGreaterThan(0);

			const assistantMsgs = messages.filter((m: any) => m.role === 'assistant');
			expect(assistantMsgs.length).toBeGreaterThan(0);

			for (const msg of messages) {
				if (imageEmbedId) break;
				const embedIds = msg.embedIds || msg.embed_ids || [];
				if (embedIds.length > 0) {
					imageEmbedId = embedIds[0];
					break;
				}
			}

			for (const msg of assistantMsgs) {
				if (imageEmbedId) break;
				imageEmbedId = extractEmbedIdFromText(msg.content || msg.text || '');
			}
		} else {
			consoleLogs.push(`[chats show stderr] ${showResult.stderr.slice(0, 400)}`);
			logCheckpoint(`Step 3 fallback: chats show unavailable (exit ${showResult.code ?? 'null'})`);
		}

		expect(imageEmbedId).toBeTruthy();
		logCheckpoint(`Found image embed ID: ${imageEmbedId}`);
		await takeScreenshot(page, 'embed-found');

		// -----------------------------------------------------------------------
		// Step 4: Fetch and decrypt the embed using `embeds show --json`
		// This exercises the full zero-knowledge embed decryption pipeline
		// -----------------------------------------------------------------------
		logCheckpoint('Step 4: Decrypting image embed via embeds show --json...');
		let embedResult = await runCli(apiUrl, ['embeds', 'show', imageEmbedId!, '--json'], 30_000);
		consoleLogs.push(`[embeds show stdout] ${embedResult.stdout.slice(0, 500)}`);
		consoleLogs.push(`[embeds show stderr] ${embedResult.stderr.slice(0, 200)}`);

		let embedData: any;
		// Image generation is async — the embed may still be processing.
		// Poll until the decrypted embed content contains image-generation metadata.
		for (let _attempt = 0; _attempt < 8; _attempt++) {
			if (embedResult.code === 0) {
				try {
					embedData = JSON.parse(embedResult.stdout);
					const currentEnvelopeType = String(embedData.embed_type || embedData.type || '');
					const currentContent = readEmbedContent(embedData);
					const currentContentType = String(currentContent.type || '');
					const currentAppId = String(currentContent.app_id || '');
					const currentSkillId = String(currentContent.skill_id || '');
					if (
						currentEnvelopeType === 'app_skill_use'
						&& currentContentType.match(/image/i)
						&& currentAppId === 'images'
						&& currentSkillId.match(/generate/i)
					) {
						break;
					}
					logCheckpoint(
						`Embed metadata is envelope="${currentEnvelopeType}", content="${currentContentType}", ` +
						`app="${currentAppId}", skill="${currentSkillId}" ` +
						`(attempt ${_attempt + 1}/8) — waiting for image generation...`
					);
				} catch (_error) {
					embedData = undefined;
				}
			}
			await new Promise((r) => setTimeout(r, 3000));
			embedResult = await runCli(apiUrl, ['embeds', 'show', imageEmbedId!, '--json'], 30_000);
			consoleLogs.push(`[embeds show stdout] ${embedResult.stdout.slice(0, 500)}`);
			consoleLogs.push(`[embeds show stderr] ${embedResult.stderr.slice(0, 200)}`);
		}

		expect(embedResult.code).toBe(0);

		try {
			embedData = JSON.parse(embedResult.stdout);
		} catch (_e) {
			throw new Error(
				`Expected JSON from embeds show --json, got:\n${embedResult.stdout}\nstderr:\n${embedResult.stderr}`
			);
		}

		// The embed should have been decrypted and contain image generation metadata
		expect(embedData).toBeTruthy();
		// embed_id or id should match what we requested
		const resolvedId = String(embedData.embed_id || embedData.id || '');
		expect(resolvedId.length).toBeGreaterThan(0);

		// The decrypted content should contain image-generation metadata.
		const embedContent = readEmbedContent(embedData);
		const embedEnvelopeType = String(embedData.embed_type || embedData.type || '');
		const embedContentType = String(embedContent.type || '');
		const embedAppId = String(embedContent.app_id || '');
		const embedSkillId = String(embedContent.skill_id || '');
		logCheckpoint(
			`Embed metadata: envelope="${embedEnvelopeType}", content="${embedContentType}", app="${embedAppId}", skill="${embedSkillId}"`
		);

		// Skill embeds use the stable app_skill_use envelope; image specifics live in decrypted content.
		expect(embedEnvelopeType).toBe('app_skill_use');
		expect(embedContentType).toMatch(/image/i);
		expect(embedAppId).toBe('images');
		expect(embedSkillId).toMatch(/generate/i);

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

	test('reverse image search via chat identifies a classic car model', async ({
		page
	}: {
		page: any;
	}) => {
		test.slow();
		test.setTimeout(420_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('CLI_IMAGES_REVERSE_SEARCH');
		const takeScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'cli-images-reverse-search'
		});
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-reverse-image-search-'));
		const imagePath = path.join(tmpDir, REVERSE_SEARCH_CAR_FILENAME);

		page.on('console', (msg: any) => consoleLogs.push(`[browser] ${msg.type()}: ${msg.text()}`));

		try {
			logCheckpoint('Downloading classic car fixture...');
			await downloadFile(REVERSE_SEARCH_CAR_IMAGE_URL, imagePath);
			expect(fs.statSync(imagePath).size).toBeGreaterThan(10_000);

			logCheckpoint('Logging in via pair auth...');
			await loginViaPair(page, apiUrl, logCheckpoint);
			await takeScreenshot(page, 'logged-in');

			logCheckpoint('Asking CLI chat to reverse-search uploaded car image...');
			const chatResult = await runCli(
				apiUrl,
				[
					'chats',
					'new',
					`Use reverse image search on this uploaded classic car photo and identify the exact car model. Reply with the model name. @${imagePath}`,
					'--json'
				],
				180_000
			);
			consoleLogs.push(`[reverse search stdout] ${chatResult.stdout.slice(0, 1000)}`);
			consoleLogs.push(`[reverse search stderr] ${chatResult.stderr.slice(0, 1000)}`);

			expect(
				chatResult.code,
				`Reverse image search chat failed. stdout: ${chatResult.stdout.slice(0, 1000)} stderr: ${chatResult.stderr.slice(0, 1000)}`
			).toBe(0);

			let chatData: any;
			try {
				chatData = JSON.parse(chatResult.stdout);
			} catch (_e) {
				throw new Error(
					`Expected JSON from chats new --json, got:\n${chatResult.stdout}\nstderr:\n${chatResult.stderr}`
				);
			}

			expect(chatData.chatId).toBeTruthy();
			const chatId = chatData.chatId;
			const assistantText = String(chatData.assistant || '');
			logCheckpoint(`Assistant response: ${assistantText.slice(0, 300)}`);
			expect(assistantText).toMatch(REVERSE_SEARCH_EXPECTED_MODEL);

			const embedIds = await collectChatEmbedIds(apiUrl, chatId);
			expect(embedIds.length).toBeGreaterThan(0);
			await expectImagesSearchEmbed(apiUrl, embedIds);
			logCheckpoint('Verified images/search embed was created for reverse image search.');

			await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 20_000);
			logCheckpoint('Test chat deleted.');
			await runCli(apiUrl, ['logout'], 10_000);
			logCheckpoint('Logged out. Test complete.');
		} finally {
			try {
				fs.rmSync(tmpDir, { recursive: true, force: true });
			} catch {
				/* non-fatal */
			}
		}
	});
});
