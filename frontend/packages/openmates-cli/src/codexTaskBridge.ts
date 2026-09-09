/**
 * Explicitly configured foreground Codex adapter children and deletion delivery.
 * Trusted local configuration selects the runtime; Project data cannot execute
 * code or choose a script. Children share the remote-access process lifetime.
 * Confirmed deletion intents use the authenticated Task retry admission path.
 */
import { createHash } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import lockfile from "proper-lockfile";
import type { OpenMatesClient } from "./client.js";
import { externalChatLookupHash } from "./tasksCli.js";
import { atomicPrivateFile } from "./projectTaskSync.js";
import { TaskDeliveryPending, TaskDeliveryRejected, withTaskDeliveryAdmission } from "./taskDelivery.js";

type Configuration = { repositories?: Record<string, {enabled?: boolean; events_enabled?: boolean; runtime?: string; snapshots?: string[]}> };
export function startCodexTaskBridges(roots: string[], snapshots: string[], stateRoot: string, notice?: (message: string) => void) {
  const configPath = join(stateRoot, "codex-adapter.json");
  const children: ChildProcess[] = [];
  if (existsSync(configPath)) {
    const config = JSON.parse(readFileSync(configPath, "utf8")) as Configuration;
    for (const root of new Set(roots.map(path => resolve(path)))) {
      const entry = config.repositories?.[root];
      if (!entry?.enabled || !entry.events_enabled || !entry.runtime || !isAbsolute(entry.runtime) || !existsSync(entry.runtime)) continue;
      // Only this authenticated remote-access instance may own these snapshots.
      if (!entry.snapshots?.length || !entry.snapshots.every(path => snapshots.includes(resolve(path)))) continue;
      const child = spawn("python3", [entry.runtime, "serve", "--repository", root], {
        cwd: root, env: {...process.env, OPENMATES_STATE_DIR: stateRoot}, stdio: ["pipe", "ignore", "ignore"],
      });
      child.on("error", () => notice?.("Codex event adapter could not start; Task sync remains available."));
      child.on("exit", code => { if (code) notice?.("Codex event adapter stopped; inspect its local status before restarting remote-access."); });
      child.stdin?.on("error", () => undefined);
      children.push(child);
    }
  }
  return {
    changed() { for (const child of children) if (child.exitCode === null && child.stdin?.writable && child.stdin.writableLength < 1024) child.stdin.write("changed\n"); },
    close() { for (const child of children) { child.stdin?.end(); child.kill("SIGTERM"); } },
  };
}

export async function flushCodexChatDeletions(client: OpenMatesClient, teamId: string | undefined, stateRoot: string, notice?: (message: string) => void) {
  const session = client.getSession();
  const scope = [session.apiUrl, session.hashedEmail, teamId || "personal"];
  const account = JSON.stringify(scope);
  const directory = join(stateRoot, "codex-chat-deletions", createHash("sha256").update(account).digest("hex"));
  if (!existsSync(directory)) return;
  const release = await lockfile.lock(directory, {retries: 0, stale: 240000});
  try {
    let attempts = 0;
    for (const name of readdirSync(directory).filter(name => /^[a-f0-9]{64}\.json$/.test(name)).sort()) {
      const path = join(directory, name);
      const record = JSON.parse(readFileSync(path, "utf8"));
      if (record.state !== "pending") continue;
      if (attempts++ >= 3) break;
      try {
        if (record.schema_version !== 1 || record.event_id + ".json" !== name || JSON.stringify(record.scope) !== account || record.evidence !== "thread/deleted" || !/^[a-f0-9-]{36}$/.test(record.thread)) throw new TaskDeliveryRejected("Invalid Codex deletion receipt; retained for review.");
        const lookup = externalChatLookupHash(client.getMasterKeyBytes(), {provider: "codex", id: record.thread});
        await withTaskDeliveryAdmission(stateRoot, account, () => client.unlinkDeletedTaskChat(lookup, record.event_id, teamId ? {teamId} : {personal: true}));
        record.state = "acknowledged";
        atomicPrivateFile(path, JSON.stringify(record));
      } catch (error) {
        if (error instanceof TaskDeliveryRejected) {
          record.state = "rejected"; record.error = error.message; atomicPrivateFile(path, JSON.stringify(record)); notice?.(error.message);
        } else if (error instanceof TaskDeliveryPending) { if (error.persistent) notice?.(error.message); }
        else throw error;
        break;
      }
    }
  } finally { await release(); }
}
