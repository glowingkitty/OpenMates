// frontend/packages/ui/src/services/userTaskService.ts
// Client-side Tasks V1 service. Durable task content is encrypted with a
// per-task key wrapped by the user's master key; the backend receives only
// ciphertext plus minimal metadata for filtering and scheduling.

import { getApiEndpoint } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
  unwrapEmbedKeyWithChatKey,
  wrapEmbedKeyWithChatKey,
} from "./cryptoService";
import { getMasterKey } from "./cryptoKeyStorage";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { listProjects } from "./projectService";

export type UserTaskStatus = "backlog" | "todo" | "in_progress" | "blocked" | "done";
export type UserTaskAssigneeType = "ai" | "user";
export type UserTaskKeyWrapperType = "master" | "chat" | "project" | "plan";
export type WorkflowRunProjectionKind = "last_run" | "current_run" | "next_run";
export type ExternalChatProvider = "opencode";
export type BlockedReasonCode = "needs_user_input" | "waiting_for_approval" | "missing_credentials" | "ambiguous_requirement" | "external_dependency" | "environment_unavailable" | "verification_failed" | "other";

export interface ExternalChatContext {
  provider: ExternalChatProvider;
  id: string;
  title: string;
}

export interface UserTaskKeyWrapperRecord {
  key_type: UserTaskKeyWrapperType;
  encrypted_task_key: string;
  hashed_chat_id?: string | null;
  hashed_project_id?: string | null;
  hashed_plan_id?: string | null;
  created_at: number;
  expires_at?: number | null;
}

export interface UserTaskProposal {
  title: string;
  description?: string | null;
  status?: UserTaskStatus;
  assignee_type?: UserTaskAssigneeType;
}

export interface UserTaskUpdateProposal {
  task_id: string;
  title?: string | null;
  description?: string | null;
  status?: UserTaskStatus | null;
  assignee_type?: UserTaskAssigneeType | null;
}

export interface EncryptedUserTaskRecord {
  id?: string;
  task_id: string;
  encrypted_task_key?: string | null;
  encrypted_title: string;
  encrypted_description?: string | null;
  encrypted_tags?: string | null;
  encrypted_activity_summary?: string | null;
  encrypted_latest_instruction?: string | null;
  status: UserTaskStatus;
  assignee_type: UserTaskAssigneeType;
  assignee_hash?: string | null;
  primary_chat_id?: string | null;
  external_chat_provider?: ExternalChatProvider | null;
  external_chat_lookup_hash?: string | null;
  encrypted_external_chat_id?: string | null;
  encrypted_external_chat_title?: string | null;
  linked_project_ids?: string[] | null;
  linked_project_hashes?: string[] | null;
  encrypted_linked_project_ids?: string | null;
  parent_task_id?: string | null;
  plan_id?: string | null;
  due_at?: number | null;
  priority?: number;
  position?: number;
  version?: number;
  created_at: number;
  updated_at: number;
  started_at?: number | null;
  completed_at?: number | null;
  blocked_reason_code?: string | null;
  encrypted_blocked_reason?: string | null;
  ai_execution_state?: string | null;
  key_wrappers?: UserTaskKeyWrapperRecord[];
}

export interface WorkflowRunTaskProjectionRecord {
  task_id: string;
  source: "workflow_run";
  projection_kind: WorkflowRunProjectionKind;
  workflow_id: string;
  workflow_run_id?: string | null;
  trigger_id?: string | null;
  label: "Workflow run";
  title?: string | null;
  status: "todo" | "in_progress" | "blocked" | "done";
  run_status: string;
  can_cancel: boolean;
  can_delete?: boolean;
  due_at?: number | null;
  scheduled_at?: number | null;
  blocked_message?: string | null;
  read_only: true;
  created_at: number;
  updated_at: number;
  position: number;
}

export interface UserTaskViewModel {
  task_id: string;
  title: string;
  description: string;
  tags: string[];
  latestInstruction: string;
  status: UserTaskStatus;
  assigneeType: UserTaskAssigneeType;
  primaryChatId: string | null;
  externalChat: ExternalChatContext | null;
  linkedProjectIds: string[];
  planId: string | null;
  dueAt: number | null;
  priority: number;
  position: number;
  version: number;
  createdAt: number;
  updatedAt: number;
  blockedReasonCode: BlockedReasonCode | null;
  blockedReason: string;
  aiExecutionState: string | null;
  encrypted: EncryptedUserTaskRecord;
}

