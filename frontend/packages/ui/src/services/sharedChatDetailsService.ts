// frontend/packages/ui/src/services/sharedChatDetailsService.ts
//
// Read-only shared-chat detail loader. Public share manifests contain encrypted
// task/plan rows plus chat-scoped key wrappers; this module unwraps them with
// the locally cached share chat key without expanding any owner permissions.
// Backend access model: unauthenticated public REST, encrypted payload only.

import { getApiEndpoint } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import { validateUserFlows, type UserPlanViewModel, type EncryptedUserPlanRecord, type UserPlanKeyWrapperRecord } from "./userPlanService";
import type { UserTaskViewModel, EncryptedUserTaskRecord, UserTaskKeyWrapperRecord } from "./userTaskService";
import { decryptWithEmbedKey, unwrapEmbedKeyWithChatKey } from "./cryptoService";
import { chatKeyManager } from "./encryption/ChatKeyManager";

interface SharedChatManifestPayload {
  plans?: EncryptedUserPlanRecord[];
  plan_key_wrappers?: Array<UserPlanKeyWrapperRecord & { hashed_plan_id?: string | null }>;
  tasks?: EncryptedUserTaskRecord[];
  task_key_wrappers?: Array<UserTaskKeyWrapperRecord & { hashed_task_id?: string | null }>;
}

export interface SharedChatCursor { timestamp: number; id: string }
export interface SharedChatPageWindow {
  hasMoreBefore: boolean;
  startCursor: SharedChatCursor | null;
}

interface SharedChatEncryptedPage extends SharedChatManifestPayload {
  items: Array<EncryptedUserPlanRecord | EncryptedUserTaskRecord>;
  key_wrappers: Array<(UserPlanKeyWrapperRecord | UserTaskKeyWrapperRecord) & {
    id?: string; hashed_plan_id?: string | null; hashed_task_id?: string | null;
  }>;
  key_wrapper_window?: { has_more_after?: boolean; end_cursor?: string | null; oversized_key_id?: string | null };
  has_more_before: boolean;
  start_cursor: SharedChatCursor | null;
  oversized_id?: string | null;
  payload_bytes: number;
}

export interface SharedChatDetails {
  plans: UserPlanViewModel[];
  tasks: UserTaskViewModel[];
  planWindow: SharedChatPageWindow;
  taskWindow: SharedChatPageWindow;
}

const EMPTY_WINDOW: SharedChatPageWindow = { hasMoreBefore: false, startCursor: null };
const MAX_WRAPPER_PAGES = 20;

function sharedAuxiliaryUrl(chatId: string, kind: "plans" | "tasks", cursor?: SharedChatCursor | null): string {
  const path = `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/${kind}`;
  if (!cursor) return getApiEndpoint(path);
  const query = new URLSearchParams({ before_timestamp: String(cursor.timestamp), before_id: cursor.id });
  return getApiEndpoint(`${path}?${query}`);
}

async function fetchEncryptedPage(chatId: string, kind: "plans" | "tasks", cursor?: SharedChatCursor | null): Promise<SharedChatEncryptedPage> {
  if (cursor && (!Number.isSafeInteger(cursor.timestamp) || cursor.timestamp < 0 || !cursor.id)) {
    throw new Error(`Shared ${kind} cursor was invalid`);
  }
  const response = await fetch(sharedAuxiliaryUrl(chatId, kind, cursor));
  if (!response.ok) throw new Error(`Shared ${kind} page failed (${response.status})`);
  const page = await response.json() as SharedChatEncryptedPage;
  if (!Array.isArray(page.items) || page.items.length > 20 || !Array.isArray(page.key_wrappers)
    || typeof page.has_more_before !== "boolean" || !Number.isSafeInteger(page.payload_bytes)
    || Number(page.payload_bytes) < 0 || Number(page.payload_bytes) > 131_072) {
    throw new Error(`Shared ${kind} page was invalid`);
  }
  const idField = kind === "plans" ? "plan_id" : "task_id";
  const positions = page.items.map((item) => ({
    timestamp: item.updated_at,
    id: (item as unknown as Record<string, unknown>)[idField] as string,
    primaryChatId: item.primary_chat_id,
  }));
  if (positions.some((position, index) => !Number.isSafeInteger(position.timestamp)
    || typeof position.id !== "string" || !position.id
    || (position.primaryChatId != null && position.primaryChatId !== chatId)
    || (index > 0 && (position.timestamp < positions[index - 1].timestamp
      || (position.timestamp === positions[index - 1].timestamp && position.id <= positions[index - 1].id))))) {
    throw new Error(`Shared ${kind} page identities or order were invalid`);
  }
  const oldest = positions[0];
  if (page.items.length && (!page.start_cursor || page.start_cursor.timestamp !== oldest.timestamp
    || page.start_cursor.id !== oldest.id)) throw new Error(`Shared ${kind} page cursor was invalid`);
  if (page.has_more_before && !page.start_cursor && !page.oversized_id) {
    throw new Error(`Shared ${kind} page cannot advance`);
  }
  if (cursor && page.start_cursor && (page.start_cursor.timestamp > cursor.timestamp
    || (page.start_cursor.timestamp === cursor.timestamp && page.start_cursor.id >= cursor.id))) {
    throw new Error(`Shared ${kind} cursor did not advance`);
  }
  return page;
}

