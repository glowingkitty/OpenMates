/*
 * OpenMates CLI local session storage.
 *
 * Purpose: persist pair-login session data and local-only incognito chats.
 * Architecture: filesystem state in ~/.openmates with strict permissions.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: chmod 700 dir and 600 files on write.
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

export interface IncognitoHistoryItem {
  role: "user" | "assistant";
  content: string;
  createdAt: number;
}

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

export function saveSession(session: OpenMatesSession): void {
  const filePath = join(ensureStateDir(), "session.json");
  writeJsonFile(filePath, session);
}

export function loadSession(): OpenMatesSession | null {
  const filePath = join(ensureStateDir(), "session.json");
  return readJsonFile<OpenMatesSession>(filePath);
}

export function clearSession(): void {
  const filePath = join(ensureStateDir(), "session.json");
  if (existsSync(filePath)) {
    rmSync(filePath);
  }
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
 * @param maxAgeMs Maximum age in milliseconds (default: 30 seconds)
 */
export function isSyncCacheFresh(maxAgeMs = 30_000): boolean {
  const cache = loadSyncCache();
  if (!cache) return false;
  return Date.now() - cache.syncedAt < maxAgeMs;
}
