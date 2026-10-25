/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Startup Sync Contract Test
 *
 * Guards the bounded startup sync architecture:
 * - Web login must not receive background_message_sync for parents outside the first 20.
 * - Phase 1b full-content sync is capped to 20 parent chats; child content stays on demand.
 * - Phase 2 remains metadata-only.
 * - Older chat content still hydrates on demand when needed.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { createStartupEvidence, persistedCounts } = require('./helpers/startup-performance-evidence.cjs');
const { createBrowserProcessEvidence, assessObservation } = require('./helpers/browser-process-evidence.cjs');
const { installResourceTimingCapture, browserResourceSnapshot, resourceEvidence, performanceAttachment, provenance, routeSelectionSha256 } = require('./helpers/performance-evidence.cjs');
const { dismissSecurityReminderIfPresent, loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const STARTUP_SYNC_FRAME_TIMEOUT_MS = 30_000;
const STARTUP_SYNC_DIAGNOSTIC_TAIL = 25;
const LOCAL_CHAT_SHELL_TIMEOUT_MS = 1_500;
const LOCAL_SHORT_WINDOW_TARGET_COUNT = 4;
const PROOF_VIDEO_STATE_HOLD_MS = process.env.PLAYWRIGHT_VIDEO_WIDTH ? 4_000 : 0;

async function holdProofVideoState(page: any): Promise<void> {
	if (PROOF_VIDEO_STATE_HOLD_MS > 0) await page.waitForTimeout(PROOF_VIDEO_STATE_HOLD_MS);
}

async function expectLoadingBelowHeader(page: any): Promise<void> {
	const header = page.getByTestId('chat-header-banner');
	const loading = page.getByTestId('active-chat-history-loading');
	await expect.poll(async () => {
		const [headerBox, loadingBox] = await Promise.all([header.boundingBox(), loading.boundingBox()]);
		if (!headerBox || !loadingBox) return Number.NEGATIVE_INFINITY;
		return loadingBox.y - (headerBox.y + headerBox.height);
	}, {
		timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS,
		message: 'Selected-chat loading status must remain below the chat header'
	}).toBeGreaterThanOrEqual(8);
}

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

/** Read existing selected-chat metadata/count without manufacturing a cold cache. */
async function readLocalStartupChat(page: any, chatId: string): Promise<{ exists: boolean; messageCount: number }> {
	return page.evaluate(async (id: string) => {
		return new Promise<{ exists: boolean; messageCount: number }>((resolve, reject) => {
			let db: IDBDatabase | null = null;
			let tx: IDBTransaction | null = null;
			let settled = false;
			const finish = (value: { exists: boolean; messageCount: number } | null) => {
				if (settled) return;
				settled = true;
				clearTimeout(timer);
				if (!value) { try { tx?.abort(); } catch { /* already complete */ } }
				db?.close();
				if (value) resolve(value);
				else reject(new Error('Existing startup chat snapshot unavailable'));
			};
			const timer = setTimeout(() => finish(null), 2000);
			const request = indexedDB.open('chats_db');
			request.onupgradeneeded = () => { request.transaction?.abort(); request.result.close(); finish(null); };
			request.onblocked = request.onerror = () => finish(null);
			request.onsuccess = () => {
				db = request.result;
				if (settled) { db.close(); return; }
				db.onversionchange = () => finish(null);
				try {
					tx = db.transaction(['chats', 'messages'], 'readonly');
					const chat = tx.objectStore('chats').get(id);
					const count = tx.objectStore('messages').index('chat_id').count(id);
					tx.oncomplete = () => finish({ exists: Boolean(chat.result), messageCount: count.result });
					tx.onerror = tx.onabort = () => finish(null);
				} catch { finish(null); }
			};
		});
	}, chatId);
}

async function prepareLocalMetadataOnlyChat(page: any, preferredChatId: string | null = null, excludedChatId: string | null = null): Promise<string | null> {
	return await page.evaluate(async ({ targetChatId, excludedChatId }: { targetChatId: string | null; excludedChatId: string | null }) => {
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
			chats.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));

			for (const chat of chats) {
				const chatId = chat.chat_id || chat.id;
				if (!chatId || chatId.startsWith('demo-') || chatId.startsWith('legal-')) continue;
				if (targetChatId && chatId !== targetChatId) continue;
				if (excludedChatId && chatId === excludedChatId) continue;
				if (Number(chat.messages_v || 0) <= 0) continue;
				if (chat.encrypted_draft_md || chat.encrypted_draft_preview) continue;

				const messages = await new Promise<any[]>((resolve, reject) => {
					const tx = db.transaction(['messages'], 'readonly');
					const index = tx.objectStore('messages').index('chat_id');
					const request = index.getAll(chatId);
					request.onerror = () => reject(request.error);
					request.onsuccess = () => resolve(request.result || []);
				});
				if (messages.length > 0) {
					await new Promise<void>((resolve, reject) => {
						const tx = db.transaction(['messages'], 'readwrite');
						const store = tx.objectStore('messages');
						for (const message of messages) store.delete(message.message_id);
						tx.oncomplete = () => resolve();
						tx.onerror = () => reject(tx.error);
						tx.onabort = () => reject(tx.error);
					});
				}
				return chatId;
			}
			return null;
		} finally {
			db.close();
		}
	}, { targetChatId: preferredChatId, excludedChatId });
}

async function getLocalChatSwitchPair(
	page: any,
	trimFirst = true
): Promise<Array<{ chatId: string; messageCount: number }>> {
	return await page.evaluate(async ({ targetCount, trimFirst }: { targetCount: number; trimFirst: boolean }) => {
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
			chats.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));

			const cleanChats: Array<{ chatId: string; messages: any[] }> = [];
			for (const chat of chats) {
				const chatId = chat.chat_id || chat.id;
				if (!chatId || chatId.startsWith('demo-') || chatId.startsWith('legal-')) continue;
				if (Number(chat.messages_v || 0) <= 0) continue;
				if (chat.encrypted_draft_md || chat.encrypted_draft_preview) continue;

				const messages = await new Promise<any[]>((resolve, reject) => {
					const tx = db.transaction(['messages'], 'readonly');
					const index = tx.objectStore('messages').index('chat_id');
					const request = index.getAll(chatId);
					request.onerror = () => reject(request.error);
					request.onsuccess = () => resolve(request.result || []);
				});
				if (messages.length === 0) continue;
				// The shared-owner fixture has one message and may tie for newest at
				// second-granularity timestamps. Prove that the short-chat source
				// really cached four messages before trimming its local window.
				if (trimFirst && cleanChats.length === 0 && messages.length < targetCount) continue;
				messages.sort((a, b) => Number(a.created_at || 0) - Number(b.created_at || 0));
				cleanChats.push({ chatId, messages });
				if (cleanChats.length >= 2) break;
			}
			if (cleanChats.length < 2) return [];

			const [firstChat, secondChat] = cleanChats;
			const messagesToDelete = trimFirst
				? firstChat.messages.slice(0, Math.max(0, firstChat.messages.length - targetCount))
				: [];
			if (messagesToDelete.length > 0) {
				await new Promise<void>((resolve, reject) => {
					const tx = db.transaction(['messages'], 'readwrite');
					const store = tx.objectStore('messages');
					for (const message of messagesToDelete) store.delete(message.message_id);
					tx.oncomplete = () => resolve();
					tx.onerror = () => reject(tx.error);
					tx.onabort = () => reject(tx.error);
				});
			}
			return [
				{ chatId: firstChat.chatId, messageCount: trimFirst ? Math.min(firstChat.messages.length, targetCount) : firstChat.messages.length },
				{ chatId: secondChat.chatId, messageCount: secondChat.messages.length }
			];
		} finally {
			db.close();
		}
	}, { targetCount: LOCAL_SHORT_WINDOW_TARGET_COUNT, trimFirst });
}

