// @vitest-environment node
/**
 * Main-socket carrier of a Rust-built voice turn: snapshot then admit on the
 * receipt's connection, resolution only on the exact-turn ACK, and a discard
 * (no admit frame) when the turn fails before commit. Socket and unit are stubs.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = (payload: Record<string, unknown>) => void;
const ws = vi.hoisted(() => {
	const handlers = new Map<string, Set<Handler>>();
	const closeHandlers = new Set<() => void>();
	return {
		connection: {} as object,
		autoSnapshot: true,
		handlers,
		closeHandlers,
		sent: [] as Array<{ type: string; payload: unknown; options: unknown }>,
		emit(type: string, payload: Record<string, unknown>) {
			for (const handler of [...(handlers.get(type) ?? [])]) handler(payload);
		},
		close() {
			for (const handler of [...closeHandlers]) handler();
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
		addEventListener: (name: string, handler: () => void) => { if (name === 'close') ws.closeHandlers.add(handler); },
		removeEventListener: (name: string, handler: () => void) => { if (name === 'close') ws.closeHandlers.delete(handler); },
		sendMessage: vi.fn(async (type: string, payload: Record<string, unknown>, options: { expectedConnection: object }) => {
			if (options?.expectedConnection !== ws.connection) throw new Error('replaced connection');
			ws.sent.push({ type, payload, options });
			if (type === 'personal_send_context_snapshot' && ws.autoSnapshot) {
				queueMicrotask(() => ws.emit('personal_send_context_snapshot_result', { request_id: payload.request_id, success: true }));
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

const shell = vi.hoisted(() => ({
	epoch: 1, save: vi.fn(), update: vi.fn(), getChat: vi.fn(), legacySend: vi.fn(), dispatch: vi.fn(),
}));
vi.mock('../../../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => 'workspace-user' }));
vi.mock('../../../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => shell.epoch }));
vi.mock('../../../db', () => ({
	chatDB: { getChat: shell.getChat, saveMessage: shell.save, updateChat: shell.update },
}));
vi.mock('../../../chatSyncService', () => ({
	chatSyncService: { webSocketConnected_FOR_SENDERS_ONLY: true, sendNewMessage: shell.legacySend, dispatchEvent: shell.dispatch },
}));
vi.mock('../../../../stores/userProfile', async () => {
	const { writable } = await import('svelte/store');
	return { userProfile: writable({ last_opened: CHAT }) };
});

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

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason: unknown) => void;
	const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
	return { promise, resolve, reject };
}

beforeEach(() => {
	ws.sent.length = 0;
	ws.handlers.clear();
	ws.closeHandlers.clear();
	ws.connection = {};
	ws.autoSnapshot = true;
	shell.epoch = 1;
	shell.save.mockReset().mockResolvedValue(undefined);
	shell.update.mockReset().mockResolvedValue(undefined);
	shell.getChat.mockReset().mockResolvedValue({ chat_id: CHAT, team_id: null, messages_v: 0 });
	shell.legacySend.mockReset();
	shell.dispatch.mockReset();
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
			return { voiceId: 'voice-turn-1', requestId: 'r1', frame: { request_id: 'r1' } };
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

describe('final voice turn with local persistence', () => {
	afterEach(() => vi.unstubAllEnvs());

	async function sender() {
		vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
		const { sendVoiceCallTurn } = await import('../../../voiceCallTurns');
		return (extra = {}) => sendVoiceCallTurn({
			callId: 'call-1', chatId: CHAT, turnId: TURN, text: 'confirmed phrase', createdAt: 1_700_000_123, ...extra,
		});
	}

	// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,video-call.audio.complete-turn-admission,video-call.privacy
	it('overlaps read-only preparation with both local writes and submits the exact core ciphertext once', async () => {
		const send = await sender();
		const save = deferred<void>();
		const update = deferred<void>();
		shell.save.mockReturnValueOnce(save.promise);
		shell.update.mockReturnValueOnce(update.promise);
		const encrypted = {
			protocol_version: 1, turn_id: TURN, message_id: TURN, chat_id: CHAT,
			encrypted_user_message: { encrypted_content: 'test-ciphertext' },
		};
		unit.commit.mockResolvedValueOnce({ admit: encrypted, userMessage: {}, waitAi: true });
		const sent = send();
		await vi.waitFor(() => expect(unit.prepare).toHaveBeenCalledOnce());
		expect(shell.save).toHaveBeenCalledOnce();
		expect(unit.commit).not.toHaveBeenCalled();
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot']);
		save.resolve(undefined);
		await vi.waitFor(() => expect(shell.update).toHaveBeenCalledOnce());
		expect(unit.commit).not.toHaveBeenCalled();
		update.resolve(undefined);
		await expect(sent).resolves.toBe(true);
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot', 'chat_turn_admit']);
		expect(ws.sent[1]).toEqual({ type: 'chat_turn_admit', payload: encrypted, options: { expectedConnection: ws.connection } });
		expect(ws.sent[1].payload).toBe(encrypted);
		expect(unit.commit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ finalText: 'confirmed phrase' }));
		expect(shell.legacySend).not.toHaveBeenCalled();
		expect(unit.discard).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.privacy
	it('makes no new snapshot when a likely-end snapshot on this socket is still valid', async () => {
		const send = await sender();
		const save = deferred<void>();
		shell.save.mockReturnValueOnce(save.promise);
		const early = prepareVoiceTurnThroughCore(CHAT, TURN);
		await early;
		const sent = send({ early });
		await vi.waitFor(() => expect(shell.save).toHaveBeenCalledOnce());
		expect(unit.begin).toHaveBeenCalledOnce();
		expect(unit.commit).not.toHaveBeenCalled();
		save.resolve(undefined);
		await expect(sent).resolves.toBe(true);
		expect(unit.begin).toHaveBeenCalledOnce();
		expect(unit.commit).toHaveBeenCalledOnce();
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot', 'chat_turn_admit']);
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.privacy
	it.each(['waiting', 'ready'])('rebuilds a %s snapshot after socket replacement while local storage is held', async (state) => {
		const send = await sender();
		const save = deferred<void>();
		shell.save.mockReturnValueOnce(save.promise);
		ws.autoSnapshot = state === 'ready';
		const oldConnection = ws.connection;
		unit.begin.mockResolvedValueOnce({ voiceId: 'stale-voice', requestId: 'stale-request',
			frame: { request_id: 'stale-request' } });
		const sent = send();
		await vi.waitFor(() => expect(ws.sent).toHaveLength(1));
		if (state === 'ready') await vi.waitFor(() => expect(unit.prepare).toHaveBeenCalledOnce());
		ws.connection = {};
		ws.close();
		ws.autoSnapshot = true;
		expect(unit.commit).not.toHaveBeenCalled();
		save.resolve(undefined);
		await expect(sent).resolves.toBe(true);
		await vi.waitFor(() => expect(unit.discard).toHaveBeenCalledExactlyOnceWith('stale-voice'));
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot', 'personal_send_context_snapshot', 'chat_turn_admit']);
		expect(ws.sent[0].options).toEqual({ expectedConnection: oldConnection });
		expect(ws.sent[1].options).toEqual({ expectedConnection: ws.connection });
		expect(ws.sent[2].options).toEqual({ expectedConnection: ws.connection });
		expect(unit.commit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ voiceId: 'voice-turn-1' }));
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.privacy
	it('aborts and retires the pending snapshot when workspace scope changes during storage', async () => {
		const send = await sender();
		const save = deferred<void>();
		shell.save.mockReturnValueOnce(save.promise);
		ws.autoSnapshot = false;
		const sent = send();
		await vi.waitFor(() => expect(ws.sent).toHaveLength(1));
		expect(ws.handlers.get('personal_send_context_snapshot_result')?.size).toBe(1);
		shell.epoch++;
		save.resolve(undefined);
		await expect(sent).resolves.toBe(false);
		await vi.waitFor(() => expect(unit.discard).toHaveBeenCalledExactlyOnceWith('voice-turn-1'));
		expect(ws.handlers.get('personal_send_context_snapshot_result')?.size).toBe(0);
		expect(ws.closeHandlers.size).toBe(0);
		ws.emit('personal_send_context_snapshot_result', { request_id: 'r1', success: true });
		expect(unit.prepare).not.toHaveBeenCalled();
		expect(unit.commit).not.toHaveBeenCalled();
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot']);
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission,video-call.privacy
	it.each(['save', 'update'] as const)('discards a prepared snapshot on local %s failure without submitting', async (write) => {
		const send = await sender();
		const persistence = deferred<void>();
		shell[write].mockReturnValueOnce(persistence.promise);
		const sent = send();
		await vi.waitFor(() => expect(unit.prepare).toHaveBeenCalledOnce());
		persistence.reject(new Error('test database error'));
		await expect(sent).rejects.toThrow('test database error');
		await vi.waitFor(() => expect(unit.discard).toHaveBeenCalledExactlyOnceWith('voice-turn-1'));
		expect(unit.commit).not.toHaveBeenCalled();
		expect(ws.sent.map((frame) => frame.type)).toEqual(['personal_send_context_snapshot']);
		expect(shell.dispatch).not.toHaveBeenCalled();
	});
});
