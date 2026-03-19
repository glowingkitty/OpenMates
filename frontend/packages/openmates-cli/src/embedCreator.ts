// frontend/packages/openmates-cli/src/embedCreator.ts
/**
 * @file Embed creation pipeline for the CLI — generates encrypted embeds
 * with proper key wrapping, matching the web app's zero-knowledge architecture.
 *
 * For each embed:
 * 1. Content is TOON-encoded (or JSON-fallback)
 * 2. A random AES-256 embed key is generated
 * 3. Content, type, and text_preview are encrypted with the embed key
 * 4. The embed key is wrapped with both master key and chat key
 * 5. SHA-256 hashes are computed for all IDs
 * 6. The encrypted embed + wrapped keys are attached to chat_message_added
 *
 * Mirrors: cryptoService.ts (encryptWithEmbedKey, wrapEmbedKeyWithMasterKey,
 *          wrapEmbedKeyWithChatKey, generateEmbedKey)
 *          chatSyncServiceSenders.ts (encrypted_embeds construction)
 *
 * Architecture: docs/architecture/embeds.md
 */

import { randomUUID, createHash, randomBytes, webcrypto } from "node:crypto";
import { encode as toonEncode } from "@toon-format/toon";

const cryptoApi = webcrypto as unknown as Crypto;
const AES_GCM_IV_LENGTH = 12;

// ── Internal crypto helpers ────────────────────────────────────────────
// Inlined here to avoid cross-module .js import issues with Node test runner.
// These mirror the same functions in crypto.ts.

function bytesToBase64(input: Uint8Array): string {
  return Buffer.from(input).toString("base64");
}

function toArrayBuffer(input: Uint8Array): ArrayBuffer {
  return input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength) as ArrayBuffer;
}

async function encryptAesGcm(
  plaintext: string,
  rawKeyBytes: Uint8Array,
): Promise<string> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const key = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(rawKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    key,
    new TextEncoder().encode(plaintext),
  );
  const cipherBytes = new Uint8Array(encrypted);
  const combined = new Uint8Array(iv.length + cipherBytes.length);
  combined.set(iv);
  combined.set(cipherBytes, iv.length);
  return bytesToBase64(combined);
}

async function wrapKey(
  embedKey: Uint8Array,
  wrappingKey: Uint8Array,
): Promise<string> {
  const cryptoKey = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(wrappingKey),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    cryptoKey,
    toArrayBuffer(embedKey),
  );
  const cipherBytes = new Uint8Array(encrypted);
  const combined = new Uint8Array(iv.length + cipherBytes.length);
  combined.set(iv);
  combined.set(cipherBytes, iv.length);
  return bytesToBase64(combined);
}

// ── Types ──────────────────────────────────────────────────────────────

/** A prepared embed ready for encryption and sending */
export interface PreparedEmbed {
  embedId: string;
  type: string;
  content: string;
  textPreview: string;
  status: string;
  filePath?: string;
  contentHash?: string;
  textLengthChars?: number;
}

/** A fully encrypted embed ready for the WebSocket payload */
export interface EncryptedEmbed {
  embed_id: string;
  encrypted_type: string;
  encrypted_content: string;
  encrypted_text_preview: string;
  status: string;
  hashed_chat_id: string;
  hashed_message_id: string;
  hashed_user_id: string;
  embed_ids?: string[];
  file_path?: string;
  content_hash?: string;
  text_length_chars?: number;
  created_at: number;
  updated_at: number;
  embed_keys: EmbedKeyWrapper[];
}

/** A wrapped embed key for storage */
export interface EmbedKeyWrapper {
  hashed_embed_id: string;
  key_type: "master" | "chat";
  hashed_chat_id: string | null;
  encrypted_embed_key: string;
  hashed_user_id: string;
  created_at: number;
}

// ── Public functions ───────────────────────────────────────────────────

/**
 * Generate a random AES-256 embed key (32 bytes).
 * Mirrors: cryptoService.ts generateEmbedKey()
 */
export function generateEmbedKey(): Uint8Array {
  return new Uint8Array(randomBytes(32));
}

