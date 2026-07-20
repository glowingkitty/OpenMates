/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Cross-client encrypted draft lifecycle contract.
 *
 * Pairs the interactive CLI with an authenticated browser, then proves draft
 * create, edit, clear, send, and missed-deletion reconciliation end to end.
 * Draft plaintext is asserted only inside authenticated client boundaries.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');
const AUDIO_FIXTURE = fs.existsSync('/workspace/backend/tests/fixtures/test_audio.wav')
	? '/workspace/backend/tests/fixtures/test_audio.wav'
	: path.resolve(__dirname, '../../../../backend/tests/fixtures/test_audio.wav');
const CLI_DRAFT_REFRESH_TIMEOUT_MS = 30_000;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);
let activeCliHome: string | null = null;
let lastTransientCliFailure = '';

type WebSocketFrameRecord = {
	direction: 'sent' | 'received';
	type: string | null;
	chatId: string | null;
	draftV: number | null;
	text: string;
};

function installWebSocketFrameTracker(page: any): WebSocketFrameRecord[] {
	const frames: WebSocketFrameRecord[] = [];
	const record = (direction: 'sent' | 'received', payload: unknown): void => {
		const text = typeof payload === 'string' ? payload : String(payload ?? '');
		let type: string | null = null;
		let chatId: string | null = null;
		let draftV: number | null = null;
		try {
			const parsed = JSON.parse(text) as {
				type?: unknown;
				event?: unknown;
				payload?: { chat_id?: unknown; chatId?: unknown; draft_v?: unknown };
				chat_id?: unknown;
				versions?: { draft_v?: unknown };
			};
			type = typeof parsed.type === 'string'
				? parsed.type
				: typeof parsed.event === 'string'
					? parsed.event
					: null;
			const rawChatId = parsed.payload?.chat_id ?? parsed.payload?.chatId ?? parsed.chat_id;
			chatId = typeof rawChatId === 'string' ? rawChatId : null;
			const rawDraftV = parsed.payload?.draft_v ?? parsed.versions?.draft_v;
			draftV = typeof rawDraftV === 'number' ? rawDraftV : null;
		} catch {
			// Non-JSON control frames are irrelevant for this draft-sync contract.
		}
		frames.push({ direction, type, chatId, draftV, text: text.slice(0, 500) });
		if (frames.length > 5_000) frames.shift();
	};

	page.on('websocket', (ws: any) => {
		ws.on('framesent', (event: { payload?: unknown }) => record('sent', event.payload));
		ws.on('framereceived', (event: { payload?: unknown }) => record('received', event.payload));
	});

	return frames;
}

async function waitForDraftUpdateReceipt(
	frames: WebSocketFrameRecord[],
	chatId: string,
	label: string,
	afterFrameIndex = 0,
	minDraftV = 1
): Promise<boolean> {
	try {
		await expect
			.poll(
				() => frames.slice(afterFrameIndex).some((frame) =>
					frame.direction === 'received' &&
					frame.type === 'draft_update_receipt' &&
					frame.chatId === chatId &&
					(frame.draftV ?? 0) >= minDraftV
				),
				{ timeout: 30_000, intervals: [500, 1_000, 2_000] }
			)
			.toBeTruthy();
		return true;
	} catch {
		console.warn(`[${label}] Draft update receipt not observed before server refresh poll. Recent WebSocket frames: ${JSON.stringify(frames.slice(Math.max(0, afterFrameIndex - 5)).slice(-40))}`);
		return false;
	}
}

async function waitForDraftDeleteReceipt(
	frames: WebSocketFrameRecord[],
	chatId: string,
	label: string,
	afterFrameIndex = 0
): Promise<boolean> {
	try {
		await expect
			.poll(
				() => frames.slice(afterFrameIndex).some((frame) =>
					frame.direction === 'received' &&
					frame.type === 'draft_delete_receipt' &&
					frame.chatId === chatId
				),
				{ timeout: 30_000, intervals: [500, 1_000, 2_000] }
			)
			.toBeTruthy();
		return true;
	} catch {
		console.warn(`[${label}] Draft delete receipt not observed before server refresh poll. Recent WebSocket frames: ${JSON.stringify(frames.slice(Math.max(0, afterFrameIndex - 5)).slice(-40))}`);
		return false;
	}
}

function deriveApiUrl(baseUrl: string): string {
	const url = new URL(baseUrl);
	if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') {
		return 'https://api.openmates.org';
	}
	if (url.hostname.startsWith('app.')) {
		return `${url.protocol}//api.${url.hostname.slice(4)}`;
	}
	if (url.hostname === 'localhost') return 'http://localhost:8000';
	throw new Error(`Cannot derive API URL from ${baseUrl}`);
}

function cliEnvironment(apiUrl: string): Record<string, string | undefined> {
	const cliDir = path.dirname(path.dirname(CLI_DIST));
	return {
		...process.env,
		...(activeCliHome ? { HOME: activeCliHome } : {}),
		OPENMATES_API_URL: apiUrl,
		NODE_PATH: path.join(cliDir, 'node_modules'),
		TERM: 'dumb'
	};
}

function createIsolatedCliHome(): string {
	return fs.mkdtempSync(path.join(os.tmpdir(), 'openmates-cross-client-cli-'));
}

function cleanupIsolatedCliHome(cliHome: string | null): void {
	if (!cliHome) return;
	fs.rmSync(cliHome, { recursive: true, force: true });
}

function logCliCacheDiagnostics(cliHome: string | null, chatId: string, label: string): void {
	if (!cliHome) return;
	const cachePath = path.join(cliHome, '.openmates', 'sync_cache.json');
	try {
		const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
		const chat = Array.isArray(cache?.chats)
			? cache.chats.find((entry: any) => String(entry?.details?.id ?? '') === chatId)
			: null;
		const details = chat?.details ?? null;
		console.log(`[${label}] CLI cache diagnostics: ${JSON.stringify({
			cacheExists: true,
			syncedAt: typeof cache?.syncedAt === 'number' ? cache.syncedAt : null,
			chatCount: Array.isArray(cache?.chats) ? cache.chats.length : null,
			hasChat: !!chat,
			draftV: typeof details?.draft_v === 'number' ? details.draft_v : null,
			hasEncryptedDraftMd: typeof details?.encrypted_draft_md === 'string' && details.encrypted_draft_md.length > 0,
			encryptedDraftMdLength: typeof details?.encrypted_draft_md === 'string' ? details.encrypted_draft_md.length : 0,
			hasEncryptedDraftPreview: typeof details?.encrypted_draft_preview === 'string' && details.encrypted_draft_preview.length > 0,
			encryptedDraftPreviewLength: typeof details?.encrypted_draft_preview === 'string' ? details.encrypted_draft_preview.length : 0,
		})}`);
	} catch (error) {
		console.log(`[${label}] CLI cache diagnostics: ${JSON.stringify({
			cacheExists: fs.existsSync(cachePath),
			error: error instanceof Error ? error.message : String(error),
		})}`);
	}
}

