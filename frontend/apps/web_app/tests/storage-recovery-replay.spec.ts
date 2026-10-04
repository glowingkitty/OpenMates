/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed, provider-free child recovery across a browser disconnect. */
// contract-test-file: infrastructure
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

const { requireSignedRecoveryProfile, observeRecoveryFrames, availableOutputs, requireActiveRecoveryDiscovery, disconnectCanonicalWrites } = require('./storage-recovery-fixtures');
import type { RecoveryFrame } from './storage-recovery-fixtures';

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
test('saved child message and summary replay through sealed output records after disconnect', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const originContext = await browser.newContext({ baseURL });
	const recoveryContext = await browser.newContext({ baseURL });
	const origin = await originContext.newPage();
	const originFrames: RecoveryFrame[] = [];
	const originErrors: string[] = [];
	origin.on('console', (entry: any) => {
		if (entry.type() === 'error') originErrors.push(entry.text().slice(0, 180));
	});
	const recovery = await recoveryContext.newPage();
	const log = createSignupLogger('storage-recovery-replay');
	const screenshot = createStepScreenshotter(log);
	const frames: Array<{ direction: 'sent' | 'received'; type: string; payload: Record<string, any> }> = [];
	recovery.on('websocket', (socket: any) => {
		const capture = (direction: 'sent' | 'received') => (frame: any) => {
			try {
				const message = JSON.parse(String(frame.payload));
				if (typeof message.type === 'string') frames.push({ direction, type: message.type, payload: message.payload ?? {} });
			} catch { /* Binary frames contain no recovery protocol. */ }
		};
		socket.on('framesent', capture('sent'));
		socket.on('framereceived', capture('received'));
	});
	try {
		await disconnectCanonicalWrites(origin, originFrames);
		await installE2EServerContentOverrideGate(origin, 'storage-recovery-replay');
		await loginToTestAccount(origin, log, screenshot);
		await requireActiveRecoveryDiscovery(originFrames);
		await startNewChat(origin, log);
		await sendMessage(origin,
			'Synthetic child recovery. STORAGE_CAPACITY_SCENARIO:child <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-child');
		const chatId = origin.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		try {
		await expect.poll(() => {
			const outputs = availableOutputs(originFrames, chatId!);
			return {
				user: outputs.some((output) => output.output_kind === 'message' && output.message_role === 'user'),
				assistant: outputs.some((output) => output.output_kind === 'message' && output.message_role === 'assistant'),
				summary: outputs.some((output) => output.output_kind === 'summary'),
			};
		}, { timeout: 120_000, message: 'Origin must publish sealed child messages and summary before disconnect' })
			.toEqual({ user: true, assistant: true, summary: true });
		} catch (error) {
			const protocol = originFrames.slice(-50).map((frame) => ({
				type: frame.type, code: frame.payload.code ?? null,
				kinds: Array.isArray(frame.payload.outputs)
					? frame.payload.outputs.map((output: any) => `${output.output_kind}:${output.message_role ?? ''}`)
					: undefined,
			}));
			throw new Error(`Child sealed outputs missing: ${String(error)}; `
				+ `protocol=${JSON.stringify(protocol)}; consoleErrors=${JSON.stringify(originErrors.slice(-8))}`);
		}
		await originContext.close();

		await loginToTestAccount(recovery, log, screenshot);
		await recovery.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), { waitUntil: 'domcontentloaded' });
		await expect.poll(() => frames.some((frame) => frame.direction === 'received'
			&& frame.type === 'recovery_outputs_available'
			&& frame.payload.outputs?.some((output: any) => output.root_chat_id === chatId)),
		{ timeout: 180_000 }).toBe(true);
		const discovered = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.filter((output: any) => output.root_chat_id === chatId);
		expect(discovered.some((output: any) => output.output_kind === 'message' && output.message_role === 'user')).toBe(true);
		expect(discovered.some((output: any) => output.output_kind === 'message' && output.message_role === 'assistant')).toBe(true);
		expect(discovered.some((output: any) => output.output_kind === 'summary')).toBe(true);
		for (const { output_kind: kind, record_id: recordId } of discovered) {
			const acknowledgedType = kind === 'message' ? 'recovery_output_persisted' : 'recovery_output_summary_persisted';
			await expect.poll(() => frames.some((frame) => frame.direction === 'received'
				&& frame.type === acknowledgedType && frame.payload.record_id === recordId
				&& frame.payload.state === 'ACKNOWLEDGED'), { timeout: 120_000 }).toBe(true);
		}
		await recovery.reload();
		await expect(recovery.getByTestId('message-assistant').filter({ hasText: 'Synthetic child' }).first())
			.toBeVisible({ timeout: 90_000 });
	} finally {
		await recoveryContext.close();
		await originContext.close().catch(() => undefined);
	}
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,storage.compression.incremental-archive
test('sealed compression checkpoint restores its canonical encrypted boundary', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const log = createSignupLogger('storage-recovery-checkpoint');
	const screenshot = createStepScreenshotter(log);
	const origin = await browser.newContext({ baseURL });
	const source = await origin.newPage();
	const sourceFrames: RecoveryFrame[] = [];
	const destination = await browser.newContext({ baseURL });
	const recovered = await destination.newPage();
	const frames: Array<{ type: string; payload: Record<string, any> }> = [];
	recovered.on('websocket', (socket: any) => socket.on('framereceived', (frame: any) => {
		try {
			const parsed = JSON.parse(String(frame.payload));
			frames.push({ type: parsed.type, payload: parsed.payload ?? {} });
		} catch { /* Ignore non-JSON frames. */ }
	}));
	try {
		await disconnectCanonicalWrites(source, sourceFrames);
		await installE2EServerContentOverrideGate(source, 'storage-recovery-replay');
		await loginToTestAccount(source, log, screenshot);
		await requireActiveRecoveryDiscovery(sourceFrames);
		await startNewChat(source, log);
		await sendMessage(source,
			'Synthetic durable checkpoint. STORAGE_CAPACITY_SCENARIO:recovery_checkpoint <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-checkpoint');
		const chatId = source.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await expect.poll(() => availableOutputs(sourceFrames, chatId!).some((output) => output.output_kind === 'checkpoint'),
			{ timeout: 120_000, message: 'Origin must publish sealed checkpoint before disconnect' }).toBe(true);
		await origin.close();
		await loginToTestAccount(recovered, log, screenshot);
		await recovered.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await expect.poll(() => frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.some((output: any) => output.root_chat_id === chatId && output.output_kind === 'checkpoint'),
		{ timeout: 180_000 }).toBe(true);
		const checkpoint = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.find((output: any) => output.root_chat_id === chatId && output.output_kind === 'checkpoint');
		await expect.poll(() => frames.some((frame) => frame.type === 'recovery_output_checkpoint_acknowledged'
			&& frame.payload.record_id === checkpoint.record_id && frame.payload.state === 'ACKNOWLEDGED'),
		{ timeout: 120_000 }).toBe(true);
	} finally {
		await origin.close().catch(() => undefined);
		await destination.close();
	}
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,storage.validation.synthetic-capacity
test('a failed durable child prompt save pauses dependent synthesis', async ({ page }: { page: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(180_000);
	const log = createSignupLogger('storage-recovery-save-failure');
	const screenshot = createStepScreenshotter(log);
	const pauses: Array<Record<string, any>> = [];
	const sourceFrames = observeRecoveryFrames(page);
	page.on('websocket', (socket: any) => socket.on('framereceived', (frame: any) => {
		try {
			const message = JSON.parse(String(frame.payload));
			if (message.type === 'recovery_output_paused') pauses.push(message.payload ?? {});
		} catch { /* Ignore non-JSON frames. */ }
	}));
	await installE2EServerContentOverrideGate(page, 'storage-recovery-replay');
	await loginToTestAccount(page, log, screenshot);
	await requireActiveRecoveryDiscovery(sourceFrames);
	await startNewChat(page, log);
	await sendMessage(page,
		'Check a failed durable child save. STORAGE_CAPACITY_SCENARIO:recovery_save_failure <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'storage-recovery-failure');
	const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
	expect(chatId).toBeTruthy();
	await expect.poll(() => pauses.some((pause) => pause.chat_id === chatId
		&& pause.child_chat_id && pause.reason_code === 'durable_output_unavailable'),
	{ timeout: 120_000 }).toBe(true);
	expect(pauses.filter((pause) => pause.chat_id === chatId)).toHaveLength(1);
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
test('another-device deletion discards a lost-ACK sealed turn without recreating its chat', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(240_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const log = createSignupLogger('storage-recovery-delete-fence');
	const screenshot = createStepScreenshotter(log);
	const originContext = await browser.newContext({ baseURL });
	const otherContext = await browser.newContext({ baseURL });
	const origin = await originContext.newPage();
	const other = await otherContext.newPage();
	const sent: Array<{ type: string; payload: Record<string, any> }> = [];
	let droppedAck = false;
	const readLocalTurn = async (page: any, messageId: string) => page.evaluate(async (id: string) => {
		const open = indexedDB.open('chats_db');
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			open.onsuccess = () => resolve(open.result);
			open.onerror = () => reject(open.error);
		});
		try {
			const request = db.transaction('messages', 'readonly').objectStore('messages').get(id);
			const row = await new Promise<Record<string, any> | undefined>((resolve, reject) => {
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			return { present: Boolean(row), journal: typeof row?.pending_encrypted_turn_preflight_v1 === 'string',
				marker: row?.pending_turn_preflight_v1 === 1 };
		} finally { db.close(); }
	}, messageId);
	try {
		await origin.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
			const server = socket.connectToServer();
			socket.onMessage((raw: unknown) => {
				try {
					const frame = JSON.parse(String(raw));
					if (frame.type === 'chat_turn_preflight') sent.push({ type: frame.type, payload: frame.payload ?? {} });
				} catch { /* Ignore non-JSON transport frames. */ }
				server.send(raw);
			});
			server.onMessage((raw: unknown) => {
				try {
					if (JSON.parse(String(raw)).type === 'chat_turn_preflight_ack' && !droppedAck) {
						droppedAck = true;
						return;
					}
				} catch { /* Ignore non-JSON transport frames. */ }
				socket.send(raw);
			});
		});
		await installE2EServerContentOverrideGate(origin, 'storage-recovery-replay');
		await loginToTestAccount(origin, log, screenshot);
		await startNewChat(origin, log);
		// The test deliberately withholds canonical acceptance. Keep the
		// helper's result observed while proving the exact durable pending turn.
		const sendState: { outcome: { accepted: boolean; error?: unknown } | null } = { outcome: null };
		const pendingSend = sendMessage(origin,
			'Deleted turn must stay deleted. STORAGE_CAPACITY_SCENARIO:round <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-deleted-turn')
			.then(() => { sendState.outcome = { accepted: true }; },
				(error: unknown) => { sendState.outcome = { accepted: false, error }; });
		await expect.poll(() => droppedAck).toBe(true);
		await expect.poll(() => origin.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null,
			{ timeout: 30_000 }).toBeTruthy();
		const chatId = origin.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		const first = sent.find((frame) => frame.payload.chat_id === chatId);
		expect(first?.payload.message_id).toBeTruthy();
		const messageId = first!.payload.message_id;
		await expect.poll(() => readLocalTurn(origin, messageId), { timeout: 30_000 })
			.toEqual({ present: true, journal: true, marker: true });
		await expect(origin.getByTestId('message-user').last()).toHaveAttribute('data-status', 'sending');
		expect(sendState.outcome, 'The live send must still be awaiting its deliberately dropped ACK').toBeNull();
		await origin.close(); // Keep originContext and its IndexedDB journal intact.
		await pendingSend;
		expect(sendState.outcome?.accepted, 'A dropped preflight ACK must not be accepted').toBe(false);
		if (sendState.outcome && !sendState.outcome.accepted) {
			expect(String(sendState.outcome.error), 'Only the expected closed-page or acceptance-timeout result may be ignored')
				.toMatch(/Target page, context or browser has been closed|Timeout 20000ms exceeded/);
		}

		await loginToTestAccount(other, log, screenshot);
		await other.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId!)}`));
		const sidebar = other.getByTestId('activity-history-wrapper');
		if (!(await sidebar.isVisible().catch(() => false))) await other.getByTestId('sidebar-toggle').click();
		const item = other.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
		await expect(item).toBeVisible({ timeout: 60_000 });
		await item.click({ button: 'right' });
		const deleteButton = other.getByTestId('chat-context-delete');
		await expect(deleteButton).toBeVisible();
		await deleteButton.click();
		await deleteButton.click();
		await expect(item).not.toBeVisible({ timeout: 30_000 });

		const restored = await originContext.newPage();
		const replayed: Array<{ type: string; payload: Record<string, any> }> = [];
		restored.on('websocket', (socket: any) => {
			for (const [direction, event] of [['sent', 'framesent'], ['received', 'framereceived']]) {
				socket.on(event, (frame: any) => {
					try {
						const parsed = JSON.parse(String(frame.payload));
						replayed.push({ type: `${direction}:${parsed.type}`, payload: parsed.payload ?? {} });
					} catch { /* Ignore non-JSON transport frames. */ }
				});
			}
		});
		// This page reuses the authenticated originContext and its IndexedDB
		// journal; a second login races the existing session's UI hydration.
		await restored.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId!)}`), { waitUntil: 'domcontentloaded' });
		await expect(restored.locator('[data-authenticated="true"]').first()).toBeVisible({ timeout: 30_000 });
		await expect.poll(() => replayed.some((frame) => frame.type === 'received:phase_2_last_20_chats_ready'
			&& frame.payload.explicit_deleted_chat_ids?.includes(chatId)), { timeout: 60_000 }).toBe(true);
		await expect.poll(() => readLocalTurn(restored, messageId), { timeout: 30_000 })
			.toEqual({ present: false, journal: false, marker: false });
		expect(replayed.some((frame) => frame.type === 'sent:chat_turn_preflight'
			&& frame.payload.chat_id === chatId), 'Deleted chat must not replay the old preflight').toBe(false);
	} finally {
		await originContext.close();
		await otherContext.close();
	}
});
