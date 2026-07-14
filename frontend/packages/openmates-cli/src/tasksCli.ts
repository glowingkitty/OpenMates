/*
 * OpenMates CLI task helpers.
 *
 * Purpose: decrypt/encrypt user-facing task records and render command output.
 * Architecture: command handlers stay in cli.ts; this module owns task view
 * models, terminal board formatting, and payload preparation for /v1/user-tasks.
 * Security: task title/description/tag fields are decrypted locally with the
 * user's master-wrapped per-task key; ciphertext is never normal CLI output.
 * Spec: docs/specs/tasks-v1/spec.yml.
 */

import { createHash, randomBytes, randomUUID } from "node:crypto";

import type {
  UserTaskAssigneeType,
  UserTaskCreateInput,
  UserTaskRecord,
  UserTaskStatus,
  UserTaskUpdateInput,
} from "./client.js";
import {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
} from "./crypto.js";

const TASK_STATUSES: UserTaskStatus[] = ["backlog", "todo", "in_progress", "blocked", "done"];
const DEFAULT_STANDALONE_PREFIX = "TASK";

export interface DecryptedUserTask {
  taskId: string;
  shortId: string;
  title: string;
  description: string;
  tags: string[];
  latestInstruction: string;
  status: UserTaskStatus;
  assigneeType: UserTaskAssigneeType;
  assigneeHash: string | null;
  primaryChatId: string | null;
  linkedProjectIds: string[];
  planId: string | null;
  dueAt: number | null;
  priority: number;
  position: number;
  queueState: string;
  blockedReasonCode: string | null;
  aiExecutionState: string | null;
  version: number;
  encrypted: UserTaskRecord;
}

export interface TaskCreateOptions {
  title: string;
  description?: string;
  status?: UserTaskStatus;
  assign?: string;
  chatId?: string | null;
  projectIds?: string[];
  planId?: string | null;
  dueAt?: number | null;
}

export interface TaskUpdateOptions {
  title?: string;
  description?: string;
  status?: UserTaskStatus;
  assign?: string;
  chatId?: string | null;
  projectIds?: string[];
  planId?: string | null;
}

export function normalizeTaskStatus(value: string | undefined): UserTaskStatus | undefined {
  if (value === undefined) return undefined;
  if (TASK_STATUSES.includes(value as UserTaskStatus)) return value as UserTaskStatus;
  throw new Error(`Unknown task status '${value}'. Expected one of: ${TASK_STATUSES.join(", ")}`);
}

export function parseAssignee(value: string | undefined): { assigneeType: UserTaskAssigneeType; assigneeHash: string | null } {
  if (!value || value === "user") return { assigneeType: "user", assigneeHash: null };
  if (["ai", "openmates", "OpenMates"].includes(value)) return { assigneeType: "ai", assigneeHash: null };
  return { assigneeType: "user", assigneeHash: value };
}

export function splitCsvFlag(value: string | boolean | undefined): string[] {
  if (typeof value !== "string") return [];
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseDueAt(value: string | boolean | undefined): number | null | undefined {
  if (value === undefined) return undefined;
  if (value === false || value === true) throw new Error("--due requires a timestamp or date value.");
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) return Math.floor(numeric);
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) throw new Error(`Invalid --due value '${value}'.`);
  return Math.floor(parsed / 1000);
}

export async function buildCreateUserTaskInput(masterKey: Uint8Array, input: TaskCreateOptions): Promise<UserTaskCreateInput> {
  const taskKey = randomBytes(32);
  const encryptedTaskKey = await encryptBytesWithAesGcm(taskKey, masterKey);
  const timestamp = nowSeconds();
  const assignee = parseAssignee(input.assign);
  const linkedProjectIds = input.projectIds ?? [];
  const status = input.status ?? (assignee.assigneeType === "ai" && !input.dueAt ? "in_progress" : "todo");
  return {
    task_id: randomUUIDCompat(),
    short_id: undefined,
    version: 1,
    encrypted_task_key: encryptedTaskKey,
    encrypted_title: await encryptWithAesGcmCombined(input.title, taskKey),
    encrypted_description: await encryptWithAesGcmCombined(input.description ?? "", taskKey),
    encrypted_tags: await encryptWithAesGcmCombined("[]", taskKey),
    encrypted_linked_project_ids: await encryptWithAesGcmCombined(JSON.stringify(linkedProjectIds), taskKey),
    status,
    assignee_type: assignee.assigneeType,
    assignee_hash: assignee.assigneeHash,
    primary_chat_id: input.chatId ?? null,
    linked_project_ids: linkedProjectIds,
    plan_id: input.planId ?? null,
    due_at: input.dueAt ?? null,
    priority: 0,
    position: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
  } as UserTaskCreateInput;
}

