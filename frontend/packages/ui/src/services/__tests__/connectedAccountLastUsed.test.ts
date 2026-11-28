// frontend/packages/ui/src/services/__tests__/connectedAccountLastUsed.test.ts
//
// Last-use recording of connected accounts is client-encrypted: the PATCH body
// carries only `encrypted_last_used_at`, never a plaintext time.

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
	vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
	return { plan: vi.fn() };
});
vi.mock('../../config/api', () => ({ getApiEndpoint: (p: string) => `https://api.test${p}` }));
vi.mock('../cryptoService', () => ({
	decryptWithMasterKey: vi.fn(async (v: string) => v.replace(/^enc:/, '')),
	encryptWithMasterKey: vi.fn(async (v: string) => `enc:${v}`)
}));
vi.mock('../rustCore/connectedAccounts/rustConnectedAccounts', () => ({
	rustPlanLastUsedTouches: mocks.plan
}));

import {
	assertNoPlaintextConnectedAccountFields,
	readConnectedAccountLastUsed,
	recordConnectedAccountsLastUsed
} from '../connectedAccountStorageService';

describe('connected-account last-use record', () => {
	beforeEach(() => vi.restoreAllMocks());

	// contract-test: supporting surface=gui.web assertions=connected-accounts.lifecycle.last-used
	it('PATCHes only the encrypted last-use time', async () => {
		const row = { id: 'acct-1', encrypted_last_used_at: 'enc:100' };
		mocks.plan.mockResolvedValue([{ id: 'acct-1', last_used_at: 5000 }]);
		const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) =>
			init?.method === 'PATCH'
				? new Response(JSON.stringify({ id: 'acct-1', sync_version: 2 }), { status: 200 })
				: new Response(JSON.stringify({ rows: [row] }), { status: 200 })
		);
		await recordConnectedAccountsLastUsed(['acct-1']);
		expect(mocks.plan.mock.calls[0][0].accounts).toEqual([{ id: 'acct-1', last_used_at: 100 }]);
		const patch = fetchSpy.mock.calls.find(([, init]) => init?.method === 'PATCH');
		expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ encrypted_last_used_at: 'enc:5000' });
	});

	// contract-test: supporting surface=gui.web assertions=connected-accounts.lifecycle.last-used
	it('reads a missing field as null and refuses a plaintext last_used_at', async () => {
		expect(await readConnectedAccountLastUsed({ id: 'a' } as never)).toBeNull();
		expect(() => assertNoPlaintextConnectedAccountFields({ last_used_at: 1 })).toThrow();
	});
});
