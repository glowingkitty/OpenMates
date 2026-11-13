/**
 * Page singleton of the shared Worker's `embedWrite` unit (U9 slice 2;
 * VITE_OPENMATES_RUST_CORE builds only). One client per bound generation,
 * opened lazily with a non-extractable copy of the master CryptoKey and shared by
 * the streamed-embed writer (rustStreamedEmbedWrite.ts) and stored-row reads
 * (embedKeyClient.ts). An unbind (`unit_unbound`) or a crash (`unit_retired`)
 * retires the unit port, which drops the client; the next call reopens in the new generation.
 *
 * The session broker binds at boot and has no bind event, so a call made
 * before the bind waits for a bound generation (bounded; refuses
 * `embed_write_not_bound`). There is no TS fallback.
 */
import { getKeyFromStorage } from '../../cryptoService';
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { currentPrincipalBinder } from '../host/serverSessionRegistry';
import { UnitPortError } from '../host/unitPort';
import { openEmbedWriteClient, type EmbedWriteClient } from './embedWriteClient';

const BIND_WAIT_MS = 15_000;
const BIND_POLL_MS = 50;

let current: { core: SharedRustCore; generation: number; client: Promise<EmbedWriteClient> } | null = null;

/**
 * The stored master key is extractable (it is re-wrapped for server sync); the
 * unit accepts only a non-extractable key, so the Worker session can never
 * export it. The raw copy lives only for the re-import and is zeroed.
 */
async function nonExtractable(key: CryptoKey): Promise<CryptoKey> {
	if (!key.extractable) return key;
	const raw = new Uint8Array(await crypto.subtle.exportKey('raw', key));
	try {
		return await crypto.subtle.importKey('raw', raw, key.algorithm, false, key.usages);
	} finally {
		raw.fill(0);
	}
}

/** Account principal of the signed-in profile (never a workspace id), null when signed out. */
async function accountPrincipal(): Promise<string | null> {
	const [{ get }, { userProfile }] = await Promise.all([import('svelte/store'), import('../../../stores/userProfile')]);
	return get(userProfile).user_id;
}

/**
 * The saved-chat admission binds the core only for a personal workspace on a
 * verified device; a streamed embed arrives in team workspaces and during device
 * verification too. When nothing is bound the account principal is bound here
 * (same principal the saved-chat admission would use; a later admission reuses it).
 */
async function bindAccountPrincipal(): Promise<void> {
	const binder = currentPrincipalBinder();
	const principal = binder ? await accountPrincipal() : null;
	if (binder && principal) await binder(principal);
}

async function boundGeneration(core: SharedRustCore): Promise<number> {
	const deadline = Date.now() + BIND_WAIT_MS;
	if (core.generation === null && !(await getKeyFromStorage())) {
		// Signed out (guest): no principal will ever bind and the unit cannot open
		// without the master key, so refuse now instead of stalling every write.
		throw new UnitPortError('embed_write_not_bound');
	}
	if (core.generation === null) {
		try {
			await bindAccountPrincipal();
		} catch (error) {
			if (core.generation === null) {
				console.warn('[RustEmbedWrite] principal bind failed', error);
				throw new UnitPortError('embed_write_not_bound');
			}
		}
	}
	while (core.generation === null) {
		if (Date.now() >= deadline) throw new UnitPortError('embed_write_not_bound');
		await new Promise((resolve) => setTimeout(resolve, BIND_POLL_MS));
	}
	return core.generation;
}

/** The `embedWrite` client of the current generation (opens it on first use). */
export async function rustEmbedWriter(): Promise<EmbedWriteClient> {
	const core = requireSharedRustCore();
	const generation = await boundGeneration(core);
	if (current && current.core === core && current.generation === generation) {
		const client = await current.client;
		if (!client.unit.closed) return client;
	}
	const stale = current;
	stale?.client.then((client) => client.close(), () => undefined);
	const opening = (async () => {
		const masterKey = await getKeyFromStorage();
		if (!masterKey) throw new UnitPortError('embed_write_no_master_key');
		return openEmbedWriteClient(core, await nonExtractable(masterKey));
	})();
	current = { core, generation, client: opening };
	opening.catch(() => { if (current?.client === opening) current = null; });
	return opening;
}

const closeHooks = new Set<() => void>();
/** Page caches of opened embed plaintext register here; they are dropped with the session. */
export function onRustEmbedWriterClosed(forget: () => void): void {
	closeHooks.add(forget);
}

/** Closes the client before a logout/account-switch unbind (its keys are forgotten with the session). */
export function closeRustEmbedWriter(): void {
	const stale = current;
	current = null;
	for (const forget of closeHooks) forget();
	stale?.client.then((client) => client.close(), () => undefined);
}

/**
 * Drops one opened client (and closes it) after a request timeout so the next
 * call reopens the `embedWrite` unit instead of reusing a stalled port. A client
 * that is no longer the current one is left alone.
 */
export function discardRustEmbedWriter(client: EmbedWriteClient): void {
	const stale = current;
	if (stale) {
		void stale.client.then((open) => { if (open === client && current === stale) current = null; }, () => undefined);
	}
	client.close();
}

/**
 * True for a Worker/unit failure that heals by itself (stalled or restarted
 * Worker, unbound generation, IndexedDB briefly unavailable): callers must not
 * record it as a permanent decryption failure.
 */
export function isTransientRustWorkerError(error: unknown): boolean {
	if (error instanceof UnitPortError) {
		return ['unit_timeout', 'unit_retired', 'unit_unbound', 'unit_closed', 'unit_aborted', 'embed_write_not_bound'].includes(error.code);
	}
	if (error instanceof Error) {
		return error.message === 'embed_store_unavailable' || error.message.startsWith('shared_core_');
	}
	return false;
}
