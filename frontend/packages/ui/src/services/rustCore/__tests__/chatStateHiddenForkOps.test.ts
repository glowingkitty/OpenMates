// Hidden-chat and fork operations of the `chatState` unit (hiddenOps.ts, forkOps.ts)
// over a fake binding: lockout mapping, lock state echo, vault lifetime (the secret
// stays in the unit), refusal codes and fork JSON marshalling. Rust decisions
// themselves are proven by chat_state/{hidden,fork}_tests.rs.
import { describe, expect, it } from 'vitest';
import { createHiddenHandlers } from '../chatState/hiddenOps';
import { createForkHandlers } from '../chatState/forkOps';
import { UnitRefusal } from '../host/unitPort';

function fakeVault() {
	const state = { unlocked: false, lockout: 0, locks: 0, freed: 0 };
	const vault = {
		is_unlocked: () => state.unlocked,
		remaining_lockout_seconds: () => state.lockout,
		unlock: async (code: string) => {
			if (state.lockout > 0) throw 'locked';
			if (code === 'wrong') throw 'crypto';
			state.unlocked = true;
			return 2;
		},
		wrap_with_code: async () => 'wrapped-with-code',
		wrap: () => 'wrapped',
		unwrap: (value: string) => (value === 'good' ? new Uint8Array([1]) : undefined),
		classify: async () => ({ class: 'hidden' as const, chatKey: new Uint8Array([2]) }),
		plan_hide: async () => ({ plan: 'needs_unlock' as const }),
		unhide: async () => { throw 'crypto'; },
		lock: () => { state.unlocked = false; state.locks++; },
		free: () => { state.freed++; },
	};
	return { state, vault };
}

async function masterKey(): Promise<CryptoKey> {
	return { type: 'secret' } as CryptoKey;
}

describe('hidden chat ops', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('maps the vault outcomes to the legacy service results and echoes the lock state', async () => {
		const { state, vault } = fakeVault();
		const handlers = createHiddenHandlers({ BrowserHiddenChatVault: function () { return vault; } as never });
		const signal = new AbortController().signal;
		const key = await masterKey();
		const base = { masterKey: key, salt: null, encryptedChatKeys: [], verifiedEncryptedChatKey: null, nowMs: 0 };

		expect(await handlers.hiddenUnlock({ ...base, code: 'wrong' }, signal)).toMatchObject({ success: false, lockedOut: false, unlocked: false });
		expect(await handlers.hiddenUnlock({ ...base, code: '1234' }, signal)).toMatchObject({ success: true, decryptedCount: 2, unlocked: true });
		expect(await handlers.hiddenWrap({ chatKey: new Uint8Array(32) }, signal)).toEqual({ encryptedChatKey: 'wrapped' });
		expect(await handlers.hiddenUnwrap({ encryptedChatKey: 'good' }, signal)).toEqual({ chatKey: new Uint8Array([1]) });
		expect(await handlers.hiddenUnwrap({ encryptedChatKey: 'bad' }, signal)).toEqual({ chatKey: null });
		expect(await handlers.hiddenUnhide({ masterKey: key, encryptedChatKey: 'x' }, signal)).toEqual({ encryptedChatKey: null });

		state.unlocked = false;
		state.lockout = 12;
		expect(await handlers.hiddenUnlock({ ...base, code: '1234' }, signal)).toMatchObject({ success: false, lockedOut: true, lockoutSeconds: 12 });
		expect(await handlers.hiddenWrap({ chatKey: new Uint8Array(32) }, signal)).toEqual({ encryptedChatKey: null });
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps the vault through a lockout and drops it once idle', async () => {
		const { state, vault } = fakeVault();
		const handlers = createHiddenHandlers({ BrowserHiddenChatVault: function () { return vault; } as never });
		const signal = new AbortController().signal;
		await handlers.hiddenClassify({ masterKey: await masterKey(), encryptedChatKey: 'k' }, signal);
		state.lockout = 5;
		expect(await handlers.hiddenLock({ nowMs: 0 }, signal)).toEqual({ unlocked: false, lockoutSeconds: 5 });
		expect(state.freed).toBe(0);
		state.lockout = 0;
		await handlers.hiddenLock({ nowMs: 0 }, signal);
		expect(state.freed).toBe(1);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses with protocol when the binding or master key is missing', async () => {
		const handlers = createHiddenHandlers({});
		await expect(handlers.hiddenClassify({ masterKey: { type: 'secret' } as CryptoKey, encryptedChatKey: 'k' }, new AbortController().signal))
			.rejects.toMatchObject({ code: 'protocol' });
	});
});

describe('fork ops', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('marshals select, re-encrypt and finalize through the binding', async () => {
		const handlers = createForkHandlers({
			chat_state_fork_select: (_messages: string, upTo: string) => [upTo],
			chat_state_fork_reencrypt_batch: () => JSON.stringify([{ message_id: 'n-1' }]),
			chat_state_fork_copy_field: (source: string | undefined) => (source ? 'copied' : undefined),
			chat_state_fork_encrypt_title: (title: string) => `enc:${title}`,
			chat_state_fork_finalize: () => JSON.stringify({ record: { chat_id: 'c' }, payload: { chat_id: 'c' } }),
		});
		const signal = new AbortController().signal;
		const keyBytes = new Uint8Array(32);
		expect(await handlers.forkSelect({ messagesJson: '[]', upToMessageId: 'm2' }, signal)).toEqual({ ids: ['m2'] });
		expect(await handlers.forkReencryptBatch({ messagesJson: '[]', newChatId: 'c', chatKey: keyBytes }, signal)).toEqual({ rows: [{ message_id: 'n-1' }] });
		expect(await handlers.forkCopyField({ sourceCiphertext: null, sourceKey: keyBytes, newKey: keyBytes }, signal)).toEqual({ value: null });
		expect(await handlers.forkCopyField({ sourceCiphertext: 'x', sourceKey: keyBytes, newKey: keyBytes }, signal)).toEqual({ value: 'copied' });
		expect(await handlers.forkEncryptTitle({ title: 'T', chatKey: keyBytes }, signal)).toEqual({ value: 'enc:T' });
		expect(await handlers.forkFinalize({ chatJson: '{}', rowsJson: '[]' }, signal)).toEqual({ record: { chat_id: 'c' }, payload: { chat_id: 'c' } });
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('answers stable Rust codes and collapses web error text to fork_refused', async () => {
		const signal = new AbortController().signal;
		const thrower = (reason: unknown) => createForkHandlers({ chat_state_fork_select: () => { throw reason; } });
		await expect(Promise.resolve().then(() => thrower('Fork point message not found').forkSelect({ messagesJson: '[]', upToMessageId: 'x' }, signal)))
			.rejects.toEqual(new UnitRefusal('fork_refused'));
		await expect(Promise.resolve().then(() => thrower('protocol').forkSelect({ messagesJson: '[]', upToMessageId: 'x' }, signal)))
			.rejects.toEqual(new UnitRefusal('protocol'));
	});
});
