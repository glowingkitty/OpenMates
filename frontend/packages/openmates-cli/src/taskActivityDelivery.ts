/*
 * Recoverable CLI activity delivery, scoped to account, API, task and actor.
 * Only the original encrypted payload and encrypted acknowledgement are saved.
 * Keeping identical ciphertext makes backend entry-id idempotency safe after
 * an uncertain HTTP outcome. A filesystem lock serializes concurrent retries.
 * Tests: tests/taskActivityDelivery.test.ts.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import lockfile from "proper-lockfile";
import { resolveStateDir } from "./storage.js";
import type { UserTaskActivityCreateInput, UserTaskActivityRecord } from "./client.js";

type Delivery = { input: UserTaskActivityCreateInput; acknowledged?: UserTaskActivityRecord };
export function activityDeliveryStore(scope: string, stateDir = resolveStateDir()) {
  const directory = join(stateDir, "task-activity-delivery", createHash("sha256").update(scope).digest("hex"));
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const pendingDirectory = join(directory, "pending");
  const acknowledgedDirectory = join(directory, "acknowledged");
  mkdirSync(pendingDirectory, { recursive: true, mode: 0o700 });
  mkdirSync(acknowledgedDirectory, { recursive: true, mode: 0o700 });
  const save = (path: string, record: Delivery) => {
    const temporary = `${path}.${process.pid}.tmp`;
    writeFileSync(temporary, JSON.stringify(record), { mode: 0o600 });
    renameSync(temporary, path);
  };
  const send = async (path: string, record: Delivery, create: (input: UserTaskActivityCreateInput) => Promise<UserTaskActivityRecord>) => {
    if (!record.acknowledged) {
      const acknowledged = await create(record.input);
      if (acknowledged.entry_id !== record.input.entry_id) throw new Error("Activity acknowledgement identity mismatch");
      record.acknowledged = acknowledged;
      save(join(acknowledgedDirectory, `${record.input.entry_id}.json`), record);
      rmSync(path, { force: true });
    }
    return record.acknowledged;
  };
  return {
    async deliver(id: string, build: () => Promise<UserTaskActivityCreateInput>, create: (input: UserTaskActivityCreateInput) => Promise<UserTaskActivityRecord>) {
      if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("--delivery-id must be a SHA-256 hex identifier");
      const release = await lockfile.lock(directory, { retries: { retries: 3, minTimeout: 100, maxTimeout: 500 }, stale: 120000 });
      try {
        const acknowledgedPath = join(acknowledgedDirectory, `${id}.json`);
        const path = existsSync(acknowledgedPath) ? acknowledgedPath : join(pendingDirectory, `${id}.json`);
        let record: Delivery;
        try { record = JSON.parse(readFileSync(path, "utf8")); }
        catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
          record = { input: await build() };
          save(path, record);
        }
        return await send(path, record, create);
      } finally { await release(); }
    },
    async flush(create: (input: UserTaskActivityCreateInput) => Promise<UserTaskActivityRecord>) {
      const release = await lockfile.lock(directory, { retries: 0, stale: 120000 });
      try {
        const names = readdirSync(pendingDirectory).filter(name => /^[a-f0-9]{64}\.json$/.test(name));
        let pending = names.length;
        let attempted = 0;
        for (const name of names) {
          const path = join(pendingDirectory, name);
          const record: Delivery = JSON.parse(readFileSync(path, "utf8"));
          if (record.acknowledged) continue;
          if (attempted >= 3) break;
          attempted++;
          try { await send(path, record, create); pending--; }
          catch { break; } // One failed network attempt per refresh; do not storm the API.
        }
        return { pending, attempted };
      } finally { await release(); }
    },
  };
}