export interface UserTaskDependencyViewModel {
  edgeId: string;
  targetRef: string;
  targetKind: "plan" | "task";
  targetId: string;
  targetStatus: string;
  satisfied: boolean;
}

export type UserTaskActivityKind = "comment" | "lifecycle_update" | "tombstone";
export type UserTaskActivitySourceSurface = "web" | "apple" | "cli" | "sdk_npm" | "sdk_pip" | "system";

export interface UserTaskActivityRecord {
  entry_id: string;
  task_id: string;
  kind: UserTaskActivityKind;
  actor_type: "user" | "ai" | "system";
  actor_hash?: string | null;
  actor_display_name?: string | null;
  actor_profile_image_url?: string | null;
  author_hash?: string | null;
  event_type: string;
  source_surface: UserTaskActivitySourceSurface;
  created_at: number;
  deleted_at?: number | null;
  deleted_by_hash?: string | null;
  deleted_by_display_name?: string | null;
  encrypted_entry_key?: string | null;
  encrypted_message?: string | null;
  encrypted_embed_key_material?: string | null;
  embed_refs: string[];
}

export interface UserTaskActivityEntry {
  entryId: string;
  taskId: string;
  kind: UserTaskActivityKind;
  actorType: "user" | "ai" | "system";
  actorHash: string | null;
  actorDisplayName: string | null;
  actorProfileImageUrl: string | null;
  authorHash: string | null;
  eventType: string;
  sourceSurface: UserTaskActivitySourceSurface;
  createdAt: number;
  deletedAt: number | null;
  deletedByHash: string | null;
  deletedByDisplayName: string | null;
  message?: string;
  embedKeyMaterial?: string;
  embedRefs: string[];
}

export interface CreateUserTaskActivityInput {
  message: string;
  embedRefs?: string[];
  embedKeyMaterial?: string;
  entryId?: string;
  createdAt?: number;
  teamId?: string;
}

export function canSubmitUserTaskActivity(message: string, embedStatuses: string[]): boolean {
  return message.trim().length > 0
    && !embedStatuses.some((status) => status === "uploading" || status === "transcribing" || status === "error");
}

export interface WorkflowRunTaskProjectionViewModel {
  task_id: string;
  source: "workflow_run";
  projectionKind: WorkflowRunProjectionKind;
  workflowId: string;
  workflowRunId: string | null;
  triggerId: string | null;
  title: string;
  description: string;
  tags: string[];
  latestInstruction: string;
  status: UserTaskStatus;
  assigneeType: UserTaskAssigneeType;
  primaryChatId: null;
  linkedProjectIds: string[];
  dueAt: number | null;
  priority: number;
  position: number;
  version: 0;
  canCancel: boolean;
  canDelete: boolean;
  readOnly: true;
}

export type TasksBoardItem = UserTaskViewModel | WorkflowRunTaskProjectionViewModel;

export interface CreateUserTaskInput {
  title: string;
  description?: string;
  tags?: string[];
  status?: UserTaskStatus;
  assigneeType?: UserTaskAssigneeType;
  assigneeHash?: string | null;
  primaryChatId?: string | null;
  externalChat?: ExternalChatContext;
  linkedProjectIds?: string[];
  dueAt?: number | null;
  priority?: number;
}

export interface ListUserTasksFilters {
  status?: UserTaskStatus;
  chatId?: string;
  externalChat?: ExternalChatContext;
  projectId?: string;
}

export interface ExtractUserTaskProposalsInput {
  correctedText: string;
  mode?: "create" | "update";
  contextChatId?: string | null;
  projectIds?: string[];
}

