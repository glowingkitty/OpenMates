// frontend/packages/ui/src/services/userPlanService.ts
// Client-side Plans V1 service. Durable plan content is encrypted with a
// per-plan key wrapped by the user's master key; the backend receives only
// ciphertext plus minimal metadata for filtering, linking, and verification.
// Spec: docs/specs/plans-v1/spec.yml

import { getApiEndpoint } from "../config/api";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
} from "./cryptoService";

export type UserPlanStatus = "draft" | "awaiting_confirmation" | "active" | "executing" | "blocked" | "completed" | "archived";
export type UserPlanCriterionStatus = "pending" | "satisfied" | "failed" | "waived";
export type UserPlanVerificationStatus = "pending" | "passed" | "failed" | "passed_unexpectedly" | "skipped" | "waived";

export interface EncryptedUserPlanRecord {
  id?: string;
  plan_id: string;
  encrypted_plan_key?: string | null;
  encrypted_title: string;
  encrypted_summary?: string | null;
  encrypted_goal?: string | null;
  encrypted_scope_in?: string | null;
  encrypted_scope_out?: string | null;
  encrypted_assumptions?: string | null;
  encrypted_open_questions?: string | null;
  encrypted_constraints?: string | null;
  encrypted_decisions?: string | null;
  encrypted_risks?: string | null;
  status: UserPlanStatus;
  primary_chat_id?: string | null;
  linked_project_ids?: string[] | null;
  current_phase_id?: string | null;
  current_step_id?: string | null;
  current_task_id?: string | null;
  planner_focus_id?: string | null;
  version?: number;
  created_at: number;
  updated_at: number;
  completed_at?: number | null;
}

export interface UserPlanViewModel {
  plan_id: string;
  title: string;
  summary: string;
  goal: string;
  scopeIn: string;
  scopeOut: string;
  assumptions: string;
  openQuestions: string;
  constraints: string;
  decisions: string;
  risks: string;
  status: UserPlanStatus;
  primaryChatId: string | null;
  linkedProjectIds: string[];
  currentPhaseId: string | null;
  currentStepId: string | null;
  currentTaskId: string | null;
  plannerFocusId: string | null;
  version: number;
  createdAt: number;
  updatedAt: number;
  completedAt: number | null;
  encrypted: EncryptedUserPlanRecord;
}

export interface CreateUserPlanInput {
  title: string;
  summary?: string;
  goal?: string;
  scopeIn?: string;
  scopeOut?: string;
  assumptions?: string;
  openQuestions?: string;
  constraints?: string;
  decisions?: string;
  risks?: string;
  status?: UserPlanStatus;
  primaryChatId?: string | null;
  linkedProjectIds?: string[];
  currentPhaseId?: string | null;
  currentStepId?: string | null;
  currentTaskId?: string | null;
  plannerFocusId?: string | null;
}

export interface ListUserPlansFilters {
  status?: UserPlanStatus;
  chatId?: string;
  projectId?: string;
  activeOnly?: boolean;
  limit?: number;
}

export interface CreatePlanCriterionInput {
  criterionId?: string;
  text: string;
  type?: string;
  status?: UserPlanCriterionStatus;
  required?: boolean;
  linkedStepIds?: string[];
  linkedTaskIds?: string[];
  verificationIds?: string[];
}

export interface CreatePlanVerificationInput {
  verificationId?: string;
  kind: string;
  phase?: string;
  status?: UserPlanVerificationStatus;
  requiredForDone?: boolean;
  covers?: string[];
  threshold?: number | null;
  assignedTo?: string | null;
  createTask?: boolean;
  taskId?: string | null;
  title?: string;
  command?: string;
  evaluationPrompt?: string;
  expectedResult?: string;
  primaryChatId?: string | null;
  linkedProjectIds?: string[];
  planStepId?: string | null;
  assigneeType?: string;
}

