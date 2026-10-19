/* eslint-disable @typescript-eslint/no-require-imports, @typescript-eslint/no-explicit-any */
/** Shared authenticated browser/CLI draft helpers. Importing this module registers no tests. */
import type { Page, WebSocketRoute } from '@playwright/test';
const { expect } = require('./cookie-audit');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const CLI_DIST = fs.existsSync('/workspace/cli/dist/cli.js')
	? '/workspace/cli/dist/cli.js'
	: path.resolve(__dirname, '../../../../packages/openmates-cli/dist/cli.js');
const AUDIO_FIXTURE = fs.existsSync('/workspace/backend/tests/fixtures/test_audio.wav')
	? '/workspace/backend/tests/fixtures/test_audio.wav'
	: path.resolve(__dirname, '../../../../../backend/tests/fixtures/test_audio.wav');
const CLI_DRAFT_REFRESH_TIMEOUT_MS = 60_000;
const DRAFT_REPLACEMENT_HELPER_TIMEOUT_MS = 30_000;
const CHAT_DELETION_RECONCILE_TIMEOUT_MS = 90_000;
let activeCliHome: string | null = null;
let lastTransientCliFailure = '';

function setIsolatedCliHome(cliHome: string): void {
	activeCliHome = cliHome;
}

function getLastTransientCliFailure(): string {
	return lastTransientCliFailure;
}

type WebSocketFrameRecord = {
	direction: 'sent' | 'received';
	type: string | null;
	chatId: string | null;
	draftV: number | null;
	changeIds: string[];
	successfulChangeIds: string[];
	conflicts: number | null;
	text: string;
};

function createWebSocketFrameRecorder(): {
	frames: WebSocketFrameRecord[];
	record(direction: 'sent' | 'received', payload: unknown): void;
} {
	const frames: WebSocketFrameRecord[] = [];
	const record = (direction: 'sent' | 'received', payload: unknown): void => {
		const text = typeof payload === 'string' ? payload : String(payload ?? '');
		let type: string | null = null;
		let chatId: string | null = null;
		let draftV: number | null = null;
		let changeIds: string[] = [];
		let successfulChangeIds: string[] = [];
		let conflicts: number | null = null;
		try {
			const parsed = JSON.parse(text) as {
				type?: unknown;
				event?: unknown;
				payload?: { chat_id?: unknown; chatId?: unknown; draft_v?: unknown; changes?: Array<{ change_id: string }>; successful_change_ids?: string[]; conflicts?: number };
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
			changeIds = parsed.payload?.changes?.map((change) => change.change_id) ?? [];
			successfulChangeIds = parsed.payload?.successful_change_ids ?? [];
			conflicts = parsed.payload?.conflicts ?? null;
		} catch {
			// Non-JSON control frames are irrelevant for this draft-sync contract.
		}
		frames.push({ direction, type, chatId, draftV, changeIds, successfulChangeIds, conflicts, text: text.slice(0, 500) });
		if (frames.length > 5_000) frames.shift();
	};

	return { frames, record };
}

function installWebSocketFrameTracker(page: any): WebSocketFrameRecord[] {
	const { frames, record } = createWebSocketFrameRecorder();
	page.on('websocket', (ws: any) => {
		ws.on('framesent', (event: { payload?: unknown }) => record('sent', event.payload));
		ws.on('framereceived', (event: { payload?: unknown }) => record('received', event.payload));
	});

	return frames;
}

/** Pass every frame to the real backend; disconnect both halves when emulating offline. */
async function installOfflineWebSocketControl(page: Page): Promise<{
	frames: WebSocketFrameRecord[];
	setOffline(offline: boolean): Promise<void>;
}> {
	const { frames, record } = createWebSocketFrameRecorder();
	let offline = false;
	const routes = new Set<WebSocketRoute>();
	await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, async (socket) => {
		if (offline) {
			await socket.close({ code: 3001, reason: 'Browser network disconnected by test' });
			return;
		}
		const server = socket.connectToServer();
		routes.add(socket);
		routes.add(server);
		// Routed sockets bypass page WebSocket frame events. Observe the actual
		// client/server bytes here and forward each frame without alteration.
		socket.onMessage((raw) => {
			record('sent', raw);
			server.send(raw);
		});
		server.onMessage((raw) => {
			record('received', raw);
			socket.send(raw);
		});
		// Keep the default bidirectional forwarding of close events.
	});
	return {
		frames,
		async setOffline(disconnected: boolean): Promise<void> {
			offline = disconnected;
			await page.context().setOffline(disconnected);
			if (disconnected) {
				// Chromium's network emulation leaves existing WebSockets open.
				// Close their browser and actual server endpoints, including earlier
				// page generations whose routes already tolerate a closed context.
				await Promise.all(Array.from(routes, (route) =>
					route.close({ code: 3001, reason: 'Browser network disconnected by test' })
				));
				routes.clear();
			}
		},
	};
}