export interface ReorderUserTaskMoveInput {
  task: UserTaskViewModel;
  beforeTaskId?: string | null;
  afterTaskId?: string | null;
  status?: UserTaskStatus;
  position?: number;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(getApiEndpoint(path), {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Tasks API failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as T;
}

const EXTERNAL_CHAT_INDEX_INFO = "openmates-task-external-chat-index-v1";
const EXTERNAL_CHAT_PROVIDER: ExternalChatProvider = "opencode";

function assertExternalChatContext(context: ExternalChatContext): void {
  if (context.provider !== EXTERNAL_CHAT_PROVIDER) {
    throw new Error(`Unsupported external chat provider '${context.provider}'. Only opencode is allowed.`);
  }
  if (!context.id) throw new Error("External chat id is required.");
}

function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function externalChatLookupHash(context: ExternalChatContext): Promise<string> {
  assertExternalChatContext(context);
  const masterKey = await getMasterKey();
  if (!masterKey) throw new Error("Could not access master key for external chat lookup.");
  const rawMasterKey = new Uint8Array(await crypto.subtle.exportKey("raw", masterKey));
  try {
    const hkdfKey = await crypto.subtle.importKey("raw", rawMasterKey, "HKDF", false, ["deriveBits"]);
    const indexKey = await crypto.subtle.deriveBits({
      name: "HKDF",
      hash: "SHA-256",
      salt: new Uint8Array(),
      info: new TextEncoder().encode(EXTERNAL_CHAT_INDEX_INFO),
    }, hkdfKey, 256);
    const hmacKey = await crypto.subtle.importKey("raw", indexKey, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const signature = await crypto.subtle.sign("HMAC", hmacKey, new TextEncoder().encode(`${context.provider}\u0000${context.id}`));
    return hex(new Uint8Array(signature));
  } finally {
    rawMasterKey.fill(0);
  }
}

async function buildQuery(filters: ListUserTasksFilters): Promise<string> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.chatId) params.set("chat_id", filters.chatId);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.externalChat) {
    params.set("external_chat_provider", filters.externalChat.provider);
    params.set("external_chat_lookup_hash", await externalChatLookupHash(filters.externalChat));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key)) ?? "";
}

async function decryptStringArray(value: string | null | undefined, key: Uint8Array): Promise<string[]> {
  const text = await decryptOptional(value, key);
  if (!text) return [];
  const parsed = JSON.parse(text) as unknown;
  return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
}

async function decryptTask(record: EncryptedUserTaskRecord): Promise<UserTaskViewModel | null> {
  if (!record.encrypted_task_key) return null;
  const taskKey = await decryptChatKeyWithMasterKey(record.encrypted_task_key);
  if (!taskKey) return null;
  const tagsText = await decryptOptional(record.encrypted_tags, taskKey);
  let tags: string[] = [];
  try {
    tags = tagsText ? JSON.parse(tagsText) : [];
  } catch {
    tags = [];
  }
  if (typeof record.version !== "number") throw new Error(`Task ${record.task_id} is missing version.`);
  return {
    task_id: record.task_id,
    title: await decryptOptional(record.encrypted_title, taskKey),
    description: await decryptOptional(record.encrypted_description, taskKey),
    latestInstruction: await decryptOptional(record.encrypted_latest_instruction, taskKey),
    tags,
    status: record.status,
    assigneeType: record.assignee_type,
    primaryChatId: record.primary_chat_id ?? null,
    externalChat: record.external_chat_provider && record.encrypted_external_chat_id ? {
      provider: record.external_chat_provider,
      id: await decryptOptional(record.encrypted_external_chat_id, taskKey),
      title: await decryptOptional(record.encrypted_external_chat_title, taskKey),
    } : null,
    linkedProjectIds: await decryptStringArray(record.encrypted_linked_project_ids, taskKey),
    planId: record.plan_id ?? null,
    dueAt: record.due_at ?? null,
    priority: record.priority ?? 0,
    position: record.position ?? 0,
    version: record.version,
    createdAt: record.created_at,
    updatedAt: record.updated_at,
    blockedReasonCode: (record.blocked_reason_code as BlockedReasonCode | null | undefined) ?? null,
    blockedReason: await decryptOptional(record.encrypted_blocked_reason, taskKey),
    aiExecutionState: record.ai_execution_state ?? null,
    encrypted: record,
  };
}

function isWorkflowRunTaskProjection(record: EncryptedUserTaskRecord | WorkflowRunTaskProjectionRecord): record is WorkflowRunTaskProjectionRecord {
  return "source" in record && record.source === "workflow_run";
}

