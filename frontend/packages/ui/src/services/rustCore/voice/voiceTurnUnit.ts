/**
 * `voiceTurn` namespace installer of the shared Rust core Worker
 * (VITE_OPENMATES_RUST_CORE builds only). Marshalling only: each call runs on
 * the ADMITTED client of the bound history `core` lease, borrowed through
 * coreClientBorrow. Chat key, wrapper and baseline are derived inside the core
 * (voice_turn_commit); the prepared turn lives in wasm behind `voiceId`, so
 * no secret crosses this unit.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { CoreBorrowRefusal, CoreClientBorrow } from '../drafts/coreClientBorrow';
import { isVoiceTurnUnitClose, type VoiceTurnProtocol } from './voiceTurnProtocol';

/** Bounded wait for the history dispatcher to become idle. */
export const VOICE_TURN_BORROW_TIMEOUT_MS = 10_000;

/** BrowserCoreClient exports of browser_voice_turn.rs (JSON strings). */
export interface VoiceTurnClient {
	voice_turn_begin(handle: string, generation: number, chatId: string, turnId: string): string;
	voice_turn_prepare(handle: string, generation: number, voiceId: string, snapshotResult: string): Promise<void>;
	voice_turn_commit(handle: string, generation: number, voiceId: string, callId: string,
		heardBoundaryJson: string, finalText: string, createdAt: number): Promise<string>;
	voice_turn_discard(voiceId: string): void;
}

export interface VoiceTurnDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal>;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

/** Core rejections are stable code strings; keep them, never internal text. */
function code(error: unknown): string {
	if (error instanceof UnitRefusal) return error.code;
	const raw = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return CODE.test(raw) ? raw : 'voice_turn_failed';
}

function parseObject(raw: unknown): Record<string, unknown> {
	if (typeof raw !== 'string') throw new UnitRefusal('voice_turn_protocol');
	let value: unknown;
	try {
		value = JSON.parse(raw);
	} catch {
		throw new UnitRefusal('voice_turn_protocol');
	}
	if (!value || typeof value !== 'object' || Array.isArray(value)) throw new UnitRefusal('voice_turn_protocol');
	return value as Record<string, unknown>;
}

function isObject(value: unknown): value is Record<string, unknown> {
	return !!value && typeof value === 'object' && !Array.isArray(value);
}

const defaultDeps = (): VoiceTurnDeps => ({
	// Socket frames queued while another borrower held the Client (the previous
	// turn's ACK among them) are applied first, so a commit reads the current
	// messages_v.
	borrow: (principal, signal, timeoutMs) => borrowCoreClient(principal, signal, timeoutMs, undefined, { drainSocketFrames: true })
});

export function createVoiceTurnHandlers(principal: string, deps: VoiceTurnDeps,
	lifetime: AbortSignal): UnitHandlers<VoiceTurnProtocol> {
	async function withClient<T>(run: (client: VoiceTurnClient, handle: string, generation: number) => Promise<T> | T): Promise<T> {
		const borrow = await deps.borrow(principal, lifetime, VOICE_TURN_BORROW_TIMEOUT_MS);
		if (borrow === 'none') throw new UnitRefusal('not_admitted');
		if (borrow === 'busy') throw new UnitRefusal('core_busy');
		if (borrow === 'local') throw new UnitRefusal('local_session');
		try {
			return await run(borrow.client as unknown as VoiceTurnClient, borrow.status.handle, borrow.status.generation);
		} catch (error) {
			throw new UnitRefusal(code(error));
		} finally {
			borrow.release();
		}
	}
	const id = (value: unknown, bad: string): string => {
		if (typeof value !== 'string' || value.length === 0 || value.length > 128) throw new UnitRefusal(bad);
		return value;
	};
	return {
		async begin(payload) {
			const request = payload as { chatId?: unknown; turnId?: unknown } | null;
			const chatId = id(request?.chatId, 'voice_turn_bad_chat');
			const turnId = id(request?.turnId, 'voice_turn_bad_turn');
			return withClient((client, handle, generation) => {
				const out = parseObject(client.voice_turn_begin(handle, generation, chatId, turnId));
				if (typeof out.voiceId !== 'string' || typeof out.requestId !== 'string' || !isObject(out.frame)) {
					throw new UnitRefusal('voice_turn_protocol');
				}
				return { voiceId: out.voiceId, requestId: out.requestId, frame: out.frame };
			});
		},
		async prepare(payload) {
			const request = payload as { voiceId?: unknown; snapshotResult?: unknown } | null;
			const voiceId = id(request?.voiceId, 'voice_turn_bad_id');
			if (!isObject(request?.snapshotResult)) throw new UnitRefusal('voice_turn_bad_snapshot');
			const snapshot = JSON.stringify(request.snapshotResult);
			return withClient(async (client, handle, generation) => {
				await client.voice_turn_prepare(handle, generation, voiceId, snapshot);
				return {};
			});
		},
		async commit(payload) {
			const request = payload as { voiceId?: unknown; callId?: unknown; finalText?: unknown; heardBoundary?: unknown; createdAt?: unknown } | null;
			const voiceId = id(request?.voiceId, 'voice_turn_bad_id');
			const callId = id(request?.callId, 'voice_turn_bad_call');
			if (typeof request?.finalText !== 'string' || request.finalText.trim().length === 0) throw new UnitRefusal('voice_turn_bad_text');
			if (request.heardBoundary != null && !isObject(request.heardBoundary)) throw new UnitRefusal('voice_turn_bad_boundary');
			const boundary = request.heardBoundary ? JSON.stringify(request.heardBoundary) : '';
			if (request.createdAt != null && !(Number.isSafeInteger(request.createdAt) && (request.createdAt as number) > 0)) throw new UnitRefusal('voice_turn_bad_time');
			const createdAt = (request.createdAt as number | undefined) ?? 0;
			const finalText = request.finalText;
			return withClient(async (client, handle, generation) => {
				const out = parseObject(await client.voice_turn_commit(handle, generation, voiceId, callId, boundary, finalText, createdAt));
				if (!isObject(out.admit) || !isObject(out.userMessage) || typeof out.waitAi !== 'boolean') {
					throw new UnitRefusal('voice_turn_protocol');
				}
				return { admit: out.admit, userMessage: out.userMessage, waitAi: out.waitAi };
			});
		},
		async discard(payload) {
			const request = payload as { voiceId?: unknown } | null;
			const voiceId = id(request?.voiceId, 'voice_turn_bad_id');
			// Discard must work even while the core is busy only if a client is
			// obtainable; an unavailable session already dropped the wasm map.
			return withClient((client) => {
				client.voice_turn_discard(voiceId);
				return {};
			});
		}
	};
}

export function installVoiceTurnUnit(context: UnitInstallContext, deps: VoiceTurnDeps = defaultDeps()): () => void {
	const principal = context.principal;
	if (context.ports.length !== 1 || !principal) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<VoiceTurnProtocol>(port, createVoiceTurnHandlers(principal, deps, context.signal));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		port.removeEventListener('message', control);
		stop();
		port.close();
	};
	function control(event: MessageEvent<unknown>): void {
		if (isVoiceTurnUnitClose(event.data)) dispose();
	}
	port.addEventListener('message', control);
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
