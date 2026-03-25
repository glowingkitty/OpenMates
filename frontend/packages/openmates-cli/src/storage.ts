/*
 * OpenMates CLI local session storage.
 *
 * Purpose: persist pair-login session data and local-only incognito chats.
 * Architecture: filesystem state in ~/.openmates with strict permissions.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: master key stored via OS keychain or machine-encrypted file when
 *           available; falls back to plaintext in session.json.
 *           See src/keychain.ts for the three-tier storage strategy.
 * Tests: frontend/packages/openmates-cli/tests/storage.test.ts
 */

import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import {
  type MasterKeyStorageType,
  storeMasterKey,
  retrieveMasterKey,
  deleteMasterKey,
} from "./keychain.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** In-memory session — always has masterKeyExportedB64 populated. */
export interface OpenMatesSession {
  apiUrl: string;
  sessionId: string;
  wsToken: string | null;
  cookies: Record<string, string>;
  masterKeyExportedB64: string;
  hashedEmail: string;
  userEmailSalt: string;
  createdAt: number;
  authorizerDeviceName: string | null;
  autoLogoutMinutes: number | null;
}

/**
 * On-disk session — master key may be absent if stored externally.
 * masterKeyStorage indicates where the key lives.
 */
interface SessionOnDisk {
  apiUrl: string;
  sessionId: string;
  wsToken: string | null;
  cookies: Record<string, string>;
  /** Present only when masterKeyStorage is "plaintext" or for legacy sessions */
  masterKeyExportedB64?: string;
  /** Where the master key is stored (absent in legacy sessions = plaintext) */
  masterKeyStorage?: MasterKeyStorageType;
  /** Base64 AES-256-GCM ciphertext (only when masterKeyStorage is "encrypted") */
  masterKeyEncrypted?: string;
  hashedEmail: string;
  userEmailSalt: string;
  createdAt: number;
  authorizerDeviceName: string | null;
  autoLogoutMinutes: number | null;
}

export interface IncognitoHistoryItem {
  role: "user" | "assistant";
  content: string;
  createdAt: number;
}

// ---------------------------------------------------------------------------
// Filesystem helpers
// ---------------------------------------------------------------------------

function getStateDir(): string {
  return join(homedir(), ".openmates");
}

function ensureStateDir(): string {
  const dir = getStateDir();
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  }
  chmodSync(dir, 0o700);
  return dir;
}