function workflowRunTaskProjection(record: WorkflowRunTaskProjectionRecord): WorkflowRunTaskProjectionViewModel {
  return {
    task_id: record.task_id,
    source: record.source,
    projectionKind: record.projection_kind,
    workflowId: record.workflow_id,
    workflowRunId: record.workflow_run_id ?? null,
    triggerId: record.trigger_id ?? null,
    title: record.title || record.label,
    description: record.blocked_message ?? "",
    tags: [],
    latestInstruction: "",
    status: record.status,
    assigneeType: "ai",
    primaryChatId: null,
    linkedProjectIds: [],
    dueAt: record.due_at ?? null,
    priority: 0,
    position: record.position,
    version: 0,
    canCancel: record.can_cancel,
    canDelete: Boolean(record.can_delete),
    readOnly: true,
  };
}

async function buildTaskKeyWrappers(
  taskKey: Uint8Array,
  encryptedTaskKey: string,
  timestamp: number,
  primaryChatId: string | null,
  linkedProjectIds: string[],
): Promise<UserTaskKeyWrapperRecord[]> {
  const wrappers: UserTaskKeyWrapperRecord[] = [
    {
      key_type: "master",
      encrypted_task_key: encryptedTaskKey,
      created_at: timestamp,
    },
  ];
  if (primaryChatId) {
    const chatKey = await chatKeyManager.getKey(primaryChatId);
    if (!chatKey) throw new Error(`Could not find chat key for primary chat ${primaryChatId}`);
    wrappers.push({
      key_type: "chat",
      hashed_chat_id: await computeSHA256(primaryChatId),
      encrypted_task_key: await wrapEmbedKeyWithChatKey(taskKey, chatKey),
      created_at: timestamp,
    });
  }
  if (linkedProjectIds.length === 0) return wrappers;

  const projects = await listProjects();
  for (const projectId of linkedProjectIds) {
    const project = projects.find((candidate) => candidate.project_id === projectId);
    if (!project) throw new Error(`Could not find project key for linked project ${projectId}`);
    wrappers.push({
      key_type: "project",
      hashed_project_id: await computeSHA256(projectId),
      encrypted_task_key: await wrapEmbedKeyWithChatKey(taskKey, project.projectKey),
      created_at: timestamp,
    });
  }
  return wrappers;
}

export async function listTaskBoardItems(filters: ListUserTasksFilters = {}): Promise<TasksBoardItem[]> {
  const data = await requestJson<{ tasks: Array<EncryptedUserTaskRecord | WorkflowRunTaskProjectionRecord> }>(`/v1/user-tasks${await buildQuery(filters)}`);
  const decrypted = await Promise.all(data.tasks.map(async (task) => {
    if (isWorkflowRunTaskProjection(task)) return workflowRunTaskProjection(task);
    return decryptTask(task);
  }));
  return decrypted.filter((task): task is TasksBoardItem => task !== null);
}

export async function listUserTasks(filters: ListUserTasksFilters = {}): Promise<UserTaskViewModel[]> {
  return (await listTaskBoardItems(filters)).filter((task): task is UserTaskViewModel => !isWorkflowRunTaskProjectionViewModel(task));
}

function taskActivityPath(taskId: string, teamId?: string, cursor?: string): string {
  const params = new URLSearchParams({ limit: "200" });
  if (teamId) params.set("team_id", teamId);
  if (cursor) params.set("cursor", cursor);
  return `/v1/user-tasks/${encodeURIComponent(taskId)}/activity?${params.toString()}`;
}

async function taskKeyForActivity(task: UserTaskViewModel): Promise<Uint8Array> {
  const taskKey = await decryptChatKeyWithMasterKey(task.encrypted.encrypted_task_key ?? "");
  if (!taskKey) throw new Error(`Could not decrypt Task Activity key for ${task.task_id}`);
  return taskKey;
}

