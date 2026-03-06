/**
 * Client Log Forwarder Service
 *
 * Forwards browser console logs from admin users to the backend for centralized
 * storage in Loki. This provides a unified view of client-side and server-side
 * logs in Grafana, making it significantly easier to debug issues without
 * requiring manual "Report Issue" submissions.
 *
 * Privacy guarantees:
 * - Only activates when the authenticated user has is_admin === true
 * - Non-admin users never have logs forwarded (enforced on both client and server)
 * - All logs pass through logCollector's existing sanitization (API keys, tokens, passwords redacted)
 * - The backend endpoint double-checks admin status before accepting logs
 *
 * Architecture:
 * - Subscribes to logCollector's onNewLog() callback to receive entries in real-time
 * - Batches entries and flushes every FLUSH_INTERVAL_MS or when the buffer reaches MAX_BATCH_SIZE
 * - POSTs batched logs to /v1/admin/client-logs (cookie-authenticated, admin-only)
 * - Generates a unique tab ID per browser tab for multi-tab disambiguation in Grafana
 */

import { logCollector } from "./logCollector";
import type { ConsoleLogEntry } from "./logCollector";
import { getApiEndpoint, apiEndpoints } from "../config/api";

/** How often to flush buffered logs to the server (milliseconds) */
const FLUSH_INTERVAL_MS = 5_000;

/** Maximum number of log entries per batch request */
const MAX_BATCH_SIZE = 50;

/**
 * Maximum number of entries to buffer before dropping the oldest.
 * This prevents unbounded memory growth during sustained log bursts
 * (e.g. sync operations generating hundreds of debug messages).
 */
const MAX_BUFFER_SIZE = 200;

/** Generate a short random ID to uniquely identify this browser tab in logs */
function generateTabId(): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let id = "";
  for (let i = 0; i < 8; i++) {
    id += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return id;
}

/** Status snapshot returned by getStatus() for debug health checks */
export interface ClientLogForwarderStatus {
  /** Whether the forwarder is currently running (start() was called, stop() was not) */
  isRunning: boolean;
  /** Unique tab ID for this browser tab (regenerated on each start()) */
  tabId: string;
  /** Number of log entries currently buffered awaiting flush */
  bufferSize: number;
  /** Total number of flush attempts since last start() */
  totalFlushAttempts: number;
  /** Number of flushes that returned HTTP 2xx */
  successfulFlushes: number;
  /** Number of flushes that failed (network error, non-2xx response) */
  failedFlushes: number;
  /** HTTP status of the most recent flush attempt, or null if none yet */
  lastFlushStatus: number | null;
  /** ISO timestamp of the most recent flush attempt, or null if none yet */
  lastFlushTime: string | null;
  /** Error message from the most recent flush failure, or null */
  lastFlushError: string | null;
  /** Whether the very first flush after start() has been attempted */
  firstFlushAttempted: boolean;
}

class ClientLogForwarder {
  private buffer: ConsoleLogEntry[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private isRunning = false;
  private tabId: string = generateTabId();

  // ── Diagnostic counters (reset on each start()) ──
  private totalFlushAttempts = 0;
  private successfulFlushes = 0;
  private failedFlushes = 0;
  private lastFlushStatus: number | null = null;
  private lastFlushTime: string | null = null;
  private lastFlushError: string | null = null;
  private firstFlushAttempted = false;

  /**
   * Bound reference to the listener function so we can unsubscribe cleanly.
   * Arrow function ensures `this` context is preserved.
   */
  private logListener = (entry: ConsoleLogEntry): void => {
    if (!this.isRunning) return;

    this.buffer.push(entry);

    // Drop oldest entries if buffer exceeds max to prevent memory issues during bursts
    if (this.buffer.length > MAX_BUFFER_SIZE) {
      this.buffer = this.buffer.slice(-MAX_BUFFER_SIZE);
    }

    // Flush immediately if we hit the batch size limit
    if (this.buffer.length >= MAX_BATCH_SIZE) {
      void this.flush();
    }
  };

  /**
   * Return a snapshot of the forwarder's current status for debug health checks.
   * Called by window.debug() health check.
   */
  public getStatus(): ClientLogForwarderStatus {
    return {
      isRunning: this.isRunning,
      tabId: this.tabId,
      bufferSize: this.buffer.length,
      totalFlushAttempts: this.totalFlushAttempts,
      successfulFlushes: this.successfulFlushes,
      failedFlushes: this.failedFlushes,
      lastFlushStatus: this.lastFlushStatus,
      lastFlushTime: this.lastFlushTime,
      lastFlushError: this.lastFlushError,
      firstFlushAttempted: this.firstFlushAttempted,
    };
  }

  /**
   * Start forwarding console logs to the server.
   * Should only be called when the authenticated user is confirmed to be an admin.
   * Safe to call multiple times (idempotent) - will not create duplicate listeners.
   */
  public start(): void {
    if (this.isRunning) return;

    this.isRunning = true;
    this.tabId = generateTabId();

    // Reset diagnostic counters for this session
    this.totalFlushAttempts = 0;
    this.successfulFlushes = 0;
    this.failedFlushes = 0;
    this.lastFlushStatus = null;
    this.lastFlushTime = null;
    this.lastFlushError = null;
    this.firstFlushAttempted = false;

    // Subscribe to real-time log entries from the collector
    logCollector.onNewLog(this.logListener);

    // Set up periodic flush interval
    this.flushTimer = setInterval(() => {
      void this.flush();
    }, FLUSH_INTERVAL_MS);

    // Use warn level so this is visible even when debug logging is filtered in browser dev tools.
    // This is a critical diagnostic breadcrumb confirming the forwarder activated for the admin user.
    // logCollector intercepts this console.warn and routes it through logListener into the buffer,
    // so the very first flush will include it as a positive "forwarder alive" signal in Loki.
    console.warn(`[ClientLogForwarder] Started - tab=${this.tabId}`);

    // Flush immediately so the startup breadcrumb reaches Loki without waiting up to
    // FLUSH_INTERVAL_MS (5s). This also acts as an early session-validity probe —
    // if the session cookie is not yet set (offline-first race), the 401 response is
    // now logged-and-continued rather than killing the forwarder.
    void this.flush();
  }

  /**
   * Stop forwarding console logs.
   * Called on logout or when admin status is revoked.
   * Flushes any remaining buffered entries before stopping.
   */
  public stop(): void {
    if (!this.isRunning) return;

    console.debug("[ClientLogForwarder] Stopping");

    this.isRunning = false;

    // Unsubscribe from log collector
    logCollector.offNewLog(this.logListener);

    // Clear the flush timer
    if (this.flushTimer !== null) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }

    // Flush remaining entries (best-effort, non-blocking)
    void this.flush();
  }

