/**
 * Client Log Forwarder — Admin Live Streaming & User Debug Sessions
 *
 * Forwards browser console logs in real-time to OpenObserve via the backend.
 *
 * Two modes:
 * 1. **Admin mode** (original): POST /v1/admin/client-logs — for admin users only,
 *    started automatically on admin login/session-restore.
 * 2. **Debug session mode**: POST /v1/settings/debug-logs — for any authenticated
 *    user with an active debug log sharing session. Started when the user
 *    activates "Share Debug Logs" in settings. Logs are tagged with a
 *    debugging_id for support to query via `debug.py logs --debug-id <ID>`.
 *
 * Architecture context: docs/architecture/admin-console-log-forwarding.md
 *
 * Flow:
 *   login/session-restore (admin) -> start() -> hooks logCollector.onNewLog
 *   -> batches every FLUSH_INTERVAL_MS -> POST /v1/admin/client-logs
 *
 *   user activates debug session -> startDebugSession(id) -> same hook/batch flow
 *   -> POST /v1/settings/debug-logs (with debugging_id in body)
 *
 *   logout / deactivate -> stop() -> unhooks listener, drains buffer
 */

import { logCollector } from "./logCollector";
import type { ConsoleLogEntry } from "./logCollector";
import { getApiEndpoint, apiEndpoints } from "../config/api";

// ----- Configuration -------------------------------------------------------

/** How often (ms) to flush the pending batch to the backend. */
const FLUSH_INTERVAL_MS = 5_000;

/** Maximum entries per batch (matches backend validation limit). */
const MAX_BATCH_SIZE = 50;

/** Maximum batches sent in one flush cycle to avoid request spikes. */
const MAX_BATCHES_PER_FLUSH = 25;

/** IndexedDB database name for durable admin log queue. */
const QUEUE_DB_NAME = "openmates_admin_client_log_queue";

/** IndexedDB object store holding unsent admin log entries. */
const QUEUE_STORE_NAME = "pending_entries";

/** Schema version for the durable admin log queue DB. */
/** Bumped 1→2: force onupgradeneeded on clients with broken schema-less v1 DB */
const QUEUE_DB_VERSION = 2;

// ---------------------------------------------------------------------------

/** Unique tab ID generated once per page load — disambiguates multiple open tabs. */
const TAB_ID = Math.random().toString(36).slice(2, 8);

function getPagePath(): string {
  try {
    return window.location.pathname;
  } catch {
    return "";
  }
}

type QueuedLogEntry = {
  id?: number;
  timestamp: number;
  level: ConsoleLogEntry["level"];
  message: string;
};

function openQueueDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB unavailable"));
      return;
    }

    const request = indexedDB.open(QUEUE_DB_NAME, QUEUE_DB_VERSION);

    request.onerror = () =>
      reject(request.error ?? new Error("Failed to open queue DB"));

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(QUEUE_STORE_NAME)) {
        db.createObjectStore(QUEUE_STORE_NAME, {
          keyPath: "id",
          autoIncrement: true,
        });
      }
    };

    request.onsuccess = () => resolve(request.result);
  });
}

class ClientLogForwarderService {
  private running = false;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private flushInProgress = false;

  /**
   * When set, the forwarder runs in debug session mode:
   * - Uses POST /v1/settings/debug-logs instead of /v1/admin/client-logs
   * - Includes the debugging_id in the request body
   * - Available to any authenticated user (not just admins)
   */
  private debugSessionId: string | null = null;

  // Fallback queue if IndexedDB is unavailable in the runtime.
  private volatileQueue: QueuedLogEntry[] = [];

  private readonly logListener = (entry: ConsoleLogEntry): void => {
    void this.enqueue(entry);
  };

  /**
   * Start forwarding in admin mode. Call only for admin users after auth.
   * Safe to call multiple times — idempotent.
   */
  start(): void {
    if (this.running) return;
    this.debugSessionId = null;
    this.running = true;
    logCollector.onNewLog(this.logListener);
    this.flushTimer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
    void this.flush();
  }

  /**
   * Start forwarding in debug session mode. Call for any authenticated user
   * who has activated a debug log sharing session.
   *
   * @param debuggingId — The debug session ID (e.g. 'dbg-a3f2c8')
   */
  startDebugSession(debuggingId: string): void {
    if (this.running) return;
    this.debugSessionId = debuggingId;
    this.running = true;
    logCollector.onNewLog(this.logListener);
    this.flushTimer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
    void this.flush();
  }

  /** Whether the forwarder is currently running (admin or debug mode). */
  get isRunning(): boolean {
    return this.running;
  }

  /** The active debug session ID, or null if in admin mode or stopped. */
  get activeDebugSessionId(): string | null {
    return this.debugSessionId;
  }

