/*
 * Recoverable CLI activity delivery, scoped to account, API, task and actor.
 * Only the original encrypted payload and encrypted acknowledgement are saved.
 * Keeping identical ciphertext makes backend entry-id idempotency safe after
 * an uncertain HTTP outcome. A filesystem lock serializes concurrent retries.
 * Tests: tests/taskActivityDelivery.test.ts.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import lockfile from "proper-lockfile";
import { resolveStateDir } from "./storage.js";
import { atomicPrivateFile } from "./projectTaskSync.js";
import { withTaskDeliveryAdmission, TaskDeliveryRejected, TaskDeliveryPending, lockTaskDeliveryRecord } from "./taskDelivery.js";
import type { OpenMatesClient, UserTaskActivityCreateInput, UserTaskActivityRecord } from "./client.js";

type Delivery = { input: UserTaskActivityCreateInput; acknowledged?: UserTaskActivityRecord; rejected?: string; owner_hash?: string };
export function activityDeliveryStore(scope: string, stateDir = resolveStateDir(), now = Date.now, ownerHash?: string) {
  const directory = join(stateDir, "task-activity-delivery", createHash("sha256").update(scope).digest("hex"));
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  let parts: string[] | null = null;
  try { const value = JSON.parse(scope); if (Array.isArray(value) && value.length === 5 && value.every(item => typeof item === "string")) parts = value; } catch { /* Legacy stores remain explicitly flushable. */ }
  const accountScope = parts ? JSON.stringify(parts.slice(0, 3)) : scope;
  if (parts) atomicPrivateFile(join(directory, "scope.json"), JSON.stringify(parts));
  const pendingDirectory = join(directory, "pending");
  const acknowledgedDirectory = join(directory, "acknowledged");
  mkdirSync(pendingDirectory, { recursive: true, mode: 0o700 });
  mkdirSync(acknowledgedDirectory, { recursive: true, mode: 0o700 });
  const save = (path: string, record: Delivery) => {
    atomicPrivateFile(path, JSON.stringify(record));
  };
  const send = async (path: string, record: Delivery, create: (input: UserTaskActivityCreateInput, ownerHash?: string) => Promise<UserTaskActivityRecord>) => {
    if (!record.acknowledged) {
      if (record.rejected) throw new TaskDeliveryRejected(record.rejected);
      let acknowledged: UserTaskActivityRecord;
      try {
        acknowledged = await withTaskDeliveryAdmission(stateDir, accountScope, async () => {
          const result = await create(record.input, record.owner_hash);
          if (result.entry_id !== record.input.entry_id) throw new TaskDeliveryRejected("Activity acknowledgement identity mismatch");
          return result;
        }, now);
      } catch (error) {
        if (error instanceof TaskDeliveryRejected) { record.rejected = error.message; save(path, record); }
        throw error;
      }
      record.acknowledged = acknowledged;
      save(join(acknowledgedDirectory, `${record.input.entry_id}.json`), record);
      rmSync(path, { force: true });
    }
    return record.acknowledged;
  };
  return {
    async deliver(id: string, build: () => Promise<UserTaskActivityCreateInput>, create: (input: UserTaskActivityCreateInput, ownerHash?: string) => Promise<UserTaskActivityRecord>) {
      if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("--delivery-id must be a SHA-256 hex identifier");
      const release = await lockTaskDeliveryRecord(directory, id);
      try {
        const acknowledgedPath = join(acknowledgedDirectory, `${id}.json`);
        const path = existsSync(acknowledgedPath) ? acknowledgedPath : join(pendingDirectory, `${id}.json`);
        let record: Delivery;
        try { record = JSON.parse(readFileSync(path, "utf8")); }
        catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
          record = { input: await build(), ...(ownerHash ? { owner_hash: ownerHash } : {}) };
          save(path, record);
        }
        return await send(path, record, create);
      } finally { await release(); }
    },
    async flush(create: (input: UserTaskActivityCreateInput, ownerHash?: string) => Promise<UserTaskActivityRecord>) {
      const release = await lockfile.lock(directory, { retries: 0, stale: 120000 });
      try {
        const names = readdirSync(pendingDirectory).filter(name => /^[a-f0-9]{64}\.json$/.test(name));
        let pending = names.length;
        let attempted = 0;
        let rejected = 0;
        let notice: string | undefined;
        for (const name of names) {
          const path = join(pendingDirectory, name);
          const record: Delivery = JSON.parse(readFileSync(path, "utf8"));
          if (record.acknowledged) continue;
          if (record.rejected) { rejected++; continue; }
          if (attempted >= 3) break;
          attempted++;
          try {
            const unlock = await lockTaskDeliveryRecord(directory, name.slice(0, -5));
            try {
              if (existsSync(path)) await send(path, JSON.parse(readFileSync(path, "utf8")), create);
              pending--;
            } finally { await unlock(); }
          }
          catch (error) {
            if (error instanceof TaskDeliveryPending) {
              if (error.persistent) notice = error.message;
            } else if (error instanceof TaskDeliveryRejected) {
              rejected++;
              notice = error.message;
            } else throw error;
            break; // One failed network attempt per refresh; do not storm the API.
          }
        }
        return { pending, attempted, rejected, ...(notice ? { notice } : {}) };
      } finally { await release(); }
    },
  };
}

/** Drain this authenticated context only; a scan with no pending work sends nothing. */
export async function flushPendingTaskActivities(client: OpenMatesClient, teamId?: string, stateDir = resolveStateDir(), onNotice?: (notice: string) => void) {
  const session = client.getSession();
  const expected = JSON.stringify([session.apiUrl, session.hashedEmail, teamId || "personal"]);
  const base = join(stateDir, "task-activity-delivery");
  if (!existsSync(base)) return;
  for (const folder of readdirSync(base)) {
    if (!/^[a-f0-9]{64}$/.test(folder)) continue;
    let scope: string[];
    try { scope = JSON.parse(readFileSync(join(base, folder, "scope.json"), "utf8")); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") continue; throw error; }
    if (!Array.isArray(scope) || scope.length !== 5 || JSON.stringify(scope.slice(0, 3)) !== expected) continue;
    if (!scope[3] || !["user", "assignee"].includes(scope[4])) continue;
    const result = await activityDeliveryStore(JSON.stringify(scope), stateDir).flush((input, expectedOwnerHash) => {
      if (scope[4] === "assignee" && !expectedOwnerHash) throw new TaskDeliveryRejected("Legacy queued activity needs explicit ownership reconciliation.");
      return client.createUserTaskActivity(scope[3], input, {
        ...(teamId ? { teamId } : { personal: true }), actorMode: scope[4] as "user" | "assignee", expectedOwnerHash,
      });
    });
    if (result.notice) onNotice?.(result.notice);
    if (result.pending > result.rejected) break;
  }
}