async function fetchExactOversizedItem(chatId: string, kind: "plans" | "tasks", id: string): Promise<SharedChatEncryptedPage> {
  const response = await fetch(getApiEndpoint(
    `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/${kind}/${encodeURIComponent(id)}`,
  ));
  if (!response.ok) throw new Error(`Shared ${kind} item failed (${response.status})`);
  const exact = await response.json() as {
    item?: EncryptedUserPlanRecord | EncryptedUserTaskRecord;
    key_wrappers?: SharedChatEncryptedPage["key_wrappers"];
    key_wrapper_window?: SharedChatEncryptedPage["key_wrapper_window"];
  };
  if (!exact.item || !Array.isArray(exact.key_wrappers)) throw new Error(`Shared ${kind} item was invalid`);
  const itemId = kind === "plans" ? (exact.item as EncryptedUserPlanRecord).plan_id
    : (exact.item as EncryptedUserTaskRecord).task_id;
  if (itemId !== id || !Number.isSafeInteger(exact.item.updated_at)
    || (exact.item.primary_chat_id != null && exact.item.primary_chat_id !== chatId)) {
    throw new Error(`Shared ${kind} item identity changed`);
  }
  return { items: [exact.item], key_wrappers: exact.key_wrappers,
    key_wrapper_window: exact.key_wrapper_window,
    has_more_before: true, start_cursor: { timestamp: exact.item.updated_at, id }, payload_bytes: 0 };
}

async function completeWrapperWindow(chatId: string, kind: "plans" | "tasks", page: SharedChatEncryptedPage): Promise<void> {
  const itemIds = page.items.map((item) => kind === "plans"
    ? (item as EncryptedUserPlanRecord).plan_id : (item as EncryptedUserTaskRecord).task_id);
  if (!itemIds.length) return;
  const seen = new Set(page.key_wrappers.map((wrapper) => wrapper.id).filter((id): id is string => !!id));
  let window = page.key_wrapper_window;
  for (let count = 0; window?.has_more_after && count < MAX_WRAPPER_PAGES; count += 1) {
    const query = new URLSearchParams({ item_ids: itemIds.join(",") });
    if (window.oversized_key_id) query.set("key_id", window.oversized_key_id);
    else if (window.end_cursor) query.set("after_key_id", window.end_cursor);
    else throw new Error(`Shared ${kind} key cursor did not advance`);
    const response = await fetch(getApiEndpoint(
      `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/${kind}/keys/window?${query}`,
    ));
    if (!response.ok) throw new Error(`Shared ${kind} keys failed (${response.status})`);
    const continuation = await response.json() as Pick<SharedChatEncryptedPage, "key_wrappers" | "key_wrapper_window">;
    if (!Array.isArray(continuation.key_wrappers) || !continuation.key_wrapper_window) {
      throw new Error(`Shared ${kind} key window was invalid`);
    }
    for (const wrapper of continuation.key_wrappers) {
      if (!wrapper.id || seen.has(wrapper.id)) continue;
      seen.add(wrapper.id);
      page.key_wrappers.push(wrapper);
    }
    if (window.oversized_key_id) {
      window = { ...continuation.key_wrapper_window, has_more_after: true,
        end_cursor: window.oversized_key_id, oversized_key_id: null };
    } else {
      if (continuation.key_wrapper_window.has_more_after
        && continuation.key_wrapper_window.end_cursor === window.end_cursor
        && !continuation.key_wrapper_window.oversized_key_id) {
        throw new Error(`Shared ${kind} key cursor did not advance`);
      }
      window = continuation.key_wrapper_window;
    }
  }
  if (window?.has_more_after) throw new Error(`Shared ${kind} key window exceeded the bounded retry limit`);
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array, context: { chatId: string; fieldName: string }): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key, context)) ?? "";
}