  /**
   * Stop forwarding and drain any buffered entries.
   * Call on logout or when admin status is lost.
   */
  async stop(): Promise<void> {
    if (!this.running) return;
    this.running = false;
    this.debugSessionId = null;
    logCollector.offNewLog(this.logListener);
    if (this.flushTimer !== null) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    // Best-effort final drain before teardown.
    await this.flush(true);
  }

  private async enqueue(entry: ConsoleLogEntry): Promise<void> {
    const queued: QueuedLogEntry = {
      timestamp: entry.timestamp,
      level: entry.level,
      message: entry.message,
    };

    try {
      const db = await openQueueDb();
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction([QUEUE_STORE_NAME], "readwrite");
        const store = tx.objectStore(QUEUE_STORE_NAME);
        const request = store.add(queued);
        request.onerror = () =>
          reject(request.error ?? new Error("Failed to enqueue log entry"));
        tx.oncomplete = () => resolve();
        tx.onerror = () =>
          reject(tx.error ?? new Error("Queue write transaction failed"));
      });
      db.close();
    } catch {
      this.volatileQueue.push(queued);
    }

    if (this.running) {
      void this.flush();
    }
  }

  private async readQueuedBatch(limit: number): Promise<QueuedLogEntry[]> {
    try {
      const db = await openQueueDb();
      const rows = await new Promise<QueuedLogEntry[]>((resolve, reject) => {
        const tx = db.transaction([QUEUE_STORE_NAME], "readonly");
        const store = tx.objectStore(QUEUE_STORE_NAME);
        const request = store.openCursor();
        const acc: QueuedLogEntry[] = [];

        request.onerror = () =>
          reject(request.error ?? new Error("Failed to read queued logs"));
        request.onsuccess = () => {
          const cursor = request.result;
          if (!cursor || acc.length >= limit) {
            resolve(acc);
            return;
          }
          acc.push(cursor.value as QueuedLogEntry);
          cursor.continue();
        };

        tx.onerror = () =>
          reject(tx.error ?? new Error("Queue read transaction failed"));
      });
      db.close();
      return rows;
    } catch {
      return [];
    }
  }

  private async deleteQueuedBatch(ids: number[]): Promise<void> {
    if (ids.length === 0) return;

    try {
      const db = await openQueueDb();
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction([QUEUE_STORE_NAME], "readwrite");
        const store = tx.objectStore(QUEUE_STORE_NAME);
        for (const id of ids) {
          store.delete(id);
        }
        tx.oncomplete = () => resolve();
        tx.onerror = () =>
          reject(tx.error ?? new Error("Queue delete transaction failed"));
      });
      db.close();
    } catch {
      // Keep entries in persistent queue when deletion fails; retry on next flush.
    }
  }

  /**
   * Flush the current buffer to the backend.
   * Never throws — log forwarding must never break the app.
   */
  private async flush(force: boolean = false): Promise<void> {
    if (this.flushInProgress) return;
    if (!this.running && !force) return;

    this.flushInProgress = true;
    try {
      let processedBatches = 0;
      while (this.running || force) {
        if (processedBatches >= MAX_BATCHES_PER_FLUSH) {
          break;
        }

        const volatileBatch = this.volatileQueue.slice(0, MAX_BATCH_SIZE);
        const durableBatch =
          volatileBatch.length > 0
            ? []
            : await this.readQueuedBatch(MAX_BATCH_SIZE);
        const batch = volatileBatch.length > 0 ? volatileBatch : durableBatch;

        if (batch.length === 0) {
          break;
        }

        const entries = batch.map((e) => ({
          timestamp: e.timestamp,
          level: e.level,
          message: e.message,
        }));

        const metadata = {
          userAgent:
            typeof navigator !== "undefined" ? navigator.userAgent : "",
          pageUrl: getPagePath(),
          tabId: TAB_ID,
        };

        // Determine endpoint and body based on mode (admin vs debug session)
        const isDebugSession = this.debugSessionId !== null;
        const endpoint = isDebugSession
          ? getApiEndpoint(apiEndpoints.settings.debugLogs)
          : getApiEndpoint(apiEndpoints.admin.clientLogs);
        const body = isDebugSession
          ? { logs: entries, metadata, debugging_id: this.debugSessionId }
          : { logs: entries, metadata };

        let responseOk = false;
        try {
          const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            credentials: "include",
            keepalive: true,
          });
          responseOk = response.ok;
        } catch {
          responseOk = false;
        }

        if (!responseOk) {
          break;
        }

        processedBatches += 1;

        if (volatileBatch.length > 0) {
          this.volatileQueue.splice(0, volatileBatch.length);
        } else {
          const ids = durableBatch
            .map((row) => row.id)
            .filter((id): id is number => typeof id === "number");
          await this.deleteQueuedBatch(ids);
        }

        if (batch.length < MAX_BATCH_SIZE) {
          break;
        }
      }
    } finally {
      this.flushInProgress = false;
    }
  }
}

export const clientLogForwarder = new ClientLogForwarderService();
