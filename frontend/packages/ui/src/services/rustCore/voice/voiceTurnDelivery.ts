/**
 * Main-socket carrier of a Rust-built voice-call turn (VITE_OPENMATES_RUST_CORE
 * builds only). The core (voiceTurn unit) builds the snapshot request and the
 * encrypted `chat_turn_admit` payload; this module only moves those frames on
 * the page's one main socket and waits for the server's exact-turn ACK. Both
 * frames go on the connection the receipt was issued for, never a replacement.
 */
import type { VoiceHeardBoundary } from '../../../types/chat';
import { webSocketService } from '../../websocketService';
import { waitForPreflightAcknowledgement } from '../../preflightAcknowledgement';
import { beginVoiceTurn, commitVoiceTurn, discardVoiceTurn, prepareVoiceTurn } from './voiceTurnClient';

const SNAPSHOT_TIMEOUT_MS = 10_000;

export interface CoreVoiceTurn {
	callId: string;
	chatId: string;
	turnId: string;
	/** Final message content (transcript plus artifact references). */
	content: string;
	/** Seconds of the page's optimistic row, so the canonical row matches it. */
	createdAt: number;
	heardBoundary?: VoiceHeardBoundary;
	/** Fixed-phase progress for content-free delivery evidence. */
	enter(phase: string): void;
	isCurrent(): boolean;
}

/** Thrown with a fixed code; carries no content. */
export class CoreVoiceTurnError extends Error {
	constructor(readonly code: string) { super(code); }
}

function snapshotResult(requestId: string, frame: Record<string, unknown>, connection: object,
	signal?: AbortSignal): Promise<Record<string, unknown>> {
	return new Promise((resolve, reject) => {
		const finish = (error?: Error, payload?: Record<string, unknown>) => {
			clearTimeout(timer);
			webSocketService.off('personal_send_context_snapshot_result', handler);
			webSocketService.removeEventListener('close', closed);
			signal?.removeEventListener('abort', aborted);
			if (error) reject(error); else resolve(payload!);
		};
		// The core validates success, turn and receipt; only the request id routes here.
		const handler = (payload: Record<string, unknown>) => {
			if (payload?.request_id === requestId) finish(undefined, payload);
		};
		const closed = () => finish(new CoreVoiceTurnError('privacy_connection_changed'));
		const aborted = () => finish(new CoreVoiceTurnError('scope_changed'));
		const timer = setTimeout(() => finish(new CoreVoiceTurnError('privacy_snapshot_timeout')), SNAPSHOT_TIMEOUT_MS);
		webSocketService.on('personal_send_context_snapshot_result', handler);
		webSocketService.addEventListener('close', closed);
		if (signal?.aborted) { aborted(); return; }
		signal?.addEventListener('abort', aborted, { once: true });
		webSocketService.sendMessage('personal_send_context_snapshot', frame, { expectedConnection: connection })
			.catch(() => finish(new CoreVoiceTurnError('privacy_snapshot_unsent')));
	});
}

/** Text-independent half of a turn, prepared by the core behind `voiceId`. */
export interface EarlyVoiceTurn {
	voiceId: string;
	/** The socket the privacy receipt belongs to; the admit must use it too. */
	connection: object;
}

/**
 * Prepare the text-independent half (snapshot + core stage) of `turnId`. Used
 * on the server's `turn.likely_end` hint and by the final send itself. Calls
 * no model and sends no admission; the caller discards an unused result.
 */
export async function prepareVoiceTurnThroughCore(chatId: string, turnId: string,
	enter: (phase: string) => void = () => {}, signal?: AbortSignal): Promise<EarlyVoiceTurn> {
	if (signal?.aborted) throw new CoreVoiceTurnError('scope_changed');
	const connection = webSocketService.getConnectionForSend();
	if (!connection) throw new CoreVoiceTurnError('disconnected');
	enter('core_beginning');
	const begun = await beginVoiceTurn(chatId, turnId);
	try {
		enter('core_snapshot');
		const result = await snapshotResult(begun.requestId, begun.frame, connection, signal);
		if (signal?.aborted) throw new CoreVoiceTurnError('scope_changed');
		enter('core_preparing');
		await prepareVoiceTurn(begun.voiceId, result);
		if (signal?.aborted) throw new CoreVoiceTurnError('scope_changed');
		return { voiceId: begun.voiceId, connection };
	} catch (error) {
		void discardVoiceTurn(begun.voiceId);
		if (!signal?.aborted && connection !== webSocketService.getConnectionForSend()) {
			throw new CoreVoiceTurnError('privacy_connection_changed');
		}
		throw error;
	}
}