async function logCliRestDraftDiagnostics(apiUrl: string, cliHome: string | null, chatId: string, label: string): Promise<void> {
	if (!cliHome) return;
	const sessionPath = path.join(cliHome, '.openmates', 'session.json');
	try {
		const session = JSON.parse(fs.readFileSync(sessionPath, 'utf8'));
		const cookies = session?.cookies && typeof session.cookies === 'object'
			? Object.entries(session.cookies)
				.map(([name, value]) => `${name}=${value}`)
				.join('; ')
			: '';
		const response = await fetch(`${apiUrl}/v1/drafts/${encodeURIComponent(chatId)}`, {
			method: 'GET',
			headers: cookies ? { Cookie: cookies } : undefined,
		});
		const data = await response.json().catch(() => null);
		const draft = data && typeof data === 'object' ? (data as { draft?: Record<string, unknown> | null }).draft : null;
		console.log(`[${label}] CLI REST draft diagnostics: ${JSON.stringify({
			status: response.status,
			ok: response.ok,
			hasSessionFile: true,
			hasCookieHeader: cookies.length > 0,
			hasDraft: !!draft,
			draftV: typeof draft?.draft_v === 'number' ? draft.draft_v : null,
			hasEncryptedDraftMd: typeof draft?.encrypted_draft_md === 'string' && draft.encrypted_draft_md.length > 0,
			encryptedDraftMdLength: typeof draft?.encrypted_draft_md === 'string' ? draft.encrypted_draft_md.length : 0,
			hasEncryptedDraftPreview: typeof draft?.encrypted_draft_preview === 'string' && draft.encrypted_draft_preview.length > 0,
			encryptedDraftPreviewLength: typeof draft?.encrypted_draft_preview === 'string' ? draft.encrypted_draft_preview.length : 0,
		})}`);
	} catch (error) {
		console.log(`[${label}] CLI REST draft diagnostics: ${JSON.stringify({
			hasSessionFile: fs.existsSync(sessionPath),
			error: error instanceof Error ? error.message : String(error),
		})}`);
	}
}

async function runCli(
	apiUrl: string,
	args: string[],
	timeoutMs = 60_000
): Promise<{ code: number | null; stdout: string; stderr: string }> {
	return new Promise((resolve) => {
		const child = spawn('node', [CLI_DIST, ...args], {
			env: cliEnvironment(apiUrl),
			stdio: ['ignore', 'pipe', 'pipe']
		});
		const stdout: string[] = [];
		const stderr: string[] = [];
		let settled = false;
		const timeout = setTimeout(() => {
			stderr.push(`CLI timed out after ${timeoutMs}ms.\n`);
			child.kill('SIGTERM');
			setTimeout(() => {
				if (child.exitCode === null) child.kill('SIGKILL');
			}, 1_000).unref();
			finish(null);
		}, timeoutMs);
		const finish = (code: number | null): void => {
			if (settled) return;
			settled = true;
			clearTimeout(timeout);
			resolve({ code, stdout: stdout.join(''), stderr: stderr.join('') });
		};
		child.stdout.on('data', (data: Buffer) => stdout.push(data.toString()));
		child.stderr.on('data', (data: Buffer) => stderr.push(data.toString()));
		child.on('error', (error: Error) => {
			stderr.push(`CLI process error: ${error.message}\n`);
			finish(null);
		});
		child.on('close', finish);
	});
}

async function runCliJson(
	apiUrl: string,
	args: string[],
	timeoutMs = 60_000,
	options: { allowTransientFailure?: boolean } = {}
): Promise<any> {
	const command = args.slice(0, 2).join(' ');
	let result: { code: number | null; stdout: string; stderr: string } | null = null;
	let sawAllowedTransientError = false;
	const maxAttempts = options.allowTransientFailure ? 2 : 6;
	for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
		result = await runCli(apiUrl, [...args, '--json'], timeoutMs);
		if (result.code === 0) return JSON.parse(result.stdout);
		const transientNetworkError = /fetch failed|ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENOTFOUND/i.test(result.stderr);
		const transientAuthError = /Session expired or invalid/i.test(result.stderr);
		sawAllowedTransientError ||= transientNetworkError || transientAuthError;
		if (!transientNetworkError || attempt === maxAttempts - 1) break;
		await new Promise((resolve) => setTimeout(resolve, 1_500 * (attempt + 1)));
	}
	if (options.allowTransientFailure && sawAllowedTransientError) {
		lastTransientCliFailure = `transient-cli-fetch-failed: openmates ${command} after ${maxAttempts} attempt(s); stdout=${JSON.stringify((result?.stdout ?? '').slice(0, 500))}; stderr=${JSON.stringify((result?.stderr ?? '').slice(0, 1_000))}`;
		return null;
	}
	expect(result, `openmates ${command} did not produce a result`).not.toBeNull();
	expect(
		result!.code,
		`openmates ${command} failed with ${result!.stdout.length} stdout bytes\nstderr:\n${result!.stderr}`
	).toBe(0);
	return JSON.parse(result!.stdout);
}