async function verifyCachedShortChatOpening(page: any): Promise<void> {
	await waitForChatReady(page, undefined, 60000);

	let localChats: Array<{ chatId: string; messageCount: number }> = [];
	await expect.poll(async () => {
		localChats = await getLocalChatSwitchPair(page);
		return localChats.length;
	}, {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS,
		message: 'Startup sync should cache a short chat plus another navigation target'
	}).toBeGreaterThanOrEqual(2);
	const [firstLocalChat, secondLocalChat] = localChats;
	expect(firstLocalChat.messageCount, 'fixture short chat retains a bounded local window').toBe(LOCAL_SHORT_WINDOW_TARGET_COUNT);
	expect(secondLocalChat.messageCount, 'second warm chat retains its persisted messages').toBeGreaterThan(0);

	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible({ timeout: 1000 }).catch(() => false)) {
		await newChatButton.click();
	}
	await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 10000 });

	const windowRoute = `**/v1/chats/${encodeURIComponent(firstLocalChat.chatId)}/messages/window**`;
	let releaseRepair: () => void = () => undefined;
	const repairGate = new Promise<void>((resolve) => {
		releaseRepair = resolve;
	});
	let repairRequested = false;
	let repairReleased = false;
	let finishRepair: () => void = () => undefined;
	const repairFinished = new Promise<void>((resolve) => {
		finishRepair = resolve;
	});
	const delayRepairResponse = async (route: any) => {
		repairRequested = true;
		try {
			const realResponse = await route.fetch();
			await repairGate;
			await route.fulfill({ response: realResponse });
		} finally {
			finishRepair();
		}
	};
	await page.route(windowRoute, delayRepairResponse, { times: 1 });

	try {
		await page.evaluate((chatId: string) => {
			window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
		}, firstLocalChat.chatId);

		await expect.poll(() => repairRequested, {
			timeout: 10000,
			message: 'Opening a cached short chat should start background completeness repair'
		}).toBe(true);

		await expect(page.getByTestId('welcome-content')).not.toBeVisible({
			timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS
		});
		await expect(page.getByTestId('chat-header-banner')).toBeVisible({
			timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS
		});
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute(
			'data-current-chat-id',
			firstLocalChat.chatId,
			{ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS }
		);
		await expect.poll(async () =>
			Number(await page.getByTestId('active-chat-container').getAttribute('data-current-message-count') || 0),
		{
			timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS,
			message: 'The bounded local message window should render before repair completes'
		}).toBeGreaterThan(0);
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-message-chat-consistent', 'true');
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-message-ids-unique', 'true');
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-message-order-valid', 'true');
		await holdProofVideoState(page);

		await page.evaluate((chatId: string) => {
			window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
		}, secondLocalChat.chatId);
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute(
			'data-current-chat-id',
			secondLocalChat.chatId,
			{ timeout: 10000 }
		);

		repairReleased = true;
		releaseRepair();
		await repairFinished;
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', secondLocalChat.chatId);
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-message-chat-consistent', 'true');
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-message-ids-unique', 'true');
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-message-order-valid', 'true');
		await holdProofVideoState(page);

	} finally {
		if (!repairReleased) releaseRepair();
		if (repairRequested) await repairFinished;
		await page.unroute(windowRoute, delayRepairResponse);
	}
}

/** Keep both selected-chat stores locked so a revisit cannot read local metadata or messages. */
async function holdSelectedChatStoreReads(page: any): Promise<void> {
	await page.evaluate(async () => {
		const testWindow = window as typeof window & {
			__releaseRecentChatStoreLock?: () => void;
			__recentChatBlockedReadDone?: { chats: boolean; messages: boolean };
		};
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
		});
		const transaction = db.transaction(['chats', 'messages'], 'readwrite');
		const store = transaction.objectStore('chats');
		let held = true;
		const keepAlive = () => {
			if (!held) return;
			const request = store.get('__recent_chat_lock_probe__');
			request.onsuccess = keepAlive;
		};
		keepAlive();
		testWindow.__recentChatBlockedReadDone = { chats: false, messages: false };
		for (const storeName of ['chats', 'messages'] as const) {
			const blockedRead = db.transaction(storeName, 'readonly').objectStore(storeName).get('__recent_chat_blocked_read__');
			blockedRead.onsuccess = () => { testWindow.__recentChatBlockedReadDone![storeName] = true; };
		}
		testWindow.__releaseRecentChatStoreLock = () => { held = false; };
		transaction.oncomplete = () => db.close();
	});
}

async function releaseSelectedChatStoreReads(page: any): Promise<void> {
	await page.evaluate(() => {
		const testWindow = window as typeof window & { __releaseRecentChatStoreLock?: () => void };
		testWindow.__releaseRecentChatStoreLock?.();
		delete testWindow.__releaseRecentChatStoreLock;
	});
}

async function getContinueCarouselState(page: any): Promise<{ visible: boolean; chatIds: string[] }> {
	return await page.evaluate(() => {
		const container = document.querySelector('[data-testid="recent-chats-scroll-container"]') as HTMLElement | null;
		const visible = !!container && container.offsetParent !== null;
		const chatIds = container
			? Array.from(container.querySelectorAll('[data-chat-id]'))
				.map((element) => element.getAttribute('data-chat-id') || '')
				.filter(Boolean)
			: [];
		return { visible, chatIds };
	});
}

type ReconnectSocketObservation = { closed: boolean; phase2Frames: number };

async function observeReconnectSockets(page: any, evidence: any = null): Promise<ReconnectSocketObservation[]> {
	const sockets: ReconnectSocketObservation[] = [];
	page.on('websocket', (socket: any) => {
		if (!socket.url().includes('/v1/ws')) return;
		if (sockets.length === 0) evidence?.begin('startup-transport');
		const observation = { closed: false, phase2Frames: 0 };
		sockets.push(observation);
		socket.on('close', () => { observation.closed = true; });
		socket.on('framereceived', (frame: any) => {
			try {
				const parsed = JSON.parse(String(frame.payload));
				evidence?.recordFrame(frame.payload, parsed);
				if (parsed?.type === 'phase_2_last_20_chats_ready') observation.phase2Frames++;
			} catch { /* Only count real Phase 2 completion frames. */ }
		});
	});
	await page.addInitScript(() => {
		const NativeWebSocket = window.WebSocket;
		const sockets: WebSocket[] = [];
		(window as typeof window & { __reconnectSockets?: WebSocket[] }).__reconnectSockets = sockets;
		window.WebSocket = class extends NativeWebSocket {
			constructor(url: string | URL, protocols?: string | string[]) {
				super(url, protocols);
				if (String(url).includes('/v1/ws')) sockets.push(this);
			}
		};
	});
	return sockets;
}

