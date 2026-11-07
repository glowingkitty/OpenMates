// contract-test-file: tooling
// spec: specifications/features/auth#auth.keys.client-wrapped
// TS-generated parity vectors for the shared Rust guest promotion policy.
// packages/openmates-rust/src/web_guest_ts_vectors.json holds inputs plus the
// outcomes of the existing anonymousChatPromotionService.ts (flag off); this test
// fails if the TypeScript behaviour drifts from the vectors, and
// web_guest_tests.rs replays the same file against Rust. It also checks the
// crypto unit routes the guest op.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockAnonymousStorage = vi.hoisted(() => ({ getAllChats: vi.fn(), getMessagesForChat: vi.fn(), clearAll: vi.fn() }));
const mockChatDB = vi.hoisted(() => ({
	init: vi.fn(), encryptMessageFields: vi.fn(), updateChat: vi.fn(), saveMessage: vi.fn(), deleteMessage: vi.fn()
}));
const mockWebSocketService = vi.hoisted(() => ({ sendMessage: vi.fn() }));

vi.mock('../../anonymousChatStorage', () => ({ anonymousChatStorage: mockAnonymousStorage }));
vi.mock('../../db', () => ({ chatDB: mockChatDB }));
vi.mock('../../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array(32)) } }));
vi.mock('../../websocketService', () => ({ webSocketService: mockWebSocketService }));
vi.mock('../../cryptoService', () => ({ encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped') }));

import { promoteAnonymousChatsAfterSignup } from '../../anonymousChatPromotionService';
import { guestPromotionPlan } from '../crypto/guestOps';
import { createCryptoUnit } from '../crypto/cryptoUnitInstaller';

interface VectorMessage { message_id: string }
const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_guest_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));

describe('guest promotion parity vectors', () => {
	beforeEach(() => vi.clearAllMocks());

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('TypeScript promotion decisions match the vectors', async () => {
		for (const c of vectors.cases) {
			vi.clearAllMocks();
			mockChatDB.encryptMessageFields.mockImplementation(async (m: VectorMessage) => ({ ...m, encrypted_content: 'enc' }));
			mockAnonymousStorage.getAllChats.mockResolvedValue([{
				chat_id: 'anonymous-x', created_at: c.chat.created_at ?? undefined, updated_at: c.chat.updated_at, is_anonymous: true
			}]);
			mockAnonymousStorage.getMessagesForChat.mockResolvedValue(c.messages.map((m: object) => ({ ...m, chat_id: 'anonymous-x' })));
			await promoteAnonymousChatsAfterSignup();
			const index = (id: string) => c.messages.findIndex((m: VectorMessage) => m.message_id === id);
			if (c.expected.promotable.length === 0) {
				expect(mockWebSocketService.sendMessage, c.name).not.toHaveBeenCalled();
				continue;
			}
			const uploaded = mockWebSocketService.sendMessage.mock.calls[0][1].message_history;
			expect(uploaded.map((m: VectorMessage) => index(m.message_id)), c.name).toEqual(c.expected.promotable);
			expect(mockChatDB.deleteMessage.mock.calls.map((call) => index(call[0])), c.name).toEqual(c.expected.delete);
			expect(mockChatDB.saveMessage.mock.calls.map((call) => index(call[0].message_id)), c.name).toEqual(c.expected.resave);
			const promoted = mockChatDB.updateChat.mock.calls[0][0];
			expect(promoted.messages_v, c.name).toBe(c.expected.messages_v);
			expect(promoted.created_at, c.name).toBe(c.expected.created_at);
			expect(promoted.last_edited_overall_timestamp, c.name).toBe(c.expected.last_edited);
		}
	});
});

describe('crypto unit guest op', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('routes guestPromotionPlan to the Rust export and decodes the plan', async () => {
		const calls: unknown[][] = [];
		const plan = { promotable: [1], delete: [], resave: [], messages_v: 1, created_at: 3, last_edited: 4 };
		// Every other export is a no-op stub: the unit only checks that each required export is a function.
		const own: Record<string, unknown> = {
			guestPromotionPlan: (input: string) => { calls.push([input]); return JSON.stringify(plan); }
		};
		const binding = new Proxy(own, { get: (target, name) => target[name as string] ?? (() => null) });
		const unit = createCryptoUnit(binding);
		const client = {
			call: async <T>(op: string, ...args: unknown[]) => {
				const replies = await unit.handle({ version: 1, requests: [{ id: 1, op: op as never, args }] });
				const response = replies!.responses[0];
				if (!('value' in response)) throw new Error('crypto unit refused the request');
				return response.value as T;
			}
		};
		const result = await guestPromotionPlan(client, { created_at: 3 }, [{ role: 'user', status: 'synced', content: 'a', created_at: 3 }]);
		expect(result).toEqual(plan);
		expect(JSON.parse(calls[0][0] as string).chat).toEqual({ created_at: 3, updated_at: null });
	});
});
