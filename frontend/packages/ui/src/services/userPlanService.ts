// frontend/packages/ui/src/services/userPlanService.ts
// Client-side Plans V1 service. Durable plan content is encrypted with a
// per-plan key wrapped by the user's master key; the backend receives only
// ciphertext plus minimal metadata for filtering, linking, and verification.
// Spec: docs/specs/plans-v1/spec.yml

import { getApiEndpoint } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
  wrapEmbedKeyWithChatKey,
} from "./cryptoService";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { listProjects } from "./projectService";

export type UserPlanStatus = "draft" | "awaiting_confirmation" | "active" | "executing" | "blocked" | "completed" | "archived";
export type UserPlanCriterionStatus = "pending" | "satisfied" | "failed" | "waived";
export type UserPlanVerificationStatus = "pending" | "passed" | "failed" | "passed_unexpectedly" | "skipped" | "waived";
export type UserPlanKeyWrapperType = "master" | "chat" | "project";

export type UserPlanAssumptionStatus = "unchecked" | "checking" | "confirmed" | "corrected" | "blocked" | "waived";
export type UserPlanReferencePatternStatus = "proposed" | "confirmed" | "blocked" | "waived";

export interface UserPlanKeyWrapperRecord {
  key_type: UserPlanKeyWrapperType;
  encrypted_plan_key: string;
  hashed_chat_id?: string | null;
  hashed_project_id?: string | null;
  created_at: number;
  expires_at?: number | null;
}

export interface UserTaskKeyWrapperRecord {
  key_type: UserPlanKeyWrapperType;
  encrypted_task_key: string;
  hashed_chat_id?: string | null;
  hashed_project_id?: string | null;
  created_at: number;
  expires_at?: number | null;
}

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
  linked_project_hashes?: string[] | null;
  encrypted_linked_project_ids?: string | null;
  current_phase_id?: string | null;
  current_step_id?: string | null;
  current_task_id?: string | null;
  planner_focus_id?: string | null;
  version?: number;
  created_at: number;
  updated_at: number;
  completed_at?: number | null;
  key_wrappers?: UserPlanKeyWrapperRecord[];
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

export interface EncryptedUserPlanCriterionRecord {
  criterion_id: string;
  type?: string | null;
  status: UserPlanCriterionStatus;
  required?: boolean | null;
  linked_step_ids?: string[] | null;
  linked_task_ids?: string[] | null;
  verification_ids?: string[] | null;
  coverage_status?: string | null;
  verification_scope?: string | null;
  version?: number | null;
  created_at?: number | null;
  updated_at?: number | null;
  encrypted_text?: string | null;
  encrypted_evidence?: string | null;
  encrypted_coverage_note?: string | null;
  encrypted_waiver_reason?: string | null;
}

export interface UserPlanCriterionViewModel {
  criterionId: string;
  text: string;
  type: string;
  status: UserPlanCriterionStatus;
  required: boolean;
  linkedStepIds: string[];
  linkedTaskIds: string[];
  verificationIds: string[];
  coverageStatus: string;
  verificationScope: string;
  evidence: string;
  coverageNote: string;
  waiverReason: string;
  version: number;
  createdAt: number | null;
  updatedAt: number | null;
  encrypted: EncryptedUserPlanCriterionRecord;
}

export interface EncryptedUserPlanVerificationRecord {
  verification_id: string;
  kind: string;
  phase?: string | null;
  status: UserPlanVerificationStatus;
  required_for_done?: boolean | null;
  covers?: string[] | null;
  lifecycle_status?: string | null;
  source_hash?: string | null;
  threshold?: number | null;
  score?: number | null;
  confidence?: string | null;
  linked_task_id?: string | null;
  linked_sub_chat_id?: string | null;
  source_embed_id?: string | null;
  runner_kind?: string | null;
  run_id?: string | null;
  created_at?: number | null;
  updated_at?: number | null;
  encrypted_description?: string | null;
  encrypted_command?: string | null;
  encrypted_evaluation_prompt?: string | null;
  encrypted_evaluator_instructions?: string | null;
  encrypted_expected_result?: string | null;
  encrypted_result_summary?: string | null;
  encrypted_required_fixes?: string | null;
  encrypted_source_path?: string | null;
  encrypted_red_phase_reason?: string | null;
}

