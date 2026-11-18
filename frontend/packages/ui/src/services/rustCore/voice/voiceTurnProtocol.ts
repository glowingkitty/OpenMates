/**
 * `voiceTurn` unit protocol of the shared Rust core Worker (voice-call turns;
 * VITE_OPENMATES_RUST_CORE builds only). The core (browser_voice_turn.rs) builds
 * the frames and keeps the prepared turn behind an opaque `voiceId`; the page
 * sends `frame` as `personal_send_context_snapshot` and `admit` as
 * `chat_turn_admit` on its one main socket. Failures arrive as stable codes.
 */

/** Spoken part of an interrupted reply (ranges are validated by the core). */
export interface VoiceHeardBoundary {
	assistantMessageId: string;
	completedSequences: number[];
	activeSequence?: number;
	activeOffsetMs?: number;
}

export type VoiceTurnProtocol = {
	/** Start a turn; `turnId` doubles as the user message id. */
	begin: {
		request: { chatId: string; turnId: string };
		response: { voiceId: string; requestId: string; frame: Record<string, unknown> };
	};
	/** Feed the socket's snapshot result; runs the text-independent stage. */
	prepare: {
		request: { voiceId: string; snapshotResult: Record<string, unknown> };
		response: Record<string, never>;
	};
	/** Final transcript: returns the admit payload (ciphertext) and the encrypted user message. */
	commit: {
		request: { voiceId: string; callId: string; finalText: string; heardBoundary?: VoiceHeardBoundary | null;
			/** Seconds of the page's optimistic row; the admitted row keeps it. */
			createdAt?: number };
		response: { admit: Record<string, unknown>; userMessage: Record<string, unknown>; waitAi: boolean };
	};
	/** Drop a begun or prepared turn; nothing is sent. */
	discard: {
		request: { voiceId: string };
		response: Record<string, never>;
	};
};

export const VOICE_TURN_UNIT_CLOSE = Object.freeze({ v: 1, type: 'voice_turn_close' });
export function isVoiceTurnUnitClose(value: unknown): boolean {
	const data = value as { v?: unknown; type?: unknown } | null;
	return data?.v === 1 && data.type === 'voice_turn_close';
}
