/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Regression coverage for cold-boot chat sync recovery.
 * Recreates the production failure mode where iOS Safari/PWA has an empty local
 * chats IndexedDB while the server still has chats but Redis cache reports
 * `is_primed=false`. The UI must keep sync pending instead of finalizing an
 * empty chat list as the user's real state.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function clearLocalChatIndexedDb(page: any): Promise<void> {
	await page.evaluate(async () => {
		await new Promise<void>((resolve, reject) => {
			const request = indexedDB.open('chats_db');

			request.onerror = () => reject(request.error ?? new Error('Failed to open chats_db'));
			request.onsuccess = () => {
				const db = request.result;
				const storesToClear = [
					'chats',
					'messages',
					'embeds',
					'embed_keys',
					'new_chat_suggestions',
					'daily_inspirations'
				].filter((storeName) => db.objectStoreNames.contains(storeName));

				if (storesToClear.length === 0) {
					db.close();
					resolve();
					return;
				}

				const transaction = db.transaction(storesToClear, 'readwrite');
				transaction.onerror = () => {
					db.close();
					reject(transaction.error ?? new Error('Failed to clear local chat stores'));
				};
				transaction.oncomplete = () => {
					db.close();
					resolve();
				};

				for (const storeName of storesToClear) {
					transaction.objectStore(storeName).clear();
				}
			};
		});
	});
}

async function expectLocalChatsCleared(page: any): Promise<void> {
	const chatCount = await page.evaluate(async () => {
		return await new Promise<number>((resolve, reject) => {
			const request = indexedDB.open('chats_db');

			request.onerror = () => reject(request.error ?? new Error('Failed to open chats_db'));
			request.onsuccess = () => {
				const db = request.result;
				if (!db.objectStoreNames.contains('chats')) {
					db.close();
					resolve(0);
					return;
				}

				const transaction = db.transaction(['chats'], 'readonly');
				const countRequest = transaction.objectStore('chats').count();
				countRequest.onerror = () => {
					db.close();
					reject(countRequest.error ?? new Error('Failed to count local chats'));
				};
				countRequest.onsuccess = () => {
					db.close();
					resolve(countRequest.result);
				};
			};
		});
	});

	expect(chatCount).toBe(0);
}

async function replaceLocalChatDbWithMissingStores(page: any): Promise<void> {
	const prepUrl = `${new URL(getE2EDebugUrl('/')).origin}/e2e-indexeddb-prep`;
	await page.route(prepUrl, (route: any) =>
		route.fulfill({
			contentType: 'text/html',
			body: '<!doctype html><title>prepare missing stores</title>'
		})
	);
	await page.goto(prepUrl);
	await page.unroute(prepUrl);

	await page.evaluate(async () => {
		await new Promise<void>((resolve, reject) => {
			const deleteRequest = indexedDB.deleteDatabase('chats_db');
			deleteRequest.onerror = () =>
				reject(deleteRequest.error ?? new Error('Failed to delete chats_db'));
			deleteRequest.onblocked = () => reject(new Error('Deleting chats_db was blocked'));
			deleteRequest.onsuccess = () => resolve();
		});

		await new Promise<void>((resolve, reject) => {
			const request = indexedDB.open('chats_db', 24);
			request.onerror = () =>
				reject(request.error ?? new Error('Failed to create partial chats_db'));
			request.onupgradeneeded = () => {
				const db = request.result;
				if (!db.objectStoreNames.contains('chats')) {
					const chatStore = db.createObjectStore('chats', { keyPath: 'chat_id' });
					chatStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', {
						unique: false
					});
					chatStore.createIndex('updated_at', 'updated_at', { unique: false });
					chatStore.createIndex('pinned', 'pinned', { unique: false });
				}
				if (!db.objectStoreNames.contains('messages')) {
					const messageStore = db.createObjectStore('messages', { keyPath: 'message_id' });
					messageStore.createIndex('chat_id_created_at', ['chat_id', 'created_at'], {
						unique: false
					});
					messageStore.createIndex('chat_id', 'chat_id', { unique: false });
					messageStore.createIndex('created_at', 'created_at', { unique: false });
				}
			};
			request.onsuccess = () => {
				request.result.close();
				resolve();
			};
		});
	});
}

async function installColdCacheWebSocketInterceptor(page: any): Promise<void> {
	await page.context().addInitScript(() => {
		const OriginalWebSocket = window.WebSocket;

		function ColdCacheWebSocket(this: WebSocket, ...args: ConstructorParameters<typeof WebSocket>) {
			const socket = new OriginalWebSocket(...args);
			let currentMessageHandler: ((this: WebSocket, ev: MessageEvent) => any) | null = null;

			Object.defineProperty(socket, 'onmessage', {
				configurable: true,
				get() {
					return currentMessageHandler;
				},
				set(handler: ((this: WebSocket, ev: MessageEvent) => any) | null) {
					currentMessageHandler = handler;
					if (!handler) {
						return;
					}

					socket.addEventListener('message', (event: MessageEvent) => {
						let parsed: any;
						try {
							parsed = JSON.parse(String(event.data));
						} catch {
							handler.call(socket, event);
							return;
						}

						const messageType = parsed?.type ?? parsed?.event;
						const blockedSyncPayloadTypes = new Set([
							'initial_sync_response',
							'cache_primed',
							'phase_1_last_chat_ready',
							'phase_1b_chat_content_ready',
							'phase_2_last_20_chats_ready',
							'background_message_sync',
							'phase_3_last_100_chats_ready',
							'chat_content_batch_response',
							'load_more_chats_response',
							'sync_metadata_chats_response',
							'phased_sync_complete'
						]);

						if (blockedSyncPayloadTypes.has(messageType)) {
							return;
						}

						if (messageType === 'sync_status_response' || messageType === 'cache_status_response') {
							const coldCacheMessage = {
								...parsed,
								is_primed: false,
								chat_count: 1,
								timestamp: Math.floor(Date.now() / 1000),
								payload: {
									...(parsed.payload ?? {}),
									is_primed: false,
									chat_count: 1,
									timestamp: Math.floor(Date.now() / 1000)
								}
							};
							handler.call(
								socket,
								new MessageEvent('message', { data: JSON.stringify(coldCacheMessage) })
							);
							return;
						}

						handler.call(socket, event);
					});
				}
			});

			return socket;
		}

		Object.setPrototypeOf(ColdCacheWebSocket, OriginalWebSocket);
		ColdCacheWebSocket.prototype = OriginalWebSocket.prototype;

		Object.defineProperty(window, 'WebSocket', {
			configurable: true,
			writable: true,
			value: ColdCacheWebSocket as typeof WebSocket
		});
	});
}

