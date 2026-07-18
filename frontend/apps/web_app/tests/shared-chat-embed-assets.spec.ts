/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * frontend/apps/web_app/tests/shared-chat-embed-assets.spec.ts
 *
 * End-to-end shared-chat asset regression. Creates a real dev chat with
 * uploaded PDF, image, and audio-recording embeds, shares it, then opens the
 * shared link from a fresh unauthenticated browser context.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const {
	createSignupLogger,
	getTestAccount,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');
const { submitPasswordAndHandleOtp } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SAMPLE_PDF = path.join(__dirname, 'fixtures', 'sample.pdf');
const SAMPLE_IMAGE = path.join(__dirname, 'fixtures', 'sample.png');
const CLI_SYNC_CACHE_FILE = path.join(os.homedir(), '.openmates', 'sync_cache.json');

const consoleLogs: string[] = [];

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') {
			return 'https://api.openmates.org';
		}
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		/* fall through */
	}
	return 'https://api.openmates.org';
}

function parseChatIdFromSendOutput(output: string): string | undefined {
	const match = output.match(/openmates chats send --chat ([a-f0-9]{8})\b/i);
	return match?.[1];
}

function writeTinyWav(filePath: string): void {
	const sampleRate = 8000;
	const durationSeconds = 1;
	const samples = sampleRate * durationSeconds;
	const dataSize = samples * 2;
	const buffer = Buffer.alloc(44 + dataSize);

	buffer.write('RIFF', 0);
	buffer.writeUInt32LE(36 + dataSize, 4);
	buffer.write('WAVE', 8);
	buffer.write('fmt ', 12);
	buffer.writeUInt32LE(16, 16);
	buffer.writeUInt16LE(1, 20);
	buffer.writeUInt16LE(1, 22);
	buffer.writeUInt32LE(sampleRate, 24);
	buffer.writeUInt32LE(sampleRate * 2, 28);
	buffer.writeUInt16LE(2, 32);
	buffer.writeUInt16LE(16, 34);
	buffer.write('data', 36);
	buffer.writeUInt32LE(dataSize, 40);

	for (let index = 0; index < samples; index += 1) {
		const value = Math.round(Math.sin((index / sampleRate) * Math.PI * 2 * 440) * 8000);
		buffer.writeInt16LE(value, 44 + index * 2);
	}

	fs.writeFileSync(filePath, buffer);
}

function clearCliSyncCache(): void {
	if (fs.existsSync(CLI_SYNC_CACHE_FILE)) {
		fs.unlinkSync(CLI_SYNC_CACHE_FILE);
	}
}

