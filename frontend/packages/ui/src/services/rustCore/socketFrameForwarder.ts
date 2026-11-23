/**
 * Page-side forwarding of server socket frames to the shared Rust core
 * (VITE_OPENMATES_RUST_CORE builds only).
 *
 * `websocketService` calls `forwardSocketFrame` for every received frame BEFORE
 * its own handlers run. Frames whose type the core applies are queued in arrival
 * order, batched per microtask and sent through the history bootstrap's
 * server-checked session (`SocketFrameSink`). Forwarding never blocks or alters
 * the page handlers, never starts a server-checked admission itself and is
 * dropped when only a local-read-only session (or none) exists.
 *
 * Ordering: one chain of Worker requests. A busy core (read or send in flight) keeps
 * the frames in its own ordered queue and applies them before its next op, so the
 * page never retries or drops. `unavailable` means the queue overflowed and was
 * cleared: the chat window must be re-admitted. Failures log a fixed code once per
 * code, never frame content.
 */
import { emitChatWindowChanged } from './chatWindowEvents';
import type { ChatAdmission, SocketFrameSummary } from './socketFramesProtocol';
import { SOCKET_FRAME_MAX_COUNT } from './socketFramesProtocol';

/** The server-checked Rust session as seen by the forwarder. */
export interface SocketFrameSink {
	/** True only while a server-checked (not local-read-only) session is live. */
	hasServerSession(): boolean;
	/** True while only a local-read-only session (cached reads, no server authority) is live. */
	hasLocalSession(): boolean;
	/** Requests the server-checked session (the bootstrap's own upgrade); rejects with its failure code. */
	ensureServerSession(): Promise<void>;
	ingest(frames: Record<string, unknown>[]): Promise<SocketFrameSummary>;
	admit(chatId: string, teamId: string | null): Promise<ChatAdmission>;
}

/** Frame types the core applies (mirror of `client/frame_ingest.rs`, incl. its `VERSION_RECEIPT_FRAMES`). */
const APPLIED_TYPES: ReadonlySet<string> = new Set([
	'new_chat_message', 'chat_message_added', 'team_chat_message_created', 'ai_message_ready', 'ai_message_update',
	'chat_message_confirmed', 'chat_turn_preflight_ack', 'chat_turn_admit', 'chat_title_updated',
	'encrypted_chat_metadata', 'chat_deleted',
	// messages_v receipts of shell-owned features (calls, system messages, queued follow-ups, deletion)
	'call_message_confirmed', 'call_message_changed', 'system_message_confirmed', 'message_deleted',
	'message_queued', 'queued_message_status', 'queued_message_updated',
	// an assistant reply this page persisted through browser recovery (version + its row)
	'recovery_job_persisted',
	// an assistant reply this page persisted directly (its stored messages_v)
	'ai_response_storage_confirmed'
]);

/** Longest one forward-chain link (an ingest batch or an admission) may hold the chain. */
const CHAIN_LINK_MAX_MS = 8_000;

let sink: SocketFrameSink | null = null;
let queued: Record<string, unknown>[] = [];
let scheduled = false;
let tail: Promise<void> = Promise.resolve();
const loggedCodes = new Set<string>();
const sinkWaiters = new Set<() => void>();

/** Registers the single sink; returns an unregister bound to this registration. */
export function registerSocketFrameSink(next: SocketFrameSink): () => void {
	sink = next;
	for (const wake of [...sinkWaiters]) wake();
	return () => { if (sink === next) { sink = null; queued = []; } };
}

function rustBuild(): boolean { return import.meta.env.VITE_OPENMATES_RUST_CORE === '1'; }

function failureCode(error: unknown): string {
	const message = error instanceof Error ? error.message : error;
	return typeof message === 'string' && /^[a-z_]{3,40}$/.test(message) ? message : 'unavailable';
}
function logOnce(code: string): void {
	if (loggedCodes.has(code)) return;
	loggedCodes.add(code);
	console.warn('[RustCore] socket frame forward failed:', code);
}

/** True when the core applies this frame (`ai_message_update` only its final chunk). */
export function isCoreAppliedFrame(frame: unknown): frame is Record<string, unknown> {
	if (typeof frame !== 'object' || frame === null) return false;
	const record = frame as Record<string, unknown>;
	const kind = typeof record.type === 'string' ? record.type : record.event;
	if (typeof kind !== 'string' || !APPLIED_TYPES.has(kind)) return false;
	if (kind !== 'ai_message_update') return true;
	const payload = (record.payload ?? record) as Record<string, unknown> | null;
	return typeof payload === 'object' && payload !== null && payload.is_final_chunk === true;
}