async function installEmptyChatDbOnBoot(page: any): Promise<void> {
	await page.context().addInitScript(() => {
		window.addEventListener(
			'DOMContentLoaded',
			() => {
				void new Promise<void>((resolve, reject) => {
					const request = indexedDB.open('chats_db');

					request.onerror = () => reject(request.error ?? new Error('Failed to open chats_db'));
					request.onsuccess = () => {
						const db = request.result;
						const storesToClear = [
							'chats',
							'messages',
							'embeds',
							'embed_keys',
							'new_chat_suggestions',
							'daily_inspirations'
						].filter((storeName) => db.objectStoreNames.contains(storeName));

						if (storesToClear.length === 0) {
							db.close();
							resolve();
							return;
						}

						const transaction = db.transaction(storesToClear, 'readwrite');
						transaction.onerror = () => {
							db.close();
							reject(transaction.error ?? new Error('Failed to clear local chat stores'));
						};
						transaction.oncomplete = () => {
							db.close();
							resolve();
						};

						for (const storeName of storesToClear) {
							transaction.objectStore(storeName).clear();
						}
					};
				});
			},
			{ once: true }
		);
	});
}

async function ensureSidebarOpen(page: any): Promise<void> {
	const activityHistory = page.getByTestId('activity-history-wrapper');
	if (await activityHistory.isVisible().catch(() => false)) return;

	const menuToggle = page.getByTestId('sidebar-toggle');
	await expect(menuToggle).toBeVisible({ timeout: 10000 });
	await menuToggle.click();
	await expect(activityHistory).toBeVisible({ timeout: 15000 });
}

test('empty local IndexedDB with cold server cache keeps sync pending instead of finalizing no chats', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('CHAT_SYNC_EMPTY_IDB_RECOVERY');
	const consoleLogs: string[] = [];
	page.on('console', (message: any) => {
		consoleLogs.push(`[${message.type()}] ${message.text()}`);
	});

	await installColdCacheWebSocketInterceptor(page);
	await loginToTestAccount(page, logCheckpoint, async () => undefined, { waitForEditor: true });
	await installEmptyChatDbOnBoot(page);

	await page.goto(getE2EDebugUrl('/?empty-idb-recovery=1'));
	await page.waitForLoadState('load');
	expect(await page.evaluate(() => window.WebSocket.name)).toBe('ColdCacheWebSocket');
	await clearLocalChatIndexedDb(page);
	await expectLocalChatsCleared(page);
	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });

	await ensureSidebarOpen(page);
	const syncingIndicator = page.getByTestId('syncing-indicator');
	await expect(syncingIndicator).toBeVisible({ timeout: 15000 });

	// Old behavior reached the retry limit after ~30s, dispatched a synthetic
	// phasedSyncComplete event, and hid the syncing indicator despite server chats.
	await page.waitForTimeout(35000);

	await expect(syncingIndicator).toBeVisible({ timeout: 5000 });
	expect(
		consoleLogs.some((entry) =>
			entry.includes('Dispatching synthetic phasedSyncComplete event (reason: timeout)')
		)
	).toBe(false);
	expect(
		consoleLogs.some(
			(entry) => entry.includes('Keeping sync pending') || entry.includes('keeping sync pending')
		)
	).toBe(true);
});

test('partial local IndexedDB schema is healed before authenticated sync starts', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('CHAT_SYNC_MISSING_STORE_RECOVERY');
	const consoleLogs: string[] = [];
	page.on('console', (message: any) => {
		consoleLogs.push(`[${message.type()}] ${message.text()}`);
	});

	await loginToTestAccount(page, logCheckpoint, async () => undefined, { waitForEditor: true });
	await replaceLocalChatDbWithMissingStores(page);

	await page.goto(getE2EDebugUrl('/?missing-store-recovery=1'));
	await page.waitForLoadState('load');
	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });
	await ensureSidebarOpen(page);

	await expect(async () => {
		const hasMissingStoreError = consoleLogs.some(
			(entry) =>
				entry.includes('One of the specified object stores was not found') ||
				entry.includes('NotFoundError')
		);
		expect(hasMissingStoreError).toBe(false);

		const storeNames = await page.evaluate(async () => {
			return await new Promise<string[]>((resolve, reject) => {
				const request = indexedDB.open('chats_db');
				request.onerror = () =>
					reject(request.error ?? new Error('Failed to open healed chats_db'));
				request.onsuccess = () => {
					const db = request.result;
					const names = Array.from(db.objectStoreNames);
					db.close();
					resolve(names);
				};
			});
		});

		expect(storeNames).toContain('pending_embed_operations');
		expect(storeNames).toContain('embed_diffs');
		expect(storeNames).toContain('daily_inspirations');
	}).toPass({ timeout: 30000, intervals: [1000, 2000, 5000] });
});