export interface PlanVerificationEvidenceInput {
  status: UserPlanVerificationStatus;
  score?: number | null;
  threshold?: number | null;
  confidence?: string | null;
  runId?: string | null;
  resultSummary?: string;
  requiredFixes?: string;
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
    throw new Error(`Plans API failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as T;
}

function buildQuery(filters: ListUserPlansFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.chatId) params.set("chat_id", filters.chatId);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.activeOnly !== undefined) params.set("active_only", String(filters.activeOnly));
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key)) ?? "";
}

async function decryptPlanKey(plan: UserPlanViewModel | EncryptedUserPlanRecord): Promise<Uint8Array> {
  const encryptedPlanKey = "encrypted" in plan ? plan.encrypted.encrypted_plan_key : plan.encrypted_plan_key;
  const planKey = await decryptChatKeyWithMasterKey(encryptedPlanKey ?? "");
  if (!planKey) throw new Error("Could not decrypt plan key");
  return planKey;
}

async function decryptPlan(record: EncryptedUserPlanRecord): Promise<UserPlanViewModel | null> {
  if (!record.encrypted_plan_key) return null;
  const planKey = await decryptChatKeyWithMasterKey(record.encrypted_plan_key);
  if (!planKey) return null;
  return {
    plan_id: record.plan_id,
    title: await decryptOptional(record.encrypted_title, planKey),
    summary: await decryptOptional(record.encrypted_summary, planKey),
    goal: await decryptOptional(record.encrypted_goal, planKey),
    scopeIn: await decryptOptional(record.encrypted_scope_in, planKey),
    scopeOut: await decryptOptional(record.encrypted_scope_out, planKey),
    assumptions: await decryptOptional(record.encrypted_assumptions, planKey),
    openQuestions: await decryptOptional(record.encrypted_open_questions, planKey),
    constraints: await decryptOptional(record.encrypted_constraints, planKey),
    decisions: await decryptOptional(record.encrypted_decisions, planKey),
    risks: await decryptOptional(record.encrypted_risks, planKey),
    status: record.status,
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: record.linked_project_ids ?? [],
    currentPhaseId: record.current_phase_id ?? null,
    currentStepId: record.current_step_id ?? null,
    currentTaskId: record.current_task_id ?? null,
    plannerFocusId: record.planner_focus_id ?? null,
    version: record.version ?? 1,
    createdAt: record.created_at,
    updatedAt: record.updated_at,
    completedAt: record.completed_at ?? null,
    encrypted: record,
  };
}

async function encryptPlanFields(input: CreateUserPlanInput, planKey: Uint8Array): Promise<Pick<EncryptedUserPlanRecord,
  "encrypted_title" | "encrypted_summary" | "encrypted_goal" | "encrypted_scope_in" | "encrypted_scope_out" |
  "encrypted_assumptions" | "encrypted_open_questions" | "encrypted_constraints" | "encrypted_decisions" | "encrypted_risks"
>> {
  return {
    encrypted_title: await encryptWithEmbedKey(input.title, planKey),
    encrypted_summary: await encryptWithEmbedKey(input.summary ?? "", planKey),
    encrypted_goal: await encryptWithEmbedKey(input.goal ?? "", planKey),
    encrypted_scope_in: await encryptWithEmbedKey(input.scopeIn ?? "", planKey),
    encrypted_scope_out: await encryptWithEmbedKey(input.scopeOut ?? "", planKey),
    encrypted_assumptions: await encryptWithEmbedKey(input.assumptions ?? "", planKey),
    encrypted_open_questions: await encryptWithEmbedKey(input.openQuestions ?? "", planKey),
    encrypted_constraints: await encryptWithEmbedKey(input.constraints ?? "", planKey),
    encrypted_decisions: await encryptWithEmbedKey(input.decisions ?? "", planKey),
    encrypted_risks: await encryptWithEmbedKey(input.risks ?? "", planKey),
  };
}

export async function listUserPlans(filters: ListUserPlansFilters = {}): Promise<UserPlanViewModel[]> {
  const data = await requestJson<{ plans: EncryptedUserPlanRecord[] }>(`/v1/user-plans${buildQuery(filters)}`);
  const decrypted = await Promise.all(data.plans.map(decryptPlan));
  return decrypted.filter((plan): plan is UserPlanViewModel => plan !== null);
}

export async function createUserPlan(input: CreateUserPlanInput): Promise<UserPlanViewModel> {
  const planKey = generateEmbedKey();
  const encryptedPlanKey = await encryptChatKeyWithMasterKey(planKey);
  if (!encryptedPlanKey) throw new Error("Could not wrap plan key with master key");
  const timestamp = nowSeconds();
  const body: EncryptedUserPlanRecord = {
    plan_id: crypto.randomUUID(),
    encrypted_plan_key: encryptedPlanKey,
    ...(await encryptPlanFields(input, planKey)),
    status: input.status ?? "draft",
    primary_chat_id: input.primaryChatId ?? null,
    linked_project_ids: input.linkedProjectIds ?? [],
    current_phase_id: input.currentPhaseId ?? null,
    current_step_id: input.currentStepId ?? null,
    current_task_id: input.currentTaskId ?? null,
    planner_focus_id: input.plannerFocusId ?? null,
    created_at: timestamp,
    updated_at: timestamp,
  };
  const data = await requestJson<{ plan: EncryptedUserPlanRecord }>("/v1/user-plans", {
    method: "POST",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptPlan(data.plan);
  if (!decrypted) throw new Error("Created plan could not be decrypted");
  return decrypted;
}

export async function updateUserPlan(plan: UserPlanViewModel, patch: Partial<CreateUserPlanInput> & { status?: UserPlanStatus }): Promise<UserPlanViewModel> {
  const planKey = await decryptPlanKey(plan);
  const body: Record<string, unknown> = { version: plan.version, updated_at: nowSeconds() };
  if (patch.title !== undefined) body.encrypted_title = await encryptWithEmbedKey(patch.title, planKey);
  if (patch.summary !== undefined) body.encrypted_summary = await encryptWithEmbedKey(patch.summary, planKey);
  if (patch.goal !== undefined) body.encrypted_goal = await encryptWithEmbedKey(patch.goal, planKey);
  if (patch.scopeIn !== undefined) body.encrypted_scope_in = await encryptWithEmbedKey(patch.scopeIn, planKey);
  if (patch.scopeOut !== undefined) body.encrypted_scope_out = await encryptWithEmbedKey(patch.scopeOut, planKey);
  if (patch.assumptions !== undefined) body.encrypted_assumptions = await encryptWithEmbedKey(patch.assumptions, planKey);
  if (patch.openQuestions !== undefined) body.encrypted_open_questions = await encryptWithEmbedKey(patch.openQuestions, planKey);
  if (patch.constraints !== undefined) body.encrypted_constraints = await encryptWithEmbedKey(patch.constraints, planKey);
  if (patch.decisions !== undefined) body.encrypted_decisions = await encryptWithEmbedKey(patch.decisions, planKey);
  if (patch.risks !== undefined) body.encrypted_risks = await encryptWithEmbedKey(patch.risks, planKey);
  if (patch.status !== undefined) body.status = patch.status;
  if (patch.primaryChatId !== undefined) body.primary_chat_id = patch.primaryChatId;
  if (patch.linkedProjectIds !== undefined) body.linked_project_ids = patch.linkedProjectIds;
  if (patch.currentPhaseId !== undefined) body.current_phase_id = patch.currentPhaseId;
  if (patch.currentStepId !== undefined) body.current_step_id = patch.currentStepId;
  if (patch.currentTaskId !== undefined) body.current_task_id = patch.currentTaskId;
  if (patch.plannerFocusId !== undefined) body.planner_focus_id = patch.plannerFocusId;
  const data = await requestJson<{ plan: EncryptedUserPlanRecord }>(`/v1/user-plans/${plan.plan_id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptPlan(data.plan);
  if (!decrypted) throw new Error("Updated plan could not be decrypted");
  return decrypted;
}

export async function activateUserPlan(plan: UserPlanViewModel, patch: { currentStepId?: string | null; currentTaskId?: string | null } = {}): Promise<UserPlanViewModel> {
  const data = await requestJson<{ plan: EncryptedUserPlanRecord }>(`/v1/user-plans/${plan.plan_id}/activate`, {
    method: "POST",
    body: JSON.stringify({
      chat_id: plan.primaryChatId,
      current_step_id: patch.currentStepId ?? plan.currentStepId,
      current_task_id: patch.currentTaskId ?? plan.currentTaskId,
      updated_at: nowSeconds(),
      version: plan.version,
    }),
  });
  const decrypted = await decryptPlan(data.plan);
  if (!decrypted) throw new Error("Activated plan could not be decrypted");
  return decrypted;
}

export async function completeUserPlan(plan: UserPlanViewModel, completionNote?: string): Promise<UserPlanViewModel> {
  const data = await requestJson<{ plan: EncryptedUserPlanRecord }>(`/v1/user-plans/${plan.plan_id}/complete`, {
    method: "POST",
    body: JSON.stringify({ updated_at: nowSeconds(), completion_note: completionNote, version: plan.version }),
  });
  const decrypted = await decryptPlan(data.plan);
  if (!decrypted) throw new Error("Completed plan could not be decrypted");
  return decrypted;
}

export async function createPlanCriterion(plan: UserPlanViewModel, input: CreatePlanCriterionInput): Promise<Record<string, unknown>> {
  const planKey = await decryptPlanKey(plan);
  const timestamp = nowSeconds();
  const data = await requestJson<{ criterion: Record<string, unknown> }>(`/v1/user-plans/${plan.plan_id}/criteria`, {
    method: "POST",
    body: JSON.stringify({
      criterion_id: input.criterionId ?? crypto.randomUUID(),
      encrypted_text: await encryptWithEmbedKey(input.text, planKey),
      type: input.type ?? "functional",
      status: input.status ?? "pending",
      required: input.required ?? true,
      linked_step_ids: input.linkedStepIds ?? [],
      linked_task_ids: input.linkedTaskIds ?? [],
      verification_ids: input.verificationIds ?? [],
      created_at: timestamp,
      updated_at: timestamp,
    }),
  });
  return data.criterion;
}

export async function createPlanVerification(plan: UserPlanViewModel, input: CreatePlanVerificationInput): Promise<Record<string, unknown>> {
  const planKey = await decryptPlanKey(plan);
  const timestamp = nowSeconds();
  const taskKey = input.createTask ? generateEmbedKey() : null;
  const encryptedTaskKey = taskKey ? await encryptChatKeyWithMasterKey(taskKey) : null;
  const data = await requestJson<{ verification: Record<string, unknown> }>(`/v1/user-plans/${plan.plan_id}/verification`, {
    method: "POST",
    body: JSON.stringify({
      verification_id: input.verificationId ?? crypto.randomUUID(),
      kind: input.kind,
      phase: input.phase ?? "final",
      status: input.status ?? "pending",
      required_for_done: input.requiredForDone ?? true,
      covers: input.covers ?? [],
      threshold: input.threshold ?? null,
      assigned_to: input.assignedTo ?? null,
      create_task: input.createTask ?? false,
      task_id: input.taskId ?? null,
      encrypted_task_key: encryptedTaskKey,
      encrypted_title: await encryptWithEmbedKey(input.title ?? "", taskKey ?? planKey),
      encrypted_command: await encryptWithEmbedKey(input.command ?? "", planKey),
      encrypted_evaluation_prompt: await encryptWithEmbedKey(input.evaluationPrompt ?? "", planKey),
      encrypted_expected_result: await encryptWithEmbedKey(input.expectedResult ?? "", planKey),
      primary_chat_id: input.primaryChatId ?? plan.primaryChatId,
      linked_project_ids: input.linkedProjectIds ?? plan.linkedProjectIds,
      plan_step_id: input.planStepId ?? plan.currentStepId,
      assignee_type: input.assigneeType ?? "user",
      created_at: timestamp,
      updated_at: timestamp,
    }),
  });
  return data.verification;
}

export async function addPlanVerificationEvidence(
  plan: UserPlanViewModel,
  verificationId: string,
  input: PlanVerificationEvidenceInput,
): Promise<Record<string, unknown>> {
  const planKey = await decryptPlanKey(plan);
  const data = await requestJson<{ verification: Record<string, unknown> }>(`/v1/user-plans/${plan.plan_id}/verification/${verificationId}/evidence`, {
    method: "POST",
    body: JSON.stringify({
      status: input.status,
      score: input.score ?? null,
      threshold: input.threshold ?? null,
      confidence: input.confidence ?? null,
      run_id: input.runId ?? null,
      encrypted_result_summary: await encryptWithEmbedKey(input.resultSummary ?? "", planKey),
      encrypted_required_fixes: await encryptWithEmbedKey(input.requiredFixes ?? "", planKey),
      updated_at: nowSeconds(),
    }),
  });
  return data.verification;
}
