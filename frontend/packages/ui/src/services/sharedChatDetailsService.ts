// frontend/packages/ui/src/services/sharedChatDetailsService.ts
//
// Read-only shared-chat detail loader. Public share manifests contain encrypted
// task/plan rows plus chat-scoped key wrappers; this module unwraps them with
// the locally cached share chat key without expanding any owner permissions.
// Backend access model: unauthenticated public REST, encrypted payload only.

import { getApiEndpoint } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import type { UserPlanViewModel, EncryptedUserPlanRecord, UserPlanKeyWrapperRecord } from "./userPlanService";
import type { UserTaskViewModel, EncryptedUserTaskRecord, UserTaskKeyWrapperRecord } from "./userTaskService";
import { decryptWithEmbedKey, unwrapEmbedKeyWithChatKey } from "./cryptoService";
import { chatKeyManager } from "./encryption/ChatKeyManager";

interface SharedChatManifestPayload {
  plans?: EncryptedUserPlanRecord[];
  plan_key_wrappers?: Array<UserPlanKeyWrapperRecord & { hashed_plan_id?: string | null }>;
  tasks?: EncryptedUserTaskRecord[];
  task_key_wrappers?: Array<UserTaskKeyWrapperRecord & { hashed_task_id?: string | null }>;
}

export interface SharedChatDetails {
  plans: UserPlanViewModel[];
  tasks: UserTaskViewModel[];
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

  return {
    plan_id: planId,
    title: await decryptOptional(record.encrypted_title, planKey, { chatId, fieldName: "shared_plan_title" }),
    summary: await decryptOptional(record.encrypted_summary, planKey, { chatId, fieldName: "shared_plan_summary" }),
    goal: await decryptOptional(record.encrypted_goal, planKey, { chatId, fieldName: "shared_plan_goal" }),
    scopeIn: await decryptOptional(record.encrypted_scope_in, planKey, { chatId, fieldName: "shared_plan_scope_in" }),
    scopeOut: await decryptOptional(record.encrypted_scope_out, planKey, { chatId, fieldName: "shared_plan_scope_out" }),
    assumptions: await decryptOptional(record.encrypted_assumptions, planKey, { chatId, fieldName: "shared_plan_assumptions" }),
    openQuestions: await decryptOptional(record.encrypted_open_questions, planKey, { chatId, fieldName: "shared_plan_open_questions" }),
    constraints: await decryptOptional(record.encrypted_constraints, planKey, { chatId, fieldName: "shared_plan_constraints" }),
    decisions: await decryptOptional(record.encrypted_decisions, planKey, { chatId, fieldName: "shared_plan_decisions" }),
    risks: await decryptOptional(record.encrypted_risks, planKey, { chatId, fieldName: "shared_plan_risks" }),
    status: record.status,
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: await decryptStringArray(record.encrypted_linked_project_ids, planKey, chatId, "shared_plan_linked_projects"),
    currentPhaseId: record.current_phase_id ?? null,
    currentStepId: record.current_step_id ?? null,
    currentTaskId: record.current_task_id ?? null,
    plannerFocusId: record.planner_focus_id ?? null,
    version: record.version ?? 1,
    createdAt: record.created_at,
    updatedAt: record.updated_at,
    completedAt: record.completed_at ?? null,
    encrypted: { ...record, encrypted_plan_key: wrapper.encrypted_plan_key },
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
    assigneeType: record.assignee_type ?? "ai",
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: await decryptStringArray(record.encrypted_linked_project_ids, taskKey, chatId, "shared_task_linked_projects"),
    dueAt: record.due_at ?? null,
    priority: record.priority ?? 0,
    position: record.position ?? 0,
    version: record.version ?? 1,
    encrypted: { ...record, encrypted_task_key: wrapper.encrypted_task_key },
  };
}

export async function loadSharedChatDetails(chatId: string): Promise<SharedChatDetails> {
  const chatKey = await loadSharedChatKey(chatId);
  if (!chatKey) return { plans: [], tasks: [] };

  const response = await fetch(getApiEndpoint(`/v1/share/chat/${encodeURIComponent(chatId)}/manifest`));
  if (!response.ok) {
    throw new Error(`Shared chat manifest failed (${response.status})`);
  }

  const payload = await response.json() as SharedChatManifestPayload;
  const [plans, tasks] = await Promise.all([
    Promise.all((payload.plans ?? []).map((plan) => decryptSharedPlan(chatId, chatKey, plan, payload.plan_key_wrappers))),
    Promise.all((payload.tasks ?? []).map((task) => decryptSharedTask(chatId, chatKey, task, payload.task_key_wrappers))),
  ]);

  return {
    plans: plans.filter((plan): plan is UserPlanViewModel => plan !== null),
    tasks: tasks.filter((task): task is UserTaskViewModel => task !== null),
  };
}
