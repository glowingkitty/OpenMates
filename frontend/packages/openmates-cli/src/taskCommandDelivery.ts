/**
 * Foreground delivery of disk intents written while the CLI was unavailable.
 * This is integration metadata; OpenMates Task records remain authoritative.
 * Intents are scoped to one authenticated account and original owning chat.
 * Existing encrypted outboxes own API retries; this layer never runs a shell,
 * starts a model, or treats pending delivery as confirmed Task state.
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import lockfile from "proper-lockfile";
import type { OpenMatesClient } from "./client.js";
import type { CachedTask } from "./projectTaskSync.js";
import { atomicPrivateFile } from "./projectTaskSync.js";
import { resolveStateDir } from "./storage.js";
import { buildCreateUserTaskInput, buildUpdateUserTaskInput, buildCreateTaskActivityInput, decryptUserTask } from "./tasksCli.js";
import { readCodexThread } from "./codexConnection.js";
import { taskMutationStore, type TaskMutation } from "./taskMutationDelivery.js";
import { activityDeliveryStore } from "./taskActivityDelivery.js";
import { failureDisposition, TaskDeliveryPending, TaskDeliveryRejected, type RetryState } from "./taskDelivery.js";

type Command = {
  schema_version: 1; id: string; scope: [string, string, string]; thread: string;
  task_id: string; project_id: string; task?: CachedTask; created_at: number;
  operation: { kind: "create" | "edit" | "activity" | "complete"; title?: string; description?: string; status?: "backlog" | "todo" | "in_progress" | "blocked" | "done"; message?: string; link_to_chat?: boolean };
  state: "pending" | "acknowledged" | "rejected"; error?: string; retry?: RetryState;
};
export async function flushTaskCommands(client: OpenMatesClient, teamId?: string, root = resolveStateDir(), onNotice?: (message: string) => void) {
  const session = client.getSession();
  const scope: Command["scope"] = [session.apiUrl, session.hashedEmail, teamId || "personal"];
  const directory = join(root, "task-command-delivery", createHash("sha256").update(JSON.stringify(scope)).digest("hex"));
  if (!existsSync(directory)) return;
  const release = await lockfile.lock(directory, {retries: 0, stale: 240000});
  try {
    const records = readdirSync(directory).filter(name => /^[a-f0-9]{64}\.json$/.test(name)).map(name => ({path: join(directory, name), command: JSON.parse(readFileSync(join(directory, name), "utf8")) as Command})).sort((a, b) => a.command.created_at - b.command.created_at);
    let attempted = 0;
    for (const {path, command} of records) {
      if (command.state !== "pending") continue;
      if (command.retry && Date.now() < command.retry.retry_at) break;
      if (attempted++ >= 3) break;
      const save = () => atomicPrivateFile(path, JSON.stringify(command));
      try {
        if (command.schema_version !== 1 || JSON.stringify(command.scope) !== JSON.stringify(scope) || command.id + ".json" !== path.split("/").at(-1)) throw new TaskDeliveryRejected("Task command account or identity mismatch.");
        const operation = command.operation;
        const master = client.getMasterKeyBytes();
        if (operation.kind === "activity") {
          if (!command.task?.encrypted || command.task.external_chat?.id !== command.thread || command.task.external_chat.provider !== "codex") throw new TaskDeliveryRejected("Queued activity lacks its original Task owner and encryption context.");
          const task = await decryptUserTask(command.task.encrypted, master);
          const ownerHash = task.encrypted.external_chat_lookup_hash;
          if (!ownerHash) throw new TaskDeliveryRejected("Queued activity lacks an ownership identity.");
          await activityDeliveryStore(JSON.stringify([...scope, task.taskId, "assignee"]), root, Date.now, ownerHash).deliver(command.id,
            () => buildCreateTaskActivityInput(task, master, {message: operation.message ?? "", entryId: command.id}),
            (input, expectedOwnerHash) => client.createUserTaskActivity(task.taskId, input, {...(teamId ? {teamId} : {personal: true}), actorMode: "assignee", expectedOwnerHash}));
        } else {
          await taskMutationStore(scope, root).deliver(command.id, async (): Promise<TaskMutation> => {
            if (operation.kind === "create") {
              const linked = operation.link_to_chat !== false;
              const owner = linked ? await readCodexThread(command.thread) : undefined;
              const input = await buildCreateUserTaskInput(master, {taskId: command.task_id, title: operation.title ?? "", description: operation.description,
                projectIds: [command.project_id], status: operation.status,
                assign: linked ? "codex" : "user", externalChat: owner ? {provider: "codex", id: owner.id, title: owner.title} : undefined});
              return {kind: "create", taskId: command.task_id, input, creator: linked ? "codex" : undefined};
            }
            if (!command.task?.encrypted || command.task.external_chat?.id !== command.thread || command.task.external_chat.provider !== "codex") throw new TaskDeliveryRejected("Queued update lacks its original Task owner and encryption context.");
            const task = await decryptUserTask(command.task.encrypted, master);
            const ownerHash = task.encrypted.external_chat_lookup_hash ?? undefined;
            if (operation.kind === "complete") return {kind: "complete", taskId: task.taskId, input: {version: task.version}, ownerHash};
            if (operation.kind !== "edit") throw new TaskDeliveryRejected("Unsupported queued Task operation.");
            return {kind: "update", taskId: task.taskId, ownerHash, input: await buildUpdateUserTaskInput(task, master, {title: operation.title, description: operation.description, status: operation.status})};
          }, client);
        }
        command.state = "acknowledged";
        delete command.error; delete command.retry;
        save();
      } catch (error) {
        if (error instanceof TaskDeliveryRejected) {
          command.state = "rejected"; command.error = error.message; save(); onNotice?.(error.message);
        } else if (error instanceof TaskDeliveryPending) {
          command.error = error.message; save(); if (error.persistent) onNotice?.(error.message);
        } else {
          try { command.retry = failureDisposition(error, command.retry ?? null, Date.now()); }
          catch (rejected) {
            if (!(rejected instanceof TaskDeliveryRejected)) throw rejected;
            command.state = "rejected"; command.error = rejected.message; save(); onNotice?.(rejected.message); break;
          }
          const persistent = !command.retry.notified && command.retry.failures >= 5 && Date.now() - command.retry.first_failure_at >= 300000;
          if (persistent) { command.retry.notified = true; command.error = "Task command delivery remains unavailable; the operation is retained."; onNotice?.(command.error); }
          save();
        }
        break;
      }
    }
  } finally { await release(); }
}
