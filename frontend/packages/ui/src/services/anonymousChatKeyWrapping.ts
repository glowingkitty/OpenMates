// frontend/packages/ui/src/services/anonymousChatKeyWrapping.ts
// Local anonymous chat-key wrapping for logged-out free-usage chats.
// Anonymous chats still use normal chat rows, message rows, and per-chat keys.
// The only difference before signup is that the per-chat key is wrapped with a
// tab/session key instead of an account master key. Signup re-wraps the same
// raw chat key with the new account master key before server sync.

import { base64ToUint8Array, uint8ArrayToBase64 } from "./cryptoService";

export const ANONYMOUS_SESSION_KEY_STORAGE = "openmates_anonymous_chat_key";

const AES_KEY_LENGTH = 256;
const AES_IV_LENGTH = 12;

function bytesToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer as ArrayBuffer;
}

async function importAnonymousSessionKey(rawKey: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    bytesToArrayBuffer(base64ToUint8Array(rawKey)),
    { name: "AES-GCM" },
    true,
    ["encrypt", "decrypt"],
  );
}

async function generateAnonymousSessionKey(): Promise<CryptoKey> {
  const key = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: AES_KEY_LENGTH },
    true,
    ["encrypt", "decrypt"],
  );
  const rawKey = new Uint8Array(await crypto.subtle.exportKey("raw", key));
  sessionStorage.setItem(ANONYMOUS_SESSION_KEY_STORAGE, uint8ArrayToBase64(rawKey));
  return key;
}

export function hasAnonymousSessionKey(): boolean {
  return (
    typeof sessionStorage !== "undefined" &&
    !!sessionStorage.getItem(ANONYMOUS_SESSION_KEY_STORAGE)
  );
}

export async function getAnonymousSessionKey(): Promise<CryptoKey | null> {
  if (typeof sessionStorage === "undefined") return null;
  const rawKey = sessionStorage.getItem(ANONYMOUS_SESSION_KEY_STORAGE);
  if (!rawKey) return null;
  return importAnonymousSessionKey(rawKey);
}

export async function ensureAnonymousSessionKey(): Promise<CryptoKey> {
  const existing = await getAnonymousSessionKey();
  if (existing) return existing;
  return generateAnonymousSessionKey();
}

export function clearAnonymousSessionKey(): void {
  if (typeof sessionStorage !== "undefined") {
    sessionStorage.removeItem(ANONYMOUS_SESSION_KEY_STORAGE);
  }
}

export async function wrapAnonymousChatKey(chatKey: Uint8Array): Promise<string> {
  const sessionKey = await ensureAnonymousSessionKey();
  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    sessionKey,
    new Uint8Array(chatKey),
  );
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);
  return uint8ArrayToBase64(combined);
}

export async function unwrapAnonymousChatKey(
  encryptedChatKeyWithIV: string | null | undefined,
): Promise<Uint8Array | null> {
  if (!encryptedChatKeyWithIV) return null;
  const sessionKey = await getAnonymousSessionKey();
  if (!sessionKey) return null;

  try {
    const combined = base64ToUint8Array(encryptedChatKeyWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      sessionKey,
      ciphertext,
    );
    return new Uint8Array(decrypted);
  } catch (error) {
    console.debug("Failed to unwrap anonymous chat key:", error);
    return null;
  }
}
