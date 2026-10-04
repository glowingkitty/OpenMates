/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed, provider-free canonical recovery receipts. */
// contract-test-file: infrastructure
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');
const { requireSignedRecoveryProfile, observeRecoveryFrames, availableOutputs, requireActiveRecoveryDiscovery, disconnectCanonicalWrites, installLegacyRecoverySocket } = require('./storage-recovery-fixtures');
import type { RecoveryFrame } from './storage-recovery-fixtures';
const { createHash } = require('node:crypto');

function summarizeReceiptWire(frames: RecoveryFrame[], recordId: string): Array<Record<string, unknown>> {
	const sentRequests = new Map<string, string>();
	for (const frame of frames) {
		const requestId = frame.payload.request_id;
		if (frame.direction === 'sent' && typeof requestId === 'string') sentRequests.set(requestId, frame.type);
	}
	return frames.filter((frame) => frame.type.startsWith('recovery_output_')
		|| frame.type.startsWith('store_embed') || frame.type === 'error').slice(-60).map((frame) => {
		const requestId = typeof frame.payload.request_id === 'string' ? frame.payload.request_id : null;
		const code = typeof frame.payload.code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(frame.payload.code)
			? frame.payload.code : null;
		const message = typeof frame.payload.message === 'string' ? frame.payload.message : '';
		const messageClass = message === 'Failed to store embed' ? 'embed_storage_failure'
			: message === 'Not authorized to store embed' ? 'embed_authorization_failure'
			: message ? 'other' : null;
		const candidateRecord = frame.payload.recovery_record_id ?? frame.payload.record_id;
		return {
			direction: frame.direction ?? 'received', type: frame.type,
			request_hash: requestId ? createHash('sha256').update(requestId).digest('hex').slice(0, 12) : null,
			request_sent_as: requestId && frame.direction !== 'sent' ? sentRequests.get(requestId) ?? null : null,
			target_record_match: typeof candidateRecord === 'string' ? candidateRecord === recordId : null,
			code, message_class: messageClass,
			state: ['ACKNOWLEDGED', 'PENDING', 'READY'].includes(frame.payload.state) ? frame.payload.state : null,
		};
	});
}

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.completion.recovery-takeover
test('legacy connection preserves typed rows while completing the existing v1 final job', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const log = createSignupLogger('storage-recovery-capability-gate');
	const screenshot = createStepScreenshotter(log);
	const producerContext = await browser.newContext({ baseURL });
	const legacyContext = await browser.newContext({ baseURL });
	const capableContext = await browser.newContext({ baseURL });
	const producer = await producerContext.newPage();
	const legacy = await legacyContext.newPage();
	const capable = await capableContext.newPage();
	const producerFrames: RecoveryFrame[] = [];
	const legacyFrames = observeRecoveryFrames(legacy);
	const capableFrames = observeRecoveryFrames(capable, true);
	try {
		await disconnectCanonicalWrites(producer, producerFrames);
		await installE2EServerContentOverrideGate(producer, 'storage-recovery-replay');
		await loginToTestAccount(producer, log, screenshot);
		await requireActiveRecoveryDiscovery(producerFrames);
		await startNewChat(producer, log);
		await sendMessage(producer,
			'Generate gated recovery data. STORAGE_CAPACITY_SCENARIO:recovery_embed <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-capability-producer');
		const chatId = producer.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await expect.poll(() => availableOutputs(producerFrames, chatId!).length,
			{ timeout: 180_000 }).toBeGreaterThan(0);
		const pendingIds = [...new Set(availableOutputs(producerFrames, chatId!)
			.map((output: any) => String(output.record_id)))];
		const rejectedEmbedId = `legacy-${pendingIds[0]}`;
		await producerContext.close();

		await installLegacyRecoverySocket(legacy);
		await loginToTestAccount(legacy, log, screenshot);
		await legacy.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await expect.poll(() => legacyFrames.some((frame) => frame.type === 'recovery_job_persisted'
			&& frame.payload.state === 'TERMINAL'), { timeout: 120_000 }).toBe(true);
		expect(legacyFrames.some((frame) => frame.type === 'recovery_outputs_available')).toBe(false);
		const rejectionRequests = await legacy.evaluate(({ recordId, rejectedEmbedId, chatId }) => {
			const socket = (window as any).__legacyRecoverySocket as WebSocket;
			const attempts: Array<[string, Record<string, unknown>]> = [
				['recovery_output_get', { protocol_version: 1, record_id: recordId }],
				['recovery_output_ack_embed', { protocol_version: 1, record_id: recordId,
					canonical_digest: '0'.repeat(64), canonical_source: 'head' }],
				['store_embed', { embed_id: rejectedEmbedId, encrypted_content: 'invalid' }],
				['store_embed_keys', { keys: [{
					hashed_embed_id: '0'.repeat(64), key_type: 'master', encrypted_embed_key: 'invalid',
				}] }],
				['store_embed_diff', { embed_id: rejectedEmbedId, version_number: 2,
					encrypted_patch: 'invalid' }],
				['commit_embed_revision', { operation_id: crypto.randomUUID(), embed_id: rejectedEmbedId,
					project_id: crypto.randomUUID(), chat_id: chatId, proposal_digest: '0'.repeat(64) }],
			];
			return attempts.map(([type, payload]) => {
				const requestId = crypto.randomUUID();
				socket.send(JSON.stringify({ type, payload: { ...payload, request_id: requestId } }));
				return { type, requestId };
			});
		}, { recordId: pendingIds[0], rejectedEmbedId, chatId });
		expect(new Set(rejectionRequests.map(({ requestId }) => requestId)).size).toBe(6);
		await expect.poll(() => rejectionRequests.every(({ requestId }) => legacyFrames.some((frame) =>
			frame.type === 'error' && frame.payload.request_id === requestId
			&& frame.payload.code === 'client_capability_required'))).toBe(true);
		expect(legacyFrames.some((frame) => frame.type === 'recovery_output_ready'
			|| frame.type === 'recovery_output_embed_acknowledged'
			|| frame.type === 'store_embed_confirmed'
			|| frame.type === 'store_embed_keys_confirmed'
			|| frame.type === 'store_embed_diff_confirmed'
			|| frame.type === 'commit_embed_revision_result')).toBe(false);
		const apiOrigin = process.env.PLAYWRIGHT_TEST_API_URL;
		if (!apiOrigin) throw new Error('Isolated recovery replay requires PLAYWRIGHT_TEST_API_URL.');
		const rejectedRead = await legacy.evaluate(async ({ chatId, embedId, apiOrigin }) => {
			const options = { credentials: 'include' as const };
			const head = await fetch(`${apiOrigin}/v1/embeds/chats/${encodeURIComponent(chatId)}`
				+ `/embeds/${encodeURIComponent(embedId)}`, options);
			const versions = await fetch(`${apiOrigin}/v1/embeds/${encodeURIComponent(embedId)}/versions`
				+ `?chat_id=${encodeURIComponent(chatId)}`, options);
			const wrappers = await fetch(`${apiOrigin}/v1/embeds/chats/${encodeURIComponent(chatId)}/keys/window`
				+ `?embed_ids=${encodeURIComponent(embedId)}`, options);
			return { head: head.status, versions: versions.status, wrappers: wrappers.status };
		}, { chatId, embedId: rejectedEmbedId, apiOrigin: apiOrigin.replace(/\/$/, '') });
		expect(rejectedRead).toEqual({ head: 404, versions: 404, wrappers: 404 });
		await legacyContext.close();

		await loginToTestAccount(capable, log, screenshot);
		await capable.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await expect.poll(() => {
			const rediscovered = new Set(availableOutputs(capableFrames, chatId!).map((output: any) => String(output.record_id)));
			return pendingIds.every((id) => rediscovered.has(id));
		}, { timeout: 180_000 }).toBe(true);
		for (const recordId of pendingIds) {
			try {
				await expect.poll(() => capableFrames.some((frame) => [
				'recovery_output_persisted', 'recovery_output_summary_persisted',
				'recovery_output_checkpoint_acknowledged', 'recovery_output_embed_acknowledged',
			].includes(frame.type) && frame.payload.record_id === recordId
				&& frame.payload.state === 'ACKNOWLEDGED'), { timeout: 120_000 }).toBe(true);
			} catch (error) {
				throw new Error(`Exact typed recovery ACK missing: ${String(error)}; `
					+ `wire=${JSON.stringify(summarizeReceiptWire(capableFrames, recordId))}`);
			}
		}
		const headReceipt = capableFrames.find((frame) => frame.type === 'store_embed_confirmed');
		expect(headReceipt?.payload.canonical_source).toBe('head');
		expect(headReceipt?.payload.canonical_digest).toMatch(/^[0-9a-f]{64}$/);
		const keyReceipt = capableFrames.find((frame) => frame.type === 'store_embed_keys_confirmed');
		expect(keyReceipt?.payload).toMatchObject({ requested_count: 2, created_count: 2, failed_count: 0 });
	} finally {
		await producerContext.close().catch(() => undefined);
		await legacyContext.close().catch(() => undefined);
		await capableContext.close().catch(() => undefined);
	}
});

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,code-run.artifacts.chat-bound-versioned
test('saved code embed and version diff replay with canonical ciphertext acknowledgements', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const log = createSignupLogger('storage-recovery-artifacts');
	const screenshot = createStepScreenshotter(log);
	const first = await browser.newContext({ baseURL });
	const firstPage = await first.newPage();
	const firstFrames: RecoveryFrame[] = [];
	const restored = await browser.newContext({ baseURL });
	const restoredPage = await restored.newPage();
	const frames: Array<{ direction: string; type: string; payload: Record<string, any> }> = [];
	const recoveryErrors: string[] = [];
	restoredPage.on('console', (entry: any) => {
		if (entry.type() === 'error' && entry.text().includes('[ChatSyncService:Recovery]')) {
			const message = entry.text();
			recoveryErrors.push(message.includes('Canonical store_embed confirmation timed out')
				? 'embed_receipt_timeout' : message.includes('embed_storage_failed')
					? 'embed_storage_failed' : 'other_recovery_error');
		}
	});
	restoredPage.on('websocket', (socket: any) => {
		for (const [direction, event] of [['sent', 'framesent'], ['received', 'framereceived']]) {
			socket.on(event, (frame: any) => {
				try {
					const parsed = JSON.parse(String(frame.payload));
					frames.push({ direction, type: parsed.type, payload: parsed.payload ?? {} });
				} catch { /* Ignore non-JSON frames. */ }
			});
		}
	});
	try {
		await disconnectCanonicalWrites(firstPage, firstFrames);
		await installE2EServerContentOverrideGate(firstPage, 'storage-recovery-replay');
		await loginToTestAccount(firstPage, log, screenshot);
		await requireActiveRecoveryDiscovery(firstFrames);
		await startNewChat(firstPage, log);
		await sendMessage(firstPage,
			'Generate the scripted code artifact. STORAGE_CAPACITY_SCENARIO:recovery_embed <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-recovery-embed');
		const chatId = firstPage.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await expect.poll(() => availableOutputs(firstFrames, chatId!).map((output) => output.output_kind),
			{ timeout: 120_000, message: 'Origin must publish sealed code embed and diff before disconnect' })
			.toEqual(expect.arrayContaining(['embed', 'diff']));
		await first.close();
		await loginToTestAccount(restoredPage, log, screenshot);
		await restoredPage.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await expect.poll(() => frames.filter((frame) => frame.direction === 'received'
			&& frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.filter((output: any) => output.root_chat_id === chatId)
			.map((output: any) => output.output_kind), { timeout: 180_000 })
			.toEqual(expect.arrayContaining(['embed', 'diff']));
		const records = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.filter((output: any) => output.root_chat_id === chatId && ['embed', 'diff'].includes(output.output_kind));
		for (const output of records) {
			try {
				await expect.poll(() => frames.some((frame) => frame.direction === 'received'
					&& frame.type === 'recovery_output_embed_acknowledged'
					&& frame.payload.record_id === output.record_id && frame.payload.state === 'ACKNOWLEDGED'),
				{ timeout: 120_000 }).toBe(true);
			} catch (error) {
				throw new Error(`Recovered ${output.output_kind} v${output.output_version} canonical ACK missing: ${String(error)}; `
					+ `wire=${JSON.stringify(summarizeReceiptWire(frames, output.record_id))}; `
					+ `recoveryErrors=${JSON.stringify(recoveryErrors.slice(-5))}`);
			}
		}
		const update = await browser.newContext({ baseURL });
		try {
			const updatePage = await update.newPage();
			const updateFrames: RecoveryFrame[] = [];
			await disconnectCanonicalWrites(updatePage, updateFrames);
			await installE2EServerContentOverrideGate(updatePage, 'storage-recovery-replay');
			await loginToTestAccount(updatePage, log, screenshot);
			await requireActiveRecoveryDiscovery(updateFrames);
			await updatePage.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
			await sendMessage(updatePage,
				'Apply the scripted patch to recovery_demo.py. STORAGE_CAPACITY_SCENARIO:recovery_diff <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
				log, screenshot, 'storage-recovery-diff');
			await expect.poll(() => availableOutputs(updateFrames, chatId!).some((output) =>
				output.output_kind === 'diff' && output.output_version > 1),
			{ timeout: 120_000, message: 'Origin must publish the sealed version diff before disconnect' })
				.toBe(true);
		} finally {
			await update.close();
		}
		await restoredPage.reload();
		await expect.poll(() => frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.some((output: any) => output.root_chat_id === chatId
				&& output.output_kind === 'diff' && output.output_version > 1),
		{ timeout: 180_000 }).toBe(true);
		const patch = frames.filter((frame) => frame.type === 'recovery_outputs_available')
			.flatMap((frame) => frame.payload.outputs ?? [])
			.find((output: any) => output.root_chat_id === chatId
				&& output.output_kind === 'diff' && output.output_version > 1);
		await expect.poll(() => frames.some((frame) => frame.direction === 'received'
			&& frame.type === 'recovery_output_embed_acknowledged'
			&& frame.payload.record_id === patch.record_id && frame.payload.state === 'ACKNOWLEDGED'),
		{ timeout: 120_000 }).toBe(true);
		await restoredPage.reload();
		await expect(restoredPage.getByTestId('message-assistant').first()).toBeVisible();
	} finally {
		await first.close().catch(() => undefined);
		await restored.close();
	}
});
