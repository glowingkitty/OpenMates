/**
 * Recording stand-ins for everything messageBookmarks, handlersMessageHighlights and
 * sendersMessageHighlights import (stores, master/chat-key crypto, IndexedDB,
 * socket). Shared by generateBookmarkHighlightVectors.mjs (temporary module tree)
 * and bookmarkHighlightVectors.test.ts (vi.mock) so both build the same vectors.
 */
import { get, writable } from 'svelte/store';
import type { VectorState } from './bookmarkHighlightBuild';

const holder = globalThis as unknown as { __bhVectors?: VectorState };
export const state: VectorState = (holder.__bhVectors ??= {
	plaintexts: new Map(), encryptedPlain: [], fetchBodies: [], payloads: [], frames: [], stored: [], cached: [], decrypted: null,
});

export const authStore = writable({ isAuthenticated: true });
export const userProfile = writable<{ user_id: string; encrypted_settings: string | null }>({ user_id: 'owner', encrypted_settings: null });
export const updateProfile = (value: Partial<{ user_id: string; encrypted_settings: string | null }>): void => userProfile.update((current) => ({ ...current, ...value }));
export const getApiEndpoint = (path: string): string => `https://api.example.test${path}`;

export const decryptWithMasterKey = async (cipher: string): Promise<string | undefined> => state.plaintexts.get(cipher);
export const encryptWithMasterKey = async (plain: string): Promise<string> => {
	const cipher = `opaque-${state.plaintexts.size}`;
	state.plaintexts.set(cipher, plain);
	state.encryptedPlain.push(plain);
	return cipher;
};

/** Resets the account profile; `settings` is the decrypted account-settings JSON (null = none). */
export function resetBookmarkAccount(settings: string | null): void {
	state.plaintexts.clear();
	if (settings !== null) state.plaintexts.set('initial', settings);
	authStore.set({ isAuthenticated: true });
	userProfile.set({ user_id: 'owner', encrypted_settings: settings === null ? null : 'initial' });
}
export const installFetch = (): void => {
	(globalThis as unknown as { fetch: unknown }).fetch = async (_url: string, init: { body: string }) => {
		state.fetchBodies.push(init.body);
		return { ok: true };
	};
};
export { get };

const KEY = new Uint8Array(32).fill(7);
export const chatDB = {};
export const webSocketService = {
	sendMessage: async (type: string, payload: Record<string, unknown>): Promise<void> => { state.frames.push({ type, payload }); },
};
export const chatKeyManager = {
	getKeySync: (): Uint8Array => KEY,
	getKey: async (): Promise<Uint8Array> => KEY,
	withKey: async (_chat: string, _purpose: string, run: (key: Uint8Array) => Promise<void>): Promise<void> => { await run(KEY); },
};
export const encryptHighlightPayload = async (payload: unknown): Promise<string> => {
	state.payloads.push(JSON.stringify(payload));
	return 'ENC';
};
export const decryptHighlightPayload = async (): Promise<unknown> => state.decrypted;
export const upsertHighlightIdb = async (_db: unknown, row: unknown): Promise<void> => { state.stored.push(row); };
export const deleteHighlightById = async (): Promise<void> => {};
export const getHighlightsForMessage = async (): Promise<unknown[]> => state.cached;
export const upsertHighlightStore = (): void => {};
export const removeHighlightStore = (): void => {};
export const markHighlightAsMine = (): void => {};