async function verifyContinueCarouselSurvivesReconnectChurn(page: any, sockets: ReconnectSocketObservation[], evidence: any = null): Promise<void> {
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible({ timeout: 1000 }).catch(() => false)) {
		await newChatButton.click();
	}
	await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS });

	const initialState = await getContinueCarouselState(page);
	expect(initialState.chatIds.length, 'test account needs at least one continue card for carousel stability coverage').toBeGreaterThan(0);

	// The authenticated carousel must fit in the real pane below the banner.
	for (const size of [{ width: 390, height: 844, large: false }, { width: 1366, height: 700, large: false }, { width: 1366, height: 1032, large: true }]) {
		await page.setViewportSize({ width: size.width, height: size.height });
		const carouselElement = page.getByTestId('recent-chats-scroll-container');
		const card = carouselElement.locator(size.large
			? '.resume-chat-large-card, .saved-embed-continue-preview'
			: '.resume-chat-card').first();
		await expect(card).toBeVisible();
		await expect(carouselElement).toHaveCSS('padding-top', size.large ? '17.5px' : '6px');
		await expect(carouselElement).toHaveCSS('padding-bottom', size.large ? '17px' : '6px');
		const [banner, carousel, input] = await Promise.all([
			page.getByTestId('daily-inspiration-area').boundingBox(),
			page.getByTestId('recent-chats-scroll-container').boundingBox(),
			page.getByTestId('message-input-wrapper').boundingBox(),
		]);
		expect(banner && carousel && input).toBeTruthy();
		expect(carousel!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height - 1);
		expect(carousel!.y + carousel!.height).toBeLessThanOrEqual(input!.y + 1);
	}
	await page.setViewportSize({ width: 1366, height: 900 });

	await expect.poll(() => sockets.some(socket => !socket.closed && socket.phase2Frames > 0), {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS,
		message: 'Initial socket must complete Phase 2 before reconnect coverage'
	}).toBe(true);
	await waitForChatReady(page);
	const previousSocketCount = sockets.length;
	const initialSocket = sockets[previousSocketCount - 1];
	evidence?.begin('established-reconnect');
	await page.evaluate(() => {
		const sockets = (window as typeof window & { __reconnectSockets?: WebSocket[] }).__reconnectSockets || [];
		const active = sockets.filter(socket => socket.readyState === WebSocket.OPEN);
		if (active.length !== 1) throw new Error(`Expected one authenticated open socket, received ${active.length}`);
		active[0].close(1000, 'Synthetic carousel reconnect');
	});
	await expect.poll(() => initialSocket.closed, {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS,
		message: 'The original real WebSocket must close'
	}).toBe(true);

	const samples: Array<{ visible: boolean; count: number }> = [];
	const deadline = Date.now() + 2000;
	while (Date.now() < deadline) {
		const state = await getContinueCarouselState(page);
		samples.push({ visible: state.visible, count: state.chatIds.length });
		await page.waitForTimeout(50);
	}

	const blankSample = samples.find((sample) => !sample.visible || sample.count === 0);
	expect(blankSample, `Continue carousel must not blank during reconnect churn; samples=${JSON.stringify(samples)}`).toBeUndefined();
	await expect.poll(() => sockets.slice(previousSocketCount).some(socket => !socket.closed && socket.phase2Frames > 0), {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS,
		message: 'A replacement real WebSocket must complete metadata delta sync with a nullable legacy version'
	}).toBe(true);
	await waitForChatReady(page);
	await evidence?.end();
}

