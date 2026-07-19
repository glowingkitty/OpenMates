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
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

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
		OPENMATES_API_URL: apiUrl,
		NODE_PATH: path.join(cliDir, 'node_modules'),
		TERM: 'dumb'
	};
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

async function runCliJson(apiUrl: string, args: string[], timeoutMs = 60_000): Promise<any> {
	const command = args.slice(0, 2).join(' ');
	let result: { code: number | null; stdout: string; stderr: string } | null = null;
	for (let attempt = 0; attempt < 6; attempt += 1) {
		result = await runCli(apiUrl, [...args, '--json'], timeoutMs);
		if (result.code === 0) return JSON.parse(result.stdout);
		const transientNetworkError = /fetch failed|ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENOTFOUND/i.test(result.stderr);
		if (!transientNetworkError || attempt === 5) break;
		await new Promise((resolve) => setTimeout(resolve, 1_500 * (attempt + 1)));
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

async function replaceMessageEditorText(page: any, chatId: string, text: string): Promise<any> {
	const host = messageEditorHost(page, chatId);
	const editor = messageEditorEditable(page, chatId);
	await expect(host).toBeVisible({ timeout: 15_000 });
	await expect(editor).toBeVisible({ timeout: 15_000 });
	await host.click();
	await page.keyboard.press('ControlOrMeta+A');
	await page.keyboard.press('ControlOrMeta+A');
	await page.keyboard.press('Backspace');
	if (text.length > 0) {
		await page.keyboard.type(text, { delay: 5 });
		const activeEditor = messageEditorEditable(page);
		await expect(activeEditor).toContainText(text, { timeout: 10_000 });
		return activeEditor;
	}
	return editor;
}

async function logDraftOpenDiagnostics(page: any, chatId: string, label: string, expectedText?: string): Promise<void> {
	const diagnostics = await page.evaluate(async ({ targetChatId, expected }: { targetChatId: string; expected?: string }) => {
		async function readIdbValue<T>(dbName: string, storeName: string, key: IDBValidKey): Promise<T | null> {
			return new Promise((resolve) => {
				const request = indexedDB.open(dbName);
				request.onerror = () => resolve(null);
				request.onsuccess = () => {
					const db = request.result;
					try {
						const transaction = db.transaction(storeName, 'readonly');
						const store = transaction.objectStore(storeName);
						const getRequest = store.get(key);
						getRequest.onerror = () => resolve(null);
						getRequest.onsuccess = () => resolve((getRequest.result as T | undefined) ?? null);
					} catch {
						resolve(null);
					} finally {
						db.close();
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

async function readLocalDraftMarkdown(page: any, chatId: string): Promise<{ markdown: string | null; draftV: number | null }> {
	return page.evaluate(async (targetChatId: string) => {
		async function readIdbValue<T>(dbName: string, storeName: string, key: IDBValidKey): Promise<T | null> {
			return new Promise((resolve) => {
				const request = indexedDB.open(dbName);
				request.onerror = () => resolve(null);
				request.onsuccess = () => {
					const db = request.result;
					try {
						const transaction = db.transaction(storeName, 'readonly');
						const store = transaction.objectStore(storeName);
						const getRequest = store.get(key);
						getRequest.onerror = () => resolve(null);
						getRequest.onsuccess = () => resolve((getRequest.result as T | undefined) ?? null);
					} catch {
						resolve(null);
					} finally {
						db.close();
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

async function expectLocalDraftMarkdown(page: any, chatId: string, expectedText: string, label: string): Promise<void> {
	try {
		await expect
			.poll(async () => (await readLocalDraftMarkdown(page, chatId)).markdown ?? '', {
				timeout: 15_000,
				intervals: [500, 1_000]
			})
			.toBe(expectedText);
	} catch (error) {
		await logDraftOpenDiagnostics(page, chatId, `${label}_LOCAL_DRAFT_AFTER_EDIT`, expectedText);
		throw error;
	}
}

function resultChatId(result: any): string {
	const chatId = String(result.chatId ?? result.chat_id ?? '');
	expect(chatId).toMatch(/^[0-9a-f-]{36}$/i);
	return chatId;
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
		await expect(editor).toContainText(expectedText, { timeout: 15_000 });
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

async function openDraft(page: any, chatId: string, expectedText: string): Promise<any> {
	const item = await locateDraftInSidebarOrSearch(page, chatId, expectedText).catch(() => null);
	if (item) {
		await expect(item).toContainText(expectedText);
		await item.click();
		await closeSearchIfOpen(page);
	} else {
		await openDraftByHash(page, chatId);
	}
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15_000 });
	try {
		await expect(editor).toContainText(expectedText, { timeout: 15_000 });
	} catch (error) {
		await logDraftOpenDiagnostics(page, chatId, 'CROSS_CLIENT_DRAFT_SYNC', expectedText);
		throw error;
	}
	return item;
}

test.describe('Cross-client encrypted draft sync', () => {
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

		await loginToTestAccount(page, log, screenshot);
		try {
			log('Pairing CLI client.');
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			log('CLI client paired.');
			await page.goto(baseUrl);
			await waitForChatReady(page, log);

			log('Creating draft from CLI.');
			const created = await runCliJson(apiUrl, ['drafts', 'create', initialText]);
			const draftChatId = String(created.chatId);
			expect(draftChatId).toMatch(/^[0-9a-f-]{36}$/i);
			cleanupDraftIds.add(draftChatId);
			await openDraft(page, draftChatId, initialText);
			log('CLI-created draft opened in web client.');

			const editor = await replaceMessageEditorText(page, draftChatId, updatedText);
			await expect(editor).toContainText(updatedText, { timeout: 10_000 });
			await page.getByTestId('input-dismiss-button').click();
			await expectLocalDraftMarkdown(page, draftChatId, updatedText, 'CROSS_CLIENT_DRAFT_SYNC');
			try {
				await expect
					.poll(async () => {
						const draft = (await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'])).draft;
						return `${draft?.draftV ?? 0}:${draft?.markdown ?? ''}`;
					}, {
						timeout: 30_000,
						intervals: [1_000, 2_000]
					})
					.toBe(`${Number(created.draftV) + 1}:${updatedText}`);
			} catch (error) {
				await logDraftOpenDiagnostics(page, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_SERVER_AFTER_EDIT', updatedText);
				throw error;
			}
			log('Web draft edit reconciled to CLI.');

			await replaceMessageEditorText(page, draftChatId, '');
			log('Web draft emptied; waiting for CLI reconciliation.');
			await expect
				.poll(async () => (await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'])).draft, {
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
			await openDraft(page, sentChatId, sentText);
			await editor.click();
			const sendButton = page.locator('[data-action="send-message"]');
			await expect(sendButton).toBeVisible({ timeout: 15_000 });
			await sendButton.click();
			await expect(page.getByTestId('message-user').last()).toContainText(sentText, { timeout: 30_000 });
			await expect
				.poll(async () => (await runCliJson(apiUrl, ['drafts', 'get', sentChatId, '--refresh'])).draft, {
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

		await loginToTestAccount(page, log, screenshot);
		try {
			log('Pairing CLI client for IdeaBucket web coverage.');
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
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

			const editor = await replaceMessageEditorText(page, draftChatId, editedDraftText);
			await expect(editor).toContainText(editedDraftText, { timeout: 10_000 });
			await page.getByTestId('input-dismiss-button').click();
			await expectLocalDraftMarkdown(page, draftChatId, editedDraftText, 'IDEABUCKET_WEB_MARKERS');
			try {
				await expect
					.poll(async () => {
						const currentDraft = (await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'])).draft;
						return currentDraft?.markdown ?? '';
					}, {
						timeout: 60_000,
						intervals: [1_000, 2_000]
					})
					.toBe(editedDraftText);
			} catch (error) {
				await logDraftOpenDiagnostics(page, draftChatId, 'IDEABUCKET_WEB_MARKERS_SERVER_AFTER_EDIT', editedDraftText);
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
		}
	});
});