/** Check the application's browser-side connection state, independently of the route controller. */
async function expectBrowserDraftTransportOffline(page: Page): Promise<void> {
	await expect.poll(() => page.evaluate(async () => {
		const hook = (window as unknown as {
			__openmatesE2EChatConnectionState?: () => Promise<{ online: boolean; websocketConnected: boolean }>;
		}).__openmatesE2EChatConnectionState;
		if (!hook) throw new Error('Browser chat connection state helper is unavailable');
		return hook();
	}), { timeout: 45_000 }).toMatchObject({ online: false, websocketConnected: false });
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
	if (activeCliHome === cliHome) activeCliHome = null;
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
		const transientNetworkError = /fetch failed|ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENOTFOUND|CLI timed out/i.test(result.stderr);
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

function messageInputSendButton(page: any, chatId: string): any {
	return page
		.locator(`[data-action="message-input"][data-current-chat-id="${chatId}"]`)
		.locator('[data-action="send-message"]')
		.first();
}

async function loadLocalChatWithE2EHook(page: any, chatId: string): Promise<{
	loaded: boolean;
	reason?: string;
	messageInputs: Array<{ chatId: string | null; visible: boolean }>;
}> {
	return page.evaluate(async (targetChatId: string) => {
		const helper = (window as typeof window & {
			__openmatesE2ELoadLocalChat?: (input: { chatId: string; chat?: Record<string, unknown> }) => Promise<{ chatId: string }>;
		}).__openmatesE2ELoadLocalChat;
		if (typeof helper !== 'function') return { loaded: false, reason: 'helper_unavailable', messageInputs: [] };
		const chat = await new Promise<Record<string, unknown> | null>((resolve) => {
			let db: IDBDatabase | null = null;
			const finish = (value: Record<string, unknown> | null) => {
				db?.close();
				resolve(value);
			};
			const request = indexedDB.open('chats_db');
			request.onerror = () => finish(null);
			request.onsuccess = () => {
				db = request.result;
				try {
					const transaction = db.transaction('chats', 'readonly');
					const getRequest = transaction.objectStore('chats').get(targetChatId);
					getRequest.onerror = () => finish(null);
					getRequest.onsuccess = () => finish((getRequest.result as Record<string, unknown> | undefined) ?? null);
				} catch {
					finish(null);
				}
			};
		});
		if (!chat) return { loaded: false, reason: 'chat_unavailable', messageInputs: [] };
		await helper({ chatId: targetChatId, chat });
		await new Promise((resolve) => window.setTimeout(resolve, 250));
		const messageInputs = Array.from(document.querySelectorAll('[data-action="message-input"]')).map((element) => ({
			chatId: element.getAttribute('data-current-chat-id'),
			visible: !!(element as HTMLElement).offsetParent,
		}));
		return { loaded: true, messageInputs };
	}, chatId);
}

async function sendCurrentMessageWithE2EHook(page: any, chatId: string): Promise<{
	expectedChatId: string;
	didSendComplete: boolean;
	text: string;
	sendDebug: Record<string, unknown> | null;
	messageInputs: Array<{ chatId: string | null; visible: boolean }>;
	userMessageCount: number;
}> {
	return page.evaluate(async (targetChatId: string) => {
		const helper = (window as typeof window & {
			__openmatesE2ESendCurrentMessage?: (input: { chatId: string }) => Promise<{
				expectedChatId: string;
				didSendComplete: boolean;
				text: string;
				sendDebug: Record<string, unknown> | null;
				messageInputs: Array<{ chatId: string | null; visible: boolean }>;
				userMessageCount: number;
			}>;
		}).__openmatesE2ESendCurrentMessage;
		if (typeof helper !== 'function') throw new Error('send helper unavailable');
		return helper({ chatId: targetChatId });
	}, chatId);
}

async function activeMessageEditorEditable(page: any, chatId: string): Promise<any> {
	await expect(async () => {
		const hash = await page.evaluate(() => window.location.hash);
		if (!hash.includes(chatId)) {
			await openDraftByHash(page, chatId);
		} else if (!(await messageEditorHost(page, chatId).isVisible().catch(() => false))) {
			await page.evaluate((targetHash: string) => {
				window.dispatchEvent(new Event('hashchange'));
				window.dispatchEvent(new CustomEvent('processPendingDeepLink', { detail: { hash: targetHash } }));
			}, `#chat-id=${chatId}`);
			const fallback = await loadLocalChatWithE2EHook(page, chatId);
			console.log(`[CROSS_CLIENT_DRAFT_SYNC_OPEN_EDITOR] Local load fallback: ${JSON.stringify(fallback)}`);
		}
		const currentHash = await page.evaluate(() => window.location.hash);
		expect(currentHash, 'Fallback to generic editor is only safe on the target chat URL').toContain(chatId);
		await expect(messageEditorHost(page, chatId)).toBeVisible({ timeout: 10_000 });
	}).toPass({ timeout: 120_000, intervals: [1_000, 2_000, 5_000] });
	const scopedEditor = messageEditorEditable(page, chatId);
	if (!(await scopedEditor.isVisible({ timeout: 1_000 }).catch(() => false))) {
		await messageEditorHost(page, chatId).click();
	}
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
	await page.evaluate(async ({ targetChatId, replacement, helperTimeoutMs }: { targetChatId: string; replacement: string; helperTimeoutMs: number }) => {
		const helper = (window as any).__openmatesE2EReplaceDraft;
		if (typeof helper !== 'function') throw new Error('E2E draft replacement helper is unavailable');
		await Promise.race([
			helper({ chatId: targetChatId, text: replacement }),
			new Promise((_, reject) => window.setTimeout(() => reject(new Error('E2E draft replacement helper timed out')), helperTimeoutMs)),
		]);
	}, { targetChatId: chatId, replacement: text, helperTimeoutMs: DRAFT_REPLACEMENT_HELPER_TIMEOUT_MS });
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

type QueuedDraftChange = {
	change_id: string;
	chat_id: string;
	type: string;
	queue_order: number;
	value: string | null;
	encrypted_draft_preview?: string | null;
	version_before_edit: number;
};

/** Inspect genuine product saves; only IDs are rewritten to expose UUID-key ordering. */
async function readQueuedDraftChanges(page: any, chatId: string, reverseIds = false): Promise<QueuedDraftChange[]> {
	return page.evaluate(({ targetChatId, reverse }: { targetChatId: string; reverse: boolean }) =>
		new Promise<QueuedDraftChange[]>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onerror = () => reject(request.error);
			request.onsuccess = () => {
				const db = request.result;
				const transaction = db.transaction('pending_sync_changes', reverse ? 'readwrite' : 'readonly');
				const store = transaction.objectStore('pending_sync_changes');
				const get = store.getAll();
				let rows: QueuedDraftChange[] = [];
				get.onsuccess = () => {
					rows = (get.result as QueuedDraftChange[]).filter((row) => row.chat_id === targetChatId);
					if (!reverse) return;
					rows.sort((a, b) => a.queue_order - b.queue_order);
					rows = rows.map((row, index) => {
						store.delete(row.change_id);
						const reordered = { ...row, change_id: `${(99999999 - index).toString()}-ffff-4fff-bfff-${crypto.randomUUID().slice(-12)}` };
						store.put(reordered);
						return reordered;
					});
				};
				transaction.oncomplete = () => { db.close(); resolve(rows); };
				transaction.onabort = () => { db.close(); reject(transaction.error ?? new Error('Outbox transaction aborted')); };
				transaction.onerror = () => { db.close(); reject(transaction.error); };
			};
		}), { targetChatId: chatId, reverse: reverseIds });
}