async function pairCli(page: any, apiUrl: string, baseUrl: string): Promise<void> {
	let lastStdout = '';
	let lastStderr = '';
	let lastError = '';
	for (let attempt = 0; attempt < 3; attempt += 1) {
		const child = spawn('node', [CLI_DIST, 'login'], {
			env: cliEnvironment(apiUrl),
			stdio: ['pipe', 'pipe', 'pipe']
		});
		const stdout: string[] = [];
		const stderr: string[] = [];
		child.stdout.on('data', (data: Buffer) => stdout.push(data.toString()));
		child.stderr.on('data', (data: Buffer) => stderr.push(data.toString()));
		child.stdin.on('error', (error: Error) => stderr.push(`CLI stdin error: ${error.message}\n`));

		try {
			const token = await expect
				.poll(() => stdout.join('').match(/pair=([A-Z0-9]{6})/)?.[1] ?? null, {
					timeout: 30_000,
					intervals: [500, 1_000]
				})
				.not.toBeNull();
			void token;
			const pairToken = stdout.join('').match(/pair=([A-Z0-9]{6})/)?.[1];
			expect(pairToken).toBeTruthy();

			await page.goto(`${baseUrl}/#pair=${pairToken}`);
			await page.getByTestId('pair-allow-button').click();
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 30_000 });
			const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
			expect(pin).toMatch(/^[A-Z0-9]{6}$/);
			await new Promise<void>((resolve, reject) => {
				child.stdin.write(`${pin}\n`, (error: Error | null | undefined) => {
					if (error) reject(new Error(`CLI login input failed: ${error.message}`));
					else resolve();
				});
			});

			const exit = await new Promise<{ code: number | null }>((resolve) => {
				const timeout = setTimeout(() => {
					child.kill('SIGTERM');
					resolve({ code: null });
				}, 30_000);
				child.on('close', (code: number | null) => {
					clearTimeout(timeout);
					resolve({ code });
				});
			});
			expect(exit.code, `CLI login failed: ${stdout.join('')} ${stderr.join('')}`).toBe(0);
			expect(stdout.join('')).toContain('Login successful');
			return;
		} catch (error) {
			lastStdout = stdout.join('');
			lastStderr = stderr.join('');
			lastError = error instanceof Error ? error.message : String(error);
			if (child.exitCode === null) child.kill('SIGTERM');
			if (attempt === 2) break;
			await new Promise((resolve) => setTimeout(resolve, 1_000 * (attempt + 1)));
		} finally {
			if (child.exitCode === null) child.kill('SIGTERM');
		}
	}
	throw new Error(`CLI pairing failed after retries: ${lastError}\nstdout:\n${lastStdout}\nstderr:\n${lastStderr}`);
}

async function openSidebar(page: any): Promise<void> {
	const toggle = page.getByTestId('sidebar-toggle');
	if (await toggle.isVisible({ timeout: 2_000 }).catch(() => false)) {
		const mounted = await page.getByTestId('chat-item-wrapper').first().isVisible().catch(() => false);
		if (!mounted) await toggle.click();
	}
}

async function closeSearchIfOpen(page: any): Promise<void> {
	if (!(await page.getByTestId('search-bar').isVisible({ timeout: 1_000 }).catch(() => false))) return;
	const closeButton = page.getByTestId('search-close-button');
	if (await closeButton.isVisible({ timeout: 1_000 }).catch(() => false)) {
		await closeButton.click();
		await expect(page.getByTestId('search-bar')).not.toBeAttached({ timeout: 10_000 });
	}
}

function chatItem(page: any, chatId: string): any {
	return page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
}

function messageEditorEditable(page: any, chatId?: string): any {
	const root = chatId
		? page.locator(`[data-action="message-input"][data-current-chat-id="${chatId}"]`)
		: page.locator('[data-action="message-input"]').last();
	return root.locator('[data-testid="message-editor"] [contenteditable="true"]').first();
}

function messageEditorHost(page: any, chatId: string): any {
	return page
		.locator(`[data-action="message-input"][data-current-chat-id="${chatId}"]`)
		.getByTestId('message-editor')
		.first();
}

async function activeMessageEditorEditable(page: any, chatId: string): Promise<any> {
	const hash = await page.evaluate(() => window.location.hash);
	if (!hash.includes(chatId)) {
		await openDraftByHash(page, chatId);
	}
	const currentHash = await page.evaluate(() => window.location.hash);
	expect(currentHash, 'Fallback to generic editor is only safe on the target chat URL').toContain(chatId);
	await expect(messageEditorHost(page, chatId)).toBeVisible({ timeout: 15_000 });
	const scopedEditor = messageEditorEditable(page, chatId);
	await expect(scopedEditor).toBeVisible({ timeout: 10_000 });
	return scopedEditor;
}

async function replaceMessageEditorText(page: any, chatId: string, text: string): Promise<any> {
	await activeMessageEditorEditable(page, chatId);
	await expect
		.poll(() => page.evaluate(() => typeof (window as any).__openmatesE2EReplaceDraft === 'function'), {
			timeout: 15_000,
			intervals: [250, 500, 1_000]
		})
		.toBe(true);
	console.log(`[CROSS_CLIENT_DRAFT_SYNC] Replacing draft text via browser helper for ${chatId}.`);
	await page.evaluate(async ({ targetChatId, replacement }: { targetChatId: string; replacement: string }) => {
		const helper = (window as any).__openmatesE2EReplaceDraft;
		if (typeof helper !== 'function') throw new Error('E2E draft replacement helper is unavailable');
		await Promise.race([
			helper({ chatId: targetChatId, text: replacement }),
			new Promise((_, reject) => window.setTimeout(() => reject(new Error('E2E draft replacement helper timed out')), 10_000)),
		]);
	}, { targetChatId: chatId, replacement: text });
	console.log(`[CROSS_CLIENT_DRAFT_SYNC] Browser helper returned for ${chatId}; waiting for local encrypted draft.`);
	await expect
		.poll(async () => (await readLocalDraftMarkdown(page, chatId)).markdown ?? '', {
			timeout: 15_000,
			intervals: [500, 1_000]
		})
		.toBe(text);
	console.log(`[CROSS_CLIENT_DRAFT_SYNC] Local encrypted draft matched replacement for ${chatId}.`);
	return messageEditorEditable(page, chatId);
}