async function once<T>(run: (active: SocketFrameSink) => Promise<T>): Promise<T> {
	const active = sink;
	if (!active || !active.hasServerSession()) throw new Error('session_expired');
	return run(active);
}

/** Admission is not queued by the Worker: a busy core answers `unavailable`, so retry briefly. */
const ADMIT_RETRY_DELAYS_MS = [50, 150, 400, 1000];
async function admitWithRetry(chatId: string, teamId: string | null): Promise<ChatAdmission> {
	for (let attempt = 0; ; attempt++) {
		try { return await once((active) => active.admit(chatId, teamId)); } catch (error) {
			if (failureCode(error) !== 'unavailable' || attempt >= ADMIT_RETRY_DELAYS_MS.length) throw error;
			await new Promise((resolve) => setTimeout(resolve, ADMIT_RETRY_DELAYS_MS[attempt]));
		}
	}
}

async function send(batch: Record<string, unknown>[]): Promise<void> {
	try {
		const summary = await once((active) => active.ingest(batch));
		for (const row of summary.changedChats) emitChatWindowChanged({ chatId: row.chatId, messagesV: row.messagesV });
	} catch (error) { logOnce(failureCode(error)); }
}

function flush(): void {
	scheduled = false;
	const frames = queued;
	queued = [];
	for (let start = 0; start < frames.length; start += SOCKET_FRAME_MAX_COUNT) {
		const batch = frames.slice(start, start + SOCKET_FRAME_MAX_COUNT);
		// Each link is bounded: one Worker request that never answers must not stall every later forward.
		tail = tail.then(() => bounded(send(batch), undefined, CHAIN_LINK_MAX_MS, 'ingest_timeout').catch((error: unknown) => logOnce(failureCode(error))));
	}
}

/**
 * Queues one received frame for the core. Synchronous and never throws, so it can
 * run first in the socket's message handler; the page handlers run unchanged after.
 */
export function forwardSocketFrame(frame: unknown): void {
	if (!rustBuild() || !sink || !sink.hasServerSession() || !isCoreAppliedFrame(frame)) return;
	queued.push(frame);
	if (!scheduled) { scheduled = true; queueMicrotask(flush); }
}

/**
 * Admission stage on `<html data-rust-core-admit>` (fixed codes only), so an E2E
 * that sees a stalled call can tell where: `sink`, `server_session`, `chain`
 * (behind earlier forwarded frames), `request` (Worker op in flight), `ok`, or
 * `failed:<code>`.
 */
function markAdmit(stage: string): void {
	if (typeof document !== 'undefined') document.documentElement.dataset.rustCoreAdmit = stage;
}

/** Admission on the forward chain (behind every frame already queued); emits `chatWindowChanged`. */
async function admitOnChain(chatId: string, teamId: string | null): Promise<ChatAdmission> {
	const run = tail.then(() => { markAdmit('request'); return admitWithRetry(chatId, teamId); });
	tail = bounded(run, undefined, CHAIN_LINK_MAX_MS, 'admit_timeout').then(() => undefined, () => undefined);
	const admission = await run;
	emitChatWindowChanged({ chatId: admission.chatId, messagesV: admission.messagesV });
	return admission;
}

/** Loads a page-created chat into the core and emits `chatWindowChanged`; null without a server session. */
export async function admitChatInRustCore(chatId: string, teamId: string | null): Promise<ChatAdmission | null> {
	if (!rustBuild() || !sink || !sink.hasServerSession()) return null;
	try { return await admitOnChain(chatId, teamId); } catch (error) { logOnce(failureCode(error)); return null; }
}

/**
 * Why a chat was not admitted. `flag_off`: not the Rust build; `no_sink`: no Rust
 * history session registered within the wait; `local_only`: the server-checked
 * session could not be reached and only the local-read-only one is live;
 * `no_session`: no session at all; `server_session_timeout`; `admit_timeout`
 * (the admission itself did not settle within `ADMIT_CHAT_WAIT_MS`); `cancelled`;
 * otherwise the core's typed failure code (`chat_unknown`, `forbidden`, ...).
 */
export type ChatAdmissionOutcome = { ok: true; admission: ChatAdmission } | { ok: false; reason: string };

export const ADMIT_SINK_WAIT_MS = 5_000;
export const ADMIT_SERVER_SESSION_WAIT_MS = 10_000;
/** Overall bound of the admission itself (chain wait + Worker op + retries). */
export const ADMIT_CHAT_WAIT_MS = 8_000;