export async function buildUpdateUserTaskInput(task: DecryptedUserTask, masterKey: Uint8Array, input: TaskUpdateOptions): Promise<UserTaskUpdateInput> {
  const taskKey = await taskKeyFromRecord(task.encrypted, masterKey);
  const patch: UserTaskUpdateInput = { version: task.version, updated_at: nowSeconds() };
  if (input.title !== undefined) patch.encrypted_title = await encryptWithAesGcmCombined(input.title, taskKey);
  if (input.description !== undefined) patch.encrypted_description = await encryptWithAesGcmCombined(input.description, taskKey);
  if (input.status !== undefined) patch.status = input.status;
  if (input.assign !== undefined) {
    const assignee = parseAssignee(input.assign);
    patch.assignee_type = assignee.assigneeType;
    patch.assignee_hash = assignee.assigneeHash;
  }
  if (input.chatId !== undefined) patch.primary_chat_id = input.chatId;
  if (input.projectIds !== undefined) {
    patch.linked_project_ids = input.projectIds;
    patch.encrypted_linked_project_ids = await encryptWithAesGcmCombined(JSON.stringify(input.projectIds), taskKey);
  }
  if (input.planId !== undefined) patch.plan_id = input.planId;
  return patch;
}

export async function decryptUserTask(record: UserTaskRecord, masterKey: Uint8Array): Promise<DecryptedUserTask> {
  if (typeof record.version !== "number") throw new Error(`Task ${record.task_id} is missing version.`);
  const taskKey = await taskKeyFromRecord(record, masterKey);
  const tags = parseStringArray(await decryptOptional(record.encrypted_tags, taskKey));
  const linkedProjectIds = parseStringArray(await decryptOptional(record.encrypted_linked_project_ids, taskKey));
  return {
    taskId: record.task_id,
    shortId: record.short_id || deriveShortId(record),
    title: await decryptOptional(record.encrypted_title, taskKey) || "(untitled task)",
    description: await decryptOptional(record.encrypted_description, taskKey),
    tags,
    latestInstruction: await decryptOptional(record.encrypted_latest_instruction, taskKey),
    status: record.status,
    assigneeType: record.assignee_type,
    assigneeHash: record.assignee_hash ?? null,
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: linkedProjectIds.length > 0 ? linkedProjectIds : (record.linked_project_ids ?? []),
    planId: record.plan_id ?? null,
    dueAt: record.due_at ?? null,
    priority: record.priority ?? 0,
    position: record.position ?? 0,
    queueState: record.queue_state ?? "none",
    blockedReasonCode: record.blocked_reason_code ?? null,
    aiExecutionState: record.ai_execution_state ?? null,
    version: record.version,
    encrypted: record,
  };
}

export async function decryptUserTasks(records: UserTaskRecord[], masterKey: Uint8Array): Promise<DecryptedUserTask[]> {
  const output: DecryptedUserTask[] = [];
  for (const record of records) output.push(await decryptUserTask(record, masterKey));
  return output;
}

export function findTask(tasks: DecryptedUserTask[], id: string): DecryptedUserTask {
  const taskIdMatch = tasks.find((candidate) => candidate.taskId === id);
  if (taskIdMatch) return taskIdMatch;
  const shortIdMatches = tasks.filter((candidate) => candidate.shortId === id);
  if (shortIdMatches.length > 1) throw new Error(`Task '${id}' is ambiguous in the current task list. Use the full task ID.`);
  const task = shortIdMatches[0];
  if (!task) throw new Error(`Task '${id}' was not found in the current task list.`);
  return task;
}

export function renderTaskList(tasks: DecryptedUserTask[]): string {
  if (tasks.length === 0) return "No tasks found.";
  const lines = ["Tasks", "ID        Status       Assignee    Queue       Title"];
  for (const task of tasks) {
    lines.push(`${pad(task.shortId, 9)} ${pad(task.status, 12)} ${pad(assigneeLabel(task), 11)} ${pad(task.queueState, 11)} ${task.title}`);
  }
  return lines.join("\n");
}

