// frontend/packages/ui/src/services/sharedChatDetailsService.ts
//
// Read-only shared-chat detail loader. Public share manifests contain encrypted
// task/plan rows plus chat-scoped key wrappers; this module unwraps them with
// the locally cached share chat key without expanding any owner permissions.
// Backend access model: unauthenticated public REST, encrypted payload only.

import { getApiEndpoint, storageArchiveFetch } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import { validateUserFlows, type UserPlanViewModel, type EncryptedUserPlanRecord, type UserPlanKeyWrapperRecord } from "./userPlanService";
import type { UserTaskViewModel, EncryptedUserTaskRecord, UserTaskKeyWrapperRecord } from "./userTaskService";
import { decryptWithEmbedKey, unwrapEmbedKeyWithChatKey } from "./cryptoService";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decideShareState } from "./shareState/decide";

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

function sharedAuxiliaryUrl(chatId: string, kind: "plans" | "tasks", cursor?: SharedChatCursor | null): string {
  const path = `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/${kind}`;
  if (!cursor) return getApiEndpoint(path);
  const query = new URLSearchParams({ before_timestamp: String(cursor.timestamp), before_id: cursor.id });
  return getApiEndpoint(`${path}?${query}`);
}

async function fetchEncryptedPage(chatId: string, kind: "plans" | "tasks", cursor?: SharedChatCursor | null): Promise<SharedChatEncryptedPage> {
  await decideShareState("detailsCursorCheck", { kind, cursor });
  const response = await storageArchiveFetch(sharedAuxiliaryUrl(chatId, kind, cursor));
  if (!response.ok) throw new Error(`Shared ${kind} page failed (${response.status})`);
  const page = await response.json() as SharedChatEncryptedPage;
  const idField = kind === "plans" ? "plan_id" : "task_id";
  // Rust (flag on) or the TS rule validates shape, identities, order and cursor movement.
  await decideShareState("detailsPageCheck", {
    kind,
    chat_id: chatId,
    cursor,
    page: {
      items_is_array: Array.isArray(page.items),
      items: Array.isArray(page.items) ? page.items.map((item) => ({
        updated_at: item.updated_at,
        id: (item as unknown as Record<string, unknown>)[idField],
        primary_chat_id: item.primary_chat_id,
      })) : undefined,
      key_wrappers_is_array: Array.isArray(page.key_wrappers),
      has_more_before: page.has_more_before,
      payload_bytes: page.payload_bytes,
      start_cursor: page.start_cursor,
      oversized_id: page.oversized_id,
    },
  });
  return page;
}

async function fetchExactOversizedItem(chatId: string, kind: "plans" | "tasks", id: string): Promise<SharedChatEncryptedPage> {
  const response = await storageArchiveFetch(getApiEndpoint(
    `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/${kind}/${encodeURIComponent(id)}`,
  ));
  if (!response.ok) throw new Error(`Shared ${kind} item failed (${response.status})`);
  const exact = await response.json() as {
    item?: EncryptedUserPlanRecord | EncryptedUserTaskRecord;
    key_wrappers?: SharedChatEncryptedPage["key_wrappers"];
    key_wrapper_window?: SharedChatEncryptedPage["key_wrapper_window"];
  };
  const record = exact.item;
  await decideShareState("detailsExactCheck", {
    kind,
    chat_id: chatId,
    id,
    exact: {
      has_item: !!record,
      key_wrappers_is_array: Array.isArray(exact.key_wrappers),
      item_id: record ? (kind === "plans" ? (record as EncryptedUserPlanRecord).plan_id
        : (record as EncryptedUserTaskRecord).task_id) : undefined,
      updated_at: record?.updated_at,
      primary_chat_id: record?.primary_chat_id,
    },
  });
  const item = record as EncryptedUserPlanRecord | EncryptedUserTaskRecord;
  return { items: [item], key_wrappers: exact.key_wrappers as SharedChatEncryptedPage["key_wrappers"],
    key_wrapper_window: exact.key_wrapper_window,
    has_more_before: true, start_cursor: { timestamp: item.updated_at, id }, payload_bytes: 0 };
}

