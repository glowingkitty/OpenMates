// frontend/packages/ui/src/services/userTaskService.ts
// Client-side Tasks V1 service. Durable task content is encrypted with a
// per-task key wrapped by the user's master key; the backend receives only
// ciphertext plus minimal metadata for filtering and scheduling.

import { getApiEndpoint } from "../config/api";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
} from "./cryptoService";

export type UserTaskStatus = "backlog" | "todo" | "in_progress" | "blocked" | "done";
export type UserTaskAssigneeType = "ai" | "user";

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
  linked_project_ids?: string[] | null;
  parent_task_id?: string | null;
  due_at?: number | null;
  priority?: number;
  position?: number;
  version?: number;
  created_at: number;
  updated_at: number;
  started_at?: number | null;
  completed_at?: number | null;
  blocked_reason_code?: string | null;
  ai_execution_state?: string | null;
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
  linkedProjectIds: string[];
  dueAt: number | null;
  priority: number;
  position: number;
  version: number;
  encrypted: EncryptedUserTaskRecord;
}

export interface CreateUserTaskInput {
  title: string;
  description?: string;
  tags?: string[];
  status?: UserTaskStatus;
  assigneeType?: UserTaskAssigneeType;
  assigneeHash?: string | null;
  primaryChatId?: string | null;
  linkedProjectIds?: string[];
  dueAt?: number | null;
  priority?: number;
}

export interface ListUserTasksFilters {
  status?: UserTaskStatus;
  chatId?: string;
  projectId?: string;
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

function buildQuery(filters: ListUserTasksFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.chatId) params.set("chat_id", filters.chatId);
  if (filters.projectId) params.set("project_id", filters.projectId);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key)) ?? "";
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
  return {
    task_id: record.task_id,
    title: await decryptOptional(record.encrypted_title, taskKey),
    description: await decryptOptional(record.encrypted_description, taskKey),
    latestInstruction: await decryptOptional(record.encrypted_latest_instruction, taskKey),
    tags,
    status: record.status,
    assigneeType: record.assignee_type,
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: record.linked_project_ids ?? [],
    dueAt: record.due_at ?? null,
    priority: record.priority ?? 0,
    position: record.position ?? 0,
    version: record.version ?? 1,
    encrypted: record,
  };
}

export async function listUserTasks(filters: ListUserTasksFilters = {}): Promise<UserTaskViewModel[]> {
  const data = await requestJson<{ tasks: EncryptedUserTaskRecord[] }>(`/v1/user-tasks${buildQuery(filters)}`);
  const decrypted = await Promise.all(data.tasks.map(decryptTask));
  return decrypted.filter((task): task is UserTaskViewModel => task !== null);
}

export async function createUserTask(input: CreateUserTaskInput): Promise<UserTaskViewModel> {
  const taskKey = generateEmbedKey();
  const encryptedTaskKey = await encryptChatKeyWithMasterKey(taskKey);
  if (!encryptedTaskKey) throw new Error("Could not wrap task key with master key");
  const timestamp = nowSeconds();
  const body: EncryptedUserTaskRecord = {
    task_id: crypto.randomUUID(),
    encrypted_task_key: encryptedTaskKey,
    encrypted_title: await encryptWithEmbedKey(input.title, taskKey),
    encrypted_description: await encryptWithEmbedKey(input.description ?? "", taskKey),
    encrypted_tags: await encryptWithEmbedKey(JSON.stringify(input.tags ?? []), taskKey),
    status: input.status ?? (input.assigneeType === "ai" && !input.dueAt ? "in_progress" : "todo"),
    assignee_type: input.assigneeType ?? "user",
    assignee_hash: input.assigneeHash ?? null,
    primary_chat_id: input.primaryChatId ?? null,
    linked_project_ids: input.linkedProjectIds ?? [],
    due_at: input.dueAt ?? null,
    priority: input.priority ?? 0,
    position: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
  };
  const data = await requestJson<{ task: EncryptedUserTaskRecord }>("/v1/user-tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptTask(data.task);
  if (!decrypted) throw new Error("Created task could not be decrypted");
  return decrypted;
}

export async function updateUserTask(task: UserTaskViewModel, patch: Partial<CreateUserTaskInput> & { status?: UserTaskStatus }): Promise<UserTaskViewModel> {
  const taskKey = await decryptChatKeyWithMasterKey(task.encrypted.encrypted_task_key ?? "");
  if (!taskKey) throw new Error("Could not decrypt task key");
  const body: Record<string, unknown> = { version: task.version, updated_at: nowSeconds() };
  if (patch.title !== undefined) body.encrypted_title = await encryptWithEmbedKey(patch.title, taskKey);
  if (patch.description !== undefined) body.encrypted_description = await encryptWithEmbedKey(patch.description, taskKey);
  if (patch.tags !== undefined) body.encrypted_tags = await encryptWithEmbedKey(JSON.stringify(patch.tags), taskKey);
  if (patch.status !== undefined) body.status = patch.status;
  if (patch.assigneeType !== undefined) body.assignee_type = patch.assigneeType;
  if (patch.assigneeHash !== undefined) body.assignee_hash = patch.assigneeHash;
  if (patch.primaryChatId !== undefined) body.primary_chat_id = patch.primaryChatId;
  if (patch.linkedProjectIds !== undefined) body.linked_project_ids = patch.linkedProjectIds;
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
  const data = await requestJson<{ task: EncryptedUserTaskRecord }>(`/v1/user-tasks/${task.task_id}/start-ai`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptTask(data.task);
  if (!decrypted) throw new Error("Started task could not be decrypted");
  return decrypted;
}