/** Plaintext stays inside the authenticated browser holding this account's master key. */
async function readServerDraftWithBrowserKey(page: any, apiUrl: string, chatId: string): Promise<{
	markdown: string | null;
	preview: string | null;
	draftV: number | null;
}> {
	return page.evaluate(async ({ apiEndpoint, targetChatId }: { apiEndpoint: string; targetChatId: string }) => {
		const response = await fetch(`${apiEndpoint}/v1/drafts/${encodeURIComponent(targetChatId)}`, { credentials: 'include' });
		if (!response.ok) throw new Error(`Authenticated draft read failed: ${response.status}`);
		const { draft } = await response.json();
		const masterKey = await new Promise<CryptoKey>((resolve, reject) => {
			const request = indexedDB.open('openmates_crypto');
			request.onerror = () => reject(request.error);
			request.onsuccess = () => {
				const db = request.result;
				const read = db.transaction('keys', 'readonly').objectStore('keys').get('master_key');
				read.onsuccess = () => { db.close(); resolve(read.result); };
				read.onerror = () => { db.close(); reject(read.error); };
			};
		});
		async function decrypt(encrypted: unknown): Promise<string | null> {
			if (typeof encrypted !== 'string' || encrypted.length === 0) return null;
			const bytes = Uint8Array.from(atob(encrypted), (character) => character.charCodeAt(0));
			const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes.slice(0, 12) }, masterKey, bytes.slice(12));
			return new TextDecoder().decode(plaintext);
		}
		return {
			markdown: await decrypt(draft?.encrypted_draft_md),
			preview: await decrypt(draft?.encrypted_draft_preview),
			draftV: typeof draft?.draft_v === 'number' ? draft.draft_v : null,
		};
	}, { apiEndpoint: apiUrl, targetChatId: chatId });
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

