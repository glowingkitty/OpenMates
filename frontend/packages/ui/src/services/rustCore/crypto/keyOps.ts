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

export type KeyOp = 'keysFingerprint' | 'keysEqual' | 'keysInjectDecision';

/** Worker export behind each op; spread into the crypto unit's async export table. */
export const KEY_ASYNC_EXPORTS: Record<KeyOp, string> = {
  keysFingerprint: 'keysFingerprint',
  keysEqual: 'keysEqual',
  keysInjectDecision: 'keysInjectDecision',
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