async function decryptTaskActivityEntry(task: UserTaskViewModel, record: UserTaskActivityRecord): Promise<UserTaskActivityEntry> {
  const entry: UserTaskActivityEntry = {
    entryId: record.entry_id,
    taskId: record.task_id,
    kind: record.kind,
    actorType: record.actor_type,
    actorHash: record.actor_hash ?? null,
    actorDisplayName: record.actor_display_name ?? null,
    actorProfileImageUrl: record.actor_profile_image_url ?? null,
    authorHash: record.author_hash ?? record.actor_hash ?? null,
    eventType: record.event_type,
    sourceSurface: record.source_surface,
    createdAt: record.created_at,
    deletedAt: record.deleted_at ?? null,
    deletedByHash: record.deleted_by_hash ?? null,
    deletedByDisplayName: record.deleted_by_display_name ?? null,
    embedRefs: record.kind === "tombstone" ? [] : record.embed_refs,
  };
  if (record.kind === "tombstone" || record.kind !== "comment") return entry;
  if (!record.encrypted_entry_key || !record.encrypted_message) {
    throw new Error(`Task Activity entry ${record.entry_id} is missing encrypted content`);
  }
  const taskKey = await taskKeyForActivity(task);
  const entryKey = await unwrapEmbedKeyWithChatKey(record.encrypted_entry_key, taskKey);
  if (!entryKey) throw new Error(`Could not decrypt Task Activity entry key ${record.entry_id}`);
  const message = await decryptWithEmbedKey(record.encrypted_message, entryKey);
  if (message === null) throw new Error(`Could not decrypt Task Activity entry ${record.entry_id}`);
  const embedKeyMaterial = record.encrypted_embed_key_material
    ? await decryptWithEmbedKey(record.encrypted_embed_key_material, taskKey)
    : null;
  if (record.encrypted_embed_key_material && embedKeyMaterial === null) {
    throw new Error(`Could not decrypt Task Activity embed keys ${record.entry_id}`);
  }
  return { ...entry, message, ...(embedKeyMaterial !== null ? { embedKeyMaterial } : {}) };
}

export async function listUserTaskActivity(task: UserTaskViewModel, teamId?: string): Promise<UserTaskActivityEntry[]> {
  const entries: UserTaskActivityEntry[] = [];
  let cursor: string | undefined;
  do {
    const page = await requestJson<{ entries: UserTaskActivityRecord[]; next_cursor: string | null }>(taskActivityPath(task.task_id, teamId, cursor));
    entries.push(...await Promise.all(page.entries.map((record) => decryptTaskActivityEntry(task, record))));
    cursor = page.next_cursor ?? undefined;
  } while (cursor);
  return entries;
}

export async function createUserTaskActivity(task: UserTaskViewModel, input: CreateUserTaskActivityInput): Promise<UserTaskActivityEntry> {
  const taskKey = await taskKeyForActivity(task);
  const entryKey = generateEmbedKey();
  const body = {
    entry_id: input.entryId ?? crypto.randomUUID(),
    encrypted_entry_key: await wrapEmbedKeyWithChatKey(entryKey, taskKey),
    encrypted_message: await encryptWithEmbedKey(input.message, entryKey),
    ...(input.embedKeyMaterial ? { encrypted_embed_key_material: await encryptWithEmbedKey(input.embedKeyMaterial, taskKey) } : {}),
    embed_refs: input.embedRefs ?? [],
    created_at: input.createdAt ?? nowSeconds(),
  };
  const data = await requestJson<{ entry: UserTaskActivityRecord }>(taskActivityPath(task.task_id, input.teamId), {
    method: "POST",
    headers: { "X-OpenMates-Client": "web" },
    body: JSON.stringify(body),
  });
  return decryptTaskActivityEntry(task, data.entry);
}

export async function deleteUserTaskActivity(task: UserTaskViewModel, entryId: string, teamId?: string): Promise<UserTaskActivityEntry> {
  const params = new URLSearchParams();
  if (teamId) params.set("team_id", teamId);
  const query = params.toString();
  const data = await requestJson<{ entry: UserTaskActivityRecord }>(
    `/v1/user-tasks/${encodeURIComponent(task.task_id)}/activity/${encodeURIComponent(entryId)}${query ? `?${query}` : ""}`,
    { method: "DELETE", headers: { "X-OpenMates-Client": "web" } },
  );
  return decryptTaskActivityEntry(task, data.entry);
}

export function isWorkflowRunTaskProjectionViewModel(task: TasksBoardItem): task is WorkflowRunTaskProjectionViewModel {
  return "source" in task && task.source === "workflow_run";
}