function readJsonFile<T>(filePath: string): T | null {
  if (!existsSync(filePath)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

function writeJsonFile(filePath: string, data: unknown): void {
  writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, {
    mode: 0o600,
  });
  chmodSync(filePath, 0o600);
}

// ---------------------------------------------------------------------------
// Session CRUD — keychain-aware
// ---------------------------------------------------------------------------

/**
 * Save session to disk. Attempts to store the master key in the OS keychain
 * or an encrypted file; only falls back to plaintext if both fail.
 */
export function saveSession(session: OpenMatesSession): void {
  const filePath = join(ensureStateDir(), "session.json");

  const result = storeMasterKey(session.masterKeyExportedB64, session.hashedEmail);

  const onDisk: SessionOnDisk = {
    apiUrl: session.apiUrl,
    sessionId: session.sessionId,
    wsToken: session.wsToken,
    cookies: session.cookies,
    hashedEmail: session.hashedEmail,
    userEmailSalt: session.userEmailSalt,
    createdAt: session.createdAt,
    authorizerDeviceName: session.authorizerDeviceName,
    autoLogoutMinutes: session.autoLogoutMinutes,
    masterKeyStorage: result.type,
  };

  if (result.type === "encrypted") {
    onDisk.masterKeyEncrypted = result.encryptedData;
  } else if (result.type === "plaintext") {
    onDisk.masterKeyExportedB64 = session.masterKeyExportedB64;
  }
  // For "keychain", the key is not stored on disk at all

  writeJsonFile(filePath, onDisk);

  if (result.type !== "plaintext") {
    process.stderr.write("Decrypting data...\n");
  }
}

/**
 * Load session from disk. Retrieves the master key from whatever storage
 * tier it was saved to. Auto-migrates legacy plaintext sessions to keychain
 * when possible.
 */
export function loadSession(): OpenMatesSession | null {
  const filePath = join(ensureStateDir(), "session.json");
  const onDisk = readJsonFile<SessionOnDisk>(filePath);
  if (!onDisk) return null;

  let masterKey: string | null = null;

  // Legacy session (no masterKeyStorage field) — key is inline
  if (!onDisk.masterKeyStorage) {
    masterKey = onDisk.masterKeyExportedB64 ?? null;

    // Auto-migrate: try to move key to keychain/encrypted storage
    if (masterKey) {
      const session = buildSession(onDisk, masterKey);
      try {
        saveSession(session);
        process.stderr.write("Decrypting data...\n");
      } catch {
        // Migration failed — keep working with plaintext key in memory
      }
    }

    return masterKey ? buildSession(onDisk, masterKey) : null;
  }

  // Retrieve key from the appropriate tier
  switch (onDisk.masterKeyStorage) {
    case "keychain":
      masterKey = retrieveMasterKey("keychain", onDisk.hashedEmail);
      break;

    case "encrypted":
      masterKey = retrieveMasterKey(
        "encrypted",
        onDisk.hashedEmail,
        onDisk.masterKeyEncrypted,
      );
      break;

    case "plaintext":
      masterKey = onDisk.masterKeyExportedB64 ?? null;
      break;
  }

  if (!masterKey) {
    process.stderr.write(
      `Failed to retrieve master key — session invalid\n`,
    );
    return null;
  }

  return buildSession(onDisk, masterKey);
}

/**
 * Clear session — removes the file and deletes the keychain entry if applicable.
 */
export function clearSession(): void {
  const filePath = join(ensureStateDir(), "session.json");

  // Read current storage type before deleting, so we can clean up the keychain
  const onDisk = readJsonFile<SessionOnDisk>(filePath);
  if (onDisk?.masterKeyStorage) {
    deleteMasterKey(onDisk.masterKeyStorage, onDisk.hashedEmail);
  }

  if (existsSync(filePath)) {
    rmSync(filePath);
  }
}

/** Reconstruct in-memory OpenMatesSession from on-disk data + master key. */
function buildSession(onDisk: SessionOnDisk, masterKey: string): OpenMatesSession {
  return {
    apiUrl: onDisk.apiUrl,
    sessionId: onDisk.sessionId,
    wsToken: onDisk.wsToken,
    cookies: onDisk.cookies,
    masterKeyExportedB64: masterKey,
    hashedEmail: onDisk.hashedEmail,
    userEmailSalt: onDisk.userEmailSalt,
    createdAt: onDisk.createdAt,
    authorizerDeviceName: onDisk.authorizerDeviceName,
    autoLogoutMinutes: onDisk.autoLogoutMinutes,
  };
}

export function loadIncognitoHistory(): IncognitoHistoryItem[] {
  const filePath = join(ensureStateDir(), "incognito.json");
  return readJsonFile<IncognitoHistoryItem[]>(filePath) ?? [];
}

export function saveIncognitoHistory(items: IncognitoHistoryItem[]): void {
  const filePath = join(ensureStateDir(), "incognito.json");
  writeJsonFile(filePath, items);
}

export function clearIncognitoHistory(): void {
  const filePath = join(ensureStateDir(), "incognito.json");
  writeJsonFile(filePath, []);
}

// ---------------------------------------------------------------------------
// Encrypted sync cache — stores raw WS data on disk (encrypted fields
// remain encrypted). Decryption happens on-demand in memory only.
// SECURITY: decrypted user data content is NEVER stored on disk.
// ---------------------------------------------------------------------------

/**
 * Raw chat record from the WS phase3 payload.
 * All encrypted_* fields are stored as-is (base64 ciphertext).
 * Plaintext metadata (id, timestamps, versions) is stored for indexing.
 */
export interface CachedChat {
  /** chat_details object as received from the WS — all encrypted fields preserved */
  details: Record<string, unknown>;
  /** Stringified message JSON objects — stored encrypted */
  messages: string[];
}

export interface CachedEmbed {
  [key: string]: unknown;
}

export interface CachedEmbedKey {
  [key: string]: unknown;
}

export interface CachedNewChatSuggestion {
  [key: string]: unknown;
}

export interface SyncCache {
  /** Timestamp of last successful sync */
  syncedAt: number;
  /** Total chat count as reported by the server */
  totalChatCount: number;
  /** Number of chats loaded (may be less than total if paginated) */
  loadedChatCount: number;
  /** Chats with encrypted fields preserved */
  chats: CachedChat[];
  /** Embeds with encrypted fields preserved */
  embeds: CachedEmbed[];
  /** Embed keys for embed decryption */
  embedKeys: CachedEmbedKey[];
  /**
   * New chat suggestions from the last sync.
   * Each entry has id, chat_id, encrypted_suggestion, created_at.
   * Decrypted on-demand with the master key.
   */
  newChatSuggestions?: CachedNewChatSuggestion[];
}

const SYNC_CACHE_FILE = "sync_cache.json";

export function saveSyncCache(cache: SyncCache): void {
  const filePath = join(ensureStateDir(), SYNC_CACHE_FILE);
  writeJsonFile(filePath, cache);
}

export function loadSyncCache(): SyncCache | null {
  const filePath = join(ensureStateDir(), SYNC_CACHE_FILE);
  return readJsonFile<SyncCache>(filePath);
}

export function clearSyncCache(): void {
  const filePath = join(ensureStateDir(), SYNC_CACHE_FILE);
  if (existsSync(filePath)) {
    rmSync(filePath);
  }
}

/**
 * Check if the sync cache is fresh enough to use without re-syncing.
 * @param maxAgeMs Maximum age in milliseconds (default: 5 minutes).
 *
 * The CLI is a stateless process — unlike the web app (30s), there's no
 * persistent WebSocket to push real-time updates.  A longer TTL avoids
 * expensive full Phase 3 syncs on every invocation while still catching
 * changes within a reasonable window.
 */
export function isSyncCacheFresh(maxAgeMs = 300_000): boolean {
  const cache = loadSyncCache();
  if (!cache) return false;
  return Date.now() - cache.syncedAt < maxAgeMs;
}
