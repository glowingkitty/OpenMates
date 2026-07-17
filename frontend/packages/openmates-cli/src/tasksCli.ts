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

import { createHash, createHmac, hkdfSync, randomBytes, randomUUID } from "node:crypto";

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
const PRIORITY_LEVELS = ["none", "low", "medium", "high", "urgent"] as const;
const LABEL_INDEX_INFO = "openmates-task-label-index-v1";

export type TaskPriorityLevel = typeof PRIORITY_LEVELS[number];

export interface DecryptedUserTask {
  taskId: string;
  source?: string;
  shortId: string;
  title: string;
  description: string;
  labels: string[];
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
  priorityLevel: TaskPriorityLevel;
  position: number;
  queueState: string;
  blockedReasonCode: string | null;
  aiExecutionState: string | null;
  readOnly?: boolean;
  version: number;
  encrypted: UserTaskRecord;
}

export interface TaskCreateOptions {
  title: string;
  description?: string;
  labels?: string[];
  tags?: string[];
  status?: UserTaskStatus;
  assign?: string;
  chatId?: string | null;
  projectIds?: string[];
  planId?: string | null;
  dueAt?: number | null;
  priority?: TaskPriorityLevel | number | null;
}

export interface TaskUpdateOptions {
  title?: string;
  description?: string;
  labels?: string[];
  tags?: string[];
  addLabels?: string[];
  addTags?: string[];
  removeLabels?: string[];
  removeTags?: string[];
  status?: UserTaskStatus;
  assign?: string;
  chatId?: string | null;
  projectIds?: string[];
  planId?: string | null;
  priority?: TaskPriorityLevel | number | null;
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

export function normalizeLabels(labels: string[] | undefined): string[] {
  const output: string[] = [];
  const seen = new Set<string>();
  for (const label of labels ?? []) {
    const normalized = label.trim().toLowerCase().replace(/\s+/g, " ");
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    output.push(normalized);
  }
  return output;
}

export function labelHashes(masterKey: Uint8Array, labels: string[]): string[] {
  const indexKey = Buffer.from(hkdfSync("sha256", Buffer.from(masterKey), Buffer.alloc(0), LABEL_INDEX_INFO, 32));
  return normalizeLabels(labels).map((label) => createHmac("sha256", indexKey).update(label).digest("hex"));
}

export function normalizeTaskPriority(value: TaskPriorityLevel | number | string | null | undefined): number | undefined {
  if (value === undefined) return undefined;
  if (value === null) return 0;
  if (typeof value === "number") {
    if (!Number.isInteger(value) || value < 0 || value > 4) throw new Error(`Invalid task priority '${value}'.`);
    return value;
  }
  const normalized = value.trim().toLowerCase();
  const index = PRIORITY_LEVELS.indexOf(normalized as TaskPriorityLevel);
  if (index < 0) throw new Error(`Unknown task priority '${value}'. Expected one of: ${PRIORITY_LEVELS.join(", ")}`);
  return index;
}

export function taskPriorityLevel(priority: number | null | undefined): TaskPriorityLevel {
  return PRIORITY_LEVELS[Math.max(0, Math.min(4, Math.trunc(priority ?? 0)))] ?? "none";
}

export async function buildCreateUserTaskInput(masterKey: Uint8Array, input: TaskCreateOptions): Promise<UserTaskCreateInput> {
  const taskKey = randomBytes(32);
  const encryptedTaskKey = await encryptBytesWithAesGcm(taskKey, masterKey);
  const timestamp = nowSeconds();
  const assignee = parseAssignee(input.assign);
  const linkedProjectIds = input.projectIds ?? [];
  const labels = normalizeLabels(input.labels ?? input.tags ?? []);
  const status = input.status ?? (assignee.assigneeType === "ai" && !input.dueAt ? "in_progress" : "todo");
  return {
    task_id: randomUUIDCompat(),
    short_id: undefined,
    version: 1,
    encrypted_task_key: encryptedTaskKey,
    encrypted_title: await encryptWithAesGcmCombined(input.title, taskKey),
    encrypted_description: await encryptWithAesGcmCombined(input.description ?? "", taskKey),
    encrypted_labels: await encryptWithAesGcmCombined(JSON.stringify(labels), taskKey),
    encrypted_tags: await encryptWithAesGcmCombined(JSON.stringify(labels), taskKey),
    label_hashes: labelHashes(masterKey, labels),
    encrypted_linked_project_ids: await encryptWithAesGcmCombined(JSON.stringify(linkedProjectIds), taskKey),
    status,
    assignee_type: assignee.assigneeType,
    assignee_hash: assignee.assigneeHash,
    primary_chat_id: input.chatId ?? null,
    linked_project_ids: linkedProjectIds,
    plan_id: input.planId ?? null,
    due_at: input.dueAt ?? null,
    priority: normalizeTaskPriority(input.priority) ?? 0,
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
  const priority = normalizeTaskPriority(input.priority);
  if (priority !== undefined) patch.priority = priority;
  const replaceLabels = input.labels ?? input.tags;
  if (replaceLabels !== undefined || input.addLabels !== undefined || input.addTags !== undefined || input.removeLabels !== undefined || input.removeTags !== undefined) {
    const remove = new Set(normalizeLabels([...(input.removeLabels ?? []), ...(input.removeTags ?? [])]));
    const base = replaceLabels !== undefined ? normalizeLabels(replaceLabels) : task.labels;
    const labels = normalizeLabels([...base.filter((label) => !remove.has(label)), ...(input.addLabels ?? []), ...(input.addTags ?? [])]);
    patch.encrypted_labels = await encryptWithAesGcmCombined(JSON.stringify(labels), taskKey);
    patch.encrypted_tags = await encryptWithAesGcmCombined(JSON.stringify(labels), taskKey);
    patch.label_hashes = labelHashes(masterKey, labels);
  }
  return patch;
}

export async function decryptUserTask(record: UserTaskRecord, masterKey: Uint8Array): Promise<DecryptedUserTask> {
  if (record.source === "workflow_run") return workflowProjectionToTask(record);
  if (typeof record.version !== "number") throw new Error(`Task ${record.task_id} is missing version.`);
  const taskKey = await taskKeyFromRecord(record, masterKey);
  const labels = parseStringArray(await decryptOptional(record.encrypted_labels || record.encrypted_tags, taskKey));
  const linkedProjectIds = parseStringArray(await decryptOptional(record.encrypted_linked_project_ids, taskKey));
  return {
    taskId: record.task_id,
    shortId: record.short_id || deriveShortId(record),
    title: await decryptOptional(record.encrypted_title, taskKey) || "(untitled task)",
    description: await decryptOptional(record.encrypted_description, taskKey),
    labels,
    tags: labels,
    latestInstruction: await decryptOptional(record.encrypted_latest_instruction, taskKey),
    status: record.status,
    assigneeType: record.assignee_type,
    assigneeHash: record.assignee_hash ?? null,
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: linkedProjectIds.length > 0 ? linkedProjectIds : (record.linked_project_ids ?? []),
    planId: record.plan_id ?? null,
    dueAt: record.due_at ?? null,
    priority: record.priority ?? 0,
    priorityLevel: taskPriorityLevel(record.priority),
    position: record.position ?? 0,
    queueState: record.queue_state ?? "none",
    blockedReasonCode: record.blocked_reason_code ?? null,
    aiExecutionState: record.ai_execution_state ?? null,
    version: record.version,
    encrypted: record,
  };
}

function workflowProjectionToTask(record: UserTaskRecord): DecryptedUserTask {
  const blockedReason = record.blocked_reason_code ?? record.blocked_reason ?? null;
  return {
    taskId: record.task_id,
    source: "workflow_run",
    shortId: record.short_id || workflowProjectionShortId(record),
    title: record.title || "Workflow run",
    description: record.blocked_message ?? "",
    labels: [],
    tags: [],
    latestInstruction: "",
    status: record.status,
    assigneeType: "user",
    assigneeHash: null,
    primaryChatId: null,
    linkedProjectIds: [],
    planId: null,
    dueAt: record.due_at ?? null,
    priority: record.priority ?? 0,
    priorityLevel: taskPriorityLevel(record.priority),
    position: record.position ?? 0,
    queueState: String(record.run_status ?? "workflow"),
    blockedReasonCode: blockedReason,
    aiExecutionState: null,
    readOnly: true,
    version: typeof record.version === "number" ? record.version : 1,
    encrypted: record,
  };
}

function workflowProjectionShortId(record: UserTaskRecord): string {
  const stableId = record.workflow_run_id || record.task_id;
  return `WF-${createHash("sha256").update(stableId).digest("hex").slice(0, 6).toUpperCase()}`;
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
  const lines = ["Tasks", "ID        Status       Priority  Labels              Title"];
  for (const task of tasks) {
    lines.push(`${pad(task.shortId, 9)} ${pad(task.status, 12)} ${pad(task.priorityLevel, 9)} ${pad(task.labels.join(","), 19)} ${task.title}`);
  }
  return lines.join("\n");
}

export function renderTaskDetail(task: DecryptedUserTask): string {
  const lines = [
    `Task ${task.shortId}`,
    `Title: ${task.title}`,
    `Status: ${task.status}`,
    `Priority: ${task.priorityLevel}`,
    `Assignee: ${assigneeLabel(task)}`,
    `Queue: ${task.queueState}`,
    `Task ID: ${task.taskId}`,
  ];
  if (task.description) lines.push(`Description: ${task.description}`);
  if (task.labels.length > 0) lines.push(`Labels: ${task.labels.join(", ")}`);
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