export function renderTaskDetail(task: DecryptedUserTask): string {
  const lines = [
    `Task ${task.shortId}`,
    `Title: ${task.title}`,
    `Status: ${task.status}`,
    `Assignee: ${assigneeLabel(task)}`,
    `Queue: ${task.queueState}`,
    `Task ID: ${task.taskId}`,
  ];
  if (task.description) lines.push(`Description: ${task.description}`);
  if (task.primaryChatId) lines.push(`Chat: ${task.primaryChatId}`);
  if (task.linkedProjectIds.length > 0) lines.push(`Projects: ${task.linkedProjectIds.join(", ")}`);
  if (task.planId) lines.push(`Plan: ${task.planId}`);
  if (task.blockedReasonCode) lines.push(`Blocked reason: ${task.blockedReasonCode}`);
  if (task.aiExecutionState) lines.push(`AI state: ${task.aiExecutionState}`);
  return lines.join("\n");
}

export function renderTaskBoard(tasks: DecryptedUserTask[], width = process.stdout.columns || 100): string {
  const columns = TASK_STATUSES.map((status) => ({ status, tasks: tasks.filter((task) => task.status === status).sort(compareTasks) }));
  if (width < 96) {
    const lines = ["OpenMates Tasks Board"];
    for (const column of columns) {
      lines.push("", `${columnTitle(column.status)} (${column.tasks.length})`, "-".repeat(24));
      lines.push(...boardColumnLines(column.tasks, 8));
    }
    return lines.join("\n");
  }
  const perColumn = 6;
  const columnWidth = 22;
  const lines = ["OpenMates Tasks Board", ""];
  lines.push(columns.map((column) => pad(`${columnTitle(column.status)} (${column.tasks.length})`, columnWidth)).join("  "));
  lines.push(columns.map(() => "-".repeat(columnWidth)).join("  "));
  const renderedColumns = columns.map((column) => boardColumnLines(column.tasks, perColumn).map((line) => truncate(line, columnWidth)));
  const maxRows = Math.max(...renderedColumns.map((column) => column.length));
  for (let row = 0; row < maxRows; row += 1) {
    lines.push(renderedColumns.map((column) => pad(column[row] ?? "", columnWidth)).join("  "));
  }
  return lines.join("\n");
}

function boardColumnLines(tasks: DecryptedUserTask[], limit: number): string[] {
  if (tasks.length === 0) return ["No tasks here."];
  const visible = tasks.slice(0, limit).flatMap((task) => [
    `[${task.shortId}] ${task.title}`,
    ` ${assigneeLabel(task)} ${task.queueState === "none" ? "" : task.queueState}`.trimEnd(),
  ]);
  if (tasks.length > limit) visible.push(`... ${tasks.length - limit} more`);
  return visible;
}

function compareTasks(a: DecryptedUserTask, b: DecryptedUserTask): number {
  return a.position - b.position || a.title.localeCompare(b.title);
}

function columnTitle(status: UserTaskStatus): string {
  if (status === "in_progress") return "In progress";
  return status.slice(0, 1).toUpperCase() + status.slice(1).replace("_", " ");
}

function assigneeLabel(task: DecryptedUserTask): string {
  return task.assigneeType === "ai" ? "OpenMates" : (task.assigneeHash ?? "user");
}

async function taskKeyFromRecord(record: UserTaskRecord, masterKey: Uint8Array): Promise<Uint8Array> {
  if (!record.encrypted_task_key) throw new Error(`Task ${record.task_id} is missing encrypted task key.`);
  const taskKey = await decryptBytesWithAesGcm(record.encrypted_task_key, masterKey);
  if (!taskKey) throw new Error(`Failed to decrypt task key for ${record.task_id}.`);
  return taskKey;
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithAesGcmCombined(value, key)) ?? "";
}

function parseStringArray(value: string): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function deriveShortId(record: UserTaskRecord): string {
  const prefix = record.short_id_prefix || DEFAULT_STANDALONE_PREFIX;
  const source = record.task_id || `${record.created_at ?? ""}-${record.position ?? ""}`;
  const digest = createHash("sha256").update(source).digest("hex").slice(0, 4).toUpperCase();
  return `${prefix}-${parseInt(digest, 16) % 10_000}`;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function randomUUIDCompat(): string {
  return randomUUID();
}

function pad(value: string, length: number): string {
  return truncate(value, length).padEnd(length);
}

function truncate(value: string, length: number): string {
  return value.length <= length ? value : `${value.slice(0, Math.max(0, length - 3))}...`;
}