// contract-test: direct surface=gui.web assertions=chat-navigation.open.local-first-coherent,sync.startup.bounded-phases,sync.phase2.metadata-only,chats.persistence.client-encrypted,chats.message.identity-idempotent
test('startup sync is bounded and older content hydrates on demand', async ({ page, context }: { page: any; context: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const startupEvidence = await createStartupEvidence(page);
	let startupSocketObserved = false;
	const receivedTypes: string[] = [];
	const phase1bChatCounts: number[] = [];
	const phase1Metadata: any[] = [];
	const onDemandBatchChatIds: string[] = [];
	const phase1bMessageWindows: Array<{ count: number; bytes: number; hasMoreBefore: boolean; startCursor: any; serverCount: number }> = [];
	const phase1bAuxWindows: Array<{ chatIds: string[]; codeWindows: any; notebookWindows: any; wrapperWindows: any; embedKeyWindows: any; codeOutputs: any[]; notebookOutputs: any[]; wrappers: any[] }> = [];
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
		phase1bMessageWindows,
		phase1bAuxWindows,
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
		const isAppSocket = ws.url().includes('/v1/ws');
		if (isAppSocket && !startupSocketObserved) { startupEvidence.begin('startup-transport'); startupSocketObserved = true; }
		websocketEvents.push('opened');
		ws.on('close', () => websocketEvents.push('closed'));

		ws.on('framesent', (frame: any) => {
			try {
				const parsed = JSON.parse(String(frame.payload));
				const type = parsed?.type || parsed?.event;
				if (type) sentTypes.push(type);
				if (type === 'request_chat_content_batch') {
					onDemandBatchChatIds.push(...(parsed?.payload?.chat_ids || []));
				}
			} catch {
				// Ignore non-JSON frames.
			}
		});

		ws.on('framereceived', (frame: any) => {
			try {
				const parsed = JSON.parse(String(frame.payload));
				if (isAppSocket) startupEvidence.recordFrame(frame.payload, parsed);
				const type = parsed?.type || parsed?.event;
				const payload = parsed?.payload ?? parsed;
				if (!type || !isAppSocket) return;

				receivedTypes.push(type);
				if (type === 'phase_1_last_chat_ready') {
					if (payload?.chat_details) phase1Metadata.push(payload.chat_details);
					phase1Metadata.push(...(payload?.recent_chat_metadata || []));
				}
				if (type === 'phase_1b_chat_content_ready') {
					phase1bChatCounts.push(payload?.chats?.length || 0);
					phase1bAuxWindows.push({
						chatIds: (payload?.chats || []).map((chat: any) => chat.chat_id),
						codeWindows: payload?.code_run_output_windows_by_chat_id,
						notebookWindows: payload?.notebook_run_output_windows_by_chat_id,
						wrapperWindows: payload?.chat_key_wrapper_windows_by_chat_id,
						embedKeyWindows: payload?.embed_key_windows_by_chat_id,
						codeOutputs: payload?.code_run_outputs || [],
						notebookOutputs: payload?.notebook_run_outputs || [],
						wrappers: payload?.chat_key_wrappers || []
					});
					for (const chat of payload?.chats || []) {
						if (!Array.isArray(chat?.messages)) continue;
						phase1bMessageWindows.push({
							count: chat.messages.length,
							bytes: chat.messages.reduce((total: number, message: any) =>
								total + new TextEncoder().encode(typeof message === 'string' ? message : JSON.stringify(message)).length, 0),
							hasMoreBefore: chat.message_window?.has_more_before,
							startCursor: chat.message_window?.start_cursor,
							serverCount: chat.server_message_count
						});
					}
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
	await dismissSecurityReminderIfPresent(page);
	await waitForStartupSyncFrames(receivedTypes, diagnostics);
	await startupEvidence.snapshotPhaseReceipts();
	await waitForChatReady(page);
	await startupEvidence.end();
	await startupEvidence.attach(testInfo);

	expect(receivedTypes).toContain('phase_1b_chat_content_ready');
	expect(receivedTypes).toContain('phase_2_last_20_chats_ready');
	expect(receivedTypes).not.toContain('background_message_sync');
	expect(phase1bChatCounts.length).toBeGreaterThan(0);
	for (const count of phase1bChatCounts) expect(count).toBe(20);
	const startupContentIds = new Set<string>(phase1bAuxWindows.flatMap(frame => frame.chatIds));
	expect(startupContentIds.size, 'Cold startup must deliver exactly 20 distinct parent content IDs').toBe(20);
	for (const frame of phase1bAuxWindows) expect(new Set(frame.chatIds).size).toBe(frame.chatIds.length);
	const metadata = new Map<string, any>([
		...phase1Metadata,
		...phase2Payloads.flatMap(payload => (payload?.chats || []).map((wrapper: any) => wrapper.chat_details))
	].filter(Boolean).map(chat => [chat.id || chat.chat_id, chat]));
	expect([...metadata.values()].filter(chat => !chat.parent_id && !chat.is_sub_chat)).toHaveLength(23);
	for (const id of startupContentIds) {
		expect(metadata.has(id)).toBe(true);
		expect(metadata.get(id)?.parent_id).toBeFalsy();
		expect(metadata.get(id)?.is_sub_chat).toBeFalsy();
	}
	const children = [...metadata.values()].filter(chat => chat.parent_id && chat.is_sub_chat);
	expect(children, 'Recent parent must carry its real encrypted child metadata').toHaveLength(1);
	const childId = children[0].id || children[0].chat_id;
	expect(startupContentIds.has(children[0].parent_id)).toBe(true);
	expect(startupContentIds.has(childId), 'Child metadata must not opt in child startup message content').toBe(false);
	expect(await readLocalStartupChat(page, childId)).toEqual({ exists: true, messageCount: 0 });
	expect(phase1bMessageWindows.length).toBe(phase1bChatCounts.reduce((sum, count) => sum + count, 0));
	for (const window of phase1bMessageWindows) {
		expect(window.count).toBeGreaterThan(0);
		expect(window.count).toBeLessThanOrEqual(20);
		expect(window.bytes).toBeLessThanOrEqual(256 * 1024);
		if (window.serverCount > window.count) {
			expect(window.hasMoreBefore).toBe(true);
			if (window.count > 0) expect(window.startCursor?.message_id).toBeTruthy();
		}
	}
	for (const frame of phase1bAuxWindows) {
		for (const chatId of frame.chatIds) {
			expect(frame.codeWindows?.[chatId]?.has_more_before).toEqual(expect.any(Boolean));
			expect(frame.notebookWindows?.[chatId]?.has_more_before).toEqual(expect.any(Boolean));
			expect(frame.wrapperWindows?.[chatId]?.has_more_before).toEqual(expect.any(Boolean));
			expect(frame.embedKeyWindows?.[chatId]?.has_more_after).toEqual(expect.any(Boolean));
		}
		expect(frame.codeOutputs.length).toBeLessThanOrEqual(frame.chatIds.length * 10);
		expect(frame.notebookOutputs.length).toBeLessThanOrEqual(frame.chatIds.length * 10);
		expect(frame.wrappers.length).toBeLessThanOrEqual(frame.chatIds.length * 20);
	}
	// The runner adds 22 encrypted parents and one child after one shared owner chat.
	expect(phase2Payloads.some((payload) => payload?.total_chat_count === 24), 'phase 2 should report all 24 fixture chats').toBe(true);
	expect(phase2Payloads.some((payload) => payload?.chats?.some((chat: any) =>
		chat?.chat_details?.messages_v === null
	)), 'The real metadata fixture must include its nullable legacy message counter').toBe(true);

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

	const activeChatId = await page.getByTestId('active-chat-container')
		.getAttribute('data-current-chat-id').catch(() => null);
	const olderParents = [...metadata.entries()].filter(([id, chat]) =>
		!chat.parent_id && !chat.is_sub_chat && chat.messages_v === 1 &&
		!startupContentIds.has(id) && id !== activeChatId);
	expect(olderParents.length, 'Real fixture must leave an older parent outside the startup content window').toBeGreaterThan(0);
	const metadataOnlyChatId = olderParents[0][0];
	// Assert the actual cold state before any loading route/helper; never delete loaded messages.
	expect(await readLocalStartupChat(page, metadataOnlyChatId)).toEqual({ exists: true, messageCount: 0 });
	expect(metadataOnlyChatId).not.toBe(activeChatId);
	await page.evaluate(() => { window.location.hash = 'tasks'; });
	await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 10000 });

	const coldWindowRoute = `**/v1/chats/${encodeURIComponent(metadataOnlyChatId)}/messages/window**`;
	let releaseColdWindow: () => void = () => undefined;
	const coldWindowGate = new Promise<void>((resolve) => {
		releaseColdWindow = resolve;
	});
	let coldWindowRequested = false;
	let coldWindowReleased = false;
	let failColdWindow = false;
	let finishColdWindow: () => void = () => undefined;
	const coldWindowFinished = new Promise<void>((resolve) => {
		finishColdWindow = resolve;
	});
	const delayColdWindowResponse = async (route: any) => {
		coldWindowRequested = true;
		try {
			const realResponse = await route.fetch();
			await coldWindowGate;
			if (failColdWindow) {
				await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"test_unavailable"}' });
			} else {
				await route.fulfill({ response: realResponse });
			}
		} finally {
			finishColdWindow();
		}
	};
	await page.route(coldWindowRoute, delayColdWindowResponse, { times: 1 });

	try {
		await page.evaluate((chatId: string) => {
			window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
		}, metadataOnlyChatId);
		await expect.poll(() => coldWindowRequested, {
			timeout: 10000,
			message: 'Opening metadata-only chat should request its real bounded window'
		}).toBe(true);
		await expect(page.getByTestId('welcome-content')).not.toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(page.getByTestId('active-chat-container')).toHaveAttribute(
			'data-current-chat-id',
			metadataOnlyChatId,
			{ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS }
		);
		await expect(page.getByTestId('chat-header-banner')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(page.getByTestId('active-chat-history-loading')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await page.getByTestId('message-editor').click();
		await expectLoadingBelowHeader(page);
		await holdProofVideoState(page);

		failColdWindow = true;
		await context.setOffline(true);
		coldWindowReleased = true;
		releaseColdWindow();
		await coldWindowFinished;
		await expect(page.getByTestId('active-chat-history-retry')).toBeVisible({ timeout: 15000 });
		await holdProofVideoState(page);
	} finally {
		if (!coldWindowReleased) releaseColdWindow();
		if (coldWindowRequested) await coldWindowFinished;
		await page.unroute(coldWindowRoute, delayColdWindowResponse);
		await context.setOffline(false);
	}
	await page.getByTestId('message-editor').press('Escape');
	await expect(page.getByTestId('message-editor')).not.toBeFocused();

	await expect.poll(() => {
		const expectedRestPath = `/v1/chats/${encodeURIComponent(metadataOnlyChatId)}/messages/window`;
		return sentTypes.includes('request_chat_content_batch') ||
			onDemandRequestUrls.some((url) => url.includes(expectedRestPath));
	}, {
		timeout: 15000,
		message: 'Opening metadata-only chat should request on-demand content hydration'
	}).toBe(true);

	// Preserve the failure/retry proof, then require successful older-parent hydration on revisit.
	await page.evaluate(() => { window.location.hash = 'tasks'; });
	await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 10000 });
	await page.evaluate((chatId: string) => {
		window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
	}, metadataOnlyChatId);
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', metadataOnlyChatId);
	await expect(page.getByTestId('chat-history-content').getByTestId('message-content').filter({
		hasText: /^Synthetic startup chat \d{2}, message 1\.$/
	})).toBeVisible({ timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS });
	await expect.poll(async () => (await readLocalStartupChat(page, metadataOnlyChatId)).messageCount, {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS
	}).toBe(1);

	// The child was genuinely metadata-only above. Opening it now must hydrate actual encrypted content.
	const childWindowPath = `/v1/chats/${encodeURIComponent(childId)}/messages/window`;
	expect(onDemandRequestUrls.some(url => url.includes(childWindowPath))).toBe(false);
	expect(onDemandBatchChatIds).not.toContain(childId);
	await page.evaluate((chatId: string) => {
		window.location.hash = `chat-id=${encodeURIComponent(chatId)}`;
	}, childId);
	await expect.poll(() => onDemandRequestUrls.some(url => url.includes(childWindowPath)) ||
		onDemandBatchChatIds.includes(childId), {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS,
		message: 'Opening the child must request its own real on-demand message content'
	}).toBe(true);
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', childId);
	await expect(page.getByTestId('chat-history-content').getByTestId('message-content').filter({
		hasText: /^Synthetic startup child chat 01, message 1\.$/
	})).toBeVisible({ timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS });
	await expect.poll(async () => (await readLocalStartupChat(page, childId)).messageCount, {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS
	}).toBe(1);

	await verifyCachedShortChatOpening(page);
});

// contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent,sync.startup.bounded-phases,chats.persistence.client-encrypted,workspace-shell.start.available-space-cards
test('continue carousel remains visible during reconnect churn', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(120000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const startupEvidence = await createStartupEvidence(page);
	const sockets = await observeReconnectSockets(page, startupEvidence);
	await loginToTestAccount(page);
	await dismissSecurityReminderIfPresent(page);
	await expect.poll(() => sockets.some(socket => !socket.closed && socket.phase2Frames > 0), { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS }).toBe(true);
	await startupEvidence.snapshotPhaseReceipts();
	await waitForChatReady(page);
	await startupEvidence.end();
	await verifyContinueCarouselSurvivesReconnectChurn(page, sockets, startupEvidence);
	await startupEvidence.attach(testInfo);
});

// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle,sync.startup.bounded-phases
test('startup socket close smoke reconnects with capabilities and bounded sync', async ({ page, context }: { page: any; context: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await context.addInitScript(() => {
		const NativeWebSocket = window.WebSocket;
		const smoke = { attempts: 0, earlyCloses: 0, closedAttempt: 0, replacementTypes: [] as string[] };
		const testWindow = window as typeof window & { __startupSocketCloseSmoke?: typeof smoke };
		testWindow.__startupSocketCloseSmoke = smoke;
		window.WebSocket = class extends NativeWebSocket {
			constructor(url: string | URL, protocols?: string | string[]) {
				super(url, protocols);
				if (!String(url).includes('/v1/ws')) return;
				const attempt = ++smoke.attempts;
				this.addEventListener('open', () => {
					if (smoke.earlyCloses === 0) {
						smoke.earlyCloses++;
						smoke.closedAttempt = attempt;
						this.close(1000, 'Synthetic startup socket close');
					}
				});
				this.addEventListener('message', (event) => {
					if (smoke.closedAttempt === 0 || attempt <= smoke.closedAttempt || typeof event.data !== 'string') return;
					try {
						const type = JSON.parse(event.data)?.type;
						if (typeof type === 'string') smoke.replacementTypes.push(type);
					} catch { /* Only record protocol message types, never payloads. */ }
				});
			}
		};
	});
	await loginToTestAccount(page);
	await expect.poll(() => page.evaluate(() => {
		const smoke = (window as typeof window & {
			__startupSocketCloseSmoke?: { attempts: number; earlyCloses: number; closedAttempt: number; replacementTypes: string[] }
		}).__startupSocketCloseSmoke;
		return {
			earlyCloses: smoke?.earlyCloses,
			reconnected: Boolean(smoke && smoke.closedAttempt > 0 && smoke.attempts > smoke.closedAttempt),
			capabilities: smoke?.replacementTypes.includes('server_capabilities'),
			phase1b: smoke?.replacementTypes.includes('phase_1b_chat_content_ready'),
			phase2: smoke?.replacementTypes.includes('phase_2_last_20_chats_ready')
		};
	}), { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS }).toEqual({
		earlyCloses: 1, reconnected: true, capabilities: true, phase1b: true, phase2: true
	});
	await waitForChatReady(page);
	// This browser smoke proves recovery after a real early client close. The
	// deterministic ASGI transport unit and isolated API logs prove server cleanup.
});

// contract-test: direct surface=gui.web assertions=chat-navigation.open.local-first-coherent,sync.startup.bounded-phases,chats.persistence.client-encrypted,chats.message.identity-idempotent
test('cached short chat opens coherently before delayed completeness repair', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await loginToTestAccount(page);
	await dismissSecurityReminderIfPresent(page);
	await verifyCachedShortChatOpening(page);
});

// contract-test: direct surface=gui.web assertions=storage.cold.independent-message-pages,sync.startup.bounded-phases
test('oversized encrypted sync cursor opens one authenticated message without full history replay', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await loginToTestAccount(page);
	await dismissSecurityReminderIfPresent(page);
	await waitForChatReady(page, undefined, 60000);
	const sharedFixtureUrl = process.env.OPENMATES_CI_SHARED_CHAT_URL;
	expect(sharedFixtureUrl, 'Fresh synthetic encrypted owner chat required for selected-message proof').toBeTruthy();
	const fixtureChatId = new URL(sharedFixtureUrl!).pathname.split('/').at(-1);
	expect(fixtureChatId, 'Synthetic fixture chat ID required').toBeTruthy();
	let chatId: string | null = null;
	await expect.poll(async () => {
		chatId = await prepareLocalMetadataOnlyChat(page, fixtureChatId!);
		return chatId;
	}, {
		timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS,
		message: 'Synthetic encrypted owner chat must reach IndexedDB before selected-message proof'
	}).toBe(fixtureChatId);
	const teamId = await page.evaluate(async (id: string) => {
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
		});
		try {
			return await new Promise<string | null>((resolve, reject) => {
				const request = db.transaction('chats', 'readonly').objectStore('chats').get(id);
				request.onsuccess = () => resolve(request.result?.team_id || null);
				request.onerror = () => reject(request.error);
			});
		} finally {
			db.close();
		}
	}, chatId);
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
	const params = new URLSearchParams({ limit: '20', respect_compression_boundary: 'false' });
	if (teamId) params.set('team_id', teamId);
	const baselineResponse = await page.request.get(`${apiUrl}/v1/chats/${encodeURIComponent(chatId!)}/messages/window?${params}`);
	expect(baselineResponse.ok()).toBeTruthy();
	const baseline = await baselineResponse.json();
	const newest = baseline.messages?.at(-1);
	expect(newest?.message_id, 'Selected encrypted message must exist').toBeTruthy();
	const selectedId = newest.message_id as string;
	const selectedTimestamp = Number(newest.created_at);
	let exactReads = 0;
	let fullHistoryReads = 0;
	page.on('request', (request: any) => {
		const path = new URL(request.url()).pathname;
		if (path === `/v1/chats/${chatId}/messages/${selectedId}`) exactReads += 1;
		if (path === `/v1/chats/${chatId}/messages`) fullHistoryReads += 1;
	});
	await page.route(`**/v1/chats/${encodeURIComponent(chatId!)}/messages/window**`, (route: any) => route.fulfill({
		status: 200,
		contentType: 'application/json',
		body: JSON.stringify({
			chat_id: chatId, messages: [], has_more_before: true, has_more_after: false,
			start_cursor: null, end_cursor: null, anchor_found: true,
			oversized_message: true,
			oversized_message_cursor: { created_at: selectedTimestamp, message_id: selectedId },
			server_message_count: baseline.server_message_count
		})
	}), { times: 1 });
	await page.evaluate((id: string) => { window.location.hash = `chat-id=${encodeURIComponent(id)}`; }, chatId);
	await expect.poll(() => exactReads, { timeout: 15000 }).toBeGreaterThanOrEqual(1);
	expect(fullHistoryReads).toBe(0);
});

