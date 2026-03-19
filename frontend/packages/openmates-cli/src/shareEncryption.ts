// frontend/packages/openmates-cli/src/shareEncryption.ts
/**
 * @file Share encryption for chat and embed share links.
 *
 * Direct Node.js port of:
 *   - frontend/packages/ui/src/services/shareEncryption.ts  (chat)
 *   - frontend/packages/ui/src/services/embedShareEncryption.ts (embed)
 *
 * The algorithm is identical — same PBKDF2 parameters, same AES-GCM IV
 * format, same URL-encoded blob serialization, same base64url encoding.
 * Any divergence here would produce share links that the web app cannot
 * decrypt.
 *
 * URL format:
 *   Chat:  {origin}/share/chat/{chatId}#key={encryptedBlob}
 *   Embed: {origin}/share/embed/{embedId}#key={encryptedBlob}
 *
 * Architecture: docs/architecture/share_chat.md
 */

import { webcrypto } from "node:crypto";

const crypto = webcrypto as unknown as Crypto;

// ── Types ──────────────────────────────────────────────────────────────

export type ShareDuration =
  | 0       // no expiration
  | 60      // 1 minute
  | 3600    // 1 hour
  | 86400   // 24 hours
  | 604800  // 7 days
  | 1209600 // 14 days
  | 2592000 // 30 days
  | 7776000; // 90 days

// ── Base64 URL-safe helpers ────────────────────────────────────────────
// Mirrors shareEncryption.ts base64UrlEncode / base64UrlDecode

function base64UrlEncode(data: Uint8Array): string {
  return Buffer.from(data)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function base64UrlDecode(str: string): Uint8Array {
  let b64 = str.replace(/-/g, "+").replace(/_/g, "/");
  while (b64.length % 4) b64 += "=";
  return new Uint8Array(Buffer.from(b64, "base64"));
}

// ── AES-GCM helpers ───────────────────────────────────────────────────
// Mirrors encryptAESGCM / decryptAESGCM in both services

async function encryptAESGCM(data: Uint8Array, key: CryptoKey): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  // Convert Uint8Arrays to ArrayBuffer for strict webcrypto typing
  const ivBuf = iv.buffer.slice(iv.byteOffset, iv.byteOffset + iv.byteLength) as ArrayBuffer;
  const dataBuf = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv: ivBuf }, key, dataBuf);
  const combined = new Uint8Array(12 + ciphertext.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(ciphertext), 12);
  return base64UrlEncode(combined);
}

// ── PBKDF2 key derivation ─────────────────────────────────────────────
// Mirrors deriveKeyFromChatId / deriveKeyFromEmbedId / deriveKeyFromPassword

const FIXED_SALT = new TextEncoder().encode("openmates-share-v1");
const PBKDF2_PARAMS = { name: "PBKDF2", iterations: 100000, hash: "SHA-256" } as const;
const AES_GCM_KEY_PARAMS = { name: "AES-GCM", length: 256 } as const;

async function deriveKeyFromId(id: string): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(id), "PBKDF2", false, ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { ...PBKDF2_PARAMS, salt: FIXED_SALT },
    material, AES_GCM_KEY_PARAMS, false, ["encrypt"],
  );
}

async function deriveKeyFromPassword(password: string, id: string): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { ...PBKDF2_PARAMS, salt: new TextEncoder().encode(`openmates-pwd-${id}`) },
    material, AES_GCM_KEY_PARAMS, false, ["encrypt"],
  );
}

// ── Blob serialization ────────────────────────────────────────────────
// Mirrors serializeKeyBlob / deserializeKeyBlob (both share the same format)

function serializeBlob(fields: Record<string, string | number>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(fields)) p.set(k, String(v));
  return p.toString();
}

// ── Chat share link ───────────────────────────────────────────────────

/**
 * Generate the encrypted blob for a chat share link.
 *
 * Mirrors: shareEncryption.ts generateShareKeyBlob()
 *
 * @param chatId          UUID of the chat
 * @param chatKeyBytes    Raw AES-256 chat key bytes (decrypted from encrypted_chat_key)
 * @param durationSeconds Expiry in seconds (0 = no expiry)
 * @param password        Optional password (max 10 chars)
 * @returns URL-safe base64 encrypted blob — append as #key=<blob>
 */
export async function generateChatShareBlob(
  chatId: string,
  chatKeyBytes: Uint8Array,
  durationSeconds: ShareDuration = 0,
  password?: string,
): Promise<string> {
  const enc = new TextEncoder();
  // Chat key as base64 (same as web app: btoa(String.fromCharCode(...key)))
  let keyForBlob = Buffer.from(chatKeyBytes).toString("base64");
  let pwdFlag: 0 | 1 = 0;

  if (password && password.length > 0) {
    const pwdKey = await deriveKeyFromPassword(password, chatId);
    keyForBlob = await encryptAESGCM(enc.encode(keyForBlob), pwdKey);
    pwdFlag = 1;
  }

  const serialized = serializeBlob({
    chat_encryption_key: keyForBlob,
    generated_at: Math.floor(Date.now() / 1000),
    duration_seconds: durationSeconds,
    pwd: pwdFlag,
  });

  const chatIdKey = await deriveKeyFromId(chatId);
  return encryptAESGCM(enc.encode(serialized), chatIdKey);
}

// ── Embed share link ──────────────────────────────────────────────────

/**
 * Generate the encrypted blob for an embed share link.
 *
 * Mirrors: embedShareEncryption.ts generateEmbedShareKeyBlob()
 *
 * @param embedId         UUID of the embed
 * @param embedKeyBytes   Raw AES-256 embed key bytes (from resolveEmbedKey)
 * @param durationSeconds Expiry in seconds (0 = no expiry)
 * @param password        Optional password (max 10 chars)
 * @returns URL-safe base64 encrypted blob — append as #key=<blob>
 */
export async function generateEmbedShareBlob(
  embedId: string,
  embedKeyBytes: Uint8Array,
  durationSeconds: ShareDuration = 0,
  password?: string,
): Promise<string> {
  const enc = new TextEncoder();
  // Embed key as base64 (mirrors: btoa(String.fromCharCode(...embedKey)))
  let keyForBlob = Buffer.from(embedKeyBytes).toString("base64");
  let pwdFlag: 0 | 1 = 0;

  if (password && password.length > 0) {
    const pwdKey = await deriveKeyFromPassword(password, embedId);
    keyForBlob = await encryptAESGCM(enc.encode(keyForBlob), pwdKey);
    pwdFlag = 1;
  }

  const serialized = serializeBlob({
    embed_encryption_key: keyForBlob,
    generated_at: Math.floor(Date.now() / 1000),
    duration_seconds: durationSeconds,
    pwd: pwdFlag,
  });

  const embedIdKey = await deriveKeyFromId(embedId);
  return encryptAESGCM(enc.encode(serialized), embedIdKey);
}

// ── URL construction ──────────────────────────────────────────────────

/** Derive the web app's origin from the API URL */
export function deriveWebOrigin(apiUrl: string): string {
  try {
    const url = new URL(apiUrl);
    // api.openmates.org → https://openmates.org
    // api.dev.openmates.org → https://dev.openmates.org
    url.hostname = url.hostname.replace(/^api\./, "");
    url.port = "";
    return url.origin;
  } catch {
    return "https://openmates.org";
  }
}

export function buildChatShareUrl(origin: string, chatId: string, blob: string): string {
  return `${origin}/share/chat/${chatId}#key=${blob}`;
}

export function buildEmbedShareUrl(origin: string, embedId: string, blob: string): string {
  return `${origin}/share/embed/${embedId}#key=${blob}`;
}
