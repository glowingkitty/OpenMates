// @vitest-environment node
/**
 * Early-end preparation bookkeeping of a call: one prepared turn at a time,
 * a resume or a newer hint discards it, the final send takes it once, and
 * hangup drops everything. The core carrier is an injected stub.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { VoiceCallEarlyTurns } from '../voiceCallEarlyTurns';

const delivery = {
	prepareVoiceTurnThroughCore: vi.fn(),
	discardEarlyVoiceTurn: vi.fn(async () => undefined),
};

const CHAT = '22222222-2222-4222-8222-222222222222';
const create = (enabled = true) => new VoiceCallEarlyTurns(enabled, async () => delivery);

beforeEach(() => {
	delivery.prepareVoiceTurnThroughCore.mockReset()
		.mockImplementation(async (_chat: string, turn: string) => ({ voiceId: `voice-${turn}`, connection: {} }));
	delivery.discardEarlyVoiceTurn.mockClear();
});

describe('VoiceCallEarlyTurns', () => {
	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
	it('prepares a hinted turn once and hands it to the final send exactly once', async () => {
		const early = create();
		early.hint(CHAT, 'turn-1');
		early.hint(CHAT, 'turn-1');
		await expect(early.take('turn-1')).resolves.toMatchObject({ voiceId: 'voice-turn-1' });
		expect(delivery.prepareVoiceTurnThroughCore).toHaveBeenCalledTimes(1);
		expect(early.take('turn-1')).toBeUndefined();
		expect(delivery.discardEarlyVoiceTurn).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
	it('discards on resume, on a newer turn hint and on hangup without sending anything', async () => {
		const early = create();
		early.hint(CHAT, 'turn-1');
		early.withdraw('turn-1');
		await vi.waitFor(() => expect(delivery.discardEarlyVoiceTurn).toHaveBeenCalledTimes(1));
		early.hint(CHAT, 'turn-2');
		early.hint(CHAT, 'turn-3');
		await vi.waitFor(() => expect(delivery.discardEarlyVoiceTurn).toHaveBeenCalledTimes(2));
		expect(early.take('turn-2')).toBeUndefined();
		early.clear();
		await vi.waitFor(() => expect(delivery.discardEarlyVoiceTurn).toHaveBeenCalledTimes(3));
		expect(early.take('turn-3')).toBeUndefined();
	});

	// contract-test: supporting surface=gui.web assertions=video-call.audio.complete-turn-admission
	it('stays inert in builds without the Rust core', () => {
		const early = create(false);
		early.hint(CHAT, 'turn-1');
		expect(early.take('turn-1')).toBeUndefined();
		expect(delivery.prepareVoiceTurnThroughCore).not.toHaveBeenCalled();
	});
});
