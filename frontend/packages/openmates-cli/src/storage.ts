/*
 * OpenMates CLI local session storage.
 *
 * Purpose: persist pair-login session data and encrypted sync cache data.
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
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";

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
  emailEncryptionKeyB64?: string | null;
  hashedEmail: string;
  userEmailSalt: string;
  createdAt: number;
  authorizerDeviceName: string | null;
  autoLogoutMinutes: number | null;
  activeTeamId?: string | null;
}

interface AnonymousStateOnDisk {
  anonymousId: string;
  createdAt: number;
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
  /** Present only when emailEncryptionKeyStorage is "plaintext" */
  emailEncryptionKeyB64?: string | null;
  /** Where the email encryption key is stored, when available */
  emailEncryptionKeyStorage?: MasterKeyStorageType;
  /** Base64 AES-256-GCM ciphertext (only when emailEncryptionKeyStorage is "encrypted") */
  emailEncryptionKeyEncrypted?: string;
  hashedEmail: string;
  userEmailSalt: string;
  createdAt: number;
  authorizerDeviceName: string | null;
  autoLogoutMinutes: number | null;
  activeTeamId?: string | null;
}

interface LocalTeamKeyEntry {
  storage: MasterKeyStorageType;
  encryptedData?: string;
  plaintextKeyB64?: string;
}

interface LocalTeamKeysOnDisk {
  teams: Record<string, LocalTeamKeyEntry>;
}

interface TrustedAccountOnDisk {
  accountId: string;
}

// ---------------------------------------------------------------------------
// Filesystem helpers
// ---------------------------------------------------------------------------

const PROFILE_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
const TRUSTED_ACCOUNT_FILE = "trusted_account.json";

export function resolveStateDir(options: {
  homeDir?: string;
  stateDir?: string;
  profile?: string;
} = {}): string {
  const homeDir = options.homeDir ?? homedir();
  const stateDir = options.stateDir ?? process.env.OPENMATES_STATE_DIR?.trim();
  if (stateDir) {
    if (!isAbsolute(stateDir)) throw new Error("OPENMATES_STATE_DIR must be an absolute path.");
    return resolve(stateDir);
  }

  const profile = options.profile ?? process.env.OPENMATES_PROFILE?.trim();
  if (!profile) return join(homeDir, ".openmates");
  if (!PROFILE_NAME_PATTERN.test(profile)) {
    throw new Error("OPENMATES_PROFILE must contain only lowercase letters, numbers, and hyphens.");
  }
  return join(homeDir, ".openmates", "profiles", profile);
}

function getStateDir(): string {
  return resolveStateDir();
}

export function resolveKeyStorageId(storageId: string, profile = process.env.OPENMATES_PROFILE?.trim()): string {
  if (!profile) return storageId;
  if (!PROFILE_NAME_PATTERN.test(profile)) {
    throw new Error("OPENMATES_PROFILE must contain only lowercase letters, numbers, and hyphens.");
  }
  return `profile:${profile}:${storageId}`;
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

export function loadAnonymousId(): string | null {
  const filePath = join(getStateDir(), "anonymous.json");
  const data = readJsonFile<AnonymousStateOnDisk>(filePath);
  return typeof data?.anonymousId === "string" && data.anonymousId.length > 0
    ? data.anonymousId
    : null;
}

export function saveAnonymousId(anonymousId: string): void {
  const filePath = join(ensureStateDir(), "anonymous.json");
  writeJsonFile(filePath, {
    anonymousId,
    createdAt: Math.floor(Date.now() / 1000),
  } satisfies AnonymousStateOnDisk);
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

  const result = storeMasterKey(session.masterKeyExportedB64, resolveKeyStorageId(session.hashedEmail));

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
    activeTeamId: session.activeTeamId ?? null,
    masterKeyStorage: result.type,
  };

  if (result.type === "encrypted") {
    onDisk.masterKeyEncrypted = result.encryptedData;
  } else if (result.type === "plaintext") {
    onDisk.masterKeyExportedB64 = session.masterKeyExportedB64;
  }
  // For "keychain", the key is not stored on disk at all

  if (session.emailEncryptionKeyB64) {
    const emailKeyResult = storeMasterKey(
      session.emailEncryptionKeyB64,
      resolveKeyStorageId(`${session.hashedEmail}:email`),
    );
    onDisk.emailEncryptionKeyStorage = emailKeyResult.type;
    if (emailKeyResult.type === "encrypted") {
      onDisk.emailEncryptionKeyEncrypted = emailKeyResult.encryptedData;
    } else if (emailKeyResult.type === "plaintext") {
      onDisk.emailEncryptionKeyB64 = session.emailEncryptionKeyB64;
    }
  }

  writeJsonFile(filePath, onDisk);

  if (result.type !== "plaintext") {
    process.stderr.write("Decrypting data...\n");
  }
}

