// contract-test-file: tooling
// @vitest-environment node
/**
 * `voiceTurn` unit protocol: begin -> prepare -> commit and discard round trip
 * through the handlers, validation refusals and stable core codes. The wasm
 * client and the core lease are stubs (the boundary other unit tests mock).
 */
import { describe, expect, it, vi } from 'vitest';

import { createVoiceTurnHandlers, type VoiceTurnClient } from '../voiceTurnUnit';
import type { CoreClientBorrow } from '../../drafts/coreClientBorrow';

const CHAT = '22222222-2222-4222-8222-222222222222';
const TURN = '33333333-3333-4333-8333-333333333333';
const SIGNAL = new AbortController().signal;

function setup(client: Partial<VoiceTurnClient>, refusal?: 'none' | 'busy' | 'local') {
	const release = vi.fn();
	const borrow = {
		client, release, status: { handle: 'h1', generation: 3, principal: 'p' }
	} as unknown as CoreClientBorrow;
	const handlers = createVoiceTurnHandlers('p', { borrow: async () => refusal ?? borrow }, new AbortController().signal);
	return { handlers, release };
}

describe('voiceTurn handlers', () => {
	it('round-trips begin, prepare and commit with the session handle and releases each borrow', async () => {
		const client: VoiceTurnClient = {
			voice_turn_begin: vi.fn(() => JSON.stringify({ voiceId: 'voice-turn-1', requestId: 'r1', frame: { purpose: 'send' } })),
			voice_turn_prepare: vi.fn(async () => undefined),
			voice_turn_commit: vi.fn(async () => JSON.stringify({ admit: { chat_id: CHAT }, userMessage: { id: TURN }, waitAi: true })),
			voice_turn_discard: vi.fn()
		};
		const { handlers, release } = setup(client);
		const begun = await handlers.begin({ chatId: CHAT, turnId: TURN }, SIGNAL);
		expect(begun).toEqual({ voiceId: 'voice-turn-1', requestId: 'r1', frame: { purpose: 'send' } });
		expect(client.voice_turn_begin).toHaveBeenCalledWith('h1', 3, CHAT, TURN);
		await expect(handlers.prepare({ voiceId: 'voice-turn-1', snapshotResult: { request_id: 'r1' } }, SIGNAL)).resolves.toEqual({});
		expect(client.voice_turn_prepare).toHaveBeenCalledWith('h1', 3, 'voice-turn-1', '{"request_id":"r1"}');
		const done = await handlers.commit({
			voiceId: 'voice-turn-1', callId: 'call-1', finalText: 'hello', createdAt: 1_700_000_123,
			heardBoundary: { assistantMessageId: 'a1', completedSequences: [0, 1], activeSequence: 2, activeOffsetMs: 400 }
		}, SIGNAL);
		expect(done).toEqual({ admit: { chat_id: CHAT }, userMessage: { id: TURN }, waitAi: true });
		expect(client.voice_turn_commit).toHaveBeenCalledWith('h1', 3, 'voice-turn-1', 'call-1',
			'{"assistantMessageId":"a1","completedSequences":[0,1],"activeSequence":2,"activeOffsetMs":400}', 'hello', 1_700_000_123);
		expect(release).toHaveBeenCalledTimes(3);
	});

	it('discards without sending and passes an absent boundary as empty', async () => {
		const client = {
			voice_turn_discard: vi.fn(),
			voice_turn_commit: vi.fn(async () => JSON.stringify({ admit: {}, userMessage: {}, waitAi: false }))
		};
		const { handlers } = setup(client);
		await expect(handlers.discard({ voiceId: 'voice-turn-1' }, SIGNAL)).resolves.toEqual({});
		expect(client.voice_turn_discard).toHaveBeenCalledWith('voice-turn-1');
		await handlers.commit({ voiceId: 'v', callId: 'c', finalText: 'x' }, SIGNAL);
		expect(client.voice_turn_commit).toHaveBeenCalledWith('h1', 3, 'v', 'c', '', 'x', 0);
		await expect(handlers.commit({ voiceId: 'v', callId: 'c', finalText: 'x', createdAt: 1.5 }, SIGNAL))
			.rejects.toMatchObject({ code: 'voice_turn_bad_time' });
	});

	it('keeps stable core codes, hides internal text and refuses bad input and lease states', async () => {
		const failing = setup({ voice_turn_prepare: vi.fn(async () => { throw 'protocol'; }), voice_turn_commit: vi.fn(async () => { throw new Error('Secret: boom'); }) });
		await expect(failing.handlers.prepare({ voiceId: 'v', snapshotResult: {} }, SIGNAL)).rejects.toMatchObject({ code: 'protocol' });
		await expect(failing.handlers.commit({ voiceId: 'v', callId: 'c', finalText: 'x' }, SIGNAL)).rejects.toMatchObject({ code: 'voice_turn_failed' });
		expect(failing.release).toHaveBeenCalledTimes(2);
		const { handlers } = setup({});
		await expect(handlers.commit({ voiceId: 'v', callId: 'c', finalText: '  ' }, SIGNAL)).rejects.toMatchObject({ code: 'voice_turn_bad_text' });
		await expect(handlers.begin({ chatId: '', turnId: TURN }, SIGNAL)).rejects.toMatchObject({ code: 'voice_turn_bad_chat' });
		await expect(handlers.prepare({ voiceId: 'v', snapshotResult: [] as never }, SIGNAL)).rejects.toMatchObject({ code: 'voice_turn_bad_snapshot' });
		await expect(setup({}, 'busy').handlers.begin({ chatId: CHAT, turnId: TURN }, SIGNAL)).rejects.toMatchObject({ code: 'core_busy' });
		await expect(setup({}, 'none').handlers.begin({ chatId: CHAT, turnId: TURN }, SIGNAL)).rejects.toMatchObject({ code: 'not_admitted' });
		await expect(setup({}, 'local').handlers.begin({ chatId: CHAT, turnId: TURN }, SIGNAL)).rejects.toMatchObject({ code: 'local_session' });
	});
});