function extractEmbedIdsFromText(content: unknown): string[] {
	const text = String(content || '');
	const ids = new Set<string>();
	for (const match of text.matchAll(/"embed_id"\s*:\s*"([^"\s]+)"/gi)) ids.add(match[1]);
	for (const match of text.matchAll(/\[!\]\(embed:([a-f0-9-]+)\)/gi)) ids.add(match[1]);
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

function isFinishedPdfEmbedContent(content: Record<string, unknown>): boolean {
	const screenshots = content.screenshot_s3_keys;
	const hasScreenshots = Array.isArray(screenshots)
		? screenshots.length > 0
		: typeof screenshots === 'string'
			? screenshots.length > 0
			: screenshots !== null && typeof screenshots === 'object' && Object.keys(screenshots).length > 0;
	return (
		content.app_id === 'pdf' &&
		content.status === 'finished' &&
		hasScreenshots &&
		typeof content.aes_key === 'string' &&
		content.aes_key.length > 0
	);
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
	child.stdout.on('data', (data: Buffer) => {
		const text = data.toString();
		stdout.push(text);
		consoleLogs.push(`[CLI] ${text.trim()}`);
	});
	child.stderr.on('data', (data: Buffer) => {
		const text = data.toString();
		stderr.push(text);
		consoleLogs.push(`[CLI err] ${text.trim()}`);
	});

	return {
		process: child,
		sendPin(pin: string) {
			child.stdin.write(`${pin}\n`);
		},
		waitForToken(): Promise<string> {
			return new Promise((resolve, reject) => {
				const timeout = setTimeout(
					() => reject(new Error('login: timeout waiting for QR token')),
					30_000
				);
				const check = () => {
					const out = stdout.join('');
					const match =
						out.match(/openmates login confirm ([A-Z0-9]{6})/) ??
						out.match(/[#?]pair=([A-Z0-9]{6})/);
					if (match) {
						clearTimeout(timeout);
						resolve(match[1]);
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
		child.stdout.on('data', (data: Buffer) => {
			const text = data.toString();
			out.push(text);
			consoleLogs.push(`[CLI stdout] ${text.trim()}`);
		});
		child.stderr.on('data', (data: Buffer) => {
			const text = data.toString();
			err.push(text);
			consoleLogs.push(`[CLI stderr] ${text.trim()}`);
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

async function loginCliViaBrowser(page: any, apiUrl: string, logCheckpoint: (msg: string) => void) {
	await page.goto('/');
	const loginButton = page.getByTestId('header-login-signup-btn');
	await expect(loginButton).toBeVisible({ timeout: 15000 });
	await loginButton.click();

	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	await page.locator('#login-email-input').fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	await page.locator('#login-password-input').fill(TEST_PASSWORD);
	await submitPasswordAndHandleOtp(page, TEST_OTP_KEY, logCheckpoint);

	const cli = spawnCliLogin(apiUrl);
	const token = await cli.waitForToken();
	if (token !== 'already') {
		await page.goto(`/#pair=${token}`);
		const allowButton = page.getByTestId('pair-allow-button');
		await expect(allowButton).toBeVisible({ timeout: 15000 });
		await allowButton.click();

		const pinDisplay = page.getByTestId('pair-pin-display');
		await expect(pinDisplay).toBeVisible({ timeout: 15000 });
		const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '').trim();
		expect(pin).toMatch(/^[A-Z0-9]{6}$/);
		cli.sendPin(pin);
	}

	const { code, output } = await cli.waitForExit();
	if (code !== 0 && !output.includes('Logged in')) {
		throw new Error(`CLI login failed (code=${code}): ${output.slice(0, 500)}`);
	}
	logCheckpoint('CLI login complete.');
}

async function waitForChatShow(apiUrl: string, chatId: string, timeoutMs = 90_000): Promise<any> {
	const startedAt = Date.now();
	let lastOutput = '';
	while (Date.now() - startedAt < timeoutMs) {
		clearCliSyncCache();
		const result = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], 30_000);
		lastOutput = result.stdout + result.stderr;
		if (result.code === 0 && result.stdout.trim()) return JSON.parse(result.stdout);
		await new Promise((resolve) => setTimeout(resolve, 2_000));
	}
	throw new Error(`Timed out waiting for chat ${chatId}: ${lastOutput.slice(0, 500)}`);
}

async function waitForFinishedPdfEmbed(
	apiUrl: string,
	chatId: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	timeoutMs = 240_000
): Promise<void> {
	const startedAt = Date.now();
	let lastSummary = 'no embeds checked';

	while (Date.now() - startedAt < timeoutMs) {
		const showData = await waitForChatShow(apiUrl, chatId, 45_000);
		const embedIds = new Set<string>();
		for (const message of showData.messages || []) {
			for (const id of message.embedIds || message.embed_ids || []) embedIds.add(id);
			for (const id of extractEmbedIdsFromText(message.content || message.text || '')) embedIds.add(id);
		}

		const summaries: string[] = [];
		for (const embedId of embedIds) {
			const embedResult = await runCli(apiUrl, ['embeds', 'show', embedId, '--json'], 30_000);
			if (embedResult.code !== 0) {
				summaries.push(`${embedId}:show_failed`);
				continue;
			}

			let embedData: any;
			try {
				embedData = JSON.parse(embedResult.stdout);
			} catch {
				summaries.push(`${embedId}:invalid_json`);
				continue;
			}

			const content = readEmbedContent(embedData);
			summaries.push(
				`${embedId}:${String(content.app_id || 'unknown')}/${String(content.skill_id || 'unknown')}/${String(content.status || 'unknown')}`
			);
			if (isFinishedPdfEmbedContent(content)) {
				logCheckpoint('Uploaded PDF embed finalized before sharing.', { embedId });
				return;
			}
		}

		lastSummary = summaries.join(', ') || 'no embed ids found';
		await new Promise((resolve) => setTimeout(resolve, 5_000));
	}

	throw new Error(`Timed out waiting for finished uploaded PDF embed: ${lastSummary}`);
}

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- SHARED EMBED ASSET DEBUG ---');
		consoleLogs.slice(-120).forEach((line) => console.log(line));
		console.log('--- END DEBUG ---\n');
	}
});

test('shared chat loads uploaded PDF, image, and audio recording assets while logged out', async ({
	page,
	browser
}: {
	page: any;
	browser: any;
}) => {
	test.slow();
	test.setTimeout(900_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.skip(!fs.existsSync(SAMPLE_PDF), `PDF fixture not found: ${SAMPLE_PDF}`);
	test.skip(!fs.existsSync(SAMPLE_IMAGE), `Image fixture not found: ${SAMPLE_IMAGE}`);

	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
	const apiUrl = deriveApiUrl(baseUrl);
	const logCheckpoint = createSignupLogger('SHARED_EMBED_ASSETS');
	const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-shared-assets-'));
	let fullChatId: string | undefined;
	let sharedContext: any;

	try {
		await loginCliViaBrowser(page, apiUrl, logCheckpoint);

		const audioPath = path.join(tmpDir, 'shared-chat-recording.wav');
		writeTinyWav(audioPath);
		logCheckpoint('Created audio fixture for upload.');

		const message =
			`Create a short response confirming these uploaded files are attached. ` +
			`@${SAMPLE_PDF} @${SAMPLE_IMAGE} @${audioPath}`;
		const sendResult = await runCli(apiUrl, ['chats', 'new', message], 600_000);
		consoleLogs.push(`Create chat stdout: ${sendResult.stdout.slice(0, 2000)}`);
		consoleLogs.push(`Create chat stderr: ${sendResult.stderr.slice(0, 2000)}`);
		expect(sendResult.code).toBe(0);

		const shortChatId = parseChatIdFromSendOutput(sendResult.stdout);
		expect(shortChatId).toBeTruthy();
		const showData = await waitForChatShow(apiUrl, shortChatId!);
		fullChatId = showData.chat?.id;
		expect(fullChatId).toMatch(/^[a-f0-9-]{36}$/);
		logCheckpoint(`Created chat ${fullChatId}.`);
		await waitForFinishedPdfEmbed(apiUrl, fullChatId!, logCheckpoint);

		const shareResult = await runCli(apiUrl, ['chats', 'share', fullChatId!, '--json'], 30_000);
		expect(shareResult.code).toBe(0);
		const shareData = JSON.parse(shareResult.stdout);
		const shareUrl = shareData.url as string;
		expect(shareUrl).toMatch(/\/share\/chat\//);
		expect(shareUrl).toContain('#key=');
		logCheckpoint('Generated share URL.');

		sharedContext = await browser.newContext({ baseURL: baseUrl });
		const sharedPage = await sharedContext.newPage();
		const presignedStatuses: number[] = [];
		sharedPage.on('response', (response: any) => {
			if (response.url().includes('/v1/embeds/presigned-url')) {
				presignedStatuses.push(response.status());
			}
		});
		sharedPage.on('console', (msg: any) => {
			consoleLogs.push(`[shared browser] ${msg.type()}: ${msg.text()}`);
		});

		await sharedPage.goto(shareUrl);
		await expect(sharedPage).toHaveURL(/#chat-id=/, { timeout: 60_000 });
		await expect(
			sharedPage.getByTestId('chat-header-banner').getByTestId('shared-chat-badge')
		).toHaveText('Shared chat', { timeout: 60_000 });

		const imageEmbed = sharedPage
			.locator('[data-testid="embed-preview"][data-app-id="images"]')
			.first();
		const pdfEmbed = sharedPage
			.locator('[data-testid="embed-preview"][data-app-id="pdf"]')
			.first();
		const audioEmbed = sharedPage
			.locator('[data-testid="embed-preview"][data-app-id="audio"][data-skill-id="transcribe"]')
			.first();

		await expect(imageEmbed).toBeVisible({ timeout: 90_000 });
		await expect(imageEmbed).toHaveAttribute('data-status', 'finished', { timeout: 90_000 });
		await expect(pdfEmbed).toBeVisible({ timeout: 120_000 });
		await expect(pdfEmbed).toHaveAttribute('data-status', 'finished', { timeout: 180_000 });
		await expect(audioEmbed).toBeVisible({ timeout: 120_000 });
		await expect(audioEmbed).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });

		await expect(imageEmbed.locator('img').first()).toBeVisible({ timeout: 60_000 });
		await expect(pdfEmbed.locator('img').first()).toBeVisible({ timeout: 120_000 });
		await expect(audioEmbed.locator('audio').first()).toHaveAttribute('src', /blob:/, {
			timeout: 60_000
		});

		await expect
			.poll(() => presignedStatuses.length, { timeout: 60_000 })
			.toBeGreaterThanOrEqual(3);
		expect(presignedStatuses.every((status) => status === 200)).toBe(true);
		await assertNoMissingTranslations(sharedPage);
		logCheckpoint('Logged-out shared chat loaded PDF, image, and audio assets.');
	} finally {
		if (sharedContext) await sharedContext.close();
		if (fullChatId) {
			await runCli(apiUrl, ['chats', 'delete', fullChatId, '--yes'], 30_000);
		}
		await runCli(apiUrl, ['logout'], 10_000);
		fs.rmSync(tmpDir, { recursive: true, force: true });
	}
});
