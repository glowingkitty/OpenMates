/** Encrypted, bounded snapshots for the TUI's Projects, Workflows, and Tasks views. */
import { createHmac } from "node:crypto";
import { chmodSync, mkdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { deserialize, serialize } from "node:v8";
import lockfile from "proper-lockfile";

import { base64ToBytes, decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "./crypto.js";
import { loadSession, resolveStateDir, type OpenMatesSession } from "./storage.js";

export const TUI_WORKSPACE_CACHE_FILE = "tui_workspace_cache.json";
const VERSION = 1;
const MAX_ENTRIES = 32;
const MAX_ENTRY_BYTES = 4 * 1024 * 1024;
const MAX_PLAINTEXT_BYTES = 16 * 1024 * 1024;
const MAX_FILE_BYTES = 24 * 1024 * 1024;
const KEY_PATTERN = /^[\x21-\x7e]{1,200}$/;

interface CacheEntry { data: string; touchedAt: number }
interface Snapshot { version: number; entries: Record<string, CacheEntry> }
interface Envelope { version: number; context: string; ciphertext: string }

/** The digest is keyed, so the file exposes no account, team, or cache-key names. */
function contextSignature(session: OpenMatesSession, stateDir: string): string {
  return createHmac("sha256", Buffer.from(session.masterKeyExportedB64, "base64"))
    .update(JSON.stringify([
      VERSION, stateDir, process.env.OPENMATES_PROFILE ?? "", session.apiUrl,
      session.hashedEmail, session.activeTeamId ?? null,
    ]))
    .digest("hex");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export interface TuiWorkspaceCache {
  /** Null means absent, corrupt, or outside the captured session context. */
  get<T>(key: string): Promise<T | null>;
  /** False means the session changed before the write completed. */
  set<T>(key: string, value: T): Promise<boolean>;
  invalidate(key?: string): Promise<boolean>;
  isCurrent(): boolean;
}

/**
 * Open a snapshot cache for one session. The caller should pass its live session
 * getter so an in-memory team/account switch fences pending async completions.
 * The persisted session is also checked to fence logout and other processes.
 */
export function createTuiWorkspaceCache(
  session: OpenMatesSession,
  currentSession: () => OpenMatesSession | null = loadSession,
): TuiWorkspaceCache {
  const stateDir = resolveStateDir();
  const path = join(stateDir, TUI_WORKSPACE_CACHE_FILE);
  const context = contextSignature(session, stateDir);
  // Renewal may replace auth credentials while preserving this login's creation
  // time. A new login can read the same account snapshot, but an old writer is fenced.
  const loginCreatedAt = session.createdAt;
  const keyBytes = base64ToBytes(session.masterKeyExportedB64);
  if (keyBytes.length !== 32) throw new Error("Workspace cache requires a 256-bit master key.");

  const isCurrent = (): boolean => {
    try {
      const live = currentSession();
      const persisted = loadSession();
      return !!live && !!persisted &&
        live.createdAt === loginCreatedAt && persisted.createdAt === loginCreatedAt &&
        contextSignature(live, stateDir) === context &&
        contextSignature(persisted, stateDir) === context;
    } catch {
      return false;
    }
  };

  const read = async (): Promise<Snapshot> => {
    const empty = (): Snapshot => ({ version: VERSION, entries: {} });
    try {
      if (statSync(path).size > MAX_FILE_BYTES) return empty();
      const disk = readFileSync(path, "utf8");
      if (Buffer.byteLength(disk) > MAX_FILE_BYTES) return empty();
      const envelope: unknown = JSON.parse(disk);
      if (!isRecord(envelope) || envelope.version !== VERSION ||
          envelope.context !== context || typeof envelope.ciphertext !== "string") return empty();
      const plaintext = await decryptWithAesGcmCombined(envelope.ciphertext, keyBytes, context);
      if (plaintext === null || Buffer.byteLength(plaintext) > MAX_PLAINTEXT_BYTES) return empty();
      const parsed: unknown = JSON.parse(plaintext);
      if (!isRecord(parsed) || parsed.version !== VERSION || !isRecord(parsed.entries)) return empty();
      const entries: Record<string, CacheEntry> = {};
      for (const [key, value] of Object.entries(parsed.entries)) {
        if (!KEY_PATTERN.test(key) || !isRecord(value) ||
            typeof value.data !== "string" || typeof value.touchedAt !== "number" ||
            !Number.isFinite(value.touchedAt) || value.touchedAt > Date.now() ||
            value.data.length > MAX_ENTRY_BYTES * 2) continue;
        entries[key] = { data: value.data, touchedAt: value.touchedAt };
      }
      return { version: VERSION, entries };
    } catch {
      return empty();
    }
  };

  const mutate = async (change: (snapshot: Snapshot) => void): Promise<boolean> => {
    if (!isCurrent()) return false;
    mkdirSync(stateDir, { recursive: true, mode: 0o700 });
    chmodSync(stateDir, 0o700);
    const release = await lockfile.lock(`${path}.write`, {
      realpath: false, stale: 30_000,
      retries: { retries: 20, factor: 1, minTimeout: 20, maxTimeout: 20 },
    });
    try {
      if (!isCurrent()) return false;
      const snapshot = await read();
      if (!isCurrent()) return false;
      change(snapshot);
      let plaintext = JSON.stringify(snapshot);
      while (Object.keys(snapshot.entries).length > MAX_ENTRIES ||
             Buffer.byteLength(plaintext) > MAX_PLAINTEXT_BYTES) {
        const oldest = Object.entries(snapshot.entries)
          .sort((a, b) => a[1].touchedAt - b[1].touchedAt)[0];
        if (!oldest) return false;
        delete snapshot.entries[oldest[0]];
        plaintext = JSON.stringify(snapshot);
      }
      const ciphertext = await encryptWithAesGcmCombined(plaintext, keyBytes, context);
      if (!isCurrent()) return false;
      const envelope: Envelope = { version: VERSION, context, ciphertext };
      const encoded = JSON.stringify(envelope);
      if (Buffer.byteLength(encoded) > MAX_FILE_BYTES) return false;
      const temporary = `${path}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
      try {
        writeFileSync(temporary, encoded, { mode: 0o600, flag: "wx" });
        chmodSync(temporary, 0o600);
        if (!isCurrent()) return false;
        renameSync(temporary, path);
      } finally {
        rmSync(temporary, { force: true });
      }
      return true;
    } finally {
      await release();
    }
  };

  return {
    isCurrent,
    async get<T>(key: string): Promise<T | null> {
      if (!KEY_PATTERN.test(key)) throw new Error("Invalid workspace cache key.");
      if (!isCurrent()) return null;
      const snapshot = await read();
      if (!isCurrent()) return null;
      const entry = snapshot.entries[key];
      if (!entry) return null;
      try {
        const bytes = Buffer.from(entry.data, "base64");
        if (bytes.length > MAX_ENTRY_BYTES) return null;
        return deserialize(bytes) as T;
      } catch {
        return null;
      }
    },
    async set<T>(key: string, value: T): Promise<boolean> {
      if (!KEY_PATTERN.test(key)) throw new Error("Invalid workspace cache key.");
      const bytes = serialize(value);
      if (bytes.length > MAX_ENTRY_BYTES) return false;
      return mutate(snapshot => {
        snapshot.entries[key] = { data: bytes.toString("base64"), touchedAt: Date.now() };
      });
    },
    async invalidate(key?: string): Promise<boolean> {
      if (key !== undefined && !KEY_PATTERN.test(key)) throw new Error("Invalid workspace cache key.");
      return mutate(snapshot => {
        if (key === undefined) snapshot.entries = {};
        else delete snapshot.entries[key];
      });
    },
  };
}
