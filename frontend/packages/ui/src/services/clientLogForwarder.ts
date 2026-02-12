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

class ClientLogForwarder {
  private buffer: ConsoleLogEntry[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private isRunning = false;
  private tabId: string = generateTabId();

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
   * Start forwarding console logs to the server.
   * Should only be called when the authenticated user is confirmed to be an admin.
   * Safe to call multiple times (idempotent) - will not create duplicate listeners.
   */
  public start(): void {
    if (this.isRunning) return;

    this.isRunning = true;
    this.tabId = generateTabId();

    // Subscribe to real-time log entries from the collector
    logCollector.onNewLog(this.logListener);

    // Set up periodic flush interval
    this.flushTimer = setInterval(() => {
      void this.flush();
    }, FLUSH_INTERVAL_MS);

    // Use warn level so this is visible even when debug logging is filtered in browser dev tools.
    // This is a critical diagnostic breadcrumb confirming the forwarder activated for the admin user.
    console.warn(`[ClientLogForwarder] Started - tab=${this.tabId}`);
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
    console.debug(
      `[ClientLogForwarder] Flushing ${entries.length} entries to ${endpoint}`,
    );

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

      console.debug(`[ClientLogForwarder] Flush response: ${response.status}`);

      // If we get a 401/403, stop forwarding (user is no longer admin or session expired)
      if (response.status === 401 || response.status === 403) {
        console.warn(
          `[ClientLogForwarder] Auth failed (${response.status}), stopping forwarder`,
        );
        this.stop();
      }
      // Silently ignore other errors (429 rate limit, 500 server error, network issues)
      // This is non-critical debug infrastructure - should never interfere with the app
    } catch (err) {
      // Network error or other fetch failure - log for debugging, then drop the entries.
      console.debug("[ClientLogForwarder] Flush failed:", err);
    }
  }
}

/** Singleton instance - import this to start/stop forwarding */
export const clientLogForwarder = new ClientLogForwarder();