export interface UserPlanVerificationViewModel {
  verificationId: string;
  kind: string;
  phase: string;
  status: UserPlanVerificationStatus;
  requiredForDone: boolean;
  covers: string[];
  lifecycleStatus: string;
  sourceHash: string | null;
  threshold: number | null;
  score: number | null;
  confidence: string | null;
  linkedTaskId: string | null;
  linkedSubChatId: string | null;
  sourceEmbedId: string | null;
  runnerKind: string | null;
  runId: string | null;
  description: string;
  command: string;
  evaluationPrompt: string;
  evaluatorInstructions: string;
  expectedResult: string;
  resultSummary: string;
  requiredFixes: string;
  sourcePath: string;
  redPhaseReason: string;
  createdAt: number | null;
  updatedAt: number | null;
  encrypted: EncryptedUserPlanVerificationRecord;
}

export interface EncryptedUserPlanAssumptionRecord {
  assumption_id: string;
  category?: string | null;
  status: UserPlanAssumptionStatus;
  required_before?: string | null;
  linked_sub_chat_id?: string | null;
  linked_task_id?: string | null;
  linked_step_ids?: string[] | null;
  linked_criterion_ids?: string[] | null;
  source_count?: number | null;
  version?: number | null;
  created_at?: number | null;
  updated_at?: number | null;
  encrypted_text?: string | null;
  encrypted_corrected_text?: string | null;
  encrypted_evidence_summary?: string | null;
  encrypted_blocker_reason?: string | null;
  encrypted_waiver_reason?: string | null;
  encrypted_sources?: string | null;
}

export interface UserPlanAssumptionViewModel {
  assumptionId: string;
  text: string;
  category: string;
  status: UserPlanAssumptionStatus;
  requiredBefore: string;
  linkedSubChatId: string | null;
  linkedTaskId: string | null;
  linkedStepIds: string[];
  linkedCriterionIds: string[];
  sourceCount: number;
  correctedText: string;
  evidenceSummary: string;
  blockerReason: string;
  waiverReason: string;
  sources: string;
  version: number;
  createdAt: number | null;
  updatedAt: number | null;
  encrypted: EncryptedUserPlanAssumptionRecord;
}

export interface EncryptedUserPlanReferencePatternRecord {
  pattern_id: string;
  category?: string | null;
  status: UserPlanReferencePatternStatus;
  required_before?: string | null;
  source_count?: number | null;
  linked_task_ids?: string[] | null;
  linked_check_ids?: string[] | null;
  version?: number | null;
  created_at?: number | null;
  updated_at?: number | null;
  encrypted_title?: string | null;
  encrypted_description?: string | null;
  encrypted_sources?: string | null;
  encrypted_match_rules?: string | null;
  encrypted_anti_patterns?: string | null;
  encrypted_evidence_summary?: string | null;
  encrypted_waiver_reason?: string | null;
}

export interface UserPlanReferencePatternViewModel {
  patternId: string;
  title: string;
  description: string;
  category: string;
  status: UserPlanReferencePatternStatus;
  requiredBefore: string;
  sourceCount: number;
  linkedTaskIds: string[];
  linkedCheckIds: string[];
  sources: string;
  matchRules: string;
  antiPatterns: string;
  evidenceSummary: string;
  waiverReason: string;
  version: number;
  createdAt: number | null;
  updatedAt: number | null;
  encrypted: EncryptedUserPlanReferencePatternRecord;
}

