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
const { randomUUID } = require('crypto');
const path = require('path');
const fs = require('fs');
const os = require('os');
const {
	createSignupLogger,
	getTestAccount,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');
const {
	createIsolatedBrowserContext,
	declareTestState,
	loginToTestAccount
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SAMPLE_PDF = path.join(__dirname, 'fixtures', 'sample.pdf');
const SAMPLE_IMAGE = path.join(__dirname, 'fixtures', 'golden_gate_bridge.jpg');
const CLI_SYNC_CACHE_FILE = path.join(os.homedir(), '.openmates', 'sync_cache.json');
const PROOF_FRAME_HOLD_MS = 5_500;

const consoleLogs: string[] = [];
const TEST_STATE = declareTestState({
	auth: 'authenticated setup followed by logged-out share',
	browserStorage: 'fresh',
	account: 'shared fixture used only to create and clean up the source chat',
	chat: 'source chat created and deleted in this test',
	notifications: 'unchanged',
	securityReminders: 'unchanged'
});

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
	for (const ref of extractEmbedRefsFromText(text)) {
		if (/^[a-f0-9-]{36}$/i.test(ref)) ids.add(ref);
		for (const id of extractEmbedIdCandidatesFromRef(ref)) ids.add(id);
	}
	return [...ids];
}

function extractEmbedRefsFromText(content: unknown): string[] {
	const text = String(content || '');
	const refs = new Set<string>();
	for (const match of text.matchAll(/\]\(embed:([A-Za-z0-9._-]+)\)/g)) refs.add(match[1]);
	for (const match of text.matchAll(/"embed_ref"\s*:\s*"([^"\s]+)"/gi)) refs.add(match[1]);
	return [...refs];
}

function extractEmbedIdCandidatesFromRef(embedRef: string): string[] {
	const ids = new Set<string>();
	if (/^[a-f0-9-]{36}$/i.test(embedRef)) ids.add(embedRef.toLowerCase());
	for (const match of embedRef.matchAll(/(?:^|-)([a-f0-9]{8})(?=-[a-f0-9]{4})/gi)) {
		ids.add(match[1].toLowerCase());
	}
	return [...ids];
}

function extractEmbedIdPrefixesFromRefs(embedRefs: Iterable<string>): string[] {
	const prefixes = new Set<string>();
	for (const embedRef of embedRefs) {
		for (const id of extractEmbedIdCandidatesFromRef(embedRef)) prefixes.add(id);
		for (const match of embedRef.matchAll(/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]+/gi)) {
			prefixes.add(match[0].toLowerCase());
		}
	}
	return [...prefixes];
}

