// @vitest-environment node
/**
 * `presentRemote` unit handlers: request shapes reach the core binding as camelCase
 * state JSON, the core's code is kept on refusal, and a missing session refuses
 * before any core call. The core client and binding are stubs.
 */
import { describe, expect, it, vi } from 'vitest';
import { createPresentRemoteHandlers } from '../presentRemoteUnit';
import type { PresentRemoteState } from '../presentRemoteProtocol';

const STATE: PresentRemoteState = { embedId: 'deck-1', sessionId: 's', seq: 1, index: 2, step: 0, notesVisible: false, presenting: true, origin: 'remote' };
const signal = new AbortController().signal;

function handlers(client: Record<string, unknown>, borrow: unknown = undefined) {
	const release = vi.fn();
	const deps = { borrow: vi.fn(async () => borrow ?? ({ client, status: { handle: 'h', generation: 3 }, release })) };
	const binding = { present_remote_accept: vi.fn(() => true) };
	return { handlers: createPresentRemoteHandlers(binding, 'p', deps as never, signal), release, binding };
}

describe('presentRemote unit handlers', () => {
	// contract-test: direct surface=gui.web assertions=slides.present.remote-one-core
	it('forwards state JSON to the core and releases the borrow', async () => {
		const client = { present_remote_encrypt: vi.fn(async () => 'cipher'), present_remote_decrypt: vi.fn(async () => JSON.stringify(STATE)) };
		const { handlers: h, release, binding } = handlers(client);
		await expect(h.encrypt({ state: STATE }, signal)).resolves.toBe('cipher');
		expect(client.present_remote_encrypt).toHaveBeenCalledWith('h', 3, JSON.stringify(STATE));
		await expect(h.decrypt({ embedId: 'deck-1', ciphertext: 'cipher' }, signal)).resolves.toEqual(STATE);
		expect(client.present_remote_decrypt).toHaveBeenCalledWith('h', 3, 'deck-1', 'cipher');
		expect(h.accept({ state: STATE }, signal)).toBe(true);
		expect(binding.present_remote_accept).toHaveBeenCalledWith(JSON.stringify(STATE));
		expect(release).toHaveBeenCalledTimes(2);
	});

	// contract-test: direct surface=gui.web assertions=slides.present.remote-relay-private
	it('keeps the core code on refusal and refuses without a session before any core call', async () => {
		const client = { present_remote_decrypt: vi.fn(async () => { throw 'present_remote_embed_mismatch'; }) };
		const { handlers: h } = handlers(client);
		await expect(h.decrypt({ embedId: 'deck-1', ciphertext: 'c' }, signal)).rejects.toMatchObject({ code: 'present_remote_embed_mismatch' });
		const { handlers: local } = handlers(client, 'local');
		await expect(local.encrypt({ state: STATE }, signal)).rejects.toMatchObject({ code: 'local_session' });
	});
});
