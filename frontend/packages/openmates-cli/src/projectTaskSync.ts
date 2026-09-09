/**
 * Atomic, private Project Task cache for foreground remote-access.
 * Encrypted batches are decrypted only on the device and committed at final frame.
 * A cursor advances with its data, never before it, and reset replaces membership.
 * Human/agent views keep every title and only shorten descriptions/latest activity.
 * Architecture: docs/plans/codex-tasks-orchestration/codex-rebuild-architecture.md.
 */
import { createHash, randomUUID } from "node:crypto";
import { chmodSync, closeSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { UserTaskRecord, UserTaskActivityRecord } from "./client.js";
import { decryptBytesWithAesGcm, encryptBytesWithAesGcm } from "./crypto.js";
import { decryptUserTask, decryptTaskActivityEntry } from "./tasksCli.js";

export interface CachedTask {
  task_id: string;
  short_id: string;
  title: string;
  description: string;
  status: string;
  version: number;
  primary_chat_id: string | null;
  external_chat: { provider: string; id: string; title?: string } | null;
  blocked_reason: string;
  blocked_reason_code: string | null;
  dependencies: Array<Record<string, unknown>>;
  latest_activity: string;
}
export interface ProjectTaskSnapshot {
  schema_version: 1;
  project_id: string;
  cursor: string;
  synced_at: string;
  connection: "connected" | "reconnecting" | "stopped" | "revoked";
  tasks: CachedTask[];
}
export interface ProjectTaskFrame {
  project_id: string;
  batch_id: string;
  part: number;
  final: boolean;
  reset: boolean;
  cursor: string;
  tasks: Array<UserTaskRecord & { latest_activity?: UserTaskActivityRecord | null; dependencies?: Array<Record<string, unknown>> }>;
  removed_task_ids: string[];
}
const digest = (value: string) => createHash("sha256").update(value).digest("hex");
export const shortenTaskText = (value: string, length: number): string => {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length <= length ? text : `${text.slice(0, length - 1)}…`;
};

export function atomicPrivateFile(path: string, content: string): void {
  const temporary = `${path}.${randomUUID()}.tmp`;
  const file = openSync(temporary, "wx", 0o600);
  try { writeFileSync(file, content); fsyncSync(file); } finally { closeSync(file); }
  renameSync(temporary, path);
}

export function renderTaskOverview(tasks: CachedTask[]): string {
  return tasks.map(task => {
    const parts = [`- ${task.short_id} [${task.status}] ${JSON.stringify(task.title)}`];
    if (task.description) parts.push(`  Description: ${JSON.stringify(shortenTaskText(task.description, 180))}`);
    if (task.blocked_reason || task.blocked_reason_code) parts.push(`  Blocker: ${JSON.stringify(task.blocked_reason || task.blocked_reason_code)}`);
    if (task.dependencies.length) parts.push(`  Dependencies: ${JSON.stringify(task.dependencies)}`);
    if (task.latest_activity) parts.push(`  Latest activity: ${JSON.stringify(shortenTaskText(task.latest_activity, 140))}`);
    return parts.join("\n");
  }).join("\n");
}

export class ProjectTaskCache {
  readonly directory: string;
  readonly projectId: string;
  private state: ProjectTaskSnapshot;
  private pending?: { id: string; part: number; reset: boolean; cursor: string; tasks: CachedTask[]; removed: string[] };
  constructor(root: string, accountScope: string, projectId: string) {
    this.projectId = projectId;
    this.directory = join(root, digest(accountScope), digest(projectId));
    mkdirSync(this.directory, { recursive: true, mode: 0o700 });
    chmodSync(this.directory, 0o700);
    try {
      const state = JSON.parse(readFileSync(join(this.directory, "snapshot.json"), "utf8"));
      if (state.schema_version !== 1 || state.project_id !== projectId || !Array.isArray(state.tasks)) throw new Error("Invalid Task sync cache");
      this.state = state;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      this.state = { schema_version: 1, project_id: projectId, cursor: "", synced_at: "", connection: "reconnecting", tasks: [] };
    }
  }
  get cursor(): string | undefined { return this.state.cursor || undefined; }
  get snapshot(): ProjectTaskSnapshot { return structuredClone(this.state); }
  connection(status: ProjectTaskSnapshot["connection"]): void {
    this.pending = undefined;
    this.state.connection = status;
    if (status === "revoked") { this.state.tasks = []; this.state.cursor = ""; }
    this.save();
  }
  private save(): void {
    // snapshot.json is the atomic source for hooks. The text file is a derived
    // convenience view and is never used as a commit/cursor boundary.
    atomicPrivateFile(join(this.directory, "snapshot.json"), JSON.stringify(this.state));
    atomicPrivateFile(join(this.directory, "tasks.txt"), `Project ${this.projectId}; sync ${this.state.connection}\n${renderTaskOverview(this.state.tasks)}\n`);
    const directoryFd = openSync(this.directory, "r");
    try { fsyncSync(directoryFd); } finally { closeSync(directoryFd); }
  }
  async accept(frame: ProjectTaskFrame, decrypt: (record: ProjectTaskFrame["tasks"][number]) => Promise<CachedTask>): Promise<boolean> {
    if (frame.project_id !== this.projectId || !Number.isSafeInteger(frame.part) || frame.part < 0
      || typeof frame.batch_id !== "string" || typeof frame.cursor !== "string" || !/^[^:]+:[0-9]+$/.test(frame.cursor)
      || typeof frame.reset !== "boolean" || typeof frame.final !== "boolean"
      || !Array.isArray(frame.tasks) || !Array.isArray(frame.removed_task_ids)) throw new Error("Invalid Task sync frame");
    if (frame.part === 0) this.pending = { id: frame.batch_id, part: 0, cursor: frame.cursor, reset: frame.reset, tasks: [], removed: [] };
    const batch = this.pending;
    if (!batch || batch.id !== frame.batch_id || batch.part !== frame.part || batch.cursor !== frame.cursor || batch.reset !== frame.reset) {
      this.pending = undefined;
      throw new Error("Task sync batch gap; reconnect to replay");
    }
    for (const record of frame.tasks) batch.tasks.push(await decrypt(record));
    batch.removed.push(...frame.removed_task_ids);
    batch.part++;
    if (!frame.final) return false;
    const oldCursor = this.state.cursor.split(":");
    const newCursor = frame.cursor.split(":");
    if (oldCursor.length === 2 && /^\d+$/.test(oldCursor[1]) && newCursor[0] === oldCursor[0] && /^\d+$/.test(newCursor[1] ?? "")
      && BigInt(newCursor[1]) < BigInt(oldCursor[1])) {
      this.pending = undefined;
      return false;
    }
    if (this.state.cursor && newCursor[0] !== oldCursor[0] && !batch.reset) {
      this.pending = undefined;
      throw new Error("Task sync epoch changed without a snapshot reset");
    }
    const tasks = new Map((batch.reset ? [] : this.state.tasks).map(task => [task.task_id, task]));
    for (const id of batch.removed) tasks.delete(id);
    for (const task of batch.tasks) tasks.set(task.task_id, task);
    this.state = { ...this.state, cursor: batch.cursor, tasks: [...tasks.values()], synced_at: new Date().toISOString(), connection: "connected" };
    this.pending = undefined;
    this.save();
    return true;
  }
}

export async function decryptProjectTask(record: ProjectTaskFrame["tasks"][number], masterKey: Uint8Array, projectKey: Uint8Array, projectId: string): Promise<CachedTask> {
  let readable = record;
  const wrappers = (record as UserTaskRecord & { key_wrappers?: Array<{ key_type: string; hashed_project_id?: string; encrypted_task_key: string }> }).key_wrappers;
  const wrapper = wrappers?.find(item => item.key_type === "project" && item.hashed_project_id === digest(projectId));
  if (wrapper) {
    const key = await decryptBytesWithAesGcm(wrapper.encrypted_task_key, projectKey);
    if (!key) throw new Error("Project Task key could not be decrypted");
    readable = { ...record, encrypted_task_key: await encryptBytesWithAesGcm(key, masterKey) };
  }
  const task = await decryptUserTask(readable, masterKey);
  const activity = record.latest_activity ? await decryptTaskActivityEntry(task, masterKey, record.latest_activity) : null;
  return {
    task_id: task.taskId, short_id: task.shortId, title: task.title,
    description: shortenTaskText(task.description, 180), status: task.status, version: task.version,
    primary_chat_id: task.primaryChatId, external_chat: task.externalChat,
    blocked_reason: task.blockedReason, blocked_reason_code: task.blockedReasonCode,
    dependencies: record.dependencies ?? [],
    latest_activity: activity ? shortenTaskText(activity.message || `${activity.eventType ?? activity.kind}${activity.nextStatus ? `: ${activity.nextStatus}` : ""}`, 140) : "",
  };
}