async function expectIdeaBucketDraftMarkers(page: any, chatId: string, expectedText: string | null): Promise<void> {
	const item = expectedText
		? await locateDraftInSidebarOrSearch(page, chatId, expectedText).catch(() => null)
		: null;
	if (item) {
		await expect(item).toBeVisible({ timeout: 5_000 });
		const sidebarItem = chatItem(page, chatId);
		const searchItem = page.locator(`[data-testid="search-chat-item"][data-result-id="${chatId}"]`).first();
		const markerHost = (await sidebarItem.isVisible().catch(() => false)) ? sidebarItem : searchItem;
		await expect(markerHost.getByTestId('ideabucket-chat-list-label')).toBeVisible({ timeout: 15_000 });
		await item.click();
		await closeSearchIfOpen(page);
	} else {
		await openDraftByHash(page, chatId);
	}
	const editor = await activeMessageEditorEditable(page, chatId);
	if (expectedText) {
		try {
			await expect(editor).toContainText(expectedText, { timeout: 45_000 });
		} catch (error) {
			await logDraftOpenDiagnostics(page, chatId, 'IDEABUCKET_WEB_MARKERS', expectedText);
			throw error;
		}
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
	const metadataResult = result.getByTestId('search-metadata-snippet').filter({ hasText: expectedText }).first();
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
	const hash = `#chat-id=${chatId}`;
	await page.goto(`${new URL(page.url()).origin}/${hash}`);
	await page.evaluate((targetHash: string) => {
		window.dispatchEvent(new CustomEvent('processPendingDeepLink', { detail: { hash: targetHash } }));
	}, hash);
}

async function openDraft(page: any, apiUrl: string, chatId: string, expectedText: string, requireRestoredText = false): Promise<any> {
	await openDraftByHash(page, chatId);
	try {
		await activeMessageEditorEditable(page, chatId);
	} catch (error) {
		await logServerDraftDiagnostics(page, apiUrl, chatId, 'CROSS_CLIENT_DRAFT_SYNC_OPEN_EDITOR', expectedText);
		await logDraftOpenDiagnostics(page, chatId, 'CROSS_CLIENT_DRAFT_SYNC_OPEN_EDITOR', expectedText);
		throw error;
	}
	if (!requireRestoredText) return null;
	try {
		await expectLocalDraftMarkdown(page, chatId, expectedText, 'CROSS_CLIENT_DRAFT_SYNC_OPEN');
	} catch (error) {
		await logServerDraftDiagnostics(page, apiUrl, chatId, 'CROSS_CLIENT_DRAFT_SYNC_OPEN', expectedText);
		await logDraftOpenDiagnostics(page, chatId, 'CROSS_CLIENT_DRAFT_SYNC', expectedText);
		throw error;
	}
	return null;
}

export {
	expectBrowserDraftTransportOffline,
	installOfflineWebSocketControl,
	AUDIO_FIXTURE,
	CHAT_DELETION_RECONCILE_TIMEOUT_MS,
	CLI_DRAFT_REFRESH_TIMEOUT_MS,
	activeMessageEditorEditable,
	chatItem,
	cleanupIsolatedCliHome,
	clearBrowserClientState,
	createIsolatedCliHome,
	deriveApiUrl,
	expectCliPairedToBrowserAccount,
	expectIdeaBucketDraftMarkers,
	expectLocalDraftMarkdown,
	expectSearchFindsChat,
	getLastTransientCliFailure,
	installWebSocketFrameTracker,
	logCliCacheDiagnostics,
	logCliRestDraftDiagnostics,
	logDraftOpenDiagnostics,
	logServerDraftDiagnostics,
	messageEditorEditable,
	messageEditorHost,
	messageInputSendButton,
	openDraft,
	openDraftByHash,
	openSidebar,
	pairCli,
	readLocalDraftMarkdown,
	readQueuedDraftChanges,
	readServerDraftWithBrowserKey,
	replaceMessageEditorText,
	resultChatId,
	runCli,
	runCliJson,
	sendCurrentMessageWithE2EHook,
	setIsolatedCliHome,
	waitForDraftDeleteReceipt,
	waitForDraftUpdateReceipt,
};
