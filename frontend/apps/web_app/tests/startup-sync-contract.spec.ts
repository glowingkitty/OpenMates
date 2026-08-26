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

async function prepareLocalMetadataOnlyChat(page: any): Promise<string | null> {
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
			chats.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));

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
	});
}

async function getLocalChatSwitchPair(
	page: any
): Promise<Array<{ chatId: string; messageCount: number }>> {
	return await page.evaluate(async (targetCount: number) => {
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
				messages.sort((a, b) => Number(a.created_at || 0) - Number(b.created_at || 0));
				cleanChats.push({ chatId, messages });
				if (cleanChats.length >= 2) break;
			}
			if (cleanChats.length < 2) return [];

			const [firstChat, secondChat] = cleanChats;
			const messagesToDelete = firstChat.messages.slice(0, Math.max(0, firstChat.messages.length - targetCount));
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
				{ chatId: firstChat.chatId, messageCount: Math.min(firstChat.messages.length, targetCount) },
				{ chatId: secondChat.chatId, messageCount: secondChat.messages.length }
			];
		} finally {
			db.close();
		}
	}, LOCAL_SHORT_WINDOW_TARGET_COUNT);
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

async function verifyContinueCarouselSurvivesReconnectChurn(page: any, context: any): Promise<void> {
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible({ timeout: 1000 }).catch(() => false)) {
		await newChatButton.click();
	}
	await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('recent-chats-scroll-container')).toBeVisible({ timeout: STARTUP_SYNC_FRAME_TIMEOUT_MS });

	const initialState = await getContinueCarouselState(page);
	expect(initialState.chatIds.length, 'test account needs at least one continue card for carousel stability coverage').toBeGreaterThan(0);

	await context.setOffline(true);
	await page.waitForTimeout(250);
	await context.setOffline(false);

	const samples: Array<{ visible: boolean; count: number }> = [];
	const deadline = Date.now() + 2000;
	while (Date.now() < deadline) {
		const state = await getContinueCarouselState(page);
		samples.push({ visible: state.visible, count: state.chatIds.length });
		await page.waitForTimeout(50);
	}

	const blankSample = samples.find((sample) => !sample.visible || sample.count === 0);
	expect(blankSample, `Continue carousel must not blank during reconnect churn; samples=${JSON.stringify(samples)}`).toBeUndefined();
}

// contract-test: direct surface=gui.web assertions=chat-navigation.open.local-first-coherent,sync.startup.bounded-phases,sync.phase2.metadata-only,chats.persistence.client-encrypted,chats.message.identity-idempotent
test('startup sync is bounded and older content hydrates on demand', async ({ page, context }: { page: any; context: any }) => {
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
	await dismissSecurityReminderIfPresent(page);
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

	const metadataOnlyChatId = await prepareLocalMetadataOnlyChat(page);
	if (!metadataOnlyChatId) {
		console.log('No local metadata-only chat found; startup sync boundary verified, skipping hydration check.');
		return;
	}

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

	await verifyCachedShortChatOpening(page);
});

// contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent,sync.startup.bounded-phases,chats.persistence.client-encrypted
test('continue carousel remains visible during reconnect churn', async ({ page, context }: { page: any; context: any }) => {
	test.slow();
	test.setTimeout(120000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await loginToTestAccount(page);
	await dismissSecurityReminderIfPresent(page);
	await verifyContinueCarouselSurvivesReconnectChurn(page, context);
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
