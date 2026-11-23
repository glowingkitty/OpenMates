import { describe, expect, it, vi } from 'vitest';
import { watchRetainedTurnOutcome, type TurnOutcomeEventSource } from '../send/rustTurnOutcomeWatch';

vi.mock('../send/sendPrepUnitClient', () => ({ sendPrepCall: vi.fn() }));

function events() {
	const handlers = new Map<string, Set<(payload: unknown) => void>>();
	const source: TurnOutcomeEventSource = {
		on: (kind, handler) => { if (!handlers.has(kind)) handlers.set(kind, new Set()); handlers.get(kind)!.add(handler); },
		off: (kind, handler) => { handlers.get(kind)?.delete(handler); },
	};
	const emit = (kind: string, payload: unknown) => { for (const handler of [...(handlers.get(kind) ?? [])]) handler(payload); };
	const count = () => [...handlers.values()].reduce((sum, set) => sum + set.size, 0);
	return { source, emit, count };
}
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('retained turn outcome watch', () => {
	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it('ends a turn the server refused for good and stops watching', async () => {
		const bus = events();
		const end = vi.fn(async () => undefined);
		const decide = vi.fn(async (request: { kind: string }) => (request.kind === 'error' ? 'rejected' as const : 'none' as const));
		watchRetainedTurnOutcome({ chatId: 'c1', messageId: 'm1', turnId: 't1', settled: new Promise(() => undefined), end, events: bus.source, decide });
		bus.emit('error', { chat_id: 'other', message_id: 'm1', retryable: false });
		await flush();
		expect(decide).not.toHaveBeenCalled();
		bus.emit('error', { chat_id: 'c1', message_id: 'm1', turn_id: 't1', retryable: false });
		await flush();
		expect(decide).toHaveBeenCalledWith(expect.objectContaining({ kind: 'error', chatId: 'c1', messageId: 'm1', turnId: 't1' }));
		expect(end).toHaveBeenCalledWith('rejected');
		expect(bus.count()).toBe(0);
	});

	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it('keeps the turn on frames the core does not treat as final', async () => {
		const bus = events();
		const end = vi.fn(async () => undefined);
		watchRetainedTurnOutcome({ chatId: 'c1', messageId: 'm1', turnId: 't1', settled: new Promise(() => undefined), end, events: bus.source, decide: async () => 'none' });
		bus.emit('chat_message_confirmed', { chat_id: 'c1', message_id: 'm1' });
		bus.emit('error', { chat_id: 'c1', message_id: 'm1', retryable: true });
		await flush();
		expect(end).not.toHaveBeenCalled();
		expect(bus.count()).toBe(2);
	});

	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it('stops when the ordinary confirmation settles and when a new attempt replaces it', async () => {
		const bus = events();
		let settle!: () => void;
		const settled = new Promise<void>((resolve) => { settle = resolve; });
		watchRetainedTurnOutcome({ chatId: 'c1', messageId: 'm1', turnId: 't1', settled: new Promise(() => undefined), end: async () => undefined, events: bus.source, decide: async () => 'finished' });
		watchRetainedTurnOutcome({ chatId: 'c1', messageId: 'm1', turnId: 't1', settled, end: async () => undefined, events: bus.source, decide: async () => 'finished' });
		expect(bus.count()).toBe(2);
		settle();
		await flush();
		expect(bus.count()).toBe(0);
	});
});