async function logDraftOpenDiagnostics(page: any, chatId: string, label: string, expectedText?: string): Promise<void> {
	const diagnostics = await page.evaluate(async ({ targetChatId, expected }: { targetChatId: string; expected?: string }) => {
		async function readIdbValue<T>(dbName: string, storeName: string, key: IDBValidKey): Promise<T | null> {
			return new Promise((resolve) => {
				let settled = false;
				let db: IDBDatabase | null = null;
				const finish = (value: T | null) => {
					if (settled) return;
					settled = true;
					window.clearTimeout(timeout);
					db?.close();
					resolve(value);
				};
				const timeout = window.setTimeout(() => finish(null), 2_000);
				const request = indexedDB.open(dbName);
				request.onerror = () => finish(null);
				request.onsuccess = () => {
					db = request.result;
					try {
						const transaction = db.transaction(storeName, 'readonly');
						const store = transaction.objectStore(storeName);
						const getRequest = store.get(key);
						getRequest.onerror = () => finish(null);
						getRequest.onsuccess = () => finish((getRequest.result as T | undefined) ?? null);
					} catch {
						finish(null);
					}
				};
			});
		}

		async function decryptWithMasterKey(encrypted: unknown): Promise<{ length: number; containsExpected: boolean; ok: boolean } | null> {
			if (typeof encrypted !== 'string' || encrypted.length === 0) return null;
			const masterKey = await readIdbValue<CryptoKey>('openmates_crypto', 'keys', 'master_key');
			if (!masterKey) return { length: 0, containsExpected: false, ok: false };
			try {
				const binary = atob(encrypted);
				const combined = new Uint8Array(binary.length);
				for (let index = 0; index < binary.length; index += 1) combined[index] = binary.charCodeAt(index);
				const decrypted = await crypto.subtle.decrypt(
					{ name: 'AES-GCM', iv: combined.slice(0, 12) },
					masterKey,
					combined.slice(12)
				);
				const text = new TextDecoder().decode(decrypted);
				return { length: text.length, containsExpected: expected ? text.includes(expected) : false, ok: true };
			} catch {
				return { length: 0, containsExpected: false, ok: false };
			}
		}

		const record = await readIdbValue<Record<string, unknown>>('chats_db', 'chats', targetChatId);
		const activeEditorWrapper = document.querySelector(`[data-action="message-input"][data-current-chat-id="${targetChatId}"]`);
		const editor = activeEditorWrapper?.querySelector('[data-testid="message-editor"]') ?? document.querySelector('[data-testid="message-editor"]');
		const messageInputs = Array.from(document.querySelectorAll('[data-action="message-input"]')).map((element) => ({
			chatId: element.getAttribute('data-current-chat-id'),
			visible: !!(element as HTMLElement).offsetParent,
			editorTextLength: element.querySelector('[data-testid="message-editor"]')?.textContent?.length ?? 0,
		}));

		const matchingRows = Array.from(document.querySelectorAll('[data-testid="chat-item-wrapper"]'))
			.filter((element) => element.getAttribute('data-chat-id') === targetChatId)
			.map((element) => ({
				textLength: element.textContent?.length ?? 0,
				active: element.classList.contains('active'),
				visible: !!(element as HTMLElement).offsetParent,
			}));

		return {
			url: window.location.href,
			hash: window.location.hash,
			editorTextLength: editor?.textContent?.length ?? 0,
			editorHtmlLength: editor?.innerHTML?.length ?? 0,
			editorChildCount: editor?.childElementCount ?? 0,
			draftRestoreDiagnostics: (window as typeof window & { __openmatesDraftRestoreDiagnostics?: unknown[] }).__openmatesDraftRestoreDiagnostics ?? [],
			messageInputDraftDiagnostics: (window as typeof window & { __openmatesMessageInputDraftDiagnostics?: unknown[] }).__openmatesMessageInputDraftDiagnostics ?? [],
			searchOpen: !!document.querySelector('[data-testid="search-bar"]'),
			messageInputs,
			matchingRows,
			chatRecord: record
				? {
						chat_id: record.chat_id,
						draft_v: record.draft_v,
						title_v: record.title_v,
						messages_v: record.messages_v,
						has_encrypted_draft_md: typeof record.encrypted_draft_md === 'string' && record.encrypted_draft_md.length > 0,
						encrypted_draft_md_length: typeof record.encrypted_draft_md === 'string' ? record.encrypted_draft_md.length : 0,
						encrypted_draft_md_decrypt: await decryptWithMasterKey(record.encrypted_draft_md),
						has_encrypted_draft_preview: typeof record.encrypted_draft_preview === 'string' && record.encrypted_draft_preview.length > 0,
						encrypted_draft_preview_length: typeof record.encrypted_draft_preview === 'string' ? record.encrypted_draft_preview.length : 0,
						encrypted_draft_preview_decrypt: await decryptWithMasterKey(record.encrypted_draft_preview),
						ideabucket: record.ideabucket,
					}
				: null,
		};
	}, { targetChatId: chatId, expected: expectedText });
	console.log(`[${label}] Draft open diagnostics: ${JSON.stringify(diagnostics)}`);
}

async function logServerDraftDiagnostics(page: any, apiUrl: string, chatId: string, label: string, expectedText?: string): Promise<void> {
	try {
		const diagnostics = await page.evaluate(async ({ apiEndpoint, targetChatId, expected }: { apiEndpoint: string; targetChatId: string; expected?: string }) => {
		async function readIdbValue<T>(dbName: string, storeName: string, key: IDBValidKey): Promise<T | null> {
			return new Promise((resolve) => {
				let settled = false;
				let db: IDBDatabase | null = null;
				const finish = (value: T | null) => {
					if (settled) return;
					settled = true;
					window.clearTimeout(timeout);
					db?.close();
					resolve(value);
				};
				const timeout = window.setTimeout(() => finish(null), 2_000);
				const request = indexedDB.open(dbName);
				request.onerror = () => finish(null);
				request.onsuccess = () => {
					db = request.result;
					try {
						const transaction = db.transaction(storeName, 'readonly');
						const store = transaction.objectStore(storeName);
						const getRequest = store.get(key);
						getRequest.onerror = () => finish(null);
						getRequest.onsuccess = () => finish((getRequest.result as T | undefined) ?? null);
					} catch {
						finish(null);
					}
				};
			});
		}

		async function decryptWithMasterKey(encrypted: unknown): Promise<{ length: number; containsExpected: boolean; ok: boolean } | null> {
			if (typeof encrypted !== 'string' || encrypted.length === 0) return null;
			const masterKey = await readIdbValue<CryptoKey>('openmates_crypto', 'keys', 'master_key');
			if (!masterKey) return { length: 0, containsExpected: false, ok: false };
			try {
				const binary = atob(encrypted);
				const combined = new Uint8Array(binary.length);
				for (let index = 0; index < binary.length; index += 1) combined[index] = binary.charCodeAt(index);
				const decrypted = await crypto.subtle.decrypt(
					{ name: 'AES-GCM', iv: combined.slice(0, 12) },
					masterKey,
					combined.slice(12)
				);
				const text = new TextDecoder().decode(decrypted);
				return { length: text.length, containsExpected: expected ? text.includes(expected) : false, ok: true };
			} catch {
				return { length: 0, containsExpected: false, ok: false };
			}
		}

		const response = await fetch(`${apiEndpoint}/v1/drafts/${encodeURIComponent(targetChatId)}`, {
			method: 'GET',
			credentials: 'include'
		});
		const data = await response.json().catch(() => null);
		const draft = data && typeof data === 'object' ? (data as { draft?: Record<string, unknown> | null }).draft : null;
		return {
			status: response.status,
			ok: response.ok,
			hasDraft: !!draft,
			draftV: typeof draft?.draft_v === 'number' ? draft.draft_v : null,
			hasEncryptedDraftMd: typeof draft?.encrypted_draft_md === 'string' && draft.encrypted_draft_md.length > 0,
			encryptedDraftMdLength: typeof draft?.encrypted_draft_md === 'string' ? draft.encrypted_draft_md.length : 0,
			encryptedDraftMdDecrypt: await decryptWithMasterKey(draft?.encrypted_draft_md),
			hasEncryptedDraftPreview: typeof draft?.encrypted_draft_preview === 'string' && draft.encrypted_draft_preview.length > 0,
			encryptedDraftPreviewLength: typeof draft?.encrypted_draft_preview === 'string' ? draft.encrypted_draft_preview.length : 0,
			encryptedDraftPreviewDecrypt: await decryptWithMasterKey(draft?.encrypted_draft_preview),
		};
		}, { apiEndpoint: apiUrl, targetChatId: chatId, expected: expectedText });
		console.log(`[${label}] Server draft diagnostics: ${JSON.stringify(diagnostics)}`);
	} catch (error) {
		console.log(`[${label}] Server draft diagnostics: ${JSON.stringify({
			error: error instanceof Error ? error.message : String(error),
		})}`);
	}
}

