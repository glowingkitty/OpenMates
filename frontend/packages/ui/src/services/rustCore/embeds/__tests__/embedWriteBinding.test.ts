// Streamed-embed writes bind the account principal themselves when the saved-chat
// admission refused (team workspace / device verification), and never for a signed-out profile.
import { afterEach, describe, expect, it, vi } from 'vitest';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';
const state = vi.hoisted(() => ({ userId: null as string | null, generation: null as number | null, key: null as { extractable: boolean } | null }));

vi.mock('svelte/store', () => ({ get: (store: { value: unknown }) => store.value }));
vi.mock('../../../../stores/userProfile', () => ({ userProfile: { get value() { return { user_id: state.userId }; } } }));
vi.mock('../../../cryptoService', () => ({ getKeyFromStorage: async () => state.key }));
vi.mock('../../host/sharedCoreRegistry', () => ({
	requireSharedRustCore: () => ({ get generation() { return state.generation; } })
}));
vi.mock('../embedWriteClient', () => ({ openEmbedWriteClient: vi.fn(async () => ({ unit: { closed: false }, close: () => undefined })) }));

import { registerPrincipalBinder } from '../../host/serverSessionRegistry';
import { openEmbedWriteClient } from '../embedWriteClient';
import { rustEmbedWriter, rustGuestEmbedWriter } from '../embedWriteSession';

describe('embed write principal binding', () => {
	afterEach(() => { state.userId = null; state.generation = null; state.key = null; });

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('binds the account principal when nothing is bound (team workspace, refused admission)', async () => {
		state.userId = PRINCIPAL;
		state.key = { extractable: false };
		const binder = vi.fn(async () => { state.generation = 1; });
		const off = registerPrincipalBinder(binder);
		await expect(rustEmbedWriter()).resolves.toMatchObject({ unit: { closed: false } });
		expect(binder).toHaveBeenCalledExactlyOnceWith(PRINCIPAL);
		off();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses embed_write_not_bound when the bind fails and nothing is bound', async () => {
		state.userId = PRINCIPAL;
		state.key = { extractable: false };
		vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const off = registerPrincipalBinder(async () => { throw new Error('boom'); });
		await expect(rustEmbedWriter()).rejects.toMatchObject({ code: 'embed_write_not_bound' });
		off();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a signed-out profile at once without binding or waiting for a bind', async () => {
		// A guest has no master key: nothing will ever bind, so waiting the bind
		// window would stall every guest embed write (Apps results rendered >30s late).
		vi.useFakeTimers();
		const binder = vi.fn(async () => undefined);
		const off = registerPrincipalBinder(binder);
		await expect(rustEmbedWriter()).rejects.toMatchObject({ code: 'embed_write_not_bound' });
		expect(vi.getTimerCount()).toBe(0);
		expect(binder).not.toHaveBeenCalled();
		off();
		vi.useRealTimers();
	});

	// contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content
	it('opens the guest writer without a principal, a bound generation or a master key', async () => {
		const binder = vi.fn(async () => undefined);
		const off = registerPrincipalBinder(binder);
		await expect(rustGuestEmbedWriter()).resolves.toMatchObject({ unit: { closed: false } });
		expect(openEmbedWriteClient).toHaveBeenLastCalledWith(expect.anything(), null);
		expect(binder).not.toHaveBeenCalled();
		off();
	});

	// contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content
	it('closes the guest writer when an account writer opens', async () => {
		const closeGuest = vi.fn();
		vi.mocked(openEmbedWriteClient).mockResolvedValueOnce({ unit: { closed: false }, close: closeGuest } as never);
		await rustGuestEmbedWriter();
		state.userId = PRINCIPAL;
		state.key = { extractable: false };
		const off = registerPrincipalBinder(async () => { state.generation = 1; });
		await rustEmbedWriter();
		expect(closeGuest).toHaveBeenCalledOnce();
		off();
	});
});
