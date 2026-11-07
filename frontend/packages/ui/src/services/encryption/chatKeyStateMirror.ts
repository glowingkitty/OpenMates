/**
 * Flag-on mirror of ChatKeyManager's key lifecycle into the Worker key store
 * (keys lane K2; spec: specifications/features/auth#auth.keys.client-wrapped).
 *
 * ChatKeyManager still loads, wraps and persists keys; every key it accepts is
 * offered to the Rust `KeyStore` in the shared Worker (`rustCore/crypto/keyOps.ts`)
 * so migrated callers can use opaque handles (`chatKeyHandles.ts`). Removal,
 * reload and logout/account-switch clearing are forwarded the same way, which
 * terminates the Worker key state. Everything is a no-op unless the flag build
 * registered the crypto client; the adapter re-offers a key on a handle miss, so
 * a call skipped before registration cannot leave a stale or missing key.
 * This module must not import ChatKeyManager (it is imported by it).
 */
import { rustWebCrypto } from '../rustCore/crypto/webCryptoClient';
import {
  keyStateClear,
  keyStateMarkPersisted,
  keyStateOffer,
  keyStateRemove,
  keyStateReset,
  type KeySourceName,
} from '../rustCore/crypto/keyOps';

function report(action: string, error: unknown): void {
  console.error(`[ChatKeyStateMirror] ${action} failed`, error);
}

/** Offers an accepted key; `force` follows the TS write path (set paths replace, injectKey upgrades only). */
export function mirrorKeyOffer(chatId: string, key: Uint8Array, source: KeySourceName, force: boolean): void {
  const client = rustWebCrypto();
  if (!client || key.length === 0) return;
  keyStateOffer(client, chatId, key, source, force).catch((error: unknown) => report('offer', error));
}

/** A created (provisional) key is now stored wrapped. */
export function mirrorKeyPersisted(chatId: string): void {
  const client = rustWebCrypto();
  if (client) keyStateMarkPersisted(client, chatId).catch((error: unknown) => report('mark persisted', error));
}

/** Forwards `removeKey`. */
export function mirrorKeyRemove(chatId: string): void {
  const client = rustWebCrypto();
  if (client) keyStateRemove(client, chatId).catch((error: unknown) => report('remove', error));
}

/** Forwards `reloadKey` (forget the key, keep nothing stale for the retry load). */
export function mirrorKeyReset(chatId: string): void {
  const client = rustWebCrypto();
  if (client) keyStateReset(client, chatId).catch((error: unknown) => report('reset', error));
}

/** Forwards `clearAll` (logout, forced logout, account switch): terminates the Worker key state. */
export function mirrorKeysClear(): void {
  const client = rustWebCrypto();
  if (client) keyStateClear(client).catch((error: unknown) => report('clear', error));
}