async function readLocalDraftMarkdown(page: any, chatId: string): Promise<{ markdown: string | null; draftV: number | null }> {
	return page.evaluate(async (targetChatId: string) => {
		async function readIdbValue<T>(dbName: string, storeName: string, key: IDBValidKey): Promise<T | null> {
			return new Promise((resolve) => {
				let settled = false;
				let db: IDBDatabase | null = null;
				const finish = (value: T | null) => {
					if (settled) return;
					settled = true;
					window.clearTimeout(timeout);
					db?.close();
					resolve(value);
				};
				const timeout = window.setTimeout(() => finish(null), 2_000);
				const request = indexedDB.open(dbName);
				request.onerror = () => finish(null);
				request.onsuccess = () => {
					db = request.result;
					try {
						const transaction = db.transaction(storeName, 'readonly');
						const store = transaction.objectStore(storeName);
						const getRequest = store.get(key);
						getRequest.onerror = () => finish(null);
						getRequest.onsuccess = () => finish((getRequest.result as T | undefined) ?? null);
					} catch {
						finish(null);
					}
				};
			});
		}

		const record = await readIdbValue<Record<string, unknown>>('chats_db', 'chats', targetChatId);
		const encrypted = record?.encrypted_draft_md;
		if (typeof encrypted !== 'string' || encrypted.length === 0) {
			return { markdown: null, draftV: typeof record?.draft_v === 'number' ? record.draft_v : null };
		}
		const masterKey = await readIdbValue<CryptoKey>('openmates_crypto', 'keys', 'master_key');
		if (!masterKey) return { markdown: null, draftV: typeof record?.draft_v === 'number' ? record.draft_v : null };
		const binary = atob(encrypted);
		const combined = new Uint8Array(binary.length);
		for (let index = 0; index < binary.length; index += 1) combined[index] = binary.charCodeAt(index);
		const decrypted = await crypto.subtle.decrypt(
			{ name: 'AES-GCM', iv: combined.slice(0, 12) },
			masterKey,
			combined.slice(12)
		);
		return {
			markdown: new TextDecoder().decode(decrypted),
			draftV: typeof record?.draft_v === 'number' ? record.draft_v : null,
		};
	}, chatId);
}

async function expectLocalDraftMarkdown(page: any, chatId: string, expectedText: string, label: string): Promise<{ markdown: string | null; draftV: number | null }> {
	try {
		await expect
			.poll(async () => (await readLocalDraftMarkdown(page, chatId)).markdown ?? '', {
				timeout: 15_000,
				intervals: [500, 1_000]
			})
			.toBe(expectedText);
	} catch (_error) {
		await logDraftOpenDiagnostics(page, chatId, `${label}_LOCAL_DRAFT_AFTER_EDIT`, expectedText);
		throw _error;
	}
	return readLocalDraftMarkdown(page, chatId);
}

function resultChatId(result: any): string {
	const chatId = String(result.chatId ?? result.chat_id ?? '');
	expect(chatId).toMatch(/^[0-9a-f-]{36}$/i);
	return chatId;
}

async function expectCliPairedToBrowserAccount(page: any, apiUrl: string): Promise<void> {
	const browserUserId = await page.evaluate(async (apiEndpoint: string) => {
		const sessionId = sessionStorage.getItem('session_id') ?? sessionStorage.getItem('openmates_session_id');
		if (!sessionId) {
			throw new Error('Browser session check failed: client session_id is missing');
		}
		const response = await fetch(`${apiEndpoint}/v1/auth/session`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ session_id: sessionId })
		});
		const data = await response.json().catch(() => ({}));
		if (!response.ok || data?.success !== true || !data?.user?.id) {
			throw new Error(
				`Browser session check failed: ${response.status} ${JSON.stringify(data).slice(0, 300)}`
			);
		}
		return String(data.user.id);
	}, apiUrl);
	const cliUser = await runCliJson(apiUrl, ['whoami'], 20_000);
	expect(
		String(cliUser.id ?? ''),
		'CLI pair login must authorize the currently logged-in browser account'
	).toBe(browserUserId);
}

async function clearBrowserClientState(page: any, baseUrl: string): Promise<void> {
	const resetUrl = `${new URL(baseUrl).origin}/e2e-ideabucket-cold-boot`;
	await page.route(resetUrl, (route: any) =>
		route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>IdeaBucket cold boot</title>' })
	);
	await page.goto(resetUrl);
	await page.evaluate(async () => {
		localStorage.clear();
		sessionStorage.clear();
		const databases = await indexedDB.databases();
		await Promise.all(
			databases
				.map((database) => database.name)
				.filter((name): name is string => Boolean(name))
				.map(
					(name) =>
						new Promise<void>((resolve, reject) => {
							const request = indexedDB.deleteDatabase(name);
							request.onerror = () => reject(request.error ?? new Error(`Failed to delete ${name}`));
							request.onblocked = () => reject(new Error(`Deleting ${name} was blocked`));
							request.onsuccess = () => resolve();
						})
				)
		);
	});
	await page.unroute(resetUrl);
	await page.context().clearCookies();
}

