/**
 * Client Log Forwarder — Admin Live Streaming, User Debug Sessions & E2E Test Mode
 *
 * Forwards browser console logs in real-time to OpenObserve via the backend.
 *
 * Three modes:
 * 1. **Admin mode**: POST /v1/admin/client-logs — for admin users only,
 *    started automatically on admin login/session-restore.
 * 2. **Debug session mode**: POST /v1/settings/debug-logs — for any authenticated
 *    user with an active debug log sharing session. Started when the user
 *    activates "Share Debug Logs" in settings. Logs are tagged with a
 *    debugging_id for support to query via `debug.py logs --debug-id <ID>`.
 * 3. **E2E test mode**: POST /e2e/client-logs — started when the app is loaded
 *    with the `#e2e-debug={runId}&e2e-token={scopedToken}` hash param injected
 *    by the Playwright test runner. Uses a scoped HMAC token (NOT the internal
 *    service token). Works pre-login so login flow itself is captured.
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
 *   E2E test load -> startE2E(runId, token) -> same hook/batch flow
 *   -> POST /e2e/client-logs (X-E2E-Debug-Token header, no session cookie)
 *
 *   logout / deactivate -> stop() -> unhooks listener, drains buffer
 *   NOTE: stop() does NOT stop E2E mode — E2E forwarding persists across
 *   login/logout cycles within the same page load so the full test flow
 *   (including the login step itself) is captured.
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

  /**
   * When set, the forwarder runs in E2E test mode:
   * - Uses POST /e2e/client-logs with X-E2E-Debug-Token header
   * - No session cookie required (credentials: "omit")
   * - Started pre-login from the #e2e-debug= hash param
   * - Survives login/logout cycles within the same page load
   */
  private e2eMode: { runId: string; token: string } | null = null;

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

  /**
   * Start forwarding in E2E test mode. Called when the page detects the
   * `#e2e-debug={runId}&e2e-token={token}` hash param injected by the
   * Playwright test runner.
   *
   * - Works pre-login: uses X-E2E-Debug-Token header, no session cookie.
   * - Survives login/logout: stop() does NOT stop E2E mode.
   * - Runs in parallel with admin/debug-session mode if those start later.
   * - Idempotent: safe to call multiple times with the same runId.
   *
   * @param runId  — The E2E run correlation ID (e.g. '2026-03-17T03:00:00Z-background-chat-notification')
   * @param token  — The scoped HMAC token (derived from INTERNAL_API_SHARED_TOKEN, NOT the token itself)
   */
  startE2E(runId: string, token: string): void {
    if (this.e2eMode?.runId === runId) return; // idempotent
    this.e2eMode = { runId, token };
    // Start the flush loop if not already running for another mode.
    // If already running for admin/debug mode, the E2E mode piggybacks on the
    // existing flush loop — flush() checks e2eMode independently.
    if (!this.running) {
      logCollector.onNewLog(this.logListener);
      this.flushTimer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
    }
    void this.flush();
    console.debug(`[ClientLogForwarder] E2E mode started, run_id=${runId}`);
  }

  /** Whether the forwarder is currently running (any mode). */
  get isRunning(): boolean {
    return this.running || this.e2eMode !== null;
  }

  /** The active debug session ID, or null if in admin mode or stopped. */
  get activeDebugSessionId(): string | null {
    return this.debugSessionId;
  }

  /** The active E2E run ID, or null if not in E2E mode. */
  get activeE2ERunId(): string | null {
    return this.e2eMode?.runId ?? null;
  }

  /**
   * Stop admin/debug-session forwarding and drain any buffered entries.
   * Call on logout or when admin status is lost.
   *
   * NOTE: This does NOT stop E2E mode. E2E mode runs for the entire page
   * lifetime so login/logout transitions are fully captured.
   */
  async stop(): Promise<void> {
    if (!this.running) return;
    this.running = false;
    this.debugSessionId = null;
    // Only remove the log listener if E2E mode is also inactive.
    // If E2E mode is active, keep the listener so E2E logs keep flowing.
    if (!this.e2eMode) {
      logCollector.offNewLog(this.logListener);
      if (this.flushTimer !== null) {
        clearInterval(this.flushTimer);
        this.flushTimer = null;
      }
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

    if (this.running || this.e2eMode) {
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
   *
   * When E2E mode is active, logs are sent to BOTH the admin/debug endpoint
   * (if running) AND the E2E endpoint in parallel. This ensures no logs are
   * lost regardless of which mode is primary.
   */
  private async flush(force: boolean = false): Promise<void> {
    if (this.flushInProgress) return;
    const shouldFlushNormal = this.running || force;
    const shouldFlushE2E = this.e2eMode !== null;
    if (!shouldFlushNormal && !shouldFlushE2E) return;

    this.flushInProgress = true;
    try {
      let processedBatches = 0;
      while (this.running || force || this.e2eMode) {
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

        // --- Send to admin/debug-session endpoint (if in normal running mode) ---
        let normalOk = !shouldFlushNormal; // skip if not in normal mode
        if (shouldFlushNormal) {
          const isDebugSession = this.debugSessionId !== null;
          const endpoint = isDebugSession
            ? getApiEndpoint(apiEndpoints.settings.debugLogs)
            : getApiEndpoint(apiEndpoints.admin.clientLogs);
          const body = isDebugSession
            ? { logs: entries, metadata, debugging_id: this.debugSessionId }
            : { logs: entries, metadata };
          try {
            const response = await fetch(endpoint, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
              credentials: "include",
              keepalive: true,
            });
            normalOk = response.ok;
          } catch {
            normalOk = false;
          }
        }

        // --- Send to E2E endpoint (if in E2E mode) ---
        let e2eOk = !shouldFlushE2E; // skip if not in E2E mode
        if (shouldFlushE2E && this.e2eMode) {
          const endpoint = getApiEndpoint(apiEndpoints.e2e.clientLogs);
          const body = {
            run_id: this.e2eMode.runId,
            logs: entries,
            metadata,
          };
          try {
            const response = await fetch(endpoint, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-E2E-Debug-Token": this.e2eMode.token,
              },
              body: JSON.stringify(body),
              credentials: "omit", // no session cookie needed
              keepalive: true,
            });
            e2eOk = response.ok;
          } catch {
            e2eOk = false;
          }
        }

        // Only advance the queue if at least one send succeeded.
        // If both failed, stop flushing (network down, retry next interval).
        const anyOk = normalOk || e2eOk;
        if (!anyOk) {
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

        // After first batch, only continue if in a running mode (not just E2E)
        // to avoid looping purely for E2E draining on stop().
        if (!this.running && !force) {
          break;
        }
      }
    } finally {
      this.flushInProgress = false;
    }
  }
}

export const clientLogForwarder = new ClientLogForwarderService();