/**
 * Load session from disk. Retrieves the master key from whatever storage
 * tier it was saved to. Legacy plaintext sessions remain readable but are not
 * rewritten during load.
 */
export function loadSession(): OpenMatesSession | null {
  const filePath = join(ensureStateDir(), "session.json");
  const onDisk = readJsonFile<SessionOnDisk>(filePath);
  if (!onDisk) return null;

  let masterKey: string | null = null;

  // Legacy session (no masterKeyStorage field) — key is inline
  if (!onDisk.masterKeyStorage) {
    masterKey = onDisk.masterKeyExportedB64 ?? null;
    return masterKey ? buildSession(onDisk, masterKey, getEmailEncryptionKeyFromDisk(onDisk)) : null;
  }

  // Retrieve key from the appropriate tier
  switch (onDisk.masterKeyStorage) {
    case "keychain":
      masterKey = retrieveMasterKey("keychain", resolveKeyStorageId(onDisk.hashedEmail));
      break;

    case "encrypted":
      masterKey = retrieveMasterKey(
        "encrypted",
        resolveKeyStorageId(onDisk.hashedEmail),
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

  return buildSession(onDisk, masterKey, getEmailEncryptionKeyFromDisk(onDisk));
}

/**
 * Clear session — removes the file and deletes the keychain entry if applicable.
 */
export function clearSession(): void {
  const filePath = join(ensureStateDir(), "session.json");

  // Read current storage type before deleting, so we can clean up the keychain
  const onDisk = readJsonFile<SessionOnDisk>(filePath);
  if (onDisk?.masterKeyStorage) {
    deleteMasterKey(onDisk.masterKeyStorage, resolveKeyStorageId(onDisk.hashedEmail));
  }
  if (onDisk?.emailEncryptionKeyStorage) {
    deleteMasterKey(onDisk.emailEncryptionKeyStorage, resolveKeyStorageId(`${onDisk.hashedEmail}:email`));
  }
  if (onDisk?.activeTeamId) {
    deleteLocalTeamKey(onDisk.hashedEmail, onDisk.activeTeamId);
  }

  if (existsSync(filePath)) {
    rmSync(filePath);
  }
}

export function purgeLocalPrivateData(): void {
  const stateDir = ensureStateDir();
  const sessionFilePath = join(stateDir, "session.json");
  const onDisk = readJsonFile<SessionOnDisk>(sessionFilePath);
  const hashedEmail = onDisk?.hashedEmail ?? null;

  clearSession();
  purgeLocalTeamKeys(hashedEmail);
  purgeSyncCaches(stateDir);
}

function purgeLocalTeamKeys(hashedEmail: string | null): void {
  const filePath = join(ensureStateDir(), LOCAL_TEAM_KEYS_FILE);
  const keys = readJsonFile<LocalTeamKeysOnDisk>(filePath);
  if (!keys) return;

  let changed = false;
  const prefix = hashedEmail ? resolveKeyStorageId(`${hashedEmail}:team:`) : null;
  for (const [storageId, entry] of Object.entries(keys.teams)) {
    if (prefix && !storageId.startsWith(prefix)) continue;
    deleteMasterKey(entry.storage, storageId);
    delete keys.teams[storageId];
    changed = true;
  }

  if (!changed) return;
  if (Object.keys(keys.teams).length === 0) {
    rmSync(filePath, { force: true });
    return;
  }
  writeJsonFile(filePath, keys);
}

function purgeSyncCaches(stateDir: string): void {
  for (const fileName of readdirSync(stateDir)) {
    if (fileName === SYNC_CACHE_FILE || (fileName.startsWith("sync_cache.team.") && fileName.endsWith(".json"))) {
      rmSync(join(stateDir, fileName), { force: true });
    }
  }
}

/** Reconstruct in-memory OpenMatesSession from on-disk data + master key. */
function getEmailEncryptionKeyFromDisk(onDisk: SessionOnDisk): string | null {
  if (!onDisk.emailEncryptionKeyStorage) return onDisk.emailEncryptionKeyB64 ?? null;
  switch (onDisk.emailEncryptionKeyStorage) {
    case "keychain":
      return retrieveMasterKey("keychain", resolveKeyStorageId(`${onDisk.hashedEmail}:email`));
    case "encrypted":
      return retrieveMasterKey(
        "encrypted",
        resolveKeyStorageId(`${onDisk.hashedEmail}:email`),
        onDisk.emailEncryptionKeyEncrypted,
      );
    case "plaintext":
      return onDisk.emailEncryptionKeyB64 ?? null;
  }
}

function buildSession(
  onDisk: SessionOnDisk,
  masterKey: string,
  emailEncryptionKey: string | null,
): OpenMatesSession {
  return {
    apiUrl: onDisk.apiUrl,
    sessionId: onDisk.sessionId,
    wsToken: onDisk.wsToken,
    cookies: onDisk.cookies,
    masterKeyExportedB64: masterKey,
    emailEncryptionKeyB64: emailEncryptionKey,
    hashedEmail: onDisk.hashedEmail,
    userEmailSalt: onDisk.userEmailSalt,
    createdAt: onDisk.createdAt,
    authorizerDeviceName: onDisk.authorizerDeviceName,
    autoLogoutMinutes: onDisk.autoLogoutMinutes,
    activeTeamId: onDisk.activeTeamId ?? null,
  };
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

export interface CachedChatKeyWrapper {
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
  /** Chat key wrappers for wrapper-first chat decryption */
  chatKeyWrappers?: CachedChatKeyWrapper[];
  /**
   * New chat suggestions from the last sync.
   * Each entry has id, chat_id, encrypted_suggestion, created_at.
   * Decrypted on-demand with the master key.
   */
  newChatSuggestions?: CachedNewChatSuggestion[];
}

const SYNC_CACHE_FILE = "sync_cache.json";
const LOCAL_TEAM_KEYS_FILE = "team_keys.json";

function teamKeyStorageId(hashedEmail: string, teamId: string): string {
  const digest = createHash("sha256").update(teamId).digest("hex").slice(0, 32);
  return resolveKeyStorageId(`${hashedEmail}:team:${digest}`);
}

export function saveLocalTeamKey(hashedEmail: string, teamId: string, teamKeyB64: string): void {
  const storageId = teamKeyStorageId(hashedEmail, teamId);
  const result = storeMasterKey(teamKeyB64, storageId);
  const filePath = join(ensureStateDir(), LOCAL_TEAM_KEYS_FILE);
  const keys = readJsonFile<LocalTeamKeysOnDisk>(filePath) ?? { teams: {} };
  keys.teams[storageId] = {
    storage: result.type,
    ...(result.type === "encrypted" ? { encryptedData: result.encryptedData } : {}),
    ...(result.type === "plaintext" ? { plaintextKeyB64: teamKeyB64 } : {}),
  };
  writeJsonFile(filePath, keys);
}

export function loadLocalTeamKey(hashedEmail: string, teamId: string): string | null {
  const storageId = teamKeyStorageId(hashedEmail, teamId);
  const filePath = join(ensureStateDir(), LOCAL_TEAM_KEYS_FILE);
  const entry = readJsonFile<LocalTeamKeysOnDisk>(filePath)?.teams[storageId];
  if (!entry) return null;
  if (entry.storage === "plaintext") return entry.plaintextKeyB64 ?? null;
  return retrieveMasterKey(entry.storage, storageId, entry.encryptedData);
}

export function deleteLocalTeamKey(hashedEmail: string, teamId: string): void {
  const storageId = teamKeyStorageId(hashedEmail, teamId);
  deleteMasterKey("keychain", storageId);
  const filePath = join(ensureStateDir(), LOCAL_TEAM_KEYS_FILE);
  const keys = readJsonFile<LocalTeamKeysOnDisk>(filePath);
  if (keys?.teams[storageId]) {
    delete keys.teams[storageId];
    writeJsonFile(filePath, keys);
  }
}

export function pruneLocalTeamArtifacts(hashedEmail: string, teamIds: string[]): void {
  const stateDir = ensureStateDir();
  const allowedKeyIds = new Set(teamIds.map((teamId) => teamKeyStorageId(hashedEmail, teamId)));
  const keysFilePath = join(stateDir, LOCAL_TEAM_KEYS_FILE);
  const keys = readJsonFile<LocalTeamKeysOnDisk>(keysFilePath);
  if (keys) {
    let changed = false;
    const prefix = resolveKeyStorageId(`${hashedEmail}:team:`);
    for (const storageId of Object.keys(keys.teams)) {
      if (storageId.startsWith(prefix) && !allowedKeyIds.has(storageId)) {
        deleteMasterKey("keychain", storageId);
        delete keys.teams[storageId];
        changed = true;
      }
    }
    if (changed) writeJsonFile(keysFilePath, keys);
  }

  const allowedCacheFiles = new Set(teamIds.map((teamId) => syncCacheFile(teamId)));
  for (const fileName of readdirSync(stateDir)) {
    if (fileName.startsWith("sync_cache.team.") && fileName.endsWith(".json") && !allowedCacheFiles.has(fileName)) {
      rmSync(join(stateDir, fileName), { force: true });
    }
  }
}

function syncCacheFile(teamId?: string | null): string {
  if (!teamId) return SYNC_CACHE_FILE;
  const digest = createHash("sha256").update(teamId).digest("hex").slice(0, 32);
  return `sync_cache.team.${digest}.json`;
}

export function saveSyncCache(cache: SyncCache, teamId?: string | null): void {
  const filePath = join(ensureStateDir(), syncCacheFile(teamId));
  writeJsonFile(filePath, cache);
}

export function loadSyncCache(teamId?: string | null): SyncCache | null {
  const filePath = join(ensureStateDir(), syncCacheFile(teamId));
  return readJsonFile<SyncCache>(filePath);
}

export function clearSyncCache(teamId?: string | null): void {
  const filePath = join(ensureStateDir(), syncCacheFile(teamId));
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
export function isSyncCacheFresh(maxAgeMs = 300_000, teamId?: string | null): boolean {
  const cache = loadSyncCache(teamId);
  if (!cache) return false;
  return Date.now() - cache.syncedAt < maxAgeMs;
}

export function loadTrustedAccountId(): string | null {
  const trusted = readJsonFile<TrustedAccountOnDisk>(join(getStateDir(), TRUSTED_ACCOUNT_FILE));
  return typeof trusted?.accountId === "string" && trusted.accountId.trim()
    ? trusted.accountId.trim()
    : null;
}

export function saveTrustedAccountId(accountId: string): void {
  const normalized = accountId.trim();
  if (!normalized) throw new Error("Cannot trust an empty OpenMates account ID.");
  const existing = loadTrustedAccountId();
  if (existing && existing !== normalized) {
    throw new Error("OpenMates account mismatch: this CLI profile is already trusted for another account.");
  }
  writeJsonFile(join(ensureStateDir(), TRUSTED_ACCOUNT_FILE), { accountId: normalized });
}

export function assertTrustedAccountId(expectedAccountId: string | null, actualAccountId: string): void {
  if (!expectedAccountId) {
    throw new Error("This CLI profile is not trusted yet. Run `openmates login` and approve the intended account.");
  }
  if (expectedAccountId !== actualAccountId) {
    throw new Error("OpenMates account mismatch: refusing authenticated access from this CLI profile.");
  }
}
