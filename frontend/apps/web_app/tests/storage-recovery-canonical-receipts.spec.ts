/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed, provider-free canonical recovery receipts. */
// contract-test-file: infrastructure
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');
const { requireSignedRecoveryProfile, observeRecoveryFrames, availableOutputs, requireActiveRecoveryDiscovery, focusRecoveryPage, requireForegroundRecoveryLifecycle, disconnectCanonicalWrites, installLegacyRecoverySocket } = require('./storage-recovery-fixtures');
import type { RecoveryFrame } from './storage-recovery-fixtures';
const { createHash } = require('node:crypto');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair, runWorkflowCli, runWorkflowCliJson, parseCliJson, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');

async function recordedContext(browser: any, baseURL: string | undefined, label: string): Promise<any> {
	const context = await browser.newContext({ baseURL, recordVideo: { dir: test.info().outputPath(label) } });
	const videos: any[] = [];
	context.on('page', (page: any) => { if (page.video()) videos.push(page.video()); });
	const close = context.close.bind(context);
	let closed = false;
	context.close = async (...args: any[]) => {
		if (closed) return;
		closed = true;
		await close(...args);
		for (const [index, video] of videos.entries()) {
			await test.info().attach(`${label}-${index}`, { path: await video.path(), contentType: 'video/webm' });
		}
	};
	return context;
}

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

function isolatedBillingSnapshot(label: string): Record<string, unknown> {
	const accountEmail = getTestAccount().email;
	if (!accountEmail) throw new Error('Disposable account is required for isolated billing diagnostics');
	let snapshot: Record<string, unknown>;
	try {
		snapshot = isolatedServiceRegression('billing_snapshot', { account_email: accountEmail });
	} catch {
		snapshot = { status: 'unavailable' };
	}
	console.log(`[isolated-billing:${label}] ${JSON.stringify(snapshot)}`);
	return snapshot;
}

async function withBillingFailureDiagnostic<T>(
	frames: RecoveryFrame[], label: string, waitForOutput: () => Promise<T>,
): Promise<T> {
	let timer: ReturnType<typeof setInterval>;
	let captured = false;
	const streamError = new Promise<never>((_resolve, reject) => {
		timer = setInterval(() => {
			if (captured || !frames.some((frame) => frame.type === 'ai_message_update'
				&& frame.payload.is_final_chunk === true
				&& (frame.payload.error === true || frame.payload.failure_reason === 'stream_error'
					|| /Sorry, something went wrong while I was trying to process your message|AI service encountered an error/i
						.test(String(frame.payload.full_content_so_far ?? ''))))) return;
			captured = true;
			const snapshot = isolatedBillingSnapshot(label);
			reject(new Error(`Synthetic producer ended with a terminal stream error; billing=${JSON.stringify(snapshot)}`));
		}, 250);
	});
	try {
		return await Promise.race([waitForOutput(), streamError]);
	} catch (error) {
		if (!captured) isolatedBillingSnapshot(label);
		throw error;
	} finally {
		clearInterval(timer!);
	}
}

// contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.completion.recovery-takeover
test('legacy connection preserves typed rows while completing the existing v1 final job', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const log = createSignupLogger('storage-recovery-capability-gate');
	const screenshot = createStepScreenshotter(log);
	const producerContext = await recordedContext(browser, baseURL, 'producer');
	const legacyContext = await recordedContext(browser, baseURL, 'legacy');
	const capableContext = await recordedContext(browser, baseURL, 'capable');
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
		await focusRecoveryPage(legacy);
		await loginToTestAccount(legacy, log, screenshot);
		await legacy.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`));
		await requireForegroundRecoveryLifecycle(legacyFrames);
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
			const options = { credentials: 'include' as const,
				headers: { 'x-openmates-client-capabilities': 'agentic-storage-v2' } };
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

		await focusRecoveryPage(capable);
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
	const first = await recordedContext(browser, baseURL, 'origin');
	const firstPage = await first.newPage();
	const firstFrames: RecoveryFrame[] = [];
	const restored = await recordedContext(browser, baseURL, 'restored');
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
		await withBillingFailureDiagnostic(firstFrames, 'saved-first-turn', () =>
			expect.poll(() => availableOutputs(firstFrames, chatId!).map((output) => output.output_kind),
				{ timeout: 120_000, message: 'Origin must publish sealed code embed and diff before disconnect' })
				.toEqual(expect.arrayContaining(['embed', 'diff'])));
		isolatedBillingSnapshot('saved-first-turn-complete');
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
		const update = await recordedContext(browser, baseURL, 'update');
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
			await withBillingFailureDiagnostic(updateFrames, 'saved-diff-turn', () =>
				expect.poll(() => availableOutputs(updateFrames, chatId!).some((output) =>
					output.output_kind === 'diff' && output.output_version > 1),
				{ timeout: 120_000, message: 'Origin must publish the sealed version diff before disconnect' })
					.toBe(true));
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

// contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery,chats.completion.recovery-takeover,chats.persistence.client-encrypted
test('CLI bootstraps root wrappers before protected canonical reads and replay stays idempotent', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(360_000);
	installRecorderDeps();
	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL;
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('root-recovery');
	const context = await recordedContext(browser, baseURL, 'cli-pairing-and-producer');
	const page = await context.newPage();
	const frames: RecoveryFrame[] = [];
	const log = createSignupLogger('storage-cli-root-recovery');
	const screenshot = createStepScreenshotter(log);
	try {
		await disconnectCanonicalWrites(page, frames);
		await installE2EServerContentOverrideGate(page, 'storage-recovery-replay');
		await focusRecoveryPage(page);
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_ROOT_RECOVERY');
		await requireActiveRecoveryDiscovery(frames);
		await startNewChat(page, log);
		await sendMessage(page,
			'Generate a CLI recovery artifact. STORAGE_CAPACITY_SCENARIO:recovery_embed <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
			log, screenshot, 'storage-cli-root-producer');
		const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		await withBillingFailureDiagnostic(frames, 'cli-producer', () =>
			expect.poll(() => availableOutputs(frames, chatId!).some((output) => output.output_kind === 'embed'),
				{ timeout: 120_000 }).toBe(true));
		const output = availableOutputs(frames, chatId!).find((row) => row.output_kind === 'embed') as any;
		expect(output.subject_id).toBeTruthy();
		const readHead = () => page.evaluate(async ({ apiUrl, chatId, embedId }) => {
			const response = await fetch(`${apiUrl}/v1/embeds/chats/${chatId}/embeds/${embedId}`, {
				credentials: 'include', headers: { 'x-openmates-client-capabilities': 'agentic-storage-v2' },
			});
			return { status: response.status, body: response.ok ? await response.json() : null };
		}, { apiUrl, chatId, embedId: output.subject_id });
		expect((await readHead()).status).toBe(404);
		const replay = await runWorkflowCli(apiUrl, home, ['chats', 'show', chatId, '--json'], 180_000,
			{ OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'storage-recovery-canonical-receipts.spec.ts' });
		if (!replay.recording || !fs.existsSync(replay.recording.videoPath) || !fs.existsSync(replay.recording.manifestPath)) {
			let reason = `exit ${replay.code}`;
			try {
				const failure = JSON.parse(replay.stdout);
				if (typeof failure.reason === 'string') reason = failure.reason.slice(0, 500);
			} catch { /* Preserve the bounded exit diagnostic when no recorder receipt exists. */ }
			throw new Error(`CLI recovery terminal capture unavailable: ${reason}`);
		}
		await test.info().attach('cli-root-recovery', { path: replay.recording.videoPath, contentType: 'video/mp4' });
		await test.info().attach('cli-root-recovery-manifest', { path: replay.recording.manifestPath, contentType: 'application/json' });
		const recovered = parseCliJson(replay, 'Recover root');
		expect(recovered.error, 'CLI root recovery must complete without a command error').toBeUndefined();
		expect(recovered.chat?.id).toBe(chatId);
		const first = await readHead();
		expect(first.status).toBe(200);
		expect(first.body.embed.version_number).toBe(output.output_version);
		expect(first.body.embed.parent_embed_id ?? null).toBeNull();
		expect(first.body.embed_keys.map((row: any) => row.key_type).sort()).toEqual(['chat', 'master']);
		await runWorkflowCliJson(apiUrl, home, ['chats', 'show', chatId], 'Repeat root read', 180_000);
		const repeated = await readHead();
		expect(repeated.body.embed.encrypted_content).toBe(first.body.embed.encrypted_content);
		expect(repeated.body.embed.version_number).toBe(first.body.embed.version_number);
		expect(repeated.body.embed_keys.map((row: any) => row.encrypted_embed_key).sort())
			.toEqual(first.body.embed_keys.map((row: any) => row.encrypted_embed_key).sort());
		frames.length = 0;
		await page.reload();
		await requireActiveRecoveryDiscovery(frames);
		expect(availableOutputs(frames, chatId!).filter((row) => ['embed', 'diff'].includes(row.output_kind))).toEqual([]);
		await expect.poll(() => {
			const billing = isolatedBillingSnapshot('replay-settled');
			return {
				status: billing.status,
				held: billing.active_held_count,
				unmatched: billing.unmatched_settlement_count,
				settled: Number((billing.reservation_status as any)?.settled) > 0,
				charged: typeof billing.balance_credits === 'number' && billing.balance_credits < 1000,
			};
		}, { timeout: 30_000, intervals: [1000, 1500, 3000],
			message: 'Completed replay turns must settle their real reservations and wallet charges' })
			.toEqual({ status: 'ok', held: 0, unmatched: 0, settled: true, charged: true });
	} finally {
		await context.close();
		removeWorkflowCliHome(home);
	}
});

function batchAuthorityFixture(ownerId: string, ids: Record<string, string>, operation: 'seed' | 'verify' | 'cleanup'): void {
	const root = path.resolve(__dirname, '../../../..');
	const compose = path.join(root, 'test-results/ci-private/compose.json');
	expect(process.env.GITHUB_ACTIONS).toBe('true');
	expect(fs.existsSync(compose), 'Requires the disposable CI stack').toBe(true);
	const program = `
import asyncio,hashlib,json,logging,os,sys,time,uuid
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
async def main():
    data=json.load(sys.stdin); ids=data['ids']; owner=data['ownerId']; op=data['operation']
    cache=CacheService(); ds=DirectusService(cache_service=cache)
    digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
    try:
        if op=='seed':
            for key in ('team','forbiddenTeam'):
                ok,_=await ds.create_item('teams',{'team_id':ids[key],'hashed_team_id':digest(ids[key]),'slug':ids[key],
                    'encrypted_name':'fixture-ciphertext','status':'active','created_at':int(time.time()),'updated_at':int(time.time())},admin_required=True)
                assert ok
            ok,_=await ds.create_item('team_memberships',{'hashed_team_id':digest(ids['team']),'hashed_user_id':digest(owner),
                'user_id':owner,'role':'viewer','status':'active','joined_at':int(time.time()),'created_at':int(time.time())},admin_required=True)
            assert ok
            for key in ('deleting','liveTeam','forbidden','personal'):
                row={'id':ids[key],'hashed_user_id':None if key=='liveTeam' else digest(owner),
                    'hashed_team_id':digest(ids['team']) if key=='liveTeam' else digest(ids['forbiddenTeam']) if key=='forbidden' else None,
                    'messages_v':0,'title_v':0,'metadata_v':0,'archived_message_count':0,
                    'storage_state':'deleting' if key=='deleting' else 'hot','created_at':int(time.time()),'updated_at':int(time.time())}
                ok,_=await ds.chat.create_chat_in_directus(row); assert ok
            for key in ('liveTeam','personal'):
                ok,_=await ds.create_item('messages',{'client_message_id':str(uuid.uuid4()),'chat_id':ids[key],
                    'hashed_user_id':digest(owner),'encrypted_content':'fixture-'+key+'-ciphertext',
                    'role':'user','created_at':int(time.time()),'updated_at':int(time.time())},admin_required=True)
                assert ok
            ok,_=await ds.create_item('chat_key_wrappers',{'hashed_chat_id':digest(ids['liveTeam']),
                'hashed_team_id':digest(ids['team']),'hashed_user_id':None,'key_type':'team','team_key_epoch':1,
                'encrypted_chat_key':'fixture-team-ciphertext','wrapper_version':1,'created_at':int(time.time())},admin_required=True)
            assert ok
            for key in ('alias','absent','deleting','liveTeam','forbidden','personal'):
                assert await cache.add_chat_to_ids_versions(owner,ids[key],int(time.time()))
        elif op=='verify':
            cached=set(await cache.get_chat_ids_versions(owner))
            assert all(ids[key] not in cached for key in ('alias','absent','deleting','forbidden'))
            assert all(ids[key] in cached for key in ('liveTeam','personal'))
        else:
            for key in ('liveTeam','personal'):
                rows=await ds.get_items('messages',params={'filter':{'chat_id':{'_eq':ids[key]}},'fields':'id','limit':5},admin_required=True,no_cache=True,raise_on_error=True)
                for row in rows: await ds.delete_item('messages',row['id'],admin_required=True)
            rows=await ds.get_items('chat_key_wrappers',params={'filter':{'hashed_chat_id':{'_eq':digest(ids['liveTeam'])}},'fields':'id','limit':5},admin_required=True,no_cache=True,raise_on_error=True)
            for row in rows: await ds.delete_item('chat_key_wrappers',row['id'],admin_required=True)
            for key in ('alias','absent','deleting','liveTeam','forbidden','personal'):
                await cache.remove_chat_from_ids_versions(owner,ids[key])
            for key in ('deleting','liveTeam','forbidden','personal'):
                await ds.delete_item('chats',ids[key],admin_required=True)
            for key in ('team','forbiddenTeam'):
                for collection in ('team_memberships','teams'):
                    rows=await ds.get_items(collection,params={'filter':{'hashed_team_id':{'_eq':digest(ids[key])}},'fields':'id','limit':5},admin_required=True,no_cache=True,raise_on_error=True)
                    for row in rows: await ds.delete_item(collection,row['id'],admin_required=True)
        print('batch authority fixture applied')
    finally:
        await ds.close(); await cache.close()
asyncio.run(main())
`;
	const result = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T', '-e', 'OPENMATES_CI_ISOLATED=1',
		'api', 'python', '-c', program], { cwd: root, input: JSON.stringify({ ownerId, ids, operation }), encoding: 'utf8', timeout: 60_000 });
	expect(result.trim()).toBe('batch authority fixture applied');
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('batch skips stale and non-UUID cached chats while preserving personal and Team authority', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(180_000);
	const context = await recordedContext(browser, process.env.PLAYWRIGHT_TEST_BASE_URL, 'batch-authority');
	const page = await context.newPage();
	const frames = observeRecoveryFrames(page);
	const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('batch-authority');
	const ids = Object.fromEntries(['absent', 'deleting', 'liveTeam', 'forbidden', 'personal', 'team', 'forbiddenTeam'].map((key) => [key, randomUUID()]));
	ids.alias = 'legal-imprint';
	let ownerId: string | undefined;
	try {
		await page.addInitScript(() => {
			const Native = window.WebSocket;
			const Capture = function(url: string | URL, protocols?: string | string[]) {
				const socket = protocols === undefined ? new Native(url) : new Native(url, protocols);
				if (String(url).includes('/v1/ws')) Object.assign(window, { __batchAuthoritySocket: socket });
				return socket;
			} as unknown as typeof WebSocket;
			Capture.prototype = Native.prototype;
			for (const field of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'] as const) {
				Object.defineProperty(Capture, field, { value: Native[field] });
			}
			Object.defineProperty(window, 'WebSocket', { value: Capture, configurable: true });
		});
		await loginWorkflowCliViaPair(page, apiUrl, home, 'BATCH_AUTHORITY');
		const identity = await runWorkflowCliJson(apiUrl, home, ['whoami'], 'Identify disposable owner');
		ownerId = identity.id ?? identity.user_id;
		expect(ownerId).toBeTruthy();
		batchAuthorityFixture(ownerId!, ids, 'seed');
		const requestBatch = async (chatIds: string[]): Promise<any> => {
			const before = frames.filter((frame) => frame.type === 'chat_content_batch_response').length;
			await page.evaluate((requestedIds) => {
				const socket = (window as any).__batchAuthoritySocket as WebSocket;
				if (socket.readyState !== WebSocket.OPEN) throw new Error('Authenticated socket must be open');
				socket.send(JSON.stringify({ type: 'request_chat_content_batch', payload: { chat_ids: requestedIds } }));
			}, chatIds);
			await expect.poll(() => frames.filter((frame) => frame.type === 'chat_content_batch_response').length)
				.toBeGreaterThan(before);
			return frames.filter((frame) => frame.type === 'chat_content_batch_response')[before].payload as any;
		};
		const response = await requestBatch(['alias', 'absent', 'liveTeam', 'forbidden', 'personal'].map((key) => ids[key]));
		expect(response.partial_error).toBeUndefined();
		expect(Object.keys(response.versions_by_chat_id).sort()).toEqual([ids.liveTeam, ids.personal].sort());
		for (const key of ['liveTeam', 'personal']) {
			expect(response.messages_by_chat_id[ids[key]]).toHaveLength(1);
			expect(JSON.parse(response.messages_by_chat_id[ids[key]][0]).encrypted_content)
				.toBe(`fixture-${key}-ciphertext`);
			expect(response.versions_by_chat_id[ids[key]].server_message_count).toBe(1);
		}
		expect(response.chat_key_wrappers).toHaveLength(1);
		expect(response.chat_key_wrappers[0]).toMatchObject({ key_type: 'team', encrypted_chat_key: 'fixture-team-ciphertext',
			hashed_team_id: createHash('sha256').update(ids.team).digest('hex') });
		for (const key of ['alias', 'absent', 'forbidden']) {
			expect(response.messages_by_chat_id[ids[key]]).toEqual([]);
			expect(response.message_windows_by_chat_id[ids[key]]).toBeUndefined();
			expect(response.embed_windows_by_chat_id[ids[key]]).toBeUndefined();
		}
		const deleting = await requestBatch([ids.deleting]);
		expect(deleting.partial_error).toBeUndefined();
		expect(deleting.messages_by_chat_id[ids.deleting]).toEqual([]);
		const aliasOnly = await requestBatch([ids.alias]);
		expect(aliasOnly.partial_error).toBeUndefined();
		expect(aliasOnly.messages_by_chat_id).toEqual({ [ids.alias]: [] });
		expect(aliasOnly.versions_by_chat_id).toEqual({});
		batchAuthorityFixture(ownerId!, ids, 'verify');
	} finally {
		try {
			if (ownerId) batchAuthorityFixture(ownerId, ids, 'cleanup');
		} finally {
			await context.close();
			removeWorkflowCliHome(home);
		}
	}
});

function isolatedServiceRegression(operation: string, ids: Record<string, string>): any {
	const root = path.resolve(__dirname, '../../../..');
	const compose = path.join(root, 'test-results/ci-private/compose.json');
	expect(process.env.GITHUB_ACTIONS).toBe('true');
	expect(fs.existsSync(compose), 'Requires the disposable CI stack').toBe(true);
	const program = fs.readFileSync(path.join(root, 'backend/tests/ci_service_error_regressions.py'), 'utf8');
	const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T', '-e', 'OPENMATES_CI_ISOLATED=1',
		'api', 'python', '-c', program], {
		cwd: root, input: JSON.stringify({ operation, ...ids }), encoding: 'utf8',
		timeout: operation === 'legacy_workflow_readiness' ? 180_000 : 120_000,
	});
	return JSON.parse(output.trim().split(/\r?\n/).at(-1)!);
}

// contract-test: infrastructure
test('orphaned recurring reminder is retired before any delivery and stays retired', async () => {
	requireSignedRecoveryProfile();
	test.setTimeout(150_000);
	const receipt = isolatedServiceRegression('orphan_reminder', {
		reminder_id: randomUUID(), owner_id: randomUUID(),
	});
	expect(receipt).toEqual({ status: 'cancelled', occurrence_count: 0, repeat_fired: false });
});

// contract-test: infrastructure
test('current Arena table creates a ranked snapshot and invalid feed preserves it', async () => {
	requireSignedRecoveryProfile();
	test.setTimeout(150_000);
	const receipt = isolatedServiceRegression('leaderboard_snapshot', {});
	expect(receipt.parsed_rows).toBe(30);
	expect(receipt.ranked_models).toBeGreaterThan(0);
	expect(receipt).toMatchObject({ source_valid: true, invalid_feed_preserved_snapshot: true });
});

// contract-test: supporting surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible
test('legacy accepted schedule without a reachable effect fails its durable run immediately', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(240_000);
	const context = await recordedContext(browser, process.env.PLAYWRIGHT_TEST_BASE_URL, 'legacy-workflow-readiness');
	const page = await context.newPage();
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('legacy-workflow-readiness');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'LEGACY_WORKFLOW_READINESS');
		const identity = await runWorkflowCliJson(apiUrl, home, ['whoami'], 'Identify disposable workflow owner');
		const ownerId = identity.id ?? identity.user_id;
		expect(ownerId).toMatch(/^[0-9a-f-]{36}$/i);
		const receipt = isolatedServiceRegression('legacy_workflow_readiness', {
			owner_id: ownerId, fixture_id: randomUUID(),
		});
		expect(receipt).toEqual({
			run_status: 'failed',
			error_summary: 'Workflow readiness requires a reachable qualifying effect',
			node_runs: 0, finished_immediately: true,
		});
	} finally {
		await context.close();
		removeWorkflowCliHome(home);
	}
});

// contract-test: supporting surface=rest_api assertions=chats.context.related-work-selection,tasks.activity.task-scoped-authorization
test('recent Task Activity uses integer Directus bounds and preserves personal and Team scope', async ({ browser }: { browser: any }) => {
	requireSignedRecoveryProfile();
	test.setTimeout(180_000);
	const context = await recordedContext(browser, process.env.PLAYWRIGHT_TEST_BASE_URL, 'recent-task-activity');
	const page = await context.newPage();
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('recent-task-activity');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'RECENT_TASK_ACTIVITY');
		const identity = await runWorkflowCliJson(apiUrl, home, ['whoami'], 'Identify disposable Task owner');
		const ownerId = identity.id ?? identity.user_id;
		expect(ownerId).toMatch(/^[0-9a-f-]{36}$/i);
		const receipt = isolatedServiceRegression('recent_task_activity', {
			owner_id: ownerId, fixture_id: randomUUID(),
		});
		expect(receipt).toEqual({
			personal_scope: true, team_scope: true,
			fractional_query_succeeded: true, exact_boundary_preserved: true,
		});
	} finally {
		await context.close();
		removeWorkflowCliHome(home);
	}
});

// contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
test('OpenRouter health probe falls back within one request and preserves failure thresholds', async () => {
	requireSignedRecoveryProfile();
	test.setTimeout(150_000);
	const receipt = isolatedServiceRegression('openrouter_health_probe', { fixture_id: randomUUID() });
	expect(receipt).toEqual({
		statuses: ['healthy', 'healthy', 'unhealthy', 'healthy', 'unhealthy'],
		failure_counts: [1, 2, 3, 0, 1],
		request_count: 5,
		auth_error: 'credential_error',
	});
});
