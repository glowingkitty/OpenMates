// Streamed-embed writes bind the account principal themselves when the saved-chat
// admission refused (team workspace / device verification), and never for a signed-out profile.
import { afterEach, describe, expect, it, vi } from 'vitest';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';
const state = vi.hoisted(() => ({ userId: null as string | null, generation: null as number | null }));

vi.mock('svelte/store', () => ({ get: (store: { value: unknown }) => store.value }));
vi.mock('../../../../stores/userProfile', () => ({ userProfile: { get value() { return { user_id: state.userId }; } } }));
vi.mock('../../../cryptoService', () => ({ getKeyFromStorage: async () => null }));
vi.mock('../../host/sharedCoreRegistry', () => ({
	requireSharedRustCore: () => ({ get generation() { return state.generation; } })
}));
vi.mock('../embedWriteClient', () => ({ openEmbedWriteClient: vi.fn() }));

import { registerPrincipalBinder } from '../../host/serverSessionRegistry';
import { rustEmbedWriter } from '../embedWriteSession';

describe('embed write principal binding', () => {
	afterEach(() => { state.userId = null; state.generation = null; });

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('binds the account principal when nothing is bound (team workspace, refused admission)', async () => {
		state.userId = PRINCIPAL;
		const binder = vi.fn(async () => { state.generation = 1; });
		const off = registerPrincipalBinder(binder);
		await expect(rustEmbedWriter()).rejects.toMatchObject({ code: 'embed_write_no_master_key' });
		expect(binder).toHaveBeenCalledExactlyOnceWith(PRINCIPAL);
		off();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses embed_write_not_bound when the bind fails and nothing is bound', async () => {
		state.userId = PRINCIPAL;
		vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const off = registerPrincipalBinder(async () => { throw new Error('boom'); });
		await expect(rustEmbedWriter()).rejects.toMatchObject({ code: 'embed_write_not_bound' });
		off();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('does not bind for a signed-out profile', async () => {
		vi.useFakeTimers();
		const binder = vi.fn(async () => undefined);
		const off = registerPrincipalBinder(binder);
		const pending = rustEmbedWriter();
		const assertion = expect(pending).rejects.toMatchObject({ code: 'embed_write_not_bound' });
		await vi.advanceTimersByTimeAsync(16_000);
		await assertion;
		expect(binder).not.toHaveBeenCalled();
		off();
		vi.useRealTimers();
	});
});
