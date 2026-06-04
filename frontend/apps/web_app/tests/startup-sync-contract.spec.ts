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

async function waitForSyncComplete(page: any): Promise<void> {
	const syncingIndicator = page.getByTestId('syncing-indicator');
	try {
		await expect(syncingIndicator).not.toBeVisible({ timeout: 30000 });
	} catch {
		console.log('WARNING: Syncing indicator still visible after 30s; continuing with captured events.');
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

test('startup sync is bounded and older content hydrates on demand', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const receivedTypes: string[] = [];
	const phase1bChatCounts: number[] = [];
	const phase2Payloads: any[] = [];
	const sentTypes: string[] = [];

	page.on('websocket', (ws: any) => {
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
			} catch {
				// Ignore non-JSON frames.
			}
		});
	});

	await loginToTestAccount(page);
	await waitForSyncComplete(page);
	await page.waitForTimeout(3000);

	expect(receivedTypes).toContain('phase_1b_chat_content_ready');
	expect(receivedTypes).toContain('phase_2_last_20_chats_ready');
	expect(receivedTypes).not.toContain('background_message_sync');
	expect(Math.max(...phase1bChatCounts)).toBeLessThanOrEqual(10);

	for (const payload of phase2Payloads) {
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

	await expect.poll(() => sentTypes.includes('request_chat_content_batch'), {
		timeout: 15000,
		message: 'Opening metadata-only chat should request on-demand content hydration'
	}).toBe(true);
});
