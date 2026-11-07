/**
 * Async key-handle API next to ChatKeyManager.getKeySync/getKey (keys lane K2;
 * spec: specifications/features/auth#auth.keys.independent-unlock).
 *
 * Flag-on (VITE_OPENMATES_RUST_CORE with the crypto client registered): a handle
 * is backed by the Worker key store, and `decrypt`/`encrypt` run in the Worker
 * with the stored key, so the page does not touch key bytes on the hot path.
 * A miss loads through ChatKeyManager (the IndexedDB loader) and offers the key
 * to the Worker once. Flag-off: the same API delegates to the existing TS
 * functions, so callers have one code path. With the flag on there is no TS
 * decrypt fallback; Worker failures surface as errors.
 */
import { chatKeyManager } from './ChatKeyManager';
import { decryptWithChatKey, encryptWithChatKey } from './MessageEncryptor';
import { rustWebCrypto } from '../rustCore/crypto/webCryptoClient';
import { rustDecryptWithChatKey, rustHandlesChatKey } from '../rustCore/crypto/webCryptoFacades';
import type { ChatContentResult } from '../rustCore/crypto/webCryptoClient';
import { keyStateDecrypt, keyStateEncrypt, keyStateHandle, keyStateOffer, type KeyHandle } from '../rustCore/crypto/keyOps';

export interface DecryptContext {
  chatId?: string;
  fieldName?: string;
}

/** An opaque reference to a chat key; carries no key bytes. */
export interface ChatKeyHandle {
  readonly chatId: string;
  /** Debug fingerprint (`computeKeyFingerprint`) of the key behind the handle. */
  readonly fingerprint: string;
  /** Decrypts chat-key content; null on failure (same contract as `decryptWithChatKey`). */
  decrypt(encrypted: string, context?: DecryptContext): Promise<string | null>;
  /** Encrypts chat-key content. */
  encrypt(plaintext: string): Promise<string>;
}

function flagOn(): boolean {
  return import.meta.env.VITE_OPENMATES_RUST_CORE === '1';
}

function tsHandle(chatId: string, key: Uint8Array, fingerprint: string): ChatKeyHandle {
  return {
    chatId,
    fingerprint,
    decrypt: (encrypted, context) => decryptWithChatKey(encrypted, key, context),
    encrypt: (plaintext) => encryptWithChatKey(plaintext, key),
  };
}

function workerHandle(chatId: string, handle: KeyHandle): ChatKeyHandle {
  const client = rustWebCrypto();
  if (!client) throw new Error('rust_web_crypto_unavailable');
  return {
    chatId,
    fingerprint: handle.fingerprint,
    async decrypt(encrypted, context) {
      const first = await keyStateDecrypt<ChatContentResult>(client, chatId, encrypted);
      if (typeof first === 'string') return first;
      // null or fingerprint mismatch: the facade owns diagnostics and candidate recovery.
      const key = await chatKeyManager.getKey(chatId);
      if (!key) return null;
      return rustDecryptWithChatKey(client, encrypted, key, { chatId, ...context }, { first });
    },
    encrypt: (plaintext) => keyStateEncrypt(client, chatId, plaintext),
  };
}

/**
 * The handle for a chat's key, loading it if needed; null when no key can be obtained
 * (same meaning as `chatKeyManager.getKey` returning null).
 */
export async function getKeyHandle(chatId: string): Promise<ChatKeyHandle | null> {
  const client = flagOn() ? rustWebCrypto() : null;
  if (!client) {
    const key = await chatKeyManager.getKey(chatId);
    return key ? tsHandle(chatId, key, chatKeyManager.getProvenance(chatId)?.keyFingerprint ?? '') : null;
  }
  const known = await keyStateHandle(client, chatId);
  if (known) return workerHandle(chatId, known);
  const key = await chatKeyManager.getKey(chatId);
  if (!key) return null;
  if (!rustHandlesChatKey(key)) throw new Error('rust_keys_unsupported_key_length');
  const source = chatKeyManager.getProvenance(chatId)?.source ?? 'injected';
  await keyStateOffer(client, chatId, key, source, false);
  const offered = await keyStateHandle(client, chatId);
  if (!offered) throw new Error('rust_keys_offer_lost');
  return workerHandle(chatId, offered);
}
