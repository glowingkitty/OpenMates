/**
 * Shared delayed admission for durable Task deliveries.
 * Account-scoped locking and cooldowns prevent a retry storm across workers.
 * Only transport metadata lives here; the encrypted operation stays in its outbox.
 * Permanent conflicts need action; transient errors become persistent only after
 * both five failed attempts and five minutes. No sleeping model run is required.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import lockfile from "proper-lockfile";
import { atomicPrivateFile } from "./projectTaskSync.js";

export interface RetryState {
  failures: number;
  first_failure_at: number;
  retry_at: number;
  notified: boolean;
}
export class TaskDeliveryPending extends Error {
  readonly retryAt: number;
  readonly persistent: boolean;
  constructor(retryAt: number, persistent = false) {
    super(persistent ? "Task sync remains unavailable; the queued update is retained." : "Task update queued for automatic retry.");
    this.retryAt = retryAt;
    this.persistent = persistent;
  }
}
export class TaskDeliveryRejected extends Error {}

export function failureDisposition(error: unknown, state: RetryState | null, now: number, random = Math.random): RetryState {
  const message = error instanceof Error ? error.message : String(error);
  const status = Number((error as { status?: number })?.status || message.match(/HTTP\s+(\d{3})/)?.[1] || 0);
  if ([400, 401, 403, 404, 409, 410, 422].includes(status)) {
    throw new TaskDeliveryRejected(`Task delivery requires action (HTTP ${status}); the operation was retained.`);
  }
  const failures = (state?.failures ?? 0) + 1;
  const retryAfter = Number((error as { retryAfterMs?: number })?.retryAfterMs || 0);
  const delay = Math.max(retryAfter, Math.min(120000, 5000 * 2 ** Math.min(failures - 1, 5)) * (0.8 + 0.4 * random()));
  return { failures, first_failure_at: state?.first_failure_at ?? now, retry_at: now + delay, notified: state?.notified ?? false };
}

export async function withTaskDeliveryAdmission<T>(root: string, accountScope: string, send: () => Promise<T>, now = Date.now): Promise<T> {
  const directory = join(root, "task-delivery-control", createHash("sha256").update(accountScope).digest("hex"));
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  let release: () => Promise<void>;
  try { release = await lockfile.lock(directory, { retries: 0, stale: 240000 }); }
  catch (error) {
    if ((error as { code?: string }).code !== "ELOCKED") throw error;
    throw new TaskDeliveryPending(now() + 5000);
  }
  const path = join(directory, "retry.json");
  try {
    let state: RetryState | null;
    try { state = JSON.parse(readFileSync(path, "utf8")); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; state = null; }
    if (state && now() < state.retry_at) throw new TaskDeliveryPending(state.retry_at);
    try {
      const result = await send();
      atomicPrivateFile(path, JSON.stringify(null));
      return result;
    } catch (error) {
      if (error instanceof TaskDeliveryRejected) throw error;
      const failed = failureDisposition(error, state, now());
      const persistent = !failed.notified && failed.failures >= 5 && now() - failed.first_failure_at >= 300000;
      if (persistent) failed.notified = true;
      atomicPrivateFile(path, JSON.stringify(failed));
      throw new TaskDeliveryPending(failed.retry_at, persistent);
    }
  } finally { await release(); }
}
