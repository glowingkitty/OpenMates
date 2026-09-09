/**
 * Durable encrypted Task mutation delivery using the existing Task API.
 * The first attempt performs only the requested mutation. After uncertainty,
 * exact scoped reads reconcile identity/version/ciphertext before any retry.
 * A newer conflicting edit is never overwritten; the original intent is retained.
 * Account admission is shared with activity delivery and owned by remote-access.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import lockfile from "proper-lockfile";
import type { OpenMatesClient, UserTaskRecord, UserTaskCreateInput, UserTaskUpdateInput } from "./client.js";
import { atomicPrivateFile } from "./projectTaskSync.js";
import { resolveStateDir } from "./storage.js";
import { TaskDeliveryPending, TaskDeliveryRejected, withTaskDeliveryAdmission } from "./taskDelivery.js";

type Scope = [string, string, string];
export type TaskMutation =
  | { kind: "create"; taskId: string; input: UserTaskCreateInput; creator?: "codex" }
  | { kind: "update"; taskId: string; input: UserTaskUpdateInput; ownerHash?: string }
  | { kind: "complete"; taskId: string; input: { version: number }; ownerHash?: string }
  | { kind: "delete"; taskId: string; version: number; ownerHash?: string };
type RecordState = { mutation: TaskMutation; uncertain?: boolean; rejected?: string; acknowledgement?: UserTaskRecord | { deleted: true; task_id: string } };
const digest = (text: string) => createHash("sha256").update(text).digest("hex");
const stable = (value: unknown): string => JSON.stringify(value, (_key, item) => item && !Array.isArray(item) && typeof item === "object" ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);

export function reconcileMutation(mutation: TaskMutation, current: UserTaskRecord | null): "accepted" | "retry" {
  if (mutation.kind === "delete") {
    if (!current) return "accepted";
    if (current.version === mutation.version && (!mutation.ownerHash || current.external_chat_lookup_hash === mutation.ownerHash)) return "retry";
    throw new TaskDeliveryRejected("Task changed after deletion was queued; review the retained operation.");
  }
  if (!current) {
    if (mutation.kind === "create") return "retry";
    throw new TaskDeliveryRejected("Queued update refers to a Task that is no longer accessible.");
  }
  if (current.task_id !== mutation.taskId) throw new TaskDeliveryRejected("Task reconciliation identity mismatch.");
  const acknowledgedRelease = mutation.kind === "update" && mutation.input.external_chat_provider === null && current.external_chat_provider == null && current.primary_chat_id == null;
  if (mutation.kind !== "create" && mutation.ownerHash && current.external_chat_lookup_hash !== mutation.ownerHash && !acknowledgedRelease) {
    throw new TaskDeliveryRejected("Task ownership changed; the queued update cannot act for its new owner.");
  }
  if (mutation.kind === "complete") {
    if (current.status === "done" && current.version === mutation.input.version + 1) return "accepted";
    if (current.version === mutation.input.version) return "retry";
    throw new TaskDeliveryRejected("Task changed while completion was uncertain; review its current state.");
  }
  // Only fields actually persisted on the Task are compared. Wrappers are
  // separate records and must not be used to infer an acknowledged mutation.
  const values = Object.entries(mutation.input).filter(([key, value]) => value !== undefined && !["version", "updated_at", "key_wrappers", "plaintext_title", "plaintext_description"].includes(key));
  const same = values.every(([key, value]) => {
    if (key === "linked_project_ids" && Array.isArray(value)) return stable(current.linked_project_hashes ?? []) === stable(value.map(id => digest(String(id))));
    return stable((current as unknown as Record<string, unknown>)[key]) === stable(value);
  });
  if (mutation.kind === "create") {
    // The immutable random Task-key ciphertext also proves an accepted create
    // when another legitimate edit has already advanced mutable fields.
    const sameCreation = Boolean(current.encrypted_task_key) && current.encrypted_task_key === mutation.input.encrypted_task_key && current.created_at === mutation.input.created_at;
    if (same || sameCreation) return "accepted";
    throw new TaskDeliveryRejected("Task creation identity already exists with different content; the original request is retained.");
  }
  if (same && current.version === mutation.input.version + 1 && !("key_wrappers" in mutation.input)) return "accepted";
  if (current.version === mutation.input.version) return "retry";
  throw new TaskDeliveryRejected("Task changed while delivery was uncertain; review the retained update instead of overwriting newer work.");
}

export function taskMutationStore(scope: Scope, root = resolveStateDir(), now = Date.now) {
  const account = JSON.stringify(scope);
  const directory = join(root, "task-mutation-delivery", digest(account));
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  atomicPrivateFile(join(directory, "scope.json"), account);
  const context = scope[2] === "personal" ? { personal: true } : { teamId: scope[2] };
  const save = (path: string, record: RecordState) => atomicPrivateFile(path, JSON.stringify(record));
  async function send(path: string, record: RecordState, client: OpenMatesClient) {
    if (record.acknowledgement) return record.acknowledgement;
    if (record.rejected) throw new TaskDeliveryRejected(record.rejected);
    const mutation = record.mutation;
    try {
      const acknowledgement = await withTaskDeliveryAdmission(root, account, async () => {
        if (record.uncertain) {
          const current = await client.getUserTask(mutation.taskId, context);
          if (reconcileMutation(mutation, current) === "accepted") return current ?? { deleted: true as const, task_id: mutation.taskId };
        }
        // Persist uncertainty before crossing the network boundary. A process
        // crash has the same recovery path as a lost HTTP response.
        record.uncertain = true;
        save(path, record);
        if (mutation.kind === "complete") return client.completeUserTask(mutation.taskId, mutation.input);
        if (mutation.kind === "create") return client.createUserTask(mutation.input, { creator: mutation.creator });
        if (mutation.kind === "update") return client.updateUserTask(mutation.taskId, mutation.input, context);
        const result = await client.deleteUserTask(mutation.taskId, mutation.version);
        if (result.deleted !== true || result.task_id !== mutation.taskId) throw new TaskDeliveryRejected("Task deletion acknowledgement mismatch.");
        return { deleted: true as const, task_id: mutation.taskId };
      }, now);
      record.acknowledgement = acknowledgement;
      save(path, record);
      return acknowledgement;
    } catch (error) {
      if (error instanceof TaskDeliveryRejected) { record.rejected = error.message; save(path, record); }
      throw error;
    }
  }
  return {
    async deliver(id: string, build: () => Promise<TaskMutation>, client: OpenMatesClient) {
      if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("Task delivery ID must be a SHA-256 hex identifier.");
      const release = await lockfile.lock(directory, { retries: 0, stale: 240000 });
      try {
        const path = join(directory, `${id}.json`);
        let record: RecordState;
        try { record = JSON.parse(readFileSync(path, "utf8")); }
        catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
          record = { mutation: await build() };
          if (["create", "complete", "delete"].includes(record.mutation.kind) && scope[2] !== "personal") throw new TaskDeliveryRejected("This mutation does not support Team-scoped delivery in the current Task API; no personal fallback was attempted.");
          save(path, record);
        }
        return await send(path, record, client);
      } finally { await release(); }
    },
    async flush(client: OpenMatesClient, onNotice?: (message: string) => void) {
      const release = await lockfile.lock(directory, { retries: 0, stale: 240000 });
      try {
        const files = readdirSync(directory).filter(name => /^[a-f0-9]{64}\.json$/.test(name)).sort();
        let attempted = 0;
        for (const file of files) {
          const path = join(directory, file);
          const record: RecordState = JSON.parse(readFileSync(path, "utf8"));
          if (record.acknowledgement || record.rejected) continue;
          if (attempted++ >= 3) break;
          try { await send(path, record, client); }
          catch (error) {
            if (error instanceof TaskDeliveryRejected || error instanceof TaskDeliveryPending && error.persistent) onNotice?.(error.message);
            else if (!(error instanceof TaskDeliveryPending)) throw error;
            break;
          }
        }
      } finally { await release(); }
    },
  };
}

export async function flushPendingTaskMutations(client: OpenMatesClient, teamId?: string, root = resolveStateDir(), onNotice?: (message: string) => void) {
  const session = client.getSession();
  const scope: Scope = [session.apiUrl, session.hashedEmail, teamId || "personal"];
  if (!existsSync(join(root, "task-mutation-delivery", digest(JSON.stringify(scope))))) return;
  await taskMutationStore(scope, root).flush(client, onNotice);
}
