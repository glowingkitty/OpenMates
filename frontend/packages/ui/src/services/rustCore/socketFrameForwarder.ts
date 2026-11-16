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
	ingest(frames: Record<string, unknown>[]): Promise<SocketFrameSummary>;
	admit(chatId: string, teamId: string | null): Promise<ChatAdmission>;
}

/** Frame types the core applies (mirror of `client/frame_ingest.rs`). */
const APPLIED_TYPES: ReadonlySet<string> = new Set([
	'new_chat_message', 'chat_message_added', 'team_chat_message_created', 'ai_message_ready', 'ai_message_update',
	'chat_message_confirmed', 'chat_turn_preflight_ack', 'chat_turn_admit', 'chat_title_updated',
	'encrypted_chat_metadata', 'chat_deleted'
]);

let sink: SocketFrameSink | null = null;
let queued: Record<string, unknown>[] = [];
let scheduled = false;
let tail: Promise<void> = Promise.resolve();
const loggedCodes = new Set<string>();

/** Registers the single sink; returns an unregister bound to this registration. */
export function registerSocketFrameSink(next: SocketFrameSink): () => void {
	sink = next;
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
		tail = tail.then(() => send(batch));
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

/** Loads a page-created chat into the core and emits `chatWindowChanged`; null without a server session. */
export async function admitChatInRustCore(chatId: string, teamId: string | null): Promise<ChatAdmission | null> {
	if (!rustBuild() || !sink || !sink.hasServerSession()) return null;
	const run = tail.then(() => admitWithRetry(chatId, teamId));
	tail = run.then(() => undefined, () => undefined);
	try {
		const admission = await run;
		emitChatWindowChanged({ chatId: admission.chatId, messagesV: admission.messagesV });
		return admission;
	} catch (error) { logOnce(failureCode(error)); return null; }
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