async function expectIdeaBucketDraftMarkers(page: any, chatId: string, expectedText: string): Promise<void> {
	const item = await locateDraftInSidebarOrSearch(page, chatId, expectedText).catch(() => null);
	if (item) {
		await expect(item).toContainText(expectedText);
		const sidebarItem = chatItem(page, chatId);
		const searchItem = page.locator(`[data-testid="search-chat-item"][data-result-id="${chatId}"]`).first();
		const markerHost = (await sidebarItem.isVisible().catch(() => false)) ? sidebarItem : searchItem;
		await expect(markerHost.getByTestId('ideabucket-chat-list-label')).toBeVisible({ timeout: 15_000 });
		await item.click();
		await closeSearchIfOpen(page);
	} else {
		await openDraftByHash(page, chatId);
	}
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15_000 });
	try {
		await expect(editor).toContainText(expectedText, { timeout: 45_000 });
	} catch (error) {
		await logDraftOpenDiagnostics(page, chatId, 'IDEABUCKET_WEB_MARKERS', expectedText);
		throw error;
	}
	await expect(page.getByTestId('ideabucket-input-pill')).toBeVisible({ timeout: 15_000 });
}

async function expectSearchFindsChat(page: any, query: string): Promise<void> {
	await openSidebar(page);
	await closeSearchIfOpen(page);
	const searchIcon = page.getByTestId('search-button');
	await expect(searchIcon).toBeVisible({ timeout: 10_000 });
	await searchIcon.click();
	const searchInput = page.getByTestId('search-input');
	await expect(searchInput).toBeVisible({ timeout: 5_000 });
	await searchInput.fill(query);
	const searchResults = page.getByTestId('search-results');
	await expect(async () => {
		const hasResults = await searchResults.isVisible().catch(() => false);
		const isWarmingUp = await page.getByTestId('warming-up').isVisible().catch(() => false);
		const resultCount = await page.getByTestId('search-chat-item').count().catch(() => 0);
		if (!hasResults || isWarmingUp || resultCount === 0) {
			await searchInput.fill('');
			await searchInput.fill(query);
		}
		await expect(searchResults).toBeVisible({ timeout: 5_000 });
		await expect(searchResults).toContainText(query);
	}).toPass({ timeout: 60_000 });
}

async function locateDraftInSidebarOrSearch(page: any, chatId: string, expectedText: string): Promise<any | null> {
	await openSidebar(page);
	await closeSearchIfOpen(page);
	const item = chatItem(page, chatId);
	if (await item.isVisible({ timeout: 5_000 }).catch(() => false)) {
		if (await item.getByText(expectedText, { exact: false }).isVisible({ timeout: 5_000 }).catch(() => false)) {
			return item;
		}
	}

	const searchIcon = page.getByTestId('search-button');
	await expect(searchIcon).toBeVisible({ timeout: 10_000 });
	await searchIcon.click();
	const searchInput = page.getByTestId('search-input');
	await expect(searchInput).toBeVisible({ timeout: 5_000 });
	await searchInput.fill(expectedText);
	const searchResults = page.getByTestId('search-results');
	const result = page.locator(`[data-testid="search-chat-item"][data-result-id="${chatId}"]`).first();
	const metadataResult = searchResults.getByTestId('search-metadata-snippet').filter({ hasText: expectedText }).first();
	await expect(async () => {
		const hasResults = await searchResults.isVisible().catch(() => false);
		const isWarmingUp = await page.getByTestId('warming-up').isVisible().catch(() => false);
		const hasChatResult = await result.isVisible().catch(() => false);
		const hasMetadataResult = await metadataResult.isVisible().catch(() => false);
		if (!hasResults || isWarmingUp || (!hasChatResult && !hasMetadataResult)) {
			await searchInput.fill('');
			await searchInput.fill(expectedText);
		}
		await expect(searchResults).toBeVisible({ timeout: 5_000 });
		expect(hasChatResult || hasMetadataResult).toBe(true);
		await expect(searchResults).toContainText(expectedText);
	}).toPass({ timeout: 60_000 });
	return (await metadataResult.isVisible().catch(() => false)) ? metadataResult : result;
}

async function openDraftByHash(page: any, chatId: string): Promise<void> {
	await closeSearchIfOpen(page);
	await page.goto(`${new URL(page.url()).origin}/#chat-id=${chatId}`);
}

async function openDraft(page: any, chatId: string, expectedText: string, requireRestoredText = false): Promise<any> {
	await openDraftByHash(page, chatId);
	const editor = messageEditorEditable(page, chatId);
	await expect(editor).toBeVisible({ timeout: 15_000 });
	if (!requireRestoredText) return null;
	try {
		await expectLocalDraftMarkdown(page, chatId, expectedText, 'CROSS_CLIENT_DRAFT_SYNC_OPEN');
	} catch (error) {
		await logDraftOpenDiagnostics(page, chatId, 'CROSS_CLIENT_DRAFT_SYNC', expectedText);
		throw error;
	}
	return null;
}

