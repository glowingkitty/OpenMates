// Worker ops `ingest_socket_frames` / `admit_chat` (protocol validation) and the page
// forwarder that feeds the shared core: type filter, order, no forward without a
// server-checked session, chatWindowChanged after a changing batch.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { validRequest, validResponse } from '../protocol';
import { onChatWindowChanged } from '../chatWindowEvents';
import { admitChatInRustCore, forwardSocketFrame, isCoreAppliedFrame, registerSocketFrameSink, settleSocketFrameForwards } from '../socketFrameForwarder';
import type { SocketFrameSink } from '../socketFrameForwarder';
import { dispatch } from '../workerDispatch';
import { drainPendingSocketFrames, newSocketQueue } from '../workerSocketQueue';
import type { WorkerRuntimeState } from '../workerRuntimeState';

const CHAT = '11111111-2222-4333-8444-555555555555';
const status = { principal: CHAT, handle: 'h1', generation: 1, persistence: 'memory_only', localReadOnly: false };

describe('chat frame op protocol', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('accepts a closed ingest request and rejects extra, empty or malformed frames', () => {
		const ok = { version: 1, id: 1, operation: 'ingest_socket_frames', handle: 'h1', generation: 1, frames: [{ type: 'chat_deleted', payload: { chat_id: CHAT } }] };
		expect(validRequest(ok)).toBe(true);
		expect(validRequest({ ...ok, extra: 1 })).toBe(false);
		expect(validRequest({ ...ok, frames: [] })).toBe(false);
		expect(validRequest({ ...ok, frames: [{ payload: {} }] })).toBe(false);
		expect(validRequest({ ...ok, frames: Array.from({ length: 65 }, () => ({ type: 'chat_deleted' })) })).toBe(false);
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('validates admit_chat ids and team id', () => {
		const ok = { version: 1, id: 2, operation: 'admit_chat', handle: 'h1', generation: 1, chatId: CHAT, teamId: null };
		expect(validRequest(ok)).toBe(true);
		expect(validRequest({ ...ok, teamId: 'team_1' })).toBe(true);
		expect(validRequest({ ...ok, chatId: 'not-a-uuid' })).toBe(false);
		expect(validRequest({ ...ok, teamId: 'bad id!' })).toBe(false);
		expect(validRequest({ ...ok, teamId: undefined })).toBe(false);
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('validates replies and the fixed failure codes only', () => {
		expect(validResponse({ version: 1, id: 1, ok: true, status, socketIngest: { appliedSeq: 3, changedChats: [{ chatId: CHAT, messagesV: 2 }], ignored: 0 } })).toBe(true);
		expect(validResponse({ version: 1, id: 1, ok: true, status, socketIngest: { appliedSeq: 3, changedChats: [], ignored: 0, text: 'x' } })).toBe(false);
		expect(validResponse({ version: 1, id: 2, ok: true, status, chatAdmission: { chatId: CHAT, messagesV: 1, historyRows: 4 } })).toBe(true);
		expect(validResponse({ version: 1, id: 2, ok: false, error: 'chat_unknown' })).toBe(true);
		expect(validResponse({ version: 1, id: 2, ok: false, error: 'something else' })).toBe(false);
	});
});

describe('socket frame forwarding', () => {
	let live = true;
	const batches: Record<string, unknown>[][] = [];
	let sink: SocketFrameSink;
	let unregister: () => void;
	beforeEach(() => {
		vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
		live = true; batches.length = 0;
		sink = {
			hasServerSession: () => live,
			ingest: vi.fn(async (frames) => { batches.push(frames); return { appliedSeq: batches.length, changedChats: [{ chatId: CHAT, messagesV: batches.length }], ignored: 0 }; }),
			admit: vi.fn(async (chatId) => ({ chatId, messagesV: 5, historyRows: 2 }))
		};
		unregister = registerSocketFrameSink(sink);
	});
	afterEach(() => { unregister(); vi.unstubAllEnvs(); });

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('forwards only applied frame types, final chunks only, in arrival order as one batch', async () => {
		forwardSocketFrame({ type: 'new_chat_message', payload: { n: 1 } });
		forwardSocketFrame({ type: 'ping' });
		forwardSocketFrame({ type: 'ai_message_update', payload: { is_final_chunk: false } });
		forwardSocketFrame({ type: 'ai_message_update', payload: { is_final_chunk: true, n: 2 } });
		forwardSocketFrame({ event: 'chat_deleted', chat_id: CHAT });
		await settleSocketFrameForwards();
		expect(batches).toHaveLength(1);
		expect(batches[0].map((frame) => frame.type ?? frame.event)).toEqual(['new_chat_message', 'ai_message_update', 'chat_deleted']);
		expect(isCoreAppliedFrame({ type: 'chat_title_updated' })).toBe(true);
		expect(isCoreAppliedFrame({ type: 'user_typing' })).toBe(false);
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps order across microtask batches and emits chatWindowChanged per changed chat', async () => {
		const seen: number[] = [];
		const off = onChatWindowChanged((event) => seen.push(event.messagesV));
		forwardSocketFrame({ type: 'chat_message_added', payload: { n: 1 } });
		await Promise.resolve();
		forwardSocketFrame({ type: 'chat_message_confirmed', payload: { n: 2 } });
		await settleSocketFrameForwards();
		await settleSocketFrameForwards();
		off();
		expect(batches.map((batch) => (batch[0].payload as { n: number }).n)).toEqual([1, 2]);
		expect(seen).toEqual([1, 2]);
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('does not forward without a server-checked session or off the Rust build', async () => {
		live = false;
		forwardSocketFrame({ type: 'new_chat_message', payload: {} });
		vi.stubEnv('VITE_OPENMATES_RUST_CORE', '0');
		live = true;
		forwardSocketFrame({ type: 'new_chat_message', payload: {} });
		await settleSocketFrameForwards();
		expect(sink.ingest).not.toHaveBeenCalled();
		expect(await admitChatInRustCore(CHAT, null)).toBeNull();
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('admits a chat through the sink and logs a failure code once', async () => {
		const seen: number[] = [];
		const off = onChatWindowChanged((event) => seen.push(event.messagesV));
		expect(await admitChatInRustCore(CHAT, 'team_1')).toEqual({ chatId: CHAT, messagesV: 5, historyRows: 2 });
		off();
		expect(seen).toEqual([5]);
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		(sink.admit as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('chat_unknown'));
		await admitChatInRustCore(CHAT, null);
		await admitChatInRustCore(CHAT, null);
		expect(warn.mock.calls.filter((call) => call[1] === 'chat_unknown')).toHaveLength(1);
		warn.mockRestore();
	});
});

describe('worker socket frame queue', () => {
	const calls: string[] = [];
	const posted: Record<string, unknown>[] = [];
	const summary = (seq: number, v: number) => JSON.stringify({ appliedSeq: seq, changedChats: [{ chatId: CHAT, messagesV: v }], ignored: 0 });
	function makeRt(): WorkerRuntimeState {
		const client = {
			status: () => ({ handle: 'h1', principal: CHAT, generation: 1, persisted: false, free: () => undefined }),
			ingest_socket_frames: vi.fn(async (_h: string, _g: number, json: string) => {
				calls.push(`ingest:${(JSON.parse(json) as { payload: { n: number } }[]).map((frame) => frame.payload.n).join(',')}`);
				return summary(calls.length, calls.length);
			}),
			admit_chat: vi.fn(async () => { calls.push('admit'); return JSON.stringify({ chatId: CHAT, messagesV: 9, historyRows: 1 }); })
		};
		return {
			client, sending: {}, busy: false, reading: null, initialSync: null, disposed: false, firstSessionDataOnlyUsed: false,
			locks: { request: async (_n: unknown, _o: unknown, run: () => Promise<unknown>) => run() }, lifetime: new AbortController(),
			endpoint: { postMessage: (message: Record<string, unknown>) => { posted.push(message); } },
			configuration: { admission: 'fresh_password' }, socketQueue: newSocketQueue(), freedClients: new Set(), retainedClients: new Map(),
			passwordAdmission: null, cacheRead: null, localRead: null, ownedCacheReads: new Map(), firstSessionTask: null, cacheMonitor: null,
			profileCache: null, retiredProfileCaches: new Set(), recoveryDrains: new Set(), failedRecoveryPorts: new Set(), casReply: null
		} as unknown as WorkerRuntimeState;
	}
	const ingest = (id: number, ns: number[]) => ({ version: 1, id, operation: 'ingest_socket_frames', handle: 'h1', generation: 1,
		frames: ns.map((n) => ({ type: 'chat_turn_preflight_ack', payload: { n } })) });
	beforeEach(() => { calls.length = 0; posted.length = 0; });

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('queues frames while a send runs and applies them in order before the next op', async () => {
		const rt = makeRt();
		await dispatch(rt, ingest(1, [1, 2]));
		await dispatch(rt, ingest(2, [3]));
		expect(calls).toEqual([]);
		expect(posted[0]).toMatchObject({ id: 1, ok: true, socketIngest: { queued: 2, appliedSeq: null, changedChats: [], ignored: 0 } });
		expect(validResponse(posted[0])).toBe(true);
		rt.sending = null;
		await dispatch(rt, { version: 1, id: 3, operation: 'admit_chat', handle: 'h1', generation: 1, chatId: CHAT, teamId: null });
		expect(calls).toEqual(['ingest:1,2,3', 'admit']);
		expect(rt.socketQueue.frames).toHaveLength(0);
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('drains the queue first on a direct ingest and merges the drained changes into its reply', async () => {
		const rt = makeRt();
		await dispatch(rt, ingest(1, [1]));
		rt.sending = null;
		await dispatch(rt, ingest(2, [2]));
		expect(calls).toEqual(['ingest:1', 'ingest:2']);
		expect(posted[1]).toMatchObject({ id: 2, ok: true, socketIngest: { appliedSeq: 2, changedChats: [{ chatId: CHAT, messagesV: 2 }] } });
		expect(validResponse(posted[1])).toBe(true);
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('clears the queue with a fixed code on overflow', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const rt = makeRt();
		for (let id = 1; id <= 32; id++) await dispatch(rt, ingest(id, Array.from({ length: 64 }, (_, n) => n)));
		expect(rt.socketQueue.frames).toHaveLength(2048);
		await dispatch(rt, ingest(33, [1]));
		expect(posted[32]).toMatchObject({ id: 33, ok: false, error: 'unavailable' });
		expect(rt.socketQueue.frames).toHaveLength(0);
		expect(warn.mock.calls.some((call) => call[1] === 'socket_queue_overflow')).toBe(true);
		warn.mockRestore();
	});
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('logs a fixed code and clears the queue when a drain fails, without throwing', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const rt = makeRt();
		await dispatch(rt, ingest(1, [1]));
		(rt.client as unknown as { ingest_socket_frames: ReturnType<typeof vi.fn> }).ingest_socket_frames.mockRejectedValue('invalid_frames');
		await expect(drainPendingSocketFrames(rt)).resolves.toBeUndefined();
		expect(rt.socketQueue.frames).toHaveLength(0);
		expect(warn.mock.calls.some((call) => call[1] === 'invalid_frames')).toBe(true);
		warn.mockRestore();
	});
});

describe('forwarder against a busy core', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('sends each batch once and never retries or re-sends a rejected batch', async () => {
		vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const ingest = vi.fn(async () => { throw new Error('unavailable'); });
		const off = registerSocketFrameSink({ hasServerSession: () => true, ingest, admit: vi.fn() });
		forwardSocketFrame({ type: 'chat_turn_preflight_ack', payload: {} });
		await settleSocketFrameForwards();
		expect(ingest).toHaveBeenCalledTimes(1);
		off(); warn.mockRestore(); vi.unstubAllEnvs();
	});
});