export async function cancelWorkflowRunTaskProjection(task: WorkflowRunTaskProjectionViewModel): Promise<void> {
  if (!task.workflowRunId) throw new Error("Workflow run projection has no run id to cancel");
  await requestJson(`/v1/workflows/${encodeURIComponent(task.workflowId)}/runs/${encodeURIComponent(task.workflowRunId)}/cancel`, {
    method: "POST",
  });
}

export async function createUserTask(input: CreateUserTaskInput): Promise<UserTaskViewModel> {
  if (input.primaryChatId && input.externalChat) throw new Error("A task cannot use both native chat and external chat context.");
  if (input.externalChat) assertExternalChatContext(input.externalChat);
  const taskKey = generateEmbedKey();
  const encryptedTaskKey = await encryptChatKeyWithMasterKey(taskKey);
  if (!encryptedTaskKey) throw new Error("Could not wrap task key with master key");
  const timestamp = nowSeconds();
  const linkedProjectIds = input.linkedProjectIds ?? [];
  const primaryChatId = input.primaryChatId ?? null;
  const body: EncryptedUserTaskRecord = {
    task_id: crypto.randomUUID(),
    encrypted_task_key: encryptedTaskKey,
    encrypted_title: await encryptWithEmbedKey(input.title, taskKey),
    encrypted_description: await encryptWithEmbedKey(input.description ?? "", taskKey),
    encrypted_tags: await encryptWithEmbedKey(JSON.stringify(input.tags ?? []), taskKey),
    encrypted_linked_project_ids: await encryptWithEmbedKey(JSON.stringify(linkedProjectIds), taskKey),
    status: input.status ?? (input.assigneeType === "ai" && !input.dueAt ? "in_progress" : "todo"),
    assignee_type: input.assigneeType ?? "user",
    assignee_hash: input.assigneeHash ?? null,
    primary_chat_id: primaryChatId,
    ...(input.externalChat ? {
      external_chat_provider: input.externalChat.provider,
      external_chat_lookup_hash: await externalChatLookupHash(input.externalChat),
      encrypted_external_chat_id: await encryptWithEmbedKey(input.externalChat.id, taskKey),
      encrypted_external_chat_title: await encryptWithEmbedKey(input.externalChat.title, taskKey),
    } : {}),
    linked_project_ids: linkedProjectIds,
    due_at: input.dueAt ?? null,
    priority: input.priority ?? 0,
    position: timestamp,
    version: 1,
    created_at: timestamp,
    updated_at: timestamp,
    key_wrappers: await buildTaskKeyWrappers(taskKey, encryptedTaskKey, timestamp, primaryChatId, linkedProjectIds),
  };
  const data = await requestJson<{ task: EncryptedUserTaskRecord }>("/v1/user-tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptTask(data.task);
  if (!decrypted) throw new Error("Created task could not be decrypted");
  return decrypted;
}

export async function listUserTaskKeyWrappers(taskId: string): Promise<UserTaskKeyWrapperRecord[]> {
  const data = await requestJson<{ key_wrappers: UserTaskKeyWrapperRecord[] }>(`/v1/user-tasks/${taskId}/key-wrappers`);
  return data.key_wrappers;
}

export async function listUserTaskDependencies(taskId: string): Promise<UserTaskDependencyViewModel[]> {
  const data = await requestJson<{
    dependencies: Array<{
      edge_id?: string | null;
      target_ref: string;
      target_kind: "plan" | "task";
      target_id: string;
      target_status?: string | null;
      satisfied: boolean;
    }>;
  }>(`/v1/user-tasks/${encodeURIComponent(taskId)}/dependencies`);
  return data.dependencies.map((dependency) => ({
    edgeId: dependency.edge_id ?? dependency.target_ref,
    targetRef: dependency.target_ref,
    targetKind: dependency.target_kind,
    targetId: dependency.target_id,
    targetStatus: dependency.target_status ?? "unknown",
    satisfied: dependency.satisfied,
  }));
}

export async function addUserTaskKeyWrappers(taskId: string, version: number, keyWrappers: UserTaskKeyWrapperRecord[]): Promise<UserTaskKeyWrapperRecord[]> {
  const data = await requestJson<{ key_wrappers: UserTaskKeyWrapperRecord[] }>(`/v1/user-tasks/${taskId}/key-wrappers`, {
    method: "POST",
    body: JSON.stringify({ version, key_wrappers: keyWrappers }),
  });
  return data.key_wrappers;
}

export async function extractUserTaskProposals(input: ExtractUserTaskProposalsInput): Promise<UserTaskProposal[]> {
  const data = await requestJson<{ proposed_tasks: UserTaskProposal[] }>("/v1/user-tasks/extract", {
    method: "POST",
    body: JSON.stringify({
      corrected_text: input.correctedText,
      mode: input.mode ?? "create",
      context_chat_id: input.contextChatId ?? null,
      project_ids: input.projectIds ?? [],
    }),
  });
  return data.proposed_tasks;
}

export async function updateUserTask(task: UserTaskViewModel, patch: Partial<CreateUserTaskInput> & { status?: UserTaskStatus }): Promise<UserTaskViewModel> {
  if (patch.primaryChatId && patch.externalChat) throw new Error("A task cannot use both native chat and external chat context.");
  if (patch.externalChat) assertExternalChatContext(patch.externalChat);
  const taskKey = await decryptChatKeyWithMasterKey(task.encrypted.encrypted_task_key ?? "");
  if (!taskKey) throw new Error("Could not decrypt task key");
  const encryptedTaskKey = task.encrypted.encrypted_task_key;
  if (!encryptedTaskKey) throw new Error("Missing encrypted task key");
  const body: Record<string, unknown> = { version: task.version, updated_at: nowSeconds() };
  if (patch.title !== undefined) body.encrypted_title = await encryptWithEmbedKey(patch.title, taskKey);
  if (patch.description !== undefined) body.encrypted_description = await encryptWithEmbedKey(patch.description, taskKey);
  if (patch.tags !== undefined) body.encrypted_tags = await encryptWithEmbedKey(JSON.stringify(patch.tags), taskKey);
  if (patch.linkedProjectIds !== undefined) body.encrypted_linked_project_ids = await encryptWithEmbedKey(JSON.stringify(patch.linkedProjectIds), taskKey);
  if (patch.status !== undefined) body.status = patch.status;
  if (patch.assigneeType !== undefined) body.assignee_type = patch.assigneeType;
  if (patch.assigneeHash !== undefined) body.assignee_hash = patch.assigneeHash;
  if (patch.primaryChatId !== undefined) {
    body.primary_chat_id = patch.primaryChatId;
    body.external_chat_provider = null;
    body.external_chat_lookup_hash = null;
    body.encrypted_external_chat_id = null;
    body.encrypted_external_chat_title = null;
  }
  if (patch.externalChat) {
    body.primary_chat_id = null;
    body.external_chat_provider = patch.externalChat.provider;
    body.external_chat_lookup_hash = await externalChatLookupHash(patch.externalChat);
    body.encrypted_external_chat_id = await encryptWithEmbedKey(patch.externalChat.id, taskKey);
    body.encrypted_external_chat_title = await encryptWithEmbedKey(patch.externalChat.title, taskKey);
  }
  if (patch.linkedProjectIds !== undefined) body.linked_project_ids = patch.linkedProjectIds;
  if (patch.linkedProjectIds !== undefined || patch.primaryChatId !== undefined || patch.externalChat !== undefined) {
    const updatedPrimaryChatId = patch.externalChat ? null : (patch.primaryChatId !== undefined ? patch.primaryChatId : task.primaryChatId);
    const updatedLinkedProjectIds = patch.linkedProjectIds !== undefined ? patch.linkedProjectIds : task.linkedProjectIds;
    body.key_wrappers = await buildTaskKeyWrappers(taskKey, encryptedTaskKey, nowSeconds(), updatedPrimaryChatId ?? null, updatedLinkedProjectIds);
  }
  if (patch.dueAt !== undefined) body.due_at = patch.dueAt;
  if (patch.priority !== undefined) body.priority = patch.priority;
  const data = await requestJson<{ task: EncryptedUserTaskRecord }>(`/v1/user-tasks/${task.task_id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptTask(data.task);
  if (!decrypted) throw new Error("Updated task could not be decrypted");
  return decrypted;
}

async function decryptTaskActionResponse(data: { task: EncryptedUserTaskRecord }): Promise<UserTaskViewModel> {
  const decrypted = await decryptTask(data.task);
  if (!decrypted) throw new Error("Task action response could not be decrypted");
  return decrypted;
}

export async function completeUserTask(task: UserTaskViewModel): Promise<UserTaskViewModel> {
  return decryptTaskActionResponse(await requestJson<{ task: EncryptedUserTaskRecord }>(`/v1/user-tasks/${task.task_id}/complete`, {
    method: "POST",
    body: JSON.stringify({ version: task.version }),
  }));
}

export async function blockUserTask(
  task: UserTaskViewModel,
  blockedReasonCode: BlockedReasonCode = "needs_user_input",
  blockedReason = "",
): Promise<UserTaskViewModel> {
  const taskKey = await decryptChatKeyWithMasterKey(task.encrypted.encrypted_task_key ?? "");
  if (!taskKey) throw new Error("Could not decrypt task key");
  return decryptTaskActionResponse(await requestJson<{ task: EncryptedUserTaskRecord }>(`/v1/user-tasks/${task.task_id}/block`, {
    method: "POST",
    body: JSON.stringify({
      version: task.version,
      blocked_reason_code: blockedReasonCode,
      ...(blockedReason ? { encrypted_blocked_reason: await encryptWithEmbedKey(blockedReason, taskKey) } : {}),
    }),
  }));
}

export async function unblockUserTask(task: UserTaskViewModel): Promise<UserTaskViewModel> {
  return decryptTaskActionResponse(await requestJson<{ task: EncryptedUserTaskRecord }>(`/v1/user-tasks/${task.task_id}/unblock`, {
    method: "POST",
    body: JSON.stringify({ version: task.version }),
  }));
}

export async function skipUserTask(task: UserTaskViewModel): Promise<UserTaskViewModel> {
  return decryptTaskActionResponse(await requestJson<{ task: EncryptedUserTaskRecord }>(`/v1/user-tasks/${task.task_id}/skip`, {
    method: "POST",
    body: JSON.stringify({ version: task.version }),
  }));
}

export async function reorderUserTasks(moves: ReorderUserTaskMoveInput[]): Promise<UserTaskViewModel[]> {
  const data = await requestJson<{ tasks: EncryptedUserTaskRecord[] }>("/v1/user-tasks/reorder", {
    method: "POST",
    body: JSON.stringify({
      moves: moves.map((move) => ({
        task_id: move.task.task_id,
        before_task_id: move.beforeTaskId ?? undefined,
        after_task_id: move.afterTaskId ?? undefined,
        status: move.status,
        position: move.position,
        version: move.task.version,
      })),
    }),
  });
  const decrypted = await Promise.all(data.tasks.map((task) => decryptTask(task)));
  return decrypted.filter((task): task is UserTaskViewModel => task !== null);
}

export async function deleteUserTask(task: UserTaskViewModel | WorkflowRunTaskProjectionViewModel): Promise<void> {
  const params = new URLSearchParams({ version: String(task.version) });
  await requestJson(`/v1/user-tasks/${task.task_id}?${params.toString()}`, {
    method: "DELETE",
  });
}

export async function startUserTaskWithAI(task: UserTaskViewModel): Promise<UserTaskViewModel> {
  const body: Record<string, unknown> = {
    version: task.version,
    updated_at: nowSeconds(),
    linked_project_ids: task.linkedProjectIds,
  };
  if (task.primaryChatId) {
    body.primary_chat_id = task.primaryChatId;
    body.plaintext_title = task.title;
    body.plaintext_description = task.description;
    body.plaintext_latest_instruction = task.latestInstruction;
  }
  if (task.linkedProjectIds.length > 0) {
    body.plaintext_project_context = `Linked projects: ${task.linkedProjectIds.join(", ")}`;
  }
  const data = await requestJson<{ task: EncryptedUserTaskRecord }>(`/v1/user-tasks/${task.task_id}/start-ai`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptTask(data.task);
  if (!decrypted) throw new Error("Started task could not be decrypted");
  return decrypted;
}