/**
 * Compute SHA-256 hash of a string, returned as hex.
 * Mirrors: message_parsing/utils.ts computeSHA256()
 */
export function computeSHA256(content: string): string {
  return createHash("sha256").update(content).digest("hex");
}

/**
 * TOON-encode an object. Falls back to JSON if TOON fails.
 */
export function toonEncodeContent(data: Record<string, unknown>): string {
  try {
    return toonEncode(data);
  } catch {
    return JSON.stringify(data);
  }
}

/**
 * Generate a new UUID for embeds.
 */
export function generateEmbedId(): string {
  return randomUUID();
}

/**
 * Create an embed reference block for insertion into message content.
 * Mirrors: urlMetadataService.ts createEmbedReferenceBlock()
 */
export function createEmbedReferenceBlock(
  type: string,
  embedId: string,
): string {
  const ref = JSON.stringify({ type, embed_id: embedId }, null, 2);
  return "```json\n" + ref + "\n```";
}

/**
 * Encrypt a prepared embed and generate wrapped keys.
 *
 * Mirrors: chatSyncServiceSenders.ts encrypted_embeds construction
 *
 * @param embed The prepared (unencrypted) embed
 * @param masterKey The user's master key (raw bytes)
 * @param chatKey The chat's AES key (raw bytes) — null for new chats
 * @param chatId The chat UUID
 * @param messageId The message UUID
 * @param userId The user's hashed email
 * @returns Fully encrypted embed ready for WebSocket payload
 */
export async function encryptEmbed(
  embed: PreparedEmbed,
  masterKey: Uint8Array,
  chatKey: Uint8Array | null,
  chatId: string,
  messageId: string,
  userId: string,
): Promise<EncryptedEmbed | null> {
  try {
    // 1. Generate unique embed key
    const embedKey = generateEmbedKey();

    // 2. Encrypt embed fields with the embed key (AES-256-GCM)
    const encryptedContent = await encryptAesGcm(embed.content, embedKey);
    const encryptedType = await encryptAesGcm(embed.type, embedKey);
    const encryptedTextPreview = await encryptAesGcm(embed.textPreview, embedKey);

    // 3. Compute hashed IDs
    const hashedEmbedId = computeSHA256(embed.embedId);
    const hashedChatId = computeSHA256(chatId);
    const hashedMessageId = computeSHA256(messageId);
    const hashedUserId = computeSHA256(userId);

    // 4. Wrap embed key with master key
    const wrappedWithMaster = await wrapKey(embedKey, masterKey);
    const nowSeconds = Math.floor(Date.now() / 1000);

    const embedKeys: EmbedKeyWrapper[] = [
      {
        hashed_embed_id: hashedEmbedId,
        key_type: "master",
        hashed_chat_id: null,
        encrypted_embed_key: wrappedWithMaster,
        hashed_user_id: hashedUserId,
        created_at: nowSeconds,
      },
    ];

    // 5. Wrap embed key with chat key (if available)
    if (chatKey) {
      const wrappedWithChat = await wrapKey(embedKey, chatKey);
      embedKeys.push({
        hashed_embed_id: hashedEmbedId,
        key_type: "chat",
        hashed_chat_id: hashedChatId,
        encrypted_embed_key: wrappedWithChat,
        hashed_user_id: hashedUserId,
        created_at: nowSeconds,
      });
    }

    return {
      embed_id: embed.embedId,
      encrypted_type: encryptedType,
      encrypted_content: encryptedContent,
      encrypted_text_preview: encryptedTextPreview,
      status: embed.status,
      hashed_chat_id: hashedChatId,
      hashed_message_id: hashedMessageId,
      hashed_user_id: hashedUserId,
      file_path: embed.filePath,
      content_hash: embed.contentHash,
      text_length_chars: embed.textLengthChars,
      created_at: nowSeconds,
      updated_at: nowSeconds,
      embed_keys: embedKeys,
    };
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    process.stderr.write(`\x1b[31mError:\x1b[0m Failed to encrypt embed: ${msg}\n`);
    return null;
  }
}