function readCachedEmbedIds(embedRefs: Iterable<string>): string[] {
	if (!fs.existsSync(CLI_SYNC_CACHE_FILE)) return [];

	const prefixes = extractEmbedIdPrefixesFromRefs(embedRefs);
	try {
		const cache = JSON.parse(fs.readFileSync(CLI_SYNC_CACHE_FILE, 'utf8'));
		const embeds = Array.isArray(cache?.embeds) ? cache.embeds : [];
		return embeds
			.map((embed: any) => String(embed?.embed_id || embed?.id || ''))
			.filter((embedId: string) =>
				embedId && (prefixes.length === 0 || prefixes.some((prefix) => embedId.startsWith(prefix)))
			);
	} catch {
		return [];
	}
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
		waitForAuthorizationPrompt(): Promise<void> {
			return new Promise((resolve, reject) => {
				const timeout = setTimeout(
					() => reject(new Error('login: timeout waiting for authorization prompt')),
					30_000
				);
				const check = () => {
					const output = [...stdout, ...stderr].join('');
					if (output.includes('Waiting for authorization') || output.includes('Logged in')) {
						clearTimeout(timeout);
						resolve();
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
	await loginToTestAccount(page, logCheckpoint);

	const cli = spawnCliLogin(apiUrl);
	const token = await cli.waitForToken();
	if (token !== 'already') {
		await cli.waitForAuthorizationPrompt();
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

async function waitForChatShow(apiUrl: string, chatId: string, timeoutMs = 180_000): Promise<any> {
	const startedAt = Date.now();
	let lastOutput = '';
	clearCliSyncCache();
	while (Date.now() - startedAt < timeoutMs) {
		const remainingMs = timeoutMs - (Date.now() - startedAt);
		const result = await runCli(apiUrl, ['chats', 'show', chatId, '--json'], Math.max(30_000, remainingMs));
		lastOutput = result.stdout + result.stderr;
		if (result.stdout.trim()) {
			try {
				return JSON.parse(result.stdout);
			} catch {
				if (result.code === 0) throw new Error(`Invalid chats show JSON: ${result.stdout.slice(0, 500)}`);
			}
		}
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
	const knownEmbedIds = new Set<string>();
	const knownEmbedRefs = new Set<string>();

	while (Date.now() - startedAt < timeoutMs) {
		let cachedEmbedIds = readCachedEmbedIds(knownEmbedRefs);
		if (knownEmbedIds.size === 0 && (knownEmbedRefs.size === 0 || cachedEmbedIds.length === 0)) {
			const showData = await waitForChatShow(apiUrl, chatId, 45_000);
			for (const message of showData.messages || []) {
				for (const id of message.embedIds || message.embed_ids || []) knownEmbedIds.add(id);
				for (const id of extractEmbedIdsFromText(message.content || message.text || '')) {
					knownEmbedIds.add(id);
				}
				for (const ref of extractEmbedRefsFromText(message.content || message.text || '')) {
					knownEmbedRefs.add(ref);
				}
			}
			cachedEmbedIds = readCachedEmbedIds(knownEmbedRefs);
		}

		const embedIds = new Set([...knownEmbedIds, ...cachedEmbedIds]);

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
			const embedRef = typeof content.embed_ref === 'string' ? content.embed_ref : '';
			if (knownEmbedRefs.size > 0 && !knownEmbedRefs.has(embedRef)) {
				summaries.push(`${embedId}:unmatched_ref`);
				continue;
			}
			summaries.push(
				`${embedId}:${String(content.app_id || 'unknown')}/${String(content.skill_id || 'unknown')}/${String(content.status || 'unknown')}`
			);
			if (isFinishedPdfEmbedContent(content)) {
				logCheckpoint('Uploaded PDF embed finalized before sharing.', { embedId });
				return;
			}
		}

		lastSummary = summaries.slice(0, 10).join(', ') || 'no embed ids found';
		if (summaries.length > 10) lastSummary += `, +${summaries.length - 10} more`;
		await new Promise((resolve) => setTimeout(resolve, 5_000));
	}

	throw new Error(`Timed out waiting for finished uploaded PDF embed: ${lastSummary}`);
}

async function holdVisibleProofFrames(page: any): Promise<void> {
	await page.getByTestId('chat-header-banner').scrollIntoViewIfNeeded();
	// playwright-determinism: allow - proof recording requires a fixed visible-frame hold.
	await page.waitForTimeout(PROOF_FRAME_HOLD_MS);
	const nextEmbedButton = page.locator('button.nav-arrow-right:visible').first();
	for (let index = 0; index < 3; index += 1) {
		// playwright-determinism: allow - each carousel item must remain visible in the proof recording.
		await page.waitForTimeout(PROOF_FRAME_HOLD_MS);
		if (index < 2) {
			const box = await nextEmbedButton.boundingBox({ timeout: 5_000 });
			if (!box) throw new Error('Shared asset proof carousel right arrow is not visible');
			await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
			// playwright-determinism: allow - allow the proof carousel transition to finish before capture.
			await page.waitForTimeout(750);
		}
	}
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

// contract-test: direct surface=gui.web assertions=chat-share-settings.shared-link-open
test('shared chat loads uploaded PDF, image, and audio recording assets while logged out', async ({
	page,
	browser
}: {
	page: any;
	browser: any;
}, testInfo: any) => {
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
	let proofContext: any | undefined;

	try {
		await loginCliViaBrowser(page, apiUrl, logCheckpoint);

		const runMarker = randomUUID().slice(0, 8);
		const pdfPath = path.join(tmpDir, `shared-proof-${runMarker}-document.pdf`);
		const imagePath = path.join(tmpDir, `shared-proof-${runMarker}-image.jpg`);
		const audioPath = path.join(tmpDir, `shared-proof-${runMarker}-recording.wav`);
		fs.copyFileSync(SAMPLE_PDF, pdfPath);
		fs.copyFileSync(SAMPLE_IMAGE, imagePath);
		writeTinyWav(audioPath);
		logCheckpoint('Created temporary asset fixtures for upload.');

		const message =
			'Create a short shared-chat note confirming the attached PDF, image, and audio recording are ready to preview. ' +
			`@${pdfPath} @${imagePath} @${audioPath}`;
		const sendResult = await runCli(
			apiUrl,
			['chats', 'new', message, '--slug', `shared-proof-${runMarker}`, '--json', '--no-task-update-jobs'],
			600_000
		);
		consoleLogs.push(`Create chat stdout: ${sendResult.stdout.slice(0, 2000)}`);
		consoleLogs.push(`Create chat stderr: ${sendResult.stderr.slice(0, 2000)}`);
		expect(sendResult.code).toBe(0);

		let sendData: any;
		try {
			sendData = JSON.parse(sendResult.stdout);
		} catch (_e) {
			throw new Error(
				`Expected JSON from chats new --json, got:\n${sendResult.stdout}\nstderr:\n${sendResult.stderr}`
			);
		}
		const createdChatId = String(sendData.chatId || sendData.chat_id || '');
		expect(createdChatId).toMatch(/^[a-f0-9-]{36}$/);
		const showData = await waitForChatShow(apiUrl, createdChatId);
		fullChatId = showData.chat?.id || createdChatId;
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

		proofContext = await createIsolatedBrowserContext(browser, TEST_STATE, {
			permissions: ['microphone'],
			viewport: { width: 390, height: 844 },
			recordVideo: {
				dir: testInfo.outputPath('shared-chat-embed-assets-proof-video'),
				size: { width: 390, height: 844 }
			}
		});
		const sharedPage = await proofContext.newPage();
		const proofVideo = sharedPage.video();
		const presignedResponses: Array<{ status: number; url: string }> = [];
		sharedPage.on('response', (response: any) => {
			if (response.url().includes('/v1/embeds/presigned-url')) {
				presignedResponses.push({ status: response.status(), url: response.url() });
			}
		});
		sharedPage.on('console', (msg: any) => {
			consoleLogs.push(`[shared browser] ${msg.type()}: ${msg.text()}`);
		});

		await sharedPage.goto(shareUrl);
		await expect(sharedPage.locator('[data-authenticated="true"]')).toHaveCount(0, { timeout: 60_000 });
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

		const renderedImage = imageEmbed.locator('img').first();
		await expect(renderedImage).toBeVisible({ timeout: 60_000 });
		await expect
			.poll(
				() =>
					renderedImage.evaluate(async (image: HTMLImageElement) => {
						if (!image.complete) await image.decode();
						if (image.naturalWidth < 2 || image.naturalHeight < 2) return false;
						const canvas = document.createElement('canvas');
						canvas.width = 16;
						canvas.height = 16;
						const context = canvas.getContext('2d');
						if (!context) return false;
						context.drawImage(image, 0, 0, canvas.width, canvas.height);
						const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
						let minimum = 255;
						let maximum = 0;
						for (let index = 0; index < pixels.length; index += 4) {
							minimum = Math.min(minimum, pixels[index], pixels[index + 1], pixels[index + 2]);
							maximum = Math.max(maximum, pixels[index], pixels[index + 1], pixels[index + 2]);
						}
						return maximum - minimum >= 32;
					}),
				{ timeout: 60_000 }
			)
			.toBe(true);
		await expect(pdfEmbed.locator('img').first()).toBeVisible({ timeout: 120_000 });
		await expect(sharedPage.getByTestId('recording-preview-audio').first()).toHaveAttribute('src', /blob:/, {
			timeout: 60_000
		});
		await expect(sharedPage.getByTestId('recording-preview-waveform').first()).toBeVisible({
			timeout: 60_000
		});
		await holdVisibleProofFrames(sharedPage);

		await expect
			.poll(() => presignedResponses.length, { timeout: 60_000 })
			.toBeGreaterThanOrEqual(3);
		const failedPresignedResponses = presignedResponses.filter((response) => response.status !== 200);
		expect(
			failedPresignedResponses,
			`Expected all shared asset presigned-url responses to be 200. Responses: ${JSON.stringify(presignedResponses)}`
		).toEqual([]);
		await assertNoMissingTranslations(sharedPage);
		logCheckpoint('Logged-out shared chat loaded PDF, image, and audio assets.');

		await proofContext.close();
		proofContext = undefined;
		if (proofVideo) {
			await testInfo.attach('shared-chat-embed-assets-proof-video', {
				path: await proofVideo.path(),
				contentType: 'video/webm'
			});
		}
	} finally {
		if (proofContext) await proofContext.close();
		if (fullChatId) {
			await runCli(apiUrl, ['chats', 'delete', fullChatId, '--yes'], 30_000);
		}
		await runCli(apiUrl, ['logout'], 10_000);
		fs.rmSync(tmpDir, { recursive: true, force: true });
	}
});
