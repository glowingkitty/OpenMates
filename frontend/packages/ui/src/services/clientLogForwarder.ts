/**
 * Client Log Forwarder — Admin Live Streaming
 *
 * Forwards browser console logs in real-time to OpenObserve (via the backend
 * proxy at /v1/admin/client-logs) for authenticated admin users only.
 *
 * Non-admin users: this service is never started.
 * Any user (on issue submit): see /v1/settings/issue-logs for the separate
 *   one-shot push path used at issue-report time.
 *
 * Architecture context: docs/architecture/admin-console-log-forwarding.md
 *
 * Flow:
 *   login/session-restore (admin) -> start() -> hooks logCollector.onNewLog
 *   -> batches every FLUSH_INTERVAL_MS -> POST /v1/admin/client-logs
 *   logout -> stop() -> unhooks listener, drains any remaining buffer
 */

import { logCollector } from "./logCollector";
import type { ConsoleLogEntry } from "./logCollector";
import { getApiEndpoint, apiEndpoints } from "../config/api";

// ----- Configuration -------------------------------------------------------

/** How often (ms) to flush the pending batch to the backend. */
const FLUSH_INTERVAL_MS = 5_000;

/** Maximum entries per batch (matches backend validation limit). */
const MAX_BATCH_SIZE = 50;

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

class ClientLogForwarderService {
  private running = false;
  private pendingBuffer: ConsoleLogEntry[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;

  private readonly logListener = (entry: ConsoleLogEntry): void => {
    this.pendingBuffer.push(entry);
    // Flush immediately when buffer is full — do not wait for the timer.
    if (this.pendingBuffer.length >= MAX_BATCH_SIZE) {
      void this.flush();
    }
  };

  /**
   * Start forwarding. Call only for admin users after successful auth.
   * Safe to call multiple times — idempotent.
   */
  start(): void {
    if (this.running) return;
    this.running = true;
    logCollector.onNewLog(this.logListener);
    this.flushTimer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
  }

  /**
   * Stop forwarding and drain any buffered entries.
   * Call on logout or when admin status is lost.
   */
  async stop(): Promise<void> {
    if (!this.running) return;
    this.running = false;
    logCollector.offNewLog(this.logListener);
    if (this.flushTimer !== null) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    // Best-effort drain before teardown.
    await this.flush();
    this.pendingBuffer = [];
  }

  /**
   * Flush the current buffer to the backend.
   * Never throws — log forwarding must never break the app.
   */
  private async flush(): Promise<void> {
    if (this.pendingBuffer.length === 0) return;

    const batch = this.pendingBuffer.splice(0, MAX_BATCH_SIZE);

    const entries = batch.map((e) => ({
      timestamp: e.timestamp,
      level: e.level,
      message: e.message,
    }));

    const metadata = {
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "",
      pageUrl: getPagePath(),
      tabId: TAB_ID,
    };

    try {
      await fetch(getApiEndpoint(apiEndpoints.admin.clientLogs), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ logs: entries, metadata }),
        // keepalive: drain succeeds even if page unloads during logout flush
        keepalive: true,
      });
    } catch {
      // Non-critical: silently discard. Never call console.* here (infinite loop risk).
    }
  }
}

export const clientLogForwarder = new ClientLogForwarderService();
