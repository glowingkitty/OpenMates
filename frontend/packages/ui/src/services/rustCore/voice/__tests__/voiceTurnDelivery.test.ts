// @vitest-environment node
/**
 * Main-socket carrier of a Rust-built voice turn: snapshot then admit on the
 * receipt's connection, resolution only on the exact-turn ACK, and a discard
 * (no admit frame) when the turn fails before commit. Socket and unit are stubs.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = (payload: Record<string, unknown>) => void;
const ws = vi.hoisted(() => {
	const handlers = new Map<string, Set<Handler>>();
	const connection = {};
	return {
		connection,
		handlers,
		sent: [] as Array<{ type: string; payload: unknown; options: unknown }>,
		emit(type: string, payload: Record<string, unknown>) {
			for (const handler of [...(handlers.get(type) ?? [])]) handler(payload);
		},
	};
});
const unit = vi.hoisted(() => ({
	begin: vi.fn(), prepare: vi.fn(), commit: vi.fn(), discard: vi.fn(),
}));

vi.mock('../../../websocketService', () => ({
	webSocketService: {
		getConnectionForSend: () => ws.connection,
		on: (type: string, handler: Handler) => {
			if (!ws.handlers.has(type)) ws.handlers.set(type, new Set());
			ws.handlers.get(type)!.add(handler);
		},
		off: (type: string, handler: Handler) => ws.handlers.get(type)?.delete(handler),
		addEventListener: () => undefined,
		removeEventListener: () => undefined,
		sendMessage: vi.fn(async (type: string, payload: unknown, options: unknown) => {
			ws.sent.push({ type, payload, options });
			if (type === 'personal_send_context_snapshot') {
				queueMicrotask(() => ws.emit('personal_send_context_snapshot_result', { request_id: 'r1', success: true }));
			}
			if (type === 'chat_turn_admit') {
				queueMicrotask(() => ws.emit('chat_turn_preflight_ack', { turn_id: TURN, preflight_id: 'p1' }));
			}
		}),
	},
}));
vi.mock('../voiceTurnClient', () => ({
	beginVoiceTurn: unit.begin, prepareVoiceTurn: unit.prepare,
	commitVoiceTurn: unit.commit, discardVoiceTurn: unit.discard,
}));

import { deliverVoiceTurnThroughCore, prepareVoiceTurnThroughCore } from '../voiceTurnDelivery';

const CHAT = '22222222-2222-4222-8222-222222222222';
const TURN = '33333333-3333-4333-8333-333333333333';

function turn(isCurrent = () => true) {
	const phases: string[] = [];
	return {
		phases,
		input: {
			callId: 'call-1', chatId: CHAT, turnId: TURN, content: 'hello there', createdAt: 1_700_000_123,
			heardBoundary: { assistant_message_id: 'a1', completed_sequences: [0, 1], active_sequence: 2, active_offset_ms: 400 },
			enter: (phase: string) => phases.push(phase), isCurrent,
		},
	};
}

beforeEach(() => {
	ws.sent.length = 0;
	ws.handlers.clear();
	unit.begin.mockReset().mockResolvedValue({ voiceId: 'voice-turn-1', requestId: 'r1', frame: { request_id: 'r1', purpose: 'send', turn_id: TURN } });
	unit.prepare.mockReset().mockResolvedValue(undefined);
	unit.commit.mockReset().mockResolvedValue({ admit: { turn_id: TURN, message_id: TURN }, userMessage: {}, waitAi: true });
	unit.discard.mockReset().mockResolvedValue(undefined);
});

describe('deliverVoiceTurnThroughCore', () => {
	// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,video-call.audio.complete-turn-admission
	it('sends the core snapshot then the core admit on the receipt connection and resolves on the turn ACK', async () => {
		const { input, phases } = turn();
		await deliverVoiceTurnThroughCore(input);
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot', 'chat_turn_admit']);
		for (const frame of ws.sent) expect(frame.options).toEqual({ expectedConnection: ws.connection });
		expect(ws.sent[1].payload).toEqual({ turn_id: TURN, message_id: TURN });
		expect(unit.prepare).toHaveBeenCalledWith('voice-turn-1', { request_id: 'r1', success: true });
		expect(unit.commit).toHaveBeenCalledWith({
			voiceId: 'voice-turn-1', callId: 'call-1', finalText: 'hello there', createdAt: 1_700_000_123,
			heardBoundary: { assistantMessageId: 'a1', completedSequences: [0, 1], activeSequence: 2, activeOffsetMs: 400 },
		});
		expect(unit.discard).not.toHaveBeenCalled();
		expect(phases).toEqual(['core_beginning', 'core_snapshot', 'core_preparing', 'core_committing', 'canonical_sending', 'receipt_reading']);
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
	it('discards the prepared turn and sends no admit when the core refuses the snapshot', async () => {
		unit.prepare.mockRejectedValue(Object.assign(new Error('privacy_snapshot_rejected'), { code: 'privacy_snapshot_rejected' }));
		await expect(deliverVoiceTurnThroughCore(turn().input)).rejects.toMatchObject({ code: 'privacy_snapshot_rejected' });
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot']);
		expect(unit.discard).toHaveBeenCalledWith('voice-turn-1');
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
	it('sends no admit when the call scope changed after the snapshot', async () => {
		let current = true;
		unit.begin.mockImplementation(async () => {
			queueMicrotask(() => { current = false; });
			return { voiceId: 'voice-turn-1', requestId: 'r1', frame: {} };
		});
		await expect(deliverVoiceTurnThroughCore(turn(() => current).input)).rejects.toMatchObject({ code: 'scope_changed' });
		expect(ws.sent.some((frame) => frame.type === 'chat_turn_admit')).toBe(false);
		expect(unit.discard).toHaveBeenCalledWith('voice-turn-1');
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
	it('reuses an early preparation on the same socket: one snapshot, no second begin, then the admit', async () => {
		const early = prepareVoiceTurnThroughCore(CHAT, TURN);
		await early;
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot']);
		const { input, phases } = turn();
		await deliverVoiceTurnThroughCore(input, early);
		expect(unit.begin).toHaveBeenCalledTimes(1);
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot', 'chat_turn_admit']);
		expect(phases).toEqual(['core_early_reused', 'core_committing', 'canonical_sending', 'receipt_reading']);
		expect(unit.discard).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
	it('drops an early preparation made on a replaced socket and prepares again', async () => {
		const early = Promise.resolve({ voiceId: 'voice-turn-0', connection: {} });
		const { input } = turn();
		await deliverVoiceTurnThroughCore(input, early);
		expect(unit.discard).toHaveBeenCalledWith('voice-turn-0');
		expect(unit.begin).toHaveBeenCalledTimes(1);
		expect(unit.commit).toHaveBeenCalledWith(expect.objectContaining({ voiceId: 'voice-turn-1' }));
	});
});
