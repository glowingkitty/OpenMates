/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Startup Sync Contract Test
 *
 * Guards the bounded startup sync architecture:
 * - Web login must not receive background_message_sync for chats 11-100.
 * - Phase 1b full-content sync is capped to 10 parent chats.
 * - Phase 2 remains metadata-only.
 * - Older chat content still hydrates on demand when needed.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const STARTUP_SYNC_FRAME_TIMEOUT_MS = 30_000;
const STARTUP_SYNC_DIAGNOSTIC_TAIL = 25;

function tail<T>(items: T[]): T[] {
	return items.slice(Math.max(0, items.length - STARTUP_SYNC_DIAGNOSTIC_TAIL));
}

function countTypes(types: string[]): Record<string, number> {
	return types.reduce((counts: Record<string, number>, type) => {
		counts[type] = (counts[type] || 0) + 1;
		return counts;
	}, {});
}

function redactedPageUrl(rawUrl: string): string {
	try {
		const url = new URL(rawUrl);
		if (url.hash) url.hash = '#<redacted>';
		return url.toString();
	} catch {
		return '<unavailable>';
	}
}

function phase2PayloadSummary(payload: any): Record<string, unknown> {
	return {
		chat_count: payload?.chat_count,
		total_chat_count: payload?.total_chat_count,
		chats_length: Array.isArray(payload?.chats) ? payload.chats.length : null,
		deleted_chat_ids_count: Array.isArray(payload?.deleted_chat_ids) ? payload.deleted_chat_ids.length : null,
		phase: payload?.phase
	};
}

async function waitForStartupSyncFrames(
	receivedTypes: string[],
	getDiagnostics: () => Record<string, unknown>
): Promise<void> {
	try {
		await expect.poll(() => ({
			phase1b: receivedTypes.includes('phase_1b_chat_content_ready'),
			phase2: receivedTypes.includes('phase_2_last_20_chats_ready')
		}), {
			timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS,
			message: 'Startup sync should receive Phase 1b content and Phase 2 metadata frames'
		}).toEqual({ phase1b: true, phase2: true });
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new Error(`${message}\nStartup sync diagnostics: ${JSON.stringify(getDiagnostics(), null, 2)}`);
	}
}

async function getLocalChatWithNoMessages(page: any): Promise<string | null> {
	return await page.evaluate(async () => {
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onerror = () => reject(request.error);
			request.onsuccess = () => resolve(request.result);
		});

		try {
			const chats = await new Promise<any[]>((resolve, reject) => {
				const tx = db.transaction(['chats'], 'readonly');
				const request = tx.objectStore('chats').getAll();
				request.onerror = () => reject(request.error);
				request.onsuccess = () => resolve(request.result || []);
			});

			for (const chat of chats) {
				const chatId = chat.chat_id || chat.id;
				if (!chatId || chatId.startsWith('demo-') || chatId.startsWith('legal-')) continue;

				const messageCount = await new Promise<number>((resolve, reject) => {
					const tx = db.transaction(['messages'], 'readonly');
					const index = tx.objectStore('messages').index('chat_id');
					const request = index.count(chatId);
					request.onerror = () => reject(request.error);
					request.onsuccess = () => resolve(request.result || 0);
				});

				if (messageCount === 0) return chatId;
			}
			return null;
		} finally {
			db.close();
		}
	});
}