async function completeWrapperWindow(chatId: string, kind: "plans" | "tasks", page: SharedChatEncryptedPage): Promise<void> {
  const itemIds = page.items.map((item) => kind === "plans"
    ? (item as EncryptedUserPlanRecord).plan_id : (item as EncryptedUserTaskRecord).task_id);
  if (!itemIds.length) return;
  const seen = page.key_wrappers.map((wrapper) => wrapper.id).filter((id): id is string => !!id);
  let window = page.key_wrapper_window;
  for (let count = 0; await decideShareState("detailsWrapperContinue", { window, count }); count += 1) {
    const step = await decideShareState("detailsWrapperStep", { kind, window: window as NonNullable<typeof window> });
    const query = new URLSearchParams({ item_ids: itemIds.join(",") });
    query.set(step.param, step.value);
    const response = await storageArchiveFetch(getApiEndpoint(
      `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/${kind}/keys/window?${query}`,
    ));
    if (!response.ok) throw new Error(`Shared ${kind} keys failed (${response.status})`);
    const continuation = await response.json() as Pick<SharedChatEncryptedPage, "key_wrappers" | "key_wrapper_window">;
    const next = await decideShareState("detailsWrapperAdvance", {
      kind,
      window: window as NonNullable<typeof window>,
      continuation: { key_wrappers_is_array: Array.isArray(continuation.key_wrappers), window: continuation.key_wrapper_window },
    });
    const add = await decideShareState("detailsWrapperDedup", {
      seen,
      wrappers: continuation.key_wrappers.map((wrapper) => ({ id: wrapper.id })),
    });
    for (const index of add) {
      seen.push(continuation.key_wrappers[index].id as string);
      page.key_wrappers.push(continuation.key_wrappers[index]);
    }
    window = next.window;
  }
  await decideShareState("detailsWrapperDone", { kind, window });
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
    await decideShareState("detailsOversizedAdvance", { kind, cursor, start_cursor: page.start_cursor });
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

/** Fields the page check reads from one raw row (non-objects become null, which is never valid). */
function subChatRowFields(row: unknown) {
  if (!row || typeof row !== "object" || Array.isArray(row)) return null;
  const item = row as Record<string, unknown>;
  return { id: item.id, parent_id: item.parent_id, is_sub_chat: item.is_sub_chat, created_at: item.created_at };
}

/** Read one requested public ciphertext page; large first rows use the selected-row endpoint. */
export async function loadSharedSubChatPage(chatId: string, before?: SharedChatCursor | null): Promise<SharedSubChatPage> {
  await decideShareState("subChatCursorCheck", { chat_id: chatId, before });
  const base = `/v1/share/chat/${encodeURIComponent(chatId)}/auxiliary/sub_chats`;
  const query = before ? `?${new URLSearchParams({ before_timestamp: String(before.timestamp), before_id: before.id })}` : "";
  const response = await storageArchiveFetch(getApiEndpoint(`${base}${query}`));
  if (!response.ok) throw new Error(`Shared subchat page failed (${response.status}).`);
  const page = await response.json() as {
    items?: unknown; has_more_before?: unknown; start_cursor?: unknown;
    oversized_id?: unknown; payload_bytes?: unknown;
  };
  const checked = await decideShareState("subChatPageCheck", {
    chat_id: chatId,
    page: {
      items_is_array: Array.isArray(page.items),
      rows: Array.isArray(page.items) ? page.items.map(subChatRowFields) : undefined,
      has_more_before: page.has_more_before,
      payload_bytes: page.payload_bytes,
      start_cursor: page.start_cursor,
      oversized_id: page.oversized_id,
    },
  });
  let items = page.items as SharedSubChatRow[];
  let cursor: SharedChatCursor | null = null;
  if (checked.mode === "fetch_oversized") {
    const selected = await storageArchiveFetch(getApiEndpoint(`${base}/${encodeURIComponent(checked.id)}`));
    if (!selected.ok) throw new Error(`Shared oversized subchat failed (${selected.status}).`);
    const body = await selected.json() as { item?: unknown };
    const identity = await decideShareState("subChatOversizedCheck", {
      chat_id: chatId, oversized_id: checked.id, item: subChatRowFields(body.item),
    });
    items = [body.item as SharedSubChatRow];
    cursor = identity.cursor;
  } else {
    cursor = checked.cursor;
  }
  await decideShareState("subChatFinalCheck", {
    rows: items.map((item) => ({ id: item.id, created_at: item.created_at })),
    cursor,
    has_more_before: page.has_more_before as boolean,
    before,
  });
  return { items, hasMoreBefore: page.has_more_before as boolean, nextCursor: cursor };
}
