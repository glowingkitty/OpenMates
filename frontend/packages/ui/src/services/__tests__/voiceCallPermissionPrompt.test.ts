/**
 * Spoken tap requests in a live call: chime, then the line; a reminder at
 * 15 s; a Memory request continues without memories at 30 s and records the
 * timeout; a tap stops everything and plays the thanks. Nothing approves.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('../websocketService', () => ({ webSocketService: { on: vi.fn() } }));
vi.mock('../assistantSpeechController', () => ({ assistantSpeechController: { playCallPrompt: vi.fn() } }));
vi.mock('../voiceCall', () => ({ voiceCallController: { subscribe: vi.fn(), playCue: vi.fn() } }));

import {
	CallPermissionPromptFlow,
	CALL_MEMORY_REQUEST_TIMEOUT_MS,
	CALL_PERMISSION_REMINDER_MS,
	type CallPermissionPromptPayload,
} from '../voiceCallPermissionPrompt';
import { parseMemoryRequestTimedOutEvent } from '../memoryRequestTimedOutEvent';

const CHAT = '22222222-2222-4222-8222-222222222222';
const base = '/audio/assistant-acknowledgements/sophia/en-US';
const payload = (kind: 'memory' | 'approval' = 'memory'): CallPermissionPromptPayload => ({
	chat_id: CHAT, request_id: 'req-1', voice_call_id: 'call-1', kind,
	clips: {
		request: `${base}/needs_memory-1.mp3`, reminder: `${base}/needs_reminder-1.mp3`,
		thanks: `${base}/approval_thanks-1.mp3`, ...(kind === 'memory' ? { timeout: `${base}/memory_timeout-1.mp3` } : {}),
	},
});

let live = true;
const deps = {
	isLiveCallFor: vi.fn(() => live),
	playCue: vi.fn(),
	playLine: vi.fn(),
	continueWithoutMemories: vi.fn(async () => undefined),
	recordTimedOut: vi.fn(async () => undefined),
	now: () => Date.now(),
};
const lines = () => deps.playLine.mock.calls.map((call) => call[1]);

describe('CallPermissionPromptFlow', () => {
	let flow: CallPermissionPromptFlow;
	beforeEach(() => {
		vi.useFakeTimers();
		live = true;
		Object.values(deps).forEach((fn) => typeof fn === 'function' && 'mockClear' in fn && fn.mockClear());
		flow = new CallPermissionPromptFlow(deps);
	});
	afterEach(() => vi.useRealTimers());

	// contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
	it('plays the chime before the request line', () => {
		flow.start(payload());
		expect(deps.playCue).toHaveBeenCalledTimes(1);
		expect(deps.playLine).not.toHaveBeenCalled();
		vi.advanceTimersByTime(500);
		expect(lines()).toEqual(['req-1:request']);
	});

	// contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
	it('reminds at 15 s and continues without memories at 30 s', async () => {
		flow.start(payload());
		expect(get(flow.countdown)?.requestId).toBe('req-1');
		vi.advanceTimersByTime(CALL_PERMISSION_REMINDER_MS + 500);
		expect(lines()).toEqual(['req-1:request', 'req-1:reminder']);
		expect(deps.playCue).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(CALL_MEMORY_REQUEST_TIMEOUT_MS);
		expect(lines()).toEqual(['req-1:request', 'req-1:reminder', 'req-1:timeout']);
		expect(deps.continueWithoutMemories).toHaveBeenCalledWith('req-1');
		expect(deps.recordTimedOut).toHaveBeenCalledWith(CHAT, 'req-1');
		expect(get(flow.countdown)).toBeNull();
		expect(flow.isActive('req-1')).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
	it('a tap stops the countdown and confirms aloud', async () => {
		flow.start(payload());
		vi.advanceTimersByTime(5_000);
		flow.answered('req-1');
		expect(lines()).toEqual(['req-1:request', 'req-1:thanks']);
		expect(get(flow.countdown)).toBeNull();
		await vi.advanceTimersByTimeAsync(CALL_MEMORY_REQUEST_TIMEOUT_MS);
		expect(deps.continueWithoutMemories).not.toHaveBeenCalled();
		expect(lines()).toEqual(['req-1:request', 'req-1:thanks']);
	});

	// contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
	it('an approval request reminds but never decides on its own', async () => {
		flow.start(payload('approval'));
		expect(get(flow.countdown)).toBeNull();
		await vi.advanceTimersByTimeAsync(CALL_MEMORY_REQUEST_TIMEOUT_MS * 3);
		expect(lines()).toEqual(['req-1:request', 'req-1:reminder']);
		expect(deps.continueWithoutMemories).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
	it('stays silent without a live call and stops when the call ends', async () => {
		live = false;
		flow.start(payload());
		expect(deps.playCue).not.toHaveBeenCalled();
		live = true;
		flow.start(payload());
		flow.dismissAll();
		await vi.advanceTimersByTimeAsync(CALL_MEMORY_REQUEST_TIMEOUT_MS);
		expect(lines()).toEqual([]);
		expect(deps.continueWithoutMemories).not.toHaveBeenCalled();
	});
});

describe('parseMemoryRequestTimedOutEvent', () => {
	// contract-test: supporting surface=gui.web assertions=video-call.chat.permission-prompt
	it('accepts only the exact presentation event', () => {
		const event = { schema_version: 1, type: 'memory_request', action: 'timed_out', request_id: 'req-1', created_at: 5 };
		expect(parseMemoryRequestTimedOutEvent(JSON.stringify(event))).toEqual(event);
		expect(parseMemoryRequestTimedOutEvent(JSON.stringify({ ...event, action: 'approved' }))).toBeNull();
		expect(parseMemoryRequestTimedOutEvent('memory_request')).toBeNull();
	});
});