// contract-test: direct surface=gui.web assertions=chat-navigation.open.local-first-coherent
test('recent chats replay the selected window while IndexedDB reconciliation waits', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await loginToTestAccount(page);
	await dismissSecurityReminderIfPresent(page);
	await waitForChatReady(page, undefined, 60000);

	let chats: Array<{ chatId: string; messageCount: number }> = [];
	await expect.poll(async () => {
		chats = await getLocalChatSwitchPair(page, false);
		return chats.length;
	}, { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS }).toBeGreaterThanOrEqual(2);
	const [first, second] = chats;
	const active = page.getByTestId('active-chat-container');
	const composerGate = page.getByTestId('chat-warm-composer-gate');
	const select = async (chatId: string) => {
		await page.evaluate((id: string) => { window.location.hash = `chat-id=${encodeURIComponent(id)}`; }, chatId);
		await expect(active).toHaveAttribute('data-current-chat-id', chatId, { timeout: 30000 });
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count') || 0), {
			timeout: 30000
		}).toBeGreaterThan(0);
		await expect(active).toHaveAttribute('data-chat-load-state', 'ready', { timeout: 30000 });
	};
	await page.evaluate(() => {
		Object.defineProperty(window, '__openmatesRecentReplayDiagnosticsEnabled', {
			value: true, writable: true, configurable: true
		});
	});
	await select(first.chatId);
	await select(second.chatId);
	const sidebar = page.getByTestId('activity-history-wrapper');
	if (await sidebar.isVisible().catch(() => false)) {
		await sidebar.getByRole('button', { name: /close/i }).click();
	}
	await expect(sidebar).not.toBeVisible();
	await holdSelectedChatStoreReads(page);
	try {
		await page.evaluate((id: string) => { window.location.hash = `chat-id=${encodeURIComponent(id)}`; }, first.chatId);
		await expect(active).toHaveAttribute('data-current-chat-id', first.chatId, { timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(active).toHaveAttribute('data-chat-load-state', 'ready', { timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count') || 0), {
			timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS
		}).toBeGreaterThan(0);
		await expect(active).toHaveAttribute('data-current-message-chat-consistent', 'true');
		await expect(active).toHaveAttribute('data-current-message-ids-unique', 'true');
		await expect(active).toHaveAttribute('data-current-message-order-valid', 'true');
		await expect(page.getByTestId('chat-history-content')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(page.getByTestId('chat-header-banner')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(composerGate).toHaveJSProperty('inert', true);
		await expect(composerGate).toHaveAttribute('aria-busy', 'true');
		await expect.poll(async () => Number(await page.getByTestId('chat-history-content').getAttribute('data-source-message-count') || 0), {
			timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS
		}).toBeGreaterThan(0);
		const readDone = await page.evaluate(() =>
			(window as typeof window & { __recentChatBlockedReadDone?: { chats: boolean; messages: boolean } }).__recentChatBlockedReadDone
		);
		expect(readDone, 'IndexedDB chat metadata and message reads should still be blocked when cached content is visible')
			.toEqual({ chats: false, messages: false });
		await page.evaluate((id: string) => { window.location.hash = `chat-id=${encodeURIComponent(id)}`; }, second.chatId);
		await expect(active).toHaveAttribute('data-current-chat-id', second.chatId, { timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(active).toHaveAttribute('data-chat-load-state', 'ready', { timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count') || 0), {
			timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS
		}).toBeGreaterThan(0);
		await expect(active).toHaveAttribute('data-current-message-chat-consistent', 'true');
		await expect(page.getByTestId('chat-history-content')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(page.getByTestId('chat-header-banner')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(composerGate).toHaveJSProperty('inert', true);
		expect(await page.evaluate(() =>
			(window as typeof window & { __recentChatBlockedReadDone?: { chats: boolean; messages: boolean } }).__recentChatBlockedReadDone
		), 'closed-sidebar A to B navigation must show cached content before either IndexedDB read completes')
			.toEqual({ chats: false, messages: false });

		// Returning through another workspace remounts the chat view. The recent
		// encrypted window must still render while both selected-chat stores remain locked.
		await page.evaluate(() => { window.location.hash = 'tasks'; });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 10000 });
		await page.evaluate((id: string) => { window.location.hash = `chat-id=${encodeURIComponent(id)}`; }, first.chatId);
		await expect(active).toHaveAttribute('data-current-chat-id', first.chatId, { timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(active).toHaveAttribute('data-chat-load-state', 'ready', { timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count') || 0), {
			timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS
		}).toBeGreaterThan(0);
		await expect(page.getByTestId('chat-history-content')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(page.getByTestId('chat-header-banner')).toBeVisible({ timeout: LOCAL_CHAT_SHELL_TIMEOUT_MS });
		await expect(composerGate).toHaveJSProperty('inert', true);
		expect(await page.evaluate(() =>
			(window as typeof window & { __recentChatBlockedReadDone?: { chats: boolean; messages: boolean } }).__recentChatBlockedReadDone
		), 'workspace return must show cached content before either IndexedDB read completes')
			.toEqual({ chats: false, messages: false });
	} catch (primaryFailure) {
		// Keep the assertion failure primary even when capture/upload fails.
		try {
			const serialized = await page.evaluate(() => {
				const value = Object.getOwnPropertyDescriptor(window, '__openmatesRecentReplayDiagnostics')?.value;
				// typeof/length on a primitive cannot invoke a page-supplied Proxy or getter.
				return typeof value === 'string' && value.length <= 4096 ? value : '[]';
			});
			const allowed: readonly string[] = ["route-enter", "route-legal", "route-stale-target", "route-already-active", "route-target-options", "route-draft-md", "route-draft-preview", "route-component-absent", "route-continue", "route-replay-accepted", "route-replay-rejected", "surface-server", "surface-unauthenticated", "surface-logging-out", "surface-forced-logout", "surface-signup", "surface-store-target", "surface-already-current", "surface-public", "surface-example", "surface-anonymous", "surface-composer-content", "surface-code-fullscreen", "surface-embed-fullscreen", "surface-wiki-fullscreen", "surface-live-message", "surface-hash-target", "surface-hash-message", "surface-hash-message-alias", "surface-hash-embed", "surface-hash-embed-alias", "surface-hash-scroll", "surface-key-absent", "surface-selection-absent", "surface-incognito", "surface-anonymous-selection", "surface-draft-only", "surface-team-context", "surface-published", "selection-entry-absent", "invalidation-metadata", "invalidation-metadata-local-list", "invalidation-metadata-chat-updated", "invalidation-metadata-draft-save", "invalidation-metadata-chat-row", "invalidation-metadata-draft-websocket", "invalidation-metadata-draft-delete-sender", "invalidation-metadata-sync-draft", "invalidation-metadata-sync-header", "invalidation-metadata-phase-sync", "invalidation-message", "invalidation-key", "invalidation-delete", "invalidation-unknown", "invalidation-workspace-clear", "invalidation-eviction", "selection-source-absent", "selection-source-target", "selection-window-absent", "selection-header-mismatch", "selection-accepted", "window-account-absent", "window-miss", "window-account-mismatch", "window-epoch-mismatch", "window-revision-mismatch", "window-accepted", "admission-account-absent", "admission-stale-read", "admission-private-selection", "admission-empty-window", "admission-message-target", "admission-unsettled-message", "admission-snapshot-failed", "admission-oversized", "admission-accepted", "admission-evicted"];
			const parsed: unknown = JSON.parse(serialized);
			const reasons = Array.isArray(parsed)
				? parsed.slice(-64).filter((value): value is string => typeof value === 'string' && allowed.includes(value)) : [];
			await testInfo.attach('cached-replay-branch-receipt', {
				body: Buffer.from(JSON.stringify({ schemaVersion: 1, reasons })), contentType: 'application/json'
			});
		} catch { /* A missing receipt must not replace the original assertion. */ }
		throw primaryFailure;
	} finally {
		await releaseSelectedChatStoreReads(page);
		await page.evaluate(() => { delete (window as any).__openmatesRecentReplayDiagnostics; delete (window as any).__openmatesRecentReplayDiagnosticsEnabled; }).catch(() => {});
	}
	await expect.poll(() => page.evaluate(() =>
		(window as typeof window & { __recentChatBlockedReadDone?: { chats: boolean; messages: boolean } }).__recentChatBlockedReadDone
	)).toEqual({ chats: true, messages: true });
	await expect(active).toHaveAttribute('data-chat-load-state', 'ready', { timeout: 30000 });
	await expect(composerGate).toHaveJSProperty('inert', false);
	await expect(composerGate).toHaveAttribute('aria-busy', 'false');
	await expect(composerGate.getByTestId('message-editor').locator('[contenteditable="true"]')).toBeVisible();
});


// contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases,sdk.web.before-after-performance
test('authenticated startup observes HTTP-cache cold fill and two same-route warm reloads', async ({ page }: { page: any }, testInfo: any) => {
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await page.addInitScript(installResourceTimingCapture);
	const sockets = await observeReconnectSockets(page);
	const meter = await createBrowserProcessEvidence(page);
	const evidence: any = {
		schemaVersion: 2, scenario: 'authenticated-http-cache-selected-decrypted-chat-cold-fill-warm-reloads',
		status: 'unavailable', samples: [], completeApprovedWebComparison: false,
		fixture: { startupChats: 23, startupParentChats: 22, startupChildChats: 1, sharedOwnerChats: 1, phase2ExpectedTotalChats: 24, startupSeedMessages: 33, selectedSeedMessages: 6, persistedCountsAreObserved: true },
		definitions: {
			cache: 'HTTP cache cleared after login, then cache enabled for one cold-fill and two warm reload attempts of the same route. SW bypass held constant. Cache eligibility/hits are observed, never asserted.',
			login: 'Login automation through phase2, explicit selection of a six-message encrypted startup fixture chat, real decrypted message DOM and usable editor. Includes navigation/network/KDF/UI/runner work and read-only fixture selection; KDF duration is not isolated.',
			reload: 'Node wall interval from immediately before reload(domcontentloaded) through phase2 and selected-chat readiness: matching active identity, nonzero loaded/source message counts, real decrypted synthetic message DOM, coherent message identity/order, usable editor and nonzero persisted messages. Does not attest full fixture persistence/decryption.',
			process: 'CPU and RSS endpoints span the measurement automation and sequential sampler overhead; raw process identities never leave the helper. See per-sample qualifications.',
			storage: 'No auth, cookies, IndexedDB, local/session storage or application caches cleared. This is not cold authentication, cold app storage, cold OS disk cache, cold code cache or a fresh browser process.',
			memory: 'Optional ResourceTiming helper JS heap is separate from procfs summed RSS; WASM linear memory is unavailable. No inference introduced. The same collector is intended for legacy BEFORE and integrated AFTER; no assumed Rust/WASM overhead.',
			initialization: 'DOMContentLoaded and application usable-ready wall intervals are observed. WASM compile/instantiate/init duration is unavailable without runtime hooks; do not infer it from zero observed WASM or total startup.',
			resources: 'Bounded ResourceTiming transfer/encoded/decoded sizes cover this selected route only. Offline production JS/WASM compression inventories and served-source receipts remain separate evidence; encodedBodyBytes is observed HTTP body size, not proof of Content-Encoding or complete asset size.',
			coverage: 'One cold HTTP-cache fill and two warm attempts; no distribution, peak memory, all-core-flow or complete approved before/after comparison claim. The separate required cached-replay 1.5s regression remains unchanged.',
		},
	};
	// Keep fixture identity and known plaintext in assertions only, never evidence.
	let selectedChatId: string;
	const assertSelectedDecryptedChatUsable = async () => {
		const active = page.getByTestId('active-chat-container');
		await expect(active).toHaveAttribute('data-current-chat-id', selectedChatId, { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS });
		await expect(active).toHaveAttribute('data-chat-load-state', 'ready', { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS });
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count') || 0), {
			timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS
		}).toBeGreaterThan(0);
		await expect(active).toHaveAttribute('data-current-message-chat-consistent', 'true');
		await expect(active).toHaveAttribute('data-current-message-ids-unique', 'true');
		await expect(active).toHaveAttribute('data-current-message-order-valid', 'true');
		const history = active.getByTestId('chat-history-content');
		await expect(history).toBeVisible();
		await expect.poll(async () => Number(await history.getAttribute('data-source-message-count') || 0), {
			timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS
		}).toBeGreaterThan(0);
		// Counts and a ready shell alone previously admitted a zero-message sample.
		// This known fixture content must have survived real encrypted hydration.
		const decryptedMessage = history.getByTestId('message-content').filter({ hasText: /^Synthetic startup chat (01|02), message [1-6]\.$/ }).first();
		await expect(decryptedMessage).toBeVisible({ timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS });
		const composer = page.getByTestId('chat-warm-composer-gate');
		await expect(composer).toHaveJSProperty('inert', false);
		await expect(composer).toHaveAttribute('aria-busy', 'false');
		await expect(composer.getByTestId('message-editor').locator('[contenteditable="true"]')).toBeEditable();
		let counts: any;
		await expect.poll(async () => {
			counts = await persistedCounts(page);
			return counts.available && counts.chats === 24 && counts.messages > 0;
		}, { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS }).toBe(true);
		return { loadedMessages: Number(await active.getAttribute('data-current-message-count')), sourceMessages: Number(await history.getAttribute('data-source-message-count')), decryptedFixtureMessageVisible: true, editorUsable: true, counts };
	};
	try {
		if (!meter.available) {
			evidence.reason = 'requires_sole_owned_local_chromium_browser_and_readable_procfs';
			test.skip(true, 'Controlled HTTP/process observations unavailable for this browser ownership/platform.');
		}
		evidence.status = 'partial';
		const loginBegin = await meter.begin();
		evidence.loginAutomation = { begin: loginBegin };
		expect(loginBegin.available, 'Admitted browser login observation requires a valid begin endpoint').toBe(true);
		const loginStartMs = Date.now();
		await loginToTestAccount(page);
		await dismissSecurityReminderIfPresent(page);
		await expect.poll(() => sockets.some(socket => !socket.closed && socket.phase2Frames > 0), { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS }).toBe(true);
		await waitForChatReady(page);
		const authenticatedShellReadyMs = Date.now() - loginStartMs;
		let selection: { chatId: string; messageCount: number } | undefined;
		await expect.poll(async () => {
			// Read only: unlike the short-window regression, do not trim fixture data.
			selection = (await getLocalChatSwitchPair(page, false)).find(chat => chat.messageCount === 6);
			return Boolean(selection);
		}, { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS }).toBe(true);
		selectedChatId = selection!.chatId;
		await page.evaluate((id: string) => { window.location.hash = `chat-id=${encodeURIComponent(id)}`; }, selectedChatId);
		const usable = await assertSelectedDecryptedChatUsable();
		evidence.loginAutomation = { begin: loginBegin, elapsedMs: Date.now() - loginStartMs, authenticatedShellReadyMs, usable, process: await meter.end() };
		evidence.loginAutomation.resources = resourceEvidence(await page.evaluate(browserResourceSnapshot), 0, process.env.OPENMATES_PERF_FRONTEND_MODE);
		evidence.loginAutomation.acceptance = assessObservation({ begin: loginBegin, end: evidence.loginAutomation.process, kind: 'login' });
		expect(evidence.loginAutomation.acceptance.accepted, evidence.loginAutomation.acceptance.reason).toBe(true);
		evidence.cacheProtocol = await meter.prepareHttpCold();
		if (!evidence.cacheProtocol.available) {
			evidence.reason = 'http_cache_control_unavailable';
			test.skip(true, 'Controlled HTTP-cache setup unavailable; no uncontrolled sample substituted.');
		}
		const route = page.url(); // In-memory pairing only; never attach raw URL/auth fragments.
		evidence.routePathSha256 = routeSelectionSha256(route);
		for (const [index, role] of ['http-cache-cold-fill', 'same-route-warm-1', 'same-route-warm-2'].entries()) {
			const previousSocketCount = sockets.length;
			const countsBefore = await persistedCounts(page);
			const begin = await meter.begin();
			const sample: any = { ordinal: index, role, begin };
			evidence.samples.push(sample);
			expect(begin.available, 'Admitted reload observation requires a valid begin endpoint').toBe(true);
			const startMs = Date.now();
			await page.reload({ waitUntil: 'domcontentloaded' });
			const domContentLoadedMs = Date.now() - startMs;
			await expect.poll(() => sockets.slice(previousSocketCount).some(socket => !socket.closed && socket.phase2Frames > 0), { timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS }).toBe(true);
			const phase2ObservedMs = Date.now() - startMs;
			await waitForChatReady(page);
			// Reload preserves the explicitly selected route; never substitute an empty new chat.
			const usable = await assertSelectedDecryptedChatUsable();
			const reloadToReadyMs = Date.now() - startMs;
			const processObservation = await meter.end();
			const countsAfter = await persistedCounts(page);
			const snapshot = await page.evaluate(browserResourceSnapshot);
			Object.assign(sample, { sameRouteAsInitial: page.url() === route,
				domContentLoadedMs, phase2ObservedMs, reloadToReadyMs, usable, process: processObservation, countsBefore, countsAfter,
				resources: { ...resourceEvidence(snapshot, index + 1, process.env.OPENMATES_PERF_FRONTEND_MODE), cacheAttempt: role + '-controlled-http-only' },
			});
			sample.acceptance = assessObservation({ begin, end: processObservation, kind: 'reload', sameRoute: sample.sameRouteAsInitial });
			expect(sample.acceptance.accepted, sample.acceptance.reason).toBe(true);
		}
		evidence.status = 'observed';
	} finally {
		await meter.close();
		evidence.provenance = provenance(testInfo, page.context().browser()?.version(), page.viewportSize(), [
			'scripts/ci_startup_sync_fixture.mjs', 'frontend/apps/web_app/tests/startup-sync-contract.spec.ts', 'frontend/apps/web_app/tests/helpers/browser-process-evidence.cjs',
			'frontend/apps/web_app/tests/helpers/performance-evidence.cjs', 'frontend/apps/web_app/tests/helpers/startup-performance-evidence.cjs',
		]);
		await testInfo.attach('controlled-http-cache-process-evidence', { contentType: 'application/json', body: performanceAttachment(evidence) });
	}
});
