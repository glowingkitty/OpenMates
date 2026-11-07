// Chat-key admission ops of the shared Worker `crypto` unit (keys lane K1).
// spec: specifications/features/auth#auth.keys.client-wrapped
// spec: specifications/surfaces/sdk#sdk.encryption.local-only
//
// Rust (`openmates_sdk::web_keys`, exports in browser_keys.rs) owns the key
// fingerprint, byte equality and the `injectKey` admission rule that
// ChatKeyManager.ts applies today. This file is the op table fragment the unit
// installer spreads into its dispatch plus the typed page-side helpers. It is
// only imported by flag-on code paths (the Worker installer and the key
// admission adapter), so flag-off builds never reference it. Replies carry
// fingerprints and decision strings only, never key bytes.
import type { WebCryptoOp } from './webCryptoClient';

export type KeyStateOp =
  | 'keysStateOffer' | 'keysStateHandle' | 'keysStateState' | 'keysStateSetState' | 'keysStateEnqueue'
  | 'keysStateCancel' | 'keysStatePending' | 'keysStateMarkPersisted' | 'keysStateReset' | 'keysStateRemove'
  | 'keysStateClear' | 'keysStateStats' | 'keysStateDecrypt' | 'keysStateEncrypt';

export type KeyOp = 'keysFingerprint' | 'keysEqual' | 'keysInjectDecision' | KeyStateOp;

/** Worker export behind each op; spread into the crypto unit's async export table. */
export const KEY_ASYNC_EXPORTS: Record<KeyOp, string> = {
  keysFingerprint: 'keysFingerprint',
  keysEqual: 'keysEqual',
  keysInjectDecision: 'keysInjectDecision',
  keysStateOffer: 'keysStateOffer',
  keysStateHandle: 'keysStateHandle',
  keysStateState: 'keysStateState',
  keysStateSetState: 'keysStateSetState',
  keysStateEnqueue: 'keysStateEnqueue',
  keysStateCancel: 'keysStateCancel',
  keysStatePending: 'keysStatePending',
  keysStateMarkPersisted: 'keysStateMarkPersisted',
  keysStateReset: 'keysStateReset',
  keysStateRemove: 'keysStateRemove',
  keysStateClear: 'keysStateClear',
  keysStateStats: 'keysStateStats',
  keysStateDecrypt: 'keysStateDecrypt',
  keysStateEncrypt: 'keysStateEncrypt',
};

export type KeySourceName =
  | 'created' | 'master_key' | 'server_sync' | 'share_link' | 'shared_storage'
  | 'bulk_init' | 'hidden_chat' | 'anonymous_session' | 'direct_chat' | 'injected';

export type InjectDecision = 'set' | 'replace' | 'upgrade_source' | 'keep' | 'reject';

/** The slice of WebCryptoClient these helpers need (so tests can pass a fake). */
export interface KeyOpsClient {
  call<T>(op: WebCryptoOp, ...args: unknown[]): Promise<T>;
}

/** `computeKeyFingerprint(key)` computed in the Worker. */
export function keyFingerprint(client: KeyOpsClient, key: Uint8Array): Promise<string> {
  return client.call<string>('keysFingerprint', key);
}

/** `keysAreEqual(a, b)` computed in the Worker. */
export function keysEqual(client: KeyOpsClient, a: Uint8Array, b: Uint8Array): Promise<boolean> {
  return client.call<boolean>('keysEqual', a, b);
}

/** What `injectKey` should do for `key` offered from `source`; rejects on an unknown source. */
export function keyInjectDecision(
  client: KeyOpsClient,
  existing: Uint8Array | null,
  currentSource: KeySourceName | null,
  key: Uint8Array,
  source: KeySourceName,
  force: boolean,
): Promise<InjectDecision> {
  return client.call<InjectDecision>('keysInjectDecision', existing ?? undefined, currentSource ?? undefined, key, source, force);
}

export type KeyLoadState = 'unloaded' | 'loading' | 'ready' | 'failed';

/** What the page may hold about a Worker-resident key: no key bytes. */
export interface KeyHandle {
  fingerprint: string;
  source: KeySourceName;
  timestamp: number;
  persisted: boolean;
  state: KeyLoadState;
}

export interface OfferOutcome {
  decision: InjectDecision;
  notifyReady: boolean;
  /** Waiter tickets to run now, in arrival order. */
  flushed: number[];
}

export type EnqueueOutcome = { kind: 'ready' } | { kind: 'queued'; ticket: number };

/** Offers a key to the Worker key store; the Worker keeps it, the reply carries no key bytes. */
export function keyStateOffer(client: KeyOpsClient, chatId: string, key: Uint8Array, source: KeySourceName, force: boolean): Promise<OfferOutcome> {
  return client.call<OfferOutcome>('keysStateOffer', chatId, new Uint8Array(key), source, force);
}

/** The handle of the chat's key, or null when the Worker holds none. */
export function keyStateHandle(client: KeyOpsClient, chatId: string): Promise<KeyHandle | null> {
  return client.call<KeyHandle | null>('keysStateHandle', chatId);
}

export function keyStateState(client: KeyOpsClient, chatId: string): Promise<KeyLoadState> {
  return client.call<KeyLoadState>('keysStateState', chatId);
}

export function keyStateSetState(client: KeyOpsClient, chatId: string, state: Exclude<KeyLoadState, 'ready'>): Promise<void> {
  return client.call<void>('keysStateSetState', chatId, state);
}

/** Parks a waiter; rejects with `rust_keys_queue_full` at the per-chat bound. */
export function keyStateEnqueue(client: KeyOpsClient, chatId: string): Promise<EnqueueOutcome> {
  return client.call<EnqueueOutcome>('keysStateEnqueue', chatId);
}

export function keyStateCancel(client: KeyOpsClient, chatId: string, ticket: number): Promise<boolean> {
  return client.call<boolean>('keysStateCancel', chatId, ticket);
}

export function keyStatePending(client: KeyOpsClient, chatId: string): Promise<number> {
  return client.call<number>('keysStatePending', chatId);
}

export function keyStateMarkPersisted(client: KeyOpsClient, chatId: string): Promise<boolean> {
  return client.call<boolean>('keysStateMarkPersisted', chatId);
}

/** Forgets the chat's key for a retry load; parked waiters stay. */
export function keyStateReset(client: KeyOpsClient, chatId: string): Promise<void> {
  return client.call<void>('keysStateReset', chatId);
}

/** Removes the chat's key; resolves the waiter tickets to reject. */
export function keyStateRemove(client: KeyOpsClient, chatId: string): Promise<number[]> {
  return client.call<number[]>('keysStateRemove', chatId);
}

/** Terminates all Worker key state (logout, account switch); resolves the waiter tickets to reject. */
export function keyStateClear(client: KeyOpsClient): Promise<number[]> {
  return client.call<number[]>('keysStateClear');
}

export function keyStateStats(client: KeyOpsClient): Promise<{ keys: number; unpersisted: number }> {
  return client.call<{ keys: number; unpersisted: number }>('keysStateStats');
}

/** `decryptWithChatKey` result shape; rejects `rust_keys_no_key` when the Worker holds no key. */
export function keyStateDecrypt<T>(client: KeyOpsClient, chatId: string, ciphertext: string): Promise<T> {
  return client.call<T>('keysStateDecrypt', chatId, ciphertext);
}

export function keyStateEncrypt(client: KeyOpsClient, chatId: string, plaintext: string): Promise<string> {
  return client.call<string>('keysStateEncrypt', chatId, plaintext);
}
