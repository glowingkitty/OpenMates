/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) watcher that ends a retained user turn
 * once the server has answered it for good.
 *
 * Every user row that still carries its sealed turn preflight is resent on each
 * connect. The shared Rust core `sendPrep` unit decides (turn_outcome.rs) whether
 * a frame is the "already completed" confirmation or a non-retryable rejection
 * of exactly this turn; the page only routes frames of the turn's chat to it and
 * runs `end`, which clears the retained journals and the retry status. There is
 * no TypeScript fallback: a failed unit call keeps the turn retained.
 */
import type { TurnOutcome } from './sendPrepProtocol';
import { sendPrepCall } from './sendPrepUnitClient';

type Handler = (payload: unknown) => void;
export interface TurnOutcomeEventSource {
	on(event: string, handler: Handler): void;
	off(event: string, handler: Handler): void;
}
export type DecideTurnOutcome = (request: {
	kind: string; payload: Record<string, unknown>; chatId: string; messageId: string; turnId: string;
}) => Promise<TurnOutcome>;

const FRAME_KINDS = ['error', 'chat_message_confirmed'] as const;
const watches = new Map<string, () => void>();

const rustDecide: DecideTurnOutcome = async (request) => (await sendPrepCall('turnOutcome', request)).outcome;

/**
 * Watch one send attempt of a retained turn. A later attempt of the same
 * message replaces the watch; `settled` (the ordinary admission confirmation)
 * stops it. Returns the stop function.
 */
export function watchRetainedTurnOutcome(input: {
	chatId: string; messageId: string; turnId: string;
	settled: Promise<void>;
	end: (outcome: Exclude<TurnOutcome, 'none'>) => Promise<void>;
	events: TurnOutcomeEventSource;
	decide?: DecideTurnOutcome;
}): () => void {
	const key = `${input.chatId}:${input.messageId}`;
	watches.get(key)?.();
	const decide = input.decide ?? rustDecide;
	let stopped = false;
	const handlers = FRAME_KINDS.map((kind) => [kind, (payload: unknown) => {
		if (stopped || typeof payload !== 'object' || payload === null || Array.isArray(payload)) return;
		const frame = payload as Record<string, unknown>;
		if (frame.chat_id !== input.chatId) return;
		void decide({ kind, payload: frame, chatId: input.chatId, messageId: input.messageId, turnId: input.turnId })
			.then(async (outcome) => {
				if (stopped || outcome === 'none') return;
				stop();
				await input.end(outcome);
			})
			.catch((error) => console.warn('[ChatSyncService:Senders] Could not end the retained turn', error));
	}] as const);
	const stop = () => {
		if (stopped) return;
		stopped = true;
		for (const [kind, handler] of handlers) input.events.off(kind, handler);
		if (watches.get(key) === stop) watches.delete(key);
	};
	for (const [kind, handler] of handlers) input.events.on(kind, handler);
	watches.set(key, stop);
	void input.settled.then(stop, stop);
	return stop;
}