/** Settles with `run`, or rejects `cancelled` on abort / `timeoutCode` past `ms`. */
function bounded<T>(run: Promise<T>, signal: AbortSignal | undefined, ms: number, timeoutCode: string, cleanup: () => void = () => undefined): Promise<T> {
	return new Promise<T>((resolve, reject) => {
		const finish = () => { clearTimeout(timer); signal?.removeEventListener('abort', onAbort); cleanup(); };
		const onAbort = () => { finish(); reject(new Error('cancelled')); };
		const timer = setTimeout(() => { finish(); reject(new Error(timeoutCode)); }, ms);
		if (signal?.aborted) { onAbort(); return; }
		signal?.addEventListener('abort', onAbort, { once: true });
		run.then((value) => { finish(); resolve(value); }, (error: unknown) => { finish(); reject(error); });
	});
}

function waitForSink(signal: AbortSignal | undefined): Promise<SocketFrameSink> {
	if (sink) return Promise.resolve(sink);
	let wake: () => void = () => undefined;
	const registered = new Promise<void>((resolve) => { wake = resolve; sinkWaiters.add(wake); });
	return bounded(registered, signal, ADMIT_SINK_WAIT_MS, 'no_sink', () => sinkWaiters.delete(wake))
		.then(() => { if (!sink) throw new Error('no_sink'); return sink; });
}

/**
 * Typed admission for callers that must refuse on failure (the voice call). Waits
 * (bounded, abortable) for the history bootstrap's sink and its server-checked
 * session, then admits on the forward chain. Never throws.
 */
export async function admitChatInRustCoreDetailed(chatId: string, teamId: string | null, signal?: AbortSignal): Promise<ChatAdmissionOutcome> {
	const outcome = await admitDetailed(chatId, teamId, signal);
	// The non-strict tsconfig does not narrow the union on `ok`; narrow by field.
	markAdmit('reason' in outcome ? `failed:${outcome.reason}` : 'ok');
	return outcome;
}

async function admitDetailed(chatId: string, teamId: string | null, signal: AbortSignal | undefined): Promise<ChatAdmissionOutcome> {
	if (!rustBuild()) return { ok: false, reason: 'flag_off' };
	let active: SocketFrameSink;
	markAdmit('sink');
	try { active = await waitForSink(signal); } catch (error) { return { ok: false, reason: failureCode(error) }; }
	const first = await admitOnServerSession(active, chatId, teamId, signal);
	// A workspace invalidation while the admission was queued (e.g. the first auth
	// refresh after signup hydrating the account id) closes the server-checked
	// session under it. That session re-admits lazily, so admit once more on it
	// instead of refusing the call (TASK-950).
	if ('reason' in first && first.reason === 'session_expired' && !signal?.aborted) {
		markAdmit('readmit');
		return admitOnServerSession(active, chatId, teamId, signal);
	}
	return first;
}

/** Ensures the server-checked session (bounded), then admits on the forward chain. */
async function admitOnServerSession(active: SocketFrameSink, chatId: string, teamId: string | null, signal: AbortSignal | undefined): Promise<ChatAdmissionOutcome> {
	if (!active.hasServerSession()) {
		markAdmit('server_session');
		try {
			await bounded(active.ensureServerSession(), signal, ADMIT_SERVER_SESSION_WAIT_MS, 'server_session_timeout');
		} catch (error) {
			const code = failureCode(error);
			if (code === 'cancelled' || code === 'server_session_timeout') return { ok: false, reason: code };
			logAdmissionFailure(code);
			return { ok: false, reason: active.hasLocalSession() ? 'local_only' : 'no_session' };
		}
		if (!active.hasServerSession()) return { ok: false, reason: active.hasLocalSession() ? 'local_only' : 'no_session' };
	}
	if (signal?.aborted) return { ok: false, reason: 'cancelled' };
	markAdmit('chain');
	try {
		return { ok: true, admission: await bounded(admitOnChain(chatId, teamId), signal, ADMIT_CHAT_WAIT_MS, 'admit_timeout') };
	} catch (error) {
		const code = failureCode(error);
		logAdmissionFailure(code);
		return { ok: false, reason: code };
	}
}

/** Admission failures are rare and user-visible, so each one is logged (frame
 * forwarding dedupes its codes and would otherwise hide them). */
function logAdmissionFailure(code: string): void {
	console.warn('[RustCore] chat admission failed:', code);
}

/** Test hook: drains the forward chain. */
export async function settleSocketFrameForwards(): Promise<void> {
	// Frames are flushed in a microtask; wait until no flush is pending and the chain is idle.
	for (;;) {
		await Promise.resolve();
		const current = tail;
		await current;
		if (!scheduled && current === tail) return;
	}
}