test.describe('Cross-client encrypted draft sync', () => {
	test.describe.configure({ mode: 'serial' });
	test.setTimeout(300_000);

	test('CLI and web reconcile draft lifecycle and missed chat deletion', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('CROSS_CLIENT_DRAFT_SYNC');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'cross-client-draft-sync' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const unique = Date.now().toString(36);
		const initialText = `CLI encrypted draft ${unique}`;
		const updatedText = `Web updated encrypted draft ${unique}`;
		const sentText = `Cross-client sent draft ${unique}`;
		const cleanupDraftIds = new Set<string>();
		const cleanupChatIds = new Set<string>();
		let cliPaired = false;
		const cliHome = createIsolatedCliHome();
		const wsFrames = installWebSocketFrameTracker(page);

		await loginToTestAccount(page, log, screenshot);
		try {
			activeCliHome = cliHome;
			log('Pairing CLI client.');
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			await expectCliPairedToBrowserAccount(page, apiUrl);
			log('CLI client paired.');
			await page.goto(baseUrl);
			await waitForChatReady(page, log);

			log('Creating draft from CLI.');
			const created = await runCliJson(apiUrl, ['drafts', 'create', initialText]);
			const draftChatId = String(created.chatId);
			expect(draftChatId).toMatch(/^[0-9a-f-]{36}$/i);
			cleanupDraftIds.add(draftChatId);
			await openDraft(page, draftChatId, initialText, true);
			log('CLI-created draft opened in web client.');

			const draftUpdateFrameStart = wsFrames.length;
			log('Replacing CLI draft from web client.');
			await replaceMessageEditorText(page, draftChatId, updatedText);
			const firstDismissButton = page.getByTestId('input-dismiss-button');
			if (await firstDismissButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
				await firstDismissButton.click();
			}
			await expectLocalDraftMarkdown(page, draftChatId, updatedText, 'CROSS_CLIENT_DRAFT_SYNC');
			log('Local web draft edit persisted; waiting for draft update receipt.');
			expect(await waitForDraftUpdateReceipt(wsFrames, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC', draftUpdateFrameStart, Number(created.draftV) + 1)).toBe(true);
			log('Draft update receipt observed; polling CLI refresh.');
			try {
				await expect
					.poll(async () => {
						const result = await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
							allowTransientFailure: true,
						});
						const draft = result?.draft;
						return `${draft?.draftV ?? 0}:${draft?.markdown ?? ''}`;
					}, {
						timeout: 120_000,
						intervals: [1_000, 2_000, 5_000]
					})
					.toBe(`${Number(created.draftV) + 1}:${updatedText}`);
			} catch (error) {
				await logCliRestDraftDiagnostics(apiUrl, cliHome, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_CLI_REST_AFTER_EDIT');
				await logServerDraftDiagnostics(page, apiUrl, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_SERVER_ROUTE_AFTER_EDIT', updatedText);
				await logDraftOpenDiagnostics(page, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_SERVER_AFTER_EDIT', updatedText);
				logCliCacheDiagnostics(cliHome, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_CLI_AFTER_EDIT');
				throw error;
			}
			log('Web draft edit reconciled to CLI.');

			await openDraft(page, draftChatId, updatedText, true);
			const draftDeleteFrameStart = wsFrames.length;
			await replaceMessageEditorText(page, draftChatId, '');
			const dismissButton = page.getByTestId('input-dismiss-button');
			if (await dismissButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
				await dismissButton.click();
			}
			log('Web draft emptied; waiting for CLI reconciliation.');
			expect(await waitForDraftDeleteReceipt(wsFrames, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC', draftDeleteFrameStart)).toBe(true);
			await expect
				.poll(async () => {
					const result = await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
						allowTransientFailure: true,
					});
					return result?.draft ?? (lastTransientCliFailure || 'transient-cli-fetch-failed');
				}, {
					timeout: 60_000,
					intervals: [1_000, 2_000]
				})
				.toBeNull();
			cleanupDraftIds.delete(draftChatId);
			log('Web draft clear reconciled to CLI.');

			log('Creating sendable draft from CLI.');
			const sendDraft = await runCliJson(apiUrl, ['drafts', 'create', sentText]);
			const sentChatId = String(sendDraft.chatId);
			cleanupDraftIds.add(sentChatId);
			await page.reload();
			await waitForChatReady(page, log);
			await openDraft(page, sentChatId, sentText, true);
			await replaceMessageEditorText(page, sentChatId, sentText);
			await messageEditorEditable(page, sentChatId).click();
			const sendButton = page.locator('[data-action="send-message"]');
			await expect(sendButton).toBeVisible({ timeout: 15_000 });
			await sendButton.click();
			await expect(page.getByTestId('message-user').last()).toContainText(sentText, { timeout: 30_000 });
			await expect
				.poll(async () => {
					const result = await runCliJson(apiUrl, ['drafts', 'get', sentChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
						allowTransientFailure: true,
					});
					return result?.draft ?? (lastTransientCliFailure || 'transient-cli-fetch-failed');
				}, {
					timeout: 30_000,
					intervals: [1_000, 2_000]
				})
				.toBeNull();
			cleanupDraftIds.delete(sentChatId);
			cleanupChatIds.add(sentChatId);
			log('Web send cleared the CLI draft.');

			log('Deleting sent chat while web client is offline.');
			await page.context().setOffline(true);
			const deletion = await runCli(apiUrl, ['chats', 'delete', sentChatId, '--yes']);
			expect(deletion.code, `CLI chat deletion failed:\n${deletion.stderr}`).toBe(0);
			expect(deletion.stdout).toContain('1/1 chat(s) deleted.');
			cleanupChatIds.delete(sentChatId);
			await page.context().setOffline(false);
			await page.reload();
			await waitForChatReady(page, log);
			await openSidebar(page);
			await expect(chatItem(page, sentChatId)).toHaveCount(0, { timeout: 30_000 });
			log('Missed chat deletion reconciled after reconnect.');
		} finally {
			await page.context().setOffline(false).catch(() => undefined);
			for (const chatId of cleanupDraftIds) {
				await runCli(apiUrl, ['drafts', 'clear', chatId], 10_000);
			}
			for (const chatId of cleanupChatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 10_000);
			}
			if (cliPaired) await runCli(apiUrl, ['logout'], 10_000);
			activeCliHome = null;
			cleanupIsolatedCliHome(cliHome);
		}
	});

	test('IdeaBucket drafts and processed chats keep encrypted provenance across web cold boot', async ({ page }: { page: any }) => {
		test.setTimeout(600_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		expect(fs.existsSync(AUDIO_FIXTURE), `Missing audio fixture at ${AUDIO_FIXTURE}`).toBeTruthy();
		const log = createSignupLogger('IDEABUCKET_WEB_MARKERS');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'ideabucket-web-markers' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const unique = Date.now().toString(36);
		const draftText = `IdeaBucket editable draft ${unique}`;
		const editedDraftText = `IdeaBucket edited draft ${unique}`;
		const audioBucketId = `e2e-audio-${unique}`;
		const draftBucketId = `e2e-draft-${unique}`;
		const processBucketId = `e2e-process-${unique}`;
		const processText = `IdeaBucket processed history ${unique}`;
		const futureSchedule = String(Math.floor(Date.now() / 1000) + 3600);
		const cleanupDraftIds = new Set<string>();
		const cleanupChatIds = new Set<string>();
		let cliPaired = false;
		const cliHome = createIsolatedCliHome();
		const wsFrames = installWebSocketFrameTracker(page);

		await loginToTestAccount(page, log, screenshot);
		try {
			activeCliHome = cliHome;
			log('Pairing CLI client for IdeaBucket web coverage.');
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			await expectCliPairedToBrowserAccount(page, apiUrl);
			await page.goto(baseUrl);
			await waitForChatReady(page, log);

			log('Creating encrypted IdeaBucket text draft from CLI.');
			const draft = await runCliJson(apiUrl, [
				'ideabucket',
				'add',
				draftText,
				'--bucket',
				draftBucketId,
				'--scheduled-at',
				futureSchedule
			]);
			const draftChatId = resultChatId(draft);
			cleanupDraftIds.add(draftChatId);
			await page.reload();
			await waitForChatReady(page, log);
			await expectIdeaBucketDraftMarkers(page, draftChatId, draftText);
			await screenshot(page, 'text-draft-markers');

			const draftUpdateFrameStart = wsFrames.length;
			const editor = await replaceMessageEditorText(page, draftChatId, editedDraftText);
			await expect(editor).toContainText(editedDraftText, { timeout: 10_000 });
			await page.getByTestId('input-dismiss-button').click();
			const localDraft = await expectLocalDraftMarkdown(page, draftChatId, editedDraftText, 'IDEABUCKET_WEB_MARKERS');
			expect(await waitForDraftUpdateReceipt(wsFrames, draftChatId, 'IDEABUCKET_WEB_MARKERS', draftUpdateFrameStart, localDraft.draftV ?? 2)).toBe(true);
			try {
				await expect
					.poll(async () => {
						const result = await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
							allowTransientFailure: true,
						});
						const currentDraft = result?.draft;
						return currentDraft?.markdown ?? '';
					}, {
						timeout: 120_000,
						intervals: [1_000, 2_000, 5_000]
					})
					.toBe(editedDraftText);
			} catch (error) {
				await logCliRestDraftDiagnostics(apiUrl, cliHome, draftChatId, 'IDEABUCKET_WEB_MARKERS_CLI_REST_AFTER_EDIT');
				await logServerDraftDiagnostics(page, apiUrl, draftChatId, 'IDEABUCKET_WEB_MARKERS_SERVER_ROUTE_AFTER_EDIT', editedDraftText);
				await logDraftOpenDiagnostics(page, draftChatId, 'IDEABUCKET_WEB_MARKERS_SERVER_AFTER_EDIT', editedDraftText);
				logCliCacheDiagnostics(cliHome, draftChatId, 'IDEABUCKET_WEB_MARKERS_CLI_AFTER_EDIT');
				throw error;
			}
			log('IdeaBucket text draft remained editable in web.');

			const status = await runCli(apiUrl, ['ideabucket', 'status', draftBucketId, '--json']);
			expect(status.code, `IdeaBucket status failed:\n${status.stderr}`).toBe(0);
			expect(status.stdout).not.toContain(draftText);
			expect(status.stdout).not.toContain(editedDraftText);
			log('IdeaBucket status returned only sparse encrypted-safe metadata.');

			log('Cold booting browser state, then logging in again.');
			await clearBrowserClientState(page, baseUrl);
			await loginToTestAccount(page, log, screenshot);
			await waitForChatReady(page, log);
			await expectIdeaBucketDraftMarkers(page, draftChatId, editedDraftText);
			await screenshot(page, 'cold-boot-draft-markers');

			log('Creating encrypted IdeaBucket audio draft from CLI.');
			const audioDraft = await runCliJson(apiUrl, [
				'ideabucket',
				'audio',
				AUDIO_FIXTURE,
				'--bucket',
				audioBucketId,
				'--scheduled-at',
				futureSchedule
			], 120_000);
			const audioChatId = resultChatId(audioDraft);
			cleanupDraftIds.add(audioChatId);
			await page.reload();
			await waitForChatReady(page, log);
			await expectIdeaBucketDraftMarkers(page, audioChatId, 'IdeaBucket');
			await expect(page.getByTestId('recording-preview-audio').first()).toBeVisible({ timeout: 30_000 });
			await screenshot(page, 'audio-draft-embed-preview');

			log('Creating and processing due IdeaBucket chat from CLI.');
			const processedDraft = await runCliJson(apiUrl, [
				'ideabucket',
				'add',
				processText,
				'--bucket',
				processBucketId,
				'--scheduled-at',
				String(Math.floor(Date.now() / 1000) - 5)
			]);
			const processedChatId = resultChatId(processedDraft);
			cleanupDraftIds.add(processedChatId);
			const processed = await runCliJson(apiUrl, ['ideabucket', 'process', processBucketId, '--now'], 90_000);
			expect(processed.status).toBe('sent');
			expect(String(processed.chat_id)).toBe(processedChatId);
			cleanupDraftIds.delete(processedChatId);
			cleanupChatIds.add(processedChatId);

			await page.reload();
			await waitForChatReady(page, log);
			await openSidebar(page);
			const processedItem = chatItem(page, processedChatId);
			await expect(processedItem).toBeVisible({ timeout: 30_000 });
			await expect(processedItem.getByTestId('ideabucket-chat-badge')).toBeVisible({ timeout: 15_000 });
			await processedItem.click();
			await expect(page.getByTestId('message-user')).toHaveCount(1, { timeout: 30_000 });
			await expect(page.getByTestId('message-user').first()).toContainText(processText, { timeout: 30_000 });
			await expect(page.getByTestId('message-system')).toHaveCount(1, { timeout: 30_000 });
			await expect(page.getByTestId('system-message-text').first()).toContainText('ideabucket_triggered_send', { timeout: 30_000 });
			await screenshot(page, 'processed-chat-marker-and-system-event');

			await expectSearchFindsChat(page, processText);
			await screenshot(page, 'processed-chat-search-result');
			log('Processed IdeaBucket chat was searchable from chat history.');
		} finally {
			for (const chatId of cleanupDraftIds) {
				await runCli(apiUrl, ['drafts', 'clear', chatId], 10_000);
			}
			for (const chatId of cleanupChatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 10_000);
			}
			if (cliPaired) await runCli(apiUrl, ['logout'], 10_000);
			activeCliHome = null;
			cleanupIsolatedCliHome(cliHome);
		}
	});
});