async function decryptStringArray(value: string | null | undefined, key: Uint8Array, chatId: string, fieldName: string): Promise<string[]> {
  const text = await decryptOptional(value, key, { chatId, fieldName });
  if (!text) return [];
  try {
    const parsed = JSON.parse(text) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch (error) {
    console.warn('[sharedChatDetailsService] Failed to parse decrypted string array:', { chatId, fieldName, error });
    return [];
  }
}

async function loadSharedChatKey(chatId: string): Promise<Uint8Array | null> {
  return chatKeyManager.getKeySync(chatId) ?? await chatKeyManager.getKey(chatId);
}

async function decryptSharedPlan(
  chatId: string,
  chatKey: Uint8Array,
  record: EncryptedUserPlanRecord,
  wrappers: SharedChatManifestPayload["plan_key_wrappers"] = [],
): Promise<UserPlanViewModel | null> {
  const planId = record.plan_id;
  const hashedPlanId = await computeSHA256(planId);
  const wrapper = wrappers.find((candidate) =>
    candidate.key_type === "chat" &&
    candidate.hashed_plan_id === hashedPlanId &&
    candidate.encrypted_plan_key
  );
  if (!wrapper?.encrypted_plan_key) return null;

  const planKey = await unwrapEmbedKeyWithChatKey(wrapper.encrypted_plan_key, chatKey, { chatId });
  if (!planKey) return null;
  const encryptedUserFlows = await decryptOptional(record.encrypted_user_flows, planKey, { chatId, fieldName: "shared_plan_user_flows" });

  return {
    plan_id: planId,
    title: await decryptOptional(record.encrypted_title, planKey, { chatId, fieldName: "shared_plan_title" }),
    goal: await decryptOptional(record.encrypted_goal, planKey, { chatId, fieldName: "shared_plan_goal" }),
    scopeIn: await decryptOptional(record.encrypted_scope_in, planKey, { chatId, fieldName: "shared_plan_scope_in" }),
    scopeOut: await decryptOptional(record.encrypted_scope_out, planKey, { chatId, fieldName: "shared_plan_scope_out" }),
    userFlows: validateUserFlows(encryptedUserFlows ? JSON.parse(encryptedUserFlows) : []),
    assumptions: await decryptOptional(record.encrypted_assumptions, planKey, { chatId, fieldName: "shared_plan_assumptions" }),
    openQuestions: await decryptOptional(record.encrypted_open_questions, planKey, { chatId, fieldName: "shared_plan_open_questions" }),
    constraints: await decryptOptional(record.encrypted_constraints, planKey, { chatId, fieldName: "shared_plan_constraints" }),
    decisions: await decryptOptional(record.encrypted_decisions, planKey, { chatId, fieldName: "shared_plan_decisions" }),
    risks: await decryptOptional(record.encrypted_risks, planKey, { chatId, fieldName: "shared_plan_risks" }),
    status: record.status,
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: await decryptStringArray(record.encrypted_linked_project_ids, planKey, chatId, "shared_plan_linked_projects"),
    plannerFocusId: record.planner_focus_id ?? null,
    version: record.version ?? 1,
    createdAt: record.created_at,
    updatedAt: record.updated_at,
    completedAt: record.completed_at ?? null,
    encrypted: { ...record, key_wrappers: [wrapper] },
  };
}

async function decryptSharedTask(
  chatId: string,
  chatKey: Uint8Array,
  record: EncryptedUserTaskRecord,
  wrappers: SharedChatManifestPayload["task_key_wrappers"] = [],
): Promise<UserTaskViewModel | null> {
  const taskId = record.task_id;
  const hashedTaskId = await computeSHA256(taskId);
  const wrapper = wrappers.find((candidate) =>
    candidate.key_type === "chat" &&
    candidate.hashed_task_id === hashedTaskId &&
    candidate.encrypted_task_key
  );
  if (!wrapper?.encrypted_task_key) return null;

  const taskKey = await unwrapEmbedKeyWithChatKey(wrapper.encrypted_task_key, chatKey, { chatId });
  if (!taskKey) return null;

  return {
    task_id: taskId,
    title: await decryptOptional(record.encrypted_title, taskKey, { chatId, fieldName: "shared_task_title" }),
    description: await decryptOptional(record.encrypted_description, taskKey, { chatId, fieldName: "shared_task_description" }),
    tags: await decryptStringArray(record.encrypted_tags, taskKey, chatId, "shared_task_tags"),
    latestInstruction: await decryptOptional(record.encrypted_latest_instruction, taskKey, { chatId, fieldName: "shared_task_latest_instruction" }),
    status: record.status,
    assigneeType: record.assignee_type ?? "openmates",
    assigneeIdentity: record.assignee_identity ?? "openmates",
    primaryChatId: record.primary_chat_id ?? null,
    externalChat: null,
    linkedProjectIds: await decryptStringArray(record.encrypted_linked_project_ids, taskKey, chatId, "shared_task_linked_projects"),
    planId: record.plan_id ?? null,
    dueAt: record.due_at ?? null,
    priority: record.priority ?? 0,
    position: record.position ?? 0,
    version: record.version ?? 1,
    createdAt: record.created_at,
    updatedAt: record.updated_at,
    blockedReasonCode: (record.blocked_reason_code as UserTaskViewModel["blockedReasonCode"]) ?? null,
    blockedReason: await decryptOptional(record.encrypted_blocked_reason, taskKey, { chatId, fieldName: "shared_task_blocked_reason" }),
    aiExecutionState: record.ai_execution_state ?? null,
    encrypted: { ...record, encrypted_task_key: wrapper.encrypted_task_key },
  };
}

export async function loadSharedChatDetailsPage(
  chatId: string, kind: "plans" | "tasks", cursor?: SharedChatCursor | null,
): Promise<{ plans: UserPlanViewModel[]; tasks: UserTaskViewModel[]; window: SharedChatPageWindow }> {
  const chatKey = await loadSharedChatKey(chatId);
  if (!chatKey) return { plans: [], tasks: [], window: EMPTY_WINDOW };
  let page = await fetchEncryptedPage(chatId, kind, cursor);
  if (page.oversized_id && page.items.length === 0) {
    page = await fetchExactOversizedItem(chatId, kind, page.oversized_id);
    if (cursor && page.start_cursor && (page.start_cursor.timestamp > cursor.timestamp
      || (page.start_cursor.timestamp === cursor.timestamp && page.start_cursor.id >= cursor.id))) {
      throw new Error(`Shared ${kind} oversized cursor did not advance`);
    }
  }
  await completeWrapperWindow(chatId, kind, page);
  const window: SharedChatPageWindow = {
    hasMoreBefore: page.has_more_before,
    startCursor: page.start_cursor,
  };
  if (page.items.length && !window.startCursor) throw new Error(`Shared ${kind} page has no cursor`);
  if (kind === "plans") {
    const wrappers = page.key_wrappers as SharedChatManifestPayload["plan_key_wrappers"];
    const plans = await Promise.all((page.items as EncryptedUserPlanRecord[])
      .map((plan) => decryptSharedPlan(chatId, chatKey, plan, wrappers)));
    if (plans.some((plan) => plan === null)) throw new Error("Shared plan key is unavailable");
    return { plans: plans as UserPlanViewModel[], tasks: [], window };
  }
  const wrappers = page.key_wrappers as SharedChatManifestPayload["task_key_wrappers"];
  const tasks = await Promise.all((page.items as EncryptedUserTaskRecord[])
    .map((task) => decryptSharedTask(chatId, chatKey, task, wrappers)));
  if (tasks.some((task) => task === null)) throw new Error("Shared task key is unavailable");
  return { plans: [], tasks: tasks as UserTaskViewModel[], window };
}

export async function loadSharedChatDetails(chatId: string): Promise<SharedChatDetails> {
  const [planPage, taskPage] = await Promise.all([
    loadSharedChatDetailsPage(chatId, "plans"), loadSharedChatDetailsPage(chatId, "tasks"),
  ]);
  return { plans: planPage.plans, tasks: taskPage.tasks,
    planWindow: planPage.window, taskWindow: taskPage.window };
}

export interface SharedSubChatRow {
  id: string;
  parent_id: string;
  is_sub_chat: boolean;
  encrypted_title?: string | null;
  encrypted_chat_summary?: string | null;
  encrypted_icon?: string | null;
  encrypted_category?: string | null;
  created_at: number;
  updated_at?: number;
  last_edited_overall_timestamp?: number;
  messages_v?: number;
  title_v?: number;
  metadata_v?: number;
  unread_count?: number;
  budget_limit?: number | null;
  budget_spent?: number;
}

export interface SharedSubChatPage {
  items: SharedSubChatRow[];
  hasMoreBefore: boolean;
  nextCursor: SharedChatCursor | null;
}

function validSharedSubChat(row: unknown, parentId: string): row is SharedSubChatRow {
  if (!row || typeof row !== "object" || Array.isArray(row)) return false;
  const item = row as Record<string, unknown>;
  return typeof item.id === "string" && item.id.length > 0
    && item.parent_id === parentId && item.is_sub_chat === true
    && Number.isSafeInteger(item.created_at) && Number(item.created_at) > 0;
}

/** Read one requested public ciphertext page; large first rows use the selected-row endpoint. */
export async function loadSharedSubChatPage(chatId: string, before?: SharedChatCursor | null): Promise<SharedSubChatPage> {
  if (!chatId || (before && (!Number.isSafeInteger(before.timestamp) || before.timestamp <= 0 || !before.id))) {
    throw new Error("Invalid shared subchat cursor.");
  }
  const base = `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/sub_chats`;
  const query = before ? `?${new URLSearchParams({ before_timestamp: String(before.timestamp), before_id: before.id })}` : "";
  const response = await fetch(getApiEndpoint(`${base}${query}`));
  if (!response.ok) throw new Error(`Shared subchat page failed (${response.status}).`);
  const page = await response.json() as {
    items?: unknown; has_more_before?: unknown; start_cursor?: unknown;
    oversized_id?: unknown; payload_bytes?: unknown;
  };
  if (!Array.isArray(page.items) || page.items.length > 20
    || typeof page.has_more_before !== "boolean"
    || !Number.isSafeInteger(page.payload_bytes) || Number(page.payload_bytes) < 0
    || Number(page.payload_bytes) > 131_072
    || page.items.some((item) => !validSharedSubChat(item, chatId))) {
    throw new Error("Shared subchat page had invalid bounded metadata.");
  }
  let items = page.items as SharedSubChatRow[];
  let cursor: SharedChatCursor | null = null;
  if (page.oversized_id != null) {
    if (items.length !== 0 || typeof page.oversized_id !== "string" || !page.oversized_id || !page.has_more_before) {
      throw new Error("Shared subchat oversized cursor was invalid.");
    }
    const selected = await fetch(getApiEndpoint(`${base}/${encodeURIComponent(page.oversized_id)}`));
    if (!selected.ok) throw new Error(`Shared oversized subchat failed (${selected.status}).`);
    const body = await selected.json() as { item?: unknown };
    if (!validSharedSubChat(body.item, chatId) || body.item.id !== page.oversized_id) {
      throw new Error("Shared oversized subchat identity did not match its cursor.");
    }
    items = [body.item];
    cursor = { timestamp: body.item.created_at, id: body.item.id };
  } else if (page.start_cursor != null) {
    const start = page.start_cursor as Record<string, unknown>;
    if (!Number.isSafeInteger(start.timestamp) || Number(start.timestamp) <= 0 || typeof start.id !== "string" || !start.id) {
      throw new Error("Shared subchat page cursor was invalid.");
    }
    cursor = { timestamp: start.timestamp as number, id: start.id };
  }
  if (items.length && (!cursor || cursor.timestamp !== items[0].created_at || cursor.id !== items[0].id
    || items.some((item, index) => index > 0 && (item.created_at < items[index - 1].created_at
      || (item.created_at === items[index - 1].created_at && item.id <= items[index - 1].id))))) {
    throw new Error("Shared subchat page was not a contiguous chronological window.");
  }
  if (page.has_more_before && !cursor) throw new Error("Shared subchat page did not provide its next cursor.");
  if (before && cursor && (cursor.timestamp > before.timestamp
    || (cursor.timestamp === before.timestamp && cursor.id >= before.id))) {
    throw new Error("Shared subchat cursor did not advance.");
  }
  return { items, hasMoreBefore: page.has_more_before, nextCursor: cursor };
}