// contract-test: direct surface=gui.web assertions=sync.startup.bounded-phases,sync.phase2.metadata-only
test('startup sync is bounded and older content hydrates on demand', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const receivedTypes: string[] = [];
	const phase1bChatCounts: number[] = [];
	const phase2Payloads: any[] = [];
	const syncStatusPayloads: any[] = [];
	const metadataResponsePayloads: any[] = [];
	const sentTypes: string[] = [];
	const onDemandRequestUrls: string[] = [];
	const consoleErrors: string[] = [];
	const pageErrors: string[] = [];
	const websocketEvents: string[] = [];

	const diagnostics = () => ({
		url: redactedPageUrl(page.url()),
		receivedTypeCounts: countTypes(receivedTypes),
		receivedTypesTail: tail(receivedTypes),
		sentTypeCounts: countTypes(sentTypes),
		sentTypesTail: tail(sentTypes),
		phase1bChatCounts,
		phase2Payloads: phase2Payloads.map(phase2PayloadSummary),
		syncStatusPayloads: tail(syncStatusPayloads),
		metadataResponsePayloads: tail(metadataResponsePayloads),
		consoleErrors: tail(consoleErrors),
		pageErrors: tail(pageErrors),
		websocketEvents: tail(websocketEvents)
	});

	page.on('console', (message: any) => {
		if (!['error', 'warning'].includes(message.type())) return;
		consoleErrors.push(`${message.type()}: ${message.text().slice(0, 500)}`);
	});

	page.on('pageerror', (error: Error) => {
		pageErrors.push((error?.message || String(error)).slice(0, 500));
	});

	page.on('request', (request: any) => {
		const url = request.url();
		if (url.includes('/messages/window')) {
			onDemandRequestUrls.push(url);
		}
	});

	page.on('websocket', (ws: any) => {
		websocketEvents.push('opened');
		ws.on('close', () => websocketEvents.push('closed'));

		ws.on('framesent', (frame: any) => {
			try {
				const parsed = JSON.parse(String(frame.payload));
				const type = parsed?.type || parsed?.event;
				if (type) sentTypes.push(type);
			} catch {
				// Ignore non-JSON frames.
			}
		});

		ws.on('framereceived', (frame: any) => {
			try {
				const parsed = JSON.parse(String(frame.payload));
				const type = parsed?.type || parsed?.event;
				const payload = parsed?.payload ?? parsed;
				if (!type) return;

				receivedTypes.push(type);
				if (type === 'phase_1b_chat_content_ready') {
					phase1bChatCounts.push(payload?.chats?.length || 0);
				}
				if (type === 'phase_2_last_20_chats_ready') {
					phase2Payloads.push(payload);
				}
				if (type === 'sync_status_response') {
					syncStatusPayloads.push({
						is_primed: payload?.is_primed,
						chat_count: payload?.chat_count,
						timestamp: payload?.timestamp
					});
				}
				if (type === 'sync_metadata_chats_response' || type === 'sync_metadata_chats_error') {
					metadataResponsePayloads.push({
						type,
						chat_count: Array.isArray(payload?.chats) ? payload.chats.length : null,
						total_count: payload?.total_count,
						error: typeof payload?.error === 'string' ? payload.error.slice(0, 300) : null
					});
				}
			} catch {
				// Ignore non-JSON frames.
			}
		});
	});

	await loginToTestAccount(page);
	await waitForStartupSyncFrames(receivedTypes, diagnostics);

	expect(receivedTypes).toContain('phase_1b_chat_content_ready');
	expect(receivedTypes).toContain('phase_2_last_20_chats_ready');
	expect(receivedTypes).not.toContain('background_message_sync');
	expect(Math.max(...phase1bChatCounts)).toBeLessThanOrEqual(10);

	for (const payload of phase2Payloads) {
		expect(payload?.chat_count).toBe((payload?.chats || []).length);
		expect(payload?.embeds).toBeUndefined();
		expect(payload?.embed_keys).toBeUndefined();
		expect(payload?.code_run_outputs).toBeUndefined();
		for (const chatWrapper of payload?.chats || []) {
			expect(chatWrapper?.messages).toBeUndefined();
			expect(chatWrapper?.compression_checkpoints).toBeUndefined();
		}
	}

	const metadataOnlyChatId = await getLocalChatWithNoMessages(page);
	if (!metadataOnlyChatId) {
		console.log('No local metadata-only chat found; startup sync boundary verified, skipping hydration check.');
		return;
	}

	const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || new URL(page.url()).origin;
	await page.goto(`${baseUrl}/#chat-id=${metadataOnlyChatId}`);

	await expect.poll(() => {
		const expectedRestPath = `/v1/chats/${encodeURIComponent(metadataOnlyChatId)}/messages/window`;
		return sentTypes.includes('request_chat_content_batch') ||
			onDemandRequestUrls.some((url) => url.includes(expectedRestPath));
	}, {
		timeout: 15000,
		message: 'Opening metadata-only chat should request on-demand content hydration'
	}).toBe(true);
});