export interface UserPlanDetailState {
  criteria: UserPlanCriterionViewModel[];
  verifications: UserPlanVerificationViewModel[];
  assumptions: UserPlanAssumptionViewModel[];
  referencePatterns: UserPlanReferencePatternViewModel[];
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

export interface CreatePlanAssumptionInput {
  assumptionId?: string;
  text: string;
  category?: string;
  status?: UserPlanAssumptionStatus;
  requiredBefore?: string;
  linkedSubChatId?: string | null;
  linkedTaskId?: string | null;
  linkedStepIds?: string[];
  linkedCriterionIds?: string[];
  sourceCount?: number;
  correctedText?: string;
  evidenceSummary?: string;
  blockerReason?: string;
  waiverReason?: string;
  sources?: string;
}

export interface UpdatePlanAssumptionInput {
  status?: UserPlanAssumptionStatus;
  requiredBefore?: string;
  linkedSubChatId?: string | null;
  linkedTaskId?: string | null;
  sourceCount?: number;
  correctedText?: string;
  evidenceSummary?: string;
  blockerReason?: string;
  waiverReason?: string;
  sources?: string;
}

export interface CreatePlanReferencePatternInput {
  patternId?: string;
  title: string;
  description?: string;
  category?: string;
  status?: UserPlanReferencePatternStatus;
  requiredBefore?: string;
  sourceCount?: number;
  linkedTaskIds?: string[];
  linkedCheckIds?: string[];
  sources?: string;
  matchRules?: string;
  antiPatterns?: string;
  evidenceSummary?: string;
  waiverReason?: string;
}

export interface UpdatePlanCriterionInput {
  status?: UserPlanCriterionStatus;
  evidence?: string;
  coverageNote?: string;
  waiverReason?: string;
  verificationIds?: string[];
  coverageStatus?: string;
  verificationScope?: string;
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

async function decryptStringArray(value: string | null | undefined, key: Uint8Array): Promise<string[]> {
  const text = await decryptOptional(value, key);
  if (!text) return [];
  const parsed = JSON.parse(text) as unknown;
  return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
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
    linkedProjectIds: await decryptStringArray(record.encrypted_linked_project_ids, planKey),
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

async function decryptCriterion(record: EncryptedUserPlanCriterionRecord, planKey: Uint8Array): Promise<UserPlanCriterionViewModel> {
  return {
    criterionId: record.criterion_id,
    text: await decryptOptional(record.encrypted_text, planKey),
    type: record.type ?? "functional",
    status: record.status,
    required: record.required ?? true,
    linkedStepIds: record.linked_step_ids ?? [],
    linkedTaskIds: record.linked_task_ids ?? [],
    verificationIds: record.verification_ids ?? [],
    coverageStatus: record.coverage_status ?? "uncovered",
    verificationScope: record.verification_scope ?? "",
    evidence: await decryptOptional(record.encrypted_evidence, planKey),
    coverageNote: await decryptOptional(record.encrypted_coverage_note, planKey),
    waiverReason: await decryptOptional(record.encrypted_waiver_reason, planKey),
    version: record.version ?? 1,
    createdAt: record.created_at ?? null,
    updatedAt: record.updated_at ?? null,
    encrypted: record,
  };
}

async function decryptVerification(record: EncryptedUserPlanVerificationRecord, planKey: Uint8Array): Promise<UserPlanVerificationViewModel> {
  return {
    verificationId: record.verification_id,
    kind: record.kind,
    phase: record.phase ?? "final",
    status: record.status,
    requiredForDone: record.required_for_done ?? true,
    covers: record.covers ?? [],
    lifecycleStatus: record.lifecycle_status ?? "proposed",
    sourceHash: record.source_hash ?? null,
    threshold: record.threshold ?? null,
    score: record.score ?? null,
    confidence: record.confidence ?? null,
    linkedTaskId: record.linked_task_id ?? null,
    linkedSubChatId: record.linked_sub_chat_id ?? null,
    sourceEmbedId: record.source_embed_id ?? null,
    runnerKind: record.runner_kind ?? null,
    runId: record.run_id ?? null,
    description: await decryptOptional(record.encrypted_description, planKey),
    command: await decryptOptional(record.encrypted_command, planKey),
    evaluationPrompt: await decryptOptional(record.encrypted_evaluation_prompt, planKey),
    evaluatorInstructions: await decryptOptional(record.encrypted_evaluator_instructions, planKey),
    expectedResult: await decryptOptional(record.encrypted_expected_result, planKey),
    resultSummary: await decryptOptional(record.encrypted_result_summary, planKey),
    requiredFixes: await decryptOptional(record.encrypted_required_fixes, planKey),
    sourcePath: await decryptOptional(record.encrypted_source_path, planKey),
    redPhaseReason: await decryptOptional(record.encrypted_red_phase_reason, planKey),
    createdAt: record.created_at ?? null,
    updatedAt: record.updated_at ?? null,
    encrypted: record,
  };
}

async function decryptAssumption(record: EncryptedUserPlanAssumptionRecord, planKey: Uint8Array): Promise<UserPlanAssumptionViewModel> {
  return {
    assumptionId: record.assumption_id,
    text: await decryptOptional(record.encrypted_text, planKey),
    category: record.category ?? "other",
    status: record.status,
    requiredBefore: record.required_before ?? "implementation",
    linkedSubChatId: record.linked_sub_chat_id ?? null,
    linkedTaskId: record.linked_task_id ?? null,
    linkedStepIds: record.linked_step_ids ?? [],
    linkedCriterionIds: record.linked_criterion_ids ?? [],
    sourceCount: record.source_count ?? 0,
    correctedText: await decryptOptional(record.encrypted_corrected_text, planKey),
    evidenceSummary: await decryptOptional(record.encrypted_evidence_summary, planKey),
    blockerReason: await decryptOptional(record.encrypted_blocker_reason, planKey),
    waiverReason: await decryptOptional(record.encrypted_waiver_reason, planKey),
    sources: await decryptOptional(record.encrypted_sources, planKey),
    version: record.version ?? 1,
    createdAt: record.created_at ?? null,
    updatedAt: record.updated_at ?? null,
    encrypted: record,
  };
}

async function decryptReferencePattern(record: EncryptedUserPlanReferencePatternRecord, planKey: Uint8Array): Promise<UserPlanReferencePatternViewModel> {
  return {
    patternId: record.pattern_id,
    title: await decryptOptional(record.encrypted_title, planKey),
    description: await decryptOptional(record.encrypted_description, planKey),
    category: record.category ?? "other",
    status: record.status,
    requiredBefore: record.required_before ?? "implementation",
    sourceCount: record.source_count ?? 0,
    linkedTaskIds: record.linked_task_ids ?? [],
    linkedCheckIds: record.linked_check_ids ?? [],
    sources: await decryptOptional(record.encrypted_sources, planKey),
    matchRules: await decryptOptional(record.encrypted_match_rules, planKey),
    antiPatterns: await decryptOptional(record.encrypted_anti_patterns, planKey),
    evidenceSummary: await decryptOptional(record.encrypted_evidence_summary, planKey),
    waiverReason: await decryptOptional(record.encrypted_waiver_reason, planKey),
    version: record.version ?? 1,
    createdAt: record.created_at ?? null,
    updatedAt: record.updated_at ?? null,
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

async function loadProjectKeys(linkedProjectIds: string[]): Promise<Array<{ projectId: string; projectKey: Uint8Array }>> {
  if (linkedProjectIds.length === 0) return [];

  const projects = await listProjects();
  const projectKeys: Array<{ projectId: string; projectKey: Uint8Array }> = [];
  for (const projectId of linkedProjectIds) {
    const project = projects.find((candidate) => candidate.project_id === projectId);
    if (!project) throw new Error(`Could not find project key for linked project ${projectId}`);
    projectKeys.push({ projectId, projectKey: project.projectKey });
  }
  return projectKeys;
}

async function buildPlanKeyWrappers(
  planKey: Uint8Array,
  encryptedPlanKey: string,
  timestamp: number,
  primaryChatId: string | null,
  linkedProjectIds: string[],
): Promise<UserPlanKeyWrapperRecord[]> {
  const wrappers: UserPlanKeyWrapperRecord[] = [
    { key_type: "master", encrypted_plan_key: encryptedPlanKey, created_at: timestamp },
  ];
  if (primaryChatId) {
    const chatKey = await chatKeyManager.getKey(primaryChatId);
    if (!chatKey) throw new Error(`Could not find chat key for primary chat ${primaryChatId}`);
    wrappers.push({
      key_type: "chat",
      hashed_chat_id: await computeSHA256(primaryChatId),
      encrypted_plan_key: await wrapEmbedKeyWithChatKey(planKey, chatKey),
      created_at: timestamp,
    });
  }
  for (const project of await loadProjectKeys(linkedProjectIds)) {
    wrappers.push({
      key_type: "project",
      hashed_project_id: await computeSHA256(project.projectId),
      encrypted_plan_key: await wrapEmbedKeyWithChatKey(planKey, project.projectKey),
      created_at: timestamp,
    });
  }
  return wrappers;
}

async function buildTaskKeyWrappers(
  taskKey: Uint8Array,
  encryptedTaskKey: string,
  timestamp: number,
  primaryChatId: string | null,
  linkedProjectIds: string[],
): Promise<UserTaskKeyWrapperRecord[]> {
  const wrappers: UserTaskKeyWrapperRecord[] = [
    { key_type: "master", encrypted_task_key: encryptedTaskKey, created_at: timestamp },
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
  for (const project of await loadProjectKeys(linkedProjectIds)) {
    wrappers.push({
      key_type: "project",
      hashed_project_id: await computeSHA256(project.projectId),
      encrypted_task_key: await wrapEmbedKeyWithChatKey(taskKey, project.projectKey),
      created_at: timestamp,
    });
  }
  return wrappers;
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
  const linkedProjectIds = input.linkedProjectIds ?? [];
  const primaryChatId = input.primaryChatId ?? null;
  const body: EncryptedUserPlanRecord = {
    plan_id: crypto.randomUUID(),
    encrypted_plan_key: encryptedPlanKey,
    ...(await encryptPlanFields(input, planKey)),
    encrypted_linked_project_ids: await encryptWithEmbedKey(JSON.stringify(linkedProjectIds), planKey),
    status: input.status ?? "draft",
    primary_chat_id: primaryChatId,
    linked_project_ids: linkedProjectIds,
    current_phase_id: input.currentPhaseId ?? null,
    current_step_id: input.currentStepId ?? null,
    current_task_id: input.currentTaskId ?? null,
    planner_focus_id: input.plannerFocusId ?? null,
    created_at: timestamp,
    updated_at: timestamp,
    key_wrappers: await buildPlanKeyWrappers(planKey, encryptedPlanKey, timestamp, primaryChatId, linkedProjectIds),
  };
  const data = await requestJson<{ plan: EncryptedUserPlanRecord }>("/v1/user-plans", {
    method: "POST",
    body: JSON.stringify(body),
  });
  const decrypted = await decryptPlan(data.plan);
  if (!decrypted) throw new Error("Created plan could not be decrypted");
  return decrypted;
}

export async function listUserPlanKeyWrappers(planId: string): Promise<UserPlanKeyWrapperRecord[]> {
  const data = await requestJson<{ key_wrappers: UserPlanKeyWrapperRecord[] }>(`/v1/user-plans/${planId}/key-wrappers`);
  return data.key_wrappers;
}

export async function addUserPlanKeyWrappers(planId: string, keyWrappers: UserPlanKeyWrapperRecord[]): Promise<UserPlanKeyWrapperRecord[]> {
  const data = await requestJson<{ key_wrappers: UserPlanKeyWrapperRecord[] }>(`/v1/user-plans/${planId}/key-wrappers`, {
    method: "POST",
    body: JSON.stringify({ key_wrappers: keyWrappers }),
  });
  return data.key_wrappers;
}

export async function updateUserPlan(plan: UserPlanViewModel, patch: Partial<CreateUserPlanInput> & { status?: UserPlanStatus }): Promise<UserPlanViewModel> {
  const planKey = await decryptPlanKey(plan);
  const encryptedPlanKey = plan.encrypted.encrypted_plan_key;
  if (!encryptedPlanKey) throw new Error("Missing encrypted plan key");
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
  if (patch.linkedProjectIds !== undefined) body.encrypted_linked_project_ids = await encryptWithEmbedKey(JSON.stringify(patch.linkedProjectIds), planKey);
  if (patch.status !== undefined) body.status = patch.status;
  if (patch.primaryChatId !== undefined) body.primary_chat_id = patch.primaryChatId;
  if (patch.linkedProjectIds !== undefined) body.linked_project_ids = patch.linkedProjectIds;
  if (patch.linkedProjectIds !== undefined || patch.primaryChatId !== undefined) {
    const updatedPrimaryChatId = patch.primaryChatId !== undefined ? patch.primaryChatId : plan.primaryChatId;
    const updatedLinkedProjectIds = patch.linkedProjectIds !== undefined ? patch.linkedProjectIds : plan.linkedProjectIds;
    body.key_wrappers = await buildPlanKeyWrappers(planKey, encryptedPlanKey, nowSeconds(), updatedPrimaryChatId ?? null, updatedLinkedProjectIds);
  }
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

export async function listPlanCriteria(plan: UserPlanViewModel): Promise<UserPlanCriterionViewModel[]> {
  const planKey = await decryptPlanKey(plan);
  const data = await requestJson<{ criteria: EncryptedUserPlanCriterionRecord[] }>(`/v1/user-plans/${plan.plan_id}/criteria`);
  return Promise.all(data.criteria.map((record) => decryptCriterion(record, planKey)));
}

export async function listPlanVerifications(plan: UserPlanViewModel): Promise<UserPlanVerificationViewModel[]> {
  const planKey = await decryptPlanKey(plan);
  const data = await requestJson<{ verifications: EncryptedUserPlanVerificationRecord[] }>(`/v1/user-plans/${plan.plan_id}/verification`);
  return Promise.all(data.verifications.map((record) => decryptVerification(record, planKey)));
}

export async function listPlanAssumptions(plan: UserPlanViewModel): Promise<UserPlanAssumptionViewModel[]> {
  const planKey = await decryptPlanKey(plan);
  const data = await requestJson<{ assumptions: EncryptedUserPlanAssumptionRecord[] }>(`/v1/user-plans/${plan.plan_id}/assumptions`);
  return Promise.all(data.assumptions.map((record) => decryptAssumption(record, planKey)));
}

export async function listPlanReferencePatterns(plan: UserPlanViewModel): Promise<UserPlanReferencePatternViewModel[]> {
  const planKey = await decryptPlanKey(plan);
  const data = await requestJson<{ reference_patterns: EncryptedUserPlanReferencePatternRecord[] }>(`/v1/user-plans/${plan.plan_id}/reference-patterns`);
  return Promise.all(data.reference_patterns.map((record) => decryptReferencePattern(record, planKey)));
}

export async function loadUserPlanDetailState(plan: UserPlanViewModel): Promise<UserPlanDetailState> {
  const [criteria, verifications, assumptions, referencePatterns] = await Promise.all([
    listPlanCriteria(plan),
    listPlanVerifications(plan),
    listPlanAssumptions(plan),
    listPlanReferencePatterns(plan),
  ]);
  return { criteria, verifications, assumptions, referencePatterns };
}

export async function createPlanCriterion(plan: UserPlanViewModel, input: CreatePlanCriterionInput): Promise<UserPlanCriterionViewModel> {
  const planKey = await decryptPlanKey(plan);
  const timestamp = nowSeconds();
  const data = await requestJson<{ criterion: EncryptedUserPlanCriterionRecord }>(`/v1/user-plans/${plan.plan_id}/criteria`, {
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
      coverage_status: input.verificationIds?.length ? "covered" : "uncovered",
      created_at: timestamp,
      updated_at: timestamp,
    }),
  });
  return decryptCriterion(data.criterion, planKey);
}

export async function updatePlanCriterion(
  plan: UserPlanViewModel,
  criterionId: string,
  input: UpdatePlanCriterionInput,
): Promise<UserPlanCriterionViewModel> {
  const planKey = await decryptPlanKey(plan);
  const body: Record<string, unknown> = { updated_at: nowSeconds() };
  if (input.status !== undefined) body.status = input.status;
  if (input.evidence !== undefined) body.encrypted_evidence = await encryptWithEmbedKey(input.evidence, planKey);
  if (input.coverageNote !== undefined) body.encrypted_coverage_note = await encryptWithEmbedKey(input.coverageNote, planKey);
  if (input.waiverReason !== undefined) body.encrypted_waiver_reason = await encryptWithEmbedKey(input.waiverReason, planKey);
  if (input.verificationIds !== undefined) body.verification_ids = input.verificationIds;
  if (input.coverageStatus !== undefined) body.coverage_status = input.coverageStatus;
  if (input.verificationScope !== undefined) body.verification_scope = input.verificationScope;

  const data = await requestJson<{ criterion: EncryptedUserPlanCriterionRecord }>(`/v1/user-plans/${plan.plan_id}/criteria/${criterionId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return decryptCriterion(data.criterion, planKey);
}

export async function createPlanVerification(plan: UserPlanViewModel, input: CreatePlanVerificationInput): Promise<UserPlanVerificationViewModel> {
  const planKey = await decryptPlanKey(plan);
  const timestamp = nowSeconds();
  const taskKey = input.createTask ? generateEmbedKey() : null;
  const encryptedTaskKey = taskKey ? await encryptChatKeyWithMasterKey(taskKey) : null;
  const linkedProjectIds = input.linkedProjectIds ?? plan.linkedProjectIds;
  const primaryChatId = input.primaryChatId ?? plan.primaryChatId;
  const data = await requestJson<{ verification: EncryptedUserPlanVerificationRecord }>(`/v1/user-plans/${plan.plan_id}/verification`, {
    method: "POST",
    body: JSON.stringify({
      verification_id: input.verificationId ?? crypto.randomUUID(),
      kind: input.kind,
      phase: input.phase ?? "final",
      status: input.status ?? "pending",
      lifecycle_status: "proposed",
      required_for_done: input.requiredForDone ?? true,
      covers: input.covers ?? [],
      threshold: input.threshold ?? null,
      assigned_to: input.assignedTo ?? null,
      create_task: input.createTask ?? false,
      task_id: input.taskId ?? null,
      encrypted_task_key: encryptedTaskKey,
      task_key_wrappers: taskKey && encryptedTaskKey
        ? await buildTaskKeyWrappers(taskKey, encryptedTaskKey, timestamp, primaryChatId, linkedProjectIds)
        : [],
      encrypted_linked_project_ids: taskKey
        ? await encryptWithEmbedKey(JSON.stringify(linkedProjectIds), taskKey)
        : null,
      encrypted_title: await encryptWithEmbedKey(input.title ?? "", taskKey ?? planKey),
      encrypted_description: await encryptWithEmbedKey(input.title ?? "", planKey),
      encrypted_command: await encryptWithEmbedKey(input.command ?? "", planKey),
      encrypted_evaluation_prompt: await encryptWithEmbedKey(input.evaluationPrompt ?? "", planKey),
      encrypted_expected_result: await encryptWithEmbedKey(input.expectedResult ?? "", planKey),
      primary_chat_id: primaryChatId,
      linked_project_ids: linkedProjectIds,
      plan_step_id: input.planStepId ?? plan.currentStepId,
      assignee_type: input.assigneeType ?? "user",
      created_at: timestamp,
      updated_at: timestamp,
    }),
  });
  return decryptVerification(data.verification, planKey);
}

export async function addPlanVerificationEvidence(
  plan: UserPlanViewModel,
  verificationId: string,
  input: PlanVerificationEvidenceInput,
): Promise<UserPlanVerificationViewModel> {
  const planKey = await decryptPlanKey(plan);
  const data = await requestJson<{ verification: EncryptedUserPlanVerificationRecord }>(`/v1/user-plans/${plan.plan_id}/verification/${verificationId}/evidence`, {
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
  return decryptVerification(data.verification, planKey);
}

export async function createPlanAssumption(plan: UserPlanViewModel, input: CreatePlanAssumptionInput): Promise<UserPlanAssumptionViewModel> {
  const planKey = await decryptPlanKey(plan);
  const timestamp = nowSeconds();
  const data = await requestJson<{ assumption: EncryptedUserPlanAssumptionRecord }>(`/v1/user-plans/${plan.plan_id}/assumptions`, {
    method: "POST",
    body: JSON.stringify({
      assumption_id: input.assumptionId ?? crypto.randomUUID(),
      encrypted_text: await encryptWithEmbedKey(input.text, planKey),
      category: input.category ?? "other",
      status: input.status ?? "unchecked",
      required_before: input.requiredBefore ?? "implementation",
      linked_sub_chat_id: input.linkedSubChatId ?? null,
      linked_task_id: input.linkedTaskId ?? null,
      linked_step_ids: input.linkedStepIds ?? [],
      linked_criterion_ids: input.linkedCriterionIds ?? [],
      source_count: input.sourceCount ?? 0,
      encrypted_corrected_text: await encryptWithEmbedKey(input.correctedText ?? "", planKey),
      encrypted_evidence_summary: await encryptWithEmbedKey(input.evidenceSummary ?? "", planKey),
      encrypted_blocker_reason: await encryptWithEmbedKey(input.blockerReason ?? "", planKey),
      encrypted_waiver_reason: await encryptWithEmbedKey(input.waiverReason ?? "", planKey),
      encrypted_sources: await encryptWithEmbedKey(input.sources ?? "", planKey),
      created_at: timestamp,
      updated_at: timestamp,
    }),
  });
  return decryptAssumption(data.assumption, planKey);
}

export async function updatePlanAssumption(
  plan: UserPlanViewModel,
  assumptionId: string,
  input: UpdatePlanAssumptionInput,
): Promise<UserPlanAssumptionViewModel> {
  const planKey = await decryptPlanKey(plan);
  const body: Record<string, unknown> = { updated_at: nowSeconds() };
  if (input.status !== undefined) body.status = input.status;
  if (input.requiredBefore !== undefined) body.required_before = input.requiredBefore;
  if (input.linkedSubChatId !== undefined) body.linked_sub_chat_id = input.linkedSubChatId;
  if (input.linkedTaskId !== undefined) body.linked_task_id = input.linkedTaskId;
  if (input.sourceCount !== undefined) body.source_count = input.sourceCount;
  if (input.correctedText !== undefined) body.encrypted_corrected_text = await encryptWithEmbedKey(input.correctedText, planKey);
  if (input.evidenceSummary !== undefined) body.encrypted_evidence_summary = await encryptWithEmbedKey(input.evidenceSummary, planKey);
  if (input.blockerReason !== undefined) body.encrypted_blocker_reason = await encryptWithEmbedKey(input.blockerReason, planKey);
  if (input.waiverReason !== undefined) body.encrypted_waiver_reason = await encryptWithEmbedKey(input.waiverReason, planKey);
  if (input.sources !== undefined) body.encrypted_sources = await encryptWithEmbedKey(input.sources, planKey);

  const data = await requestJson<{ assumption: EncryptedUserPlanAssumptionRecord }>(`/v1/user-plans/${plan.plan_id}/assumptions/${assumptionId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return decryptAssumption(data.assumption, planKey);
}

export async function createPlanReferencePattern(plan: UserPlanViewModel, input: CreatePlanReferencePatternInput): Promise<UserPlanReferencePatternViewModel> {
  const planKey = await decryptPlanKey(plan);
  const timestamp = nowSeconds();
  const data = await requestJson<{ reference_pattern: EncryptedUserPlanReferencePatternRecord }>(`/v1/user-plans/${plan.plan_id}/reference-patterns`, {
    method: "POST",
    body: JSON.stringify({
      pattern_id: input.patternId ?? crypto.randomUUID(),
      encrypted_title: await encryptWithEmbedKey(input.title, planKey),
      encrypted_description: await encryptWithEmbedKey(input.description ?? "", planKey),
      category: input.category ?? "other",
      status: input.status ?? "proposed",
      required_before: input.requiredBefore ?? "implementation",
      source_count: input.sourceCount ?? 0,
      linked_task_ids: input.linkedTaskIds ?? [],
      linked_check_ids: input.linkedCheckIds ?? [],
      encrypted_sources: await encryptWithEmbedKey(input.sources ?? "", planKey),
      encrypted_match_rules: await encryptWithEmbedKey(input.matchRules ?? "", planKey),
      encrypted_anti_patterns: await encryptWithEmbedKey(input.antiPatterns ?? "", planKey),
      encrypted_evidence_summary: await encryptWithEmbedKey(input.evidenceSummary ?? "", planKey),
      encrypted_waiver_reason: await encryptWithEmbedKey(input.waiverReason ?? "", planKey),
      created_at: timestamp,
      updated_at: timestamp,
    }),
  });
  return decryptReferencePattern(data.reference_pattern, planKey);
}