/** Drop an early preparation that will not be committed. Never throws. */
export async function discardEarlyVoiceTurn(early: Promise<EarlyVoiceTurn> | undefined): Promise<void> {
	if (!early) return;
	try {
		await discardVoiceTurn((await early).voiceId);
	} catch {
		// A failed preparation already dropped its core entry.
	}
}

async function prepareForDelivery(turn: CoreVoiceTurn, early: Promise<EarlyVoiceTurn> | undefined,
	signal: AbortSignal): Promise<EarlyVoiceTurn> {
	const prepared = await early?.catch(() => undefined);
	if (prepared) {
		if (!signal.aborted && turn.isCurrent() && prepared.connection === webSocketService.getConnectionForSend()) {
			turn.enter('core_early_reused');
			return prepared;
		}
		void discardVoiceTurn(prepared.voiceId);
	}
	if (signal.aborted || !turn.isCurrent()) throw new CoreVoiceTurnError('scope_changed');
	return prepareVoiceTurnThroughCore(turn.chatId, turn.turnId, turn.enter, signal);
}

/**
 * Prepare the privacy snapshot while the shell persists its optimistic row.
 * Commit and send exactly once, after that persistence and the current scope
 * and socket have been checked. A replacement socket requires a fresh snapshot.
 */
export async function deliverVoiceTurnThroughCore(turn: CoreVoiceTurn, early?: Promise<EarlyVoiceTurn>,
	persistence?: Promise<boolean>): Promise<boolean> {
	const controller = new AbortController();
	let preparation = prepareForDelivery(turn, early, controller.signal);
	void preparation.catch(() => undefined); // Persistence may finish or fail first.
	let prepared: EarlyVoiceTurn | undefined;
	let committed = false;
	try {
		if (persistence && !await persistence) return false;
		if (!turn.isCurrent()) throw new CoreVoiceTurnError('scope_changed');

		try {
			prepared = await preparation;
		} catch (error) {
			// A reconnect can retire an in-flight snapshot while the local write
			// is pending. Other preparation failures keep their original result.
			if (!(error instanceof CoreVoiceTurnError) || error.code !== 'privacy_connection_changed'
				|| !turn.isCurrent() || !webSocketService.getConnectionForSend()) throw error;
		}
		if (prepared && prepared.connection !== webSocketService.getConnectionForSend()) {
			void discardVoiceTurn(prepared.voiceId);
			prepared = undefined;
		}
		if (!turn.isCurrent()) throw new CoreVoiceTurnError('scope_changed');
		if (!prepared) {
			preparation = prepareVoiceTurnThroughCore(turn.chatId, turn.turnId, turn.enter, controller.signal);
			prepared = await preparation;
		}
		if (!turn.isCurrent()) throw new CoreVoiceTurnError('scope_changed');
		if (prepared.connection !== webSocketService.getConnectionForSend()) {
			throw new CoreVoiceTurnError('privacy_connection_changed');
		}
		turn.enter('core_committing');
		const boundary = turn.heardBoundary;
		const out = await commitVoiceTurn({
			voiceId: prepared.voiceId, callId: turn.callId, finalText: turn.content, createdAt: turn.createdAt,
			heardBoundary: boundary ? {
				assistantMessageId: boundary.assistant_message_id,
				completedSequences: boundary.completed_sequences,
				...(boundary.active_sequence != null ? { activeSequence: boundary.active_sequence } : {}),
				activeOffsetMs: boundary.active_offset_ms,
			} : null,
		});
		committed = true;
		if (!turn.isCurrent()) throw new CoreVoiceTurnError('scope_changed');
		// Register before dispatch: the ACK may arrive before sendMessage resolves.
		const ack = waitForPreflightAcknowledgement(turn.turnId, webSocketService, () => {}, undefined, true);
		void ack.catch(() => undefined);
		turn.enter('canonical_sending');
		await webSocketService.sendMessage('chat_turn_admit', out.admit, { expectedConnection: prepared.connection });
		turn.enter('receipt_reading');
		await ack;
		return true;
	} finally {
		controller.abort();
		// Commit consumed the turn. A failed local write may interrupt preparation;
		// cancel its socket listener, and discard any result that already landed.
		if (!committed) {
			if (prepared) void discardVoiceTurn(prepared.voiceId);
			else void discardEarlyVoiceTurn(preparation);
		}
	}
}