  /**
   * Send buffered log entries to the backend.
   * Entries are removed from the buffer before the request is made to avoid
   * re-sending on retry. If the request fails, entries are silently dropped
   * (this is non-critical debug data, not business logic).
   */
  private async flush(): Promise<void> {
    if (this.buffer.length === 0) return;

    // Take entries from the buffer (drain it) so new entries can accumulate
    // while this request is in flight
    const entries = this.buffer.splice(0, MAX_BATCH_SIZE);

    const endpoint = getApiEndpoint(apiEndpoints.admin.clientLogs);
    const isFirstFlush = !this.firstFlushAttempted;
    this.firstFlushAttempted = true;
    this.totalFlushAttempts++;
    this.lastFlushTime = new Date().toISOString();

    // Log first flush attempt at warn level so it is always visible in the browser console.
    // This is the key diagnostic breadcrumb: if this line appears, the forwarder started
    // and is actively attempting to send logs. If it does NOT appear, start() was never called.
    if (isFirstFlush) {
      console.warn(
        `[ClientLogForwarder] First flush attempt — sending ${entries.length} entries to ${endpoint}`,
      );
    } else {
      console.debug(
        `[ClientLogForwarder] Flushing ${entries.length} entries to ${endpoint}`,
      );
    }

    try {
      const payload = {
        logs: entries.map((entry) => ({
          timestamp: entry.timestamp,
          level: entry.level,
          message: entry.message,
        })),
        metadata: {
          userAgent: navigator.userAgent,
          pageUrl: window.location.pathname + window.location.search,
          tabId: this.tabId,
        },
      };

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        credentials: "include", // Send auth cookies
        body: JSON.stringify(payload),
      });

      this.lastFlushStatus = response.status;
      this.lastFlushError = null;

      if (response.ok) {
        this.successfulFlushes++;
      } else {
        this.failedFlushes++;
      }

      // Log first successful flush at warn level for diagnostic visibility
      if (isFirstFlush) {
        console.warn(
          `[ClientLogForwarder] First flush response: ${response.status} ${response.ok ? "(OK)" : "(FAILED)"}`,
        );
      } else {
        console.debug(
          `[ClientLogForwarder] Flush response: ${response.status}`,
        );
      }

      // Auth errors (401/403) are logged but do NOT stop the forwarder.
      //
      // Rationale: the forwarder is started optimistically during the offline-first
      // phase (before the session cookie is fully established). A 401 at that point
      // would kill the forwarder permanently, and the subsequent start() call from
      // the login completion path may be missed if is_admin is momentarily missing
      // from the response — leaving no forwarding for the rest of the session.
      //
      // Instead we let the forwarder keep running. The backend validates admin status
      // on every request, so a genuine de-admin event will simply cause all future
      // flushes to return 401 (harmless network chatter). When the session becomes
      // valid again after login, the next flush succeeds automatically.
      if (response.status === 401 || response.status === 403) {
        console.warn(
          `[ClientLogForwarder] Auth error (${response.status}) — keeping forwarder alive, will retry on next flush`,
        );
      } else if (!response.ok) {
        // Log unexpected non-2xx responses at error level so they are visible and reach Loki
        console.error(
          `[ClientLogForwarder] Unexpected flush response: ${response.status} ${response.statusText}`,
        );
      }
    } catch (err) {
      this.failedFlushes++;
      this.lastFlushStatus = null;
      this.lastFlushError = err instanceof Error ? err.message : String(err);

      // Network error or other fetch failure - log at error level so it is visible
      // in the browser console AND forwarded to Loki on the next successful flush.
      console.error("[ClientLogForwarder] Flush failed (network error):", err);
    }
  }
}

/** Singleton instance - import this to start/stop forwarding */
export const clientLogForwarder = new ClientLogForwarder();
