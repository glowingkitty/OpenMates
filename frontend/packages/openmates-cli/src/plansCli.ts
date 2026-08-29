/*
 * OpenMates CLI plan helpers.
 *
 * Purpose: decrypt/encrypt user-facing plan records and render command output.
 * Architecture: command handlers stay in cli.ts; this module owns local plan
 * view models and payload preparation for /v1/user-plans.
 * Security: plan text fields are decrypted locally with a user's master-wrapped
 * per-plan key; ciphertext is never normal CLI output.
 * Spec: docs/specs/plans-v1/spec.yml.
 */

import { createHash, randomBytes, randomUUID } from "node:crypto";

import type {
  UserPlanCreateInput,
  UserPlanCriterionRecord,
  UserPlanLearningLevel,
  UserPlanLearningRecord,
  UserPlanLearningStatus,
  UserPlanLearningTargetKind,
  UserPlanLearningType,
  UserPlanRecord,
  UserPlanStatus,
  UserPlanUpdateInput,
  UserPlanVerificationRecord,
  UserPlanVerificationStatus,
} from "./client.js";
import {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
} from "./crypto.js";
import {
  buildEncryptedObjectSlugMetadata,
  decryptObjectSlug,
  objectSlugMatches,
} from "./objectSlugs.js";

const PLAN_STATUSES: UserPlanStatus[] = ["draft", "checking_assumptions", "awaiting_confirmation", "active", "executing", "running_checks", "blocked", "completed", "archived"];
const LEARNING_TYPES: UserPlanLearningType[] = ["workflow_improvement", "agent_instruction_improvement"];
const LEARNING_TARGET_KINDS: UserPlanLearningTargetKind[] = ["workflow", "project_agent_instructions"];
const LEARNING_STATUSES: UserPlanLearningStatus[] = ["draft", "proposed", "accepted", "applied", "rejected", "duplicate", "merged"];
const LEARNING_LEVELS: UserPlanLearningLevel[] = ["low", "medium", "high"];
const FINALIZED_LEARNING_STATUSES = new Set<UserPlanLearningStatus>(["proposed", "accepted", "applied"]);
const DEFAULT_PLAN_PREFIX = "PLAN";

export type UserPlanEvidenceReference =
  | { kind: "embed"; embed_id: string; start_line?: number; end_line?: number }
  | { kind: "file"; path: string; start_line?: number; end_line?: number }
  | { kind: "url"; url: string };
export interface UserPlanFlow {
  flow_id: string;
  title: string;
  actor?: string;
  steps: Array<{ step_id: string; text: string; references?: UserPlanEvidenceReference[] }>;
  expected_outcome: string;
  linked_task_ids?: string[];
  linked_criterion_ids?: string[];
}

function validateUserFlows(value: UserPlanFlow[]): UserPlanFlow[] {
  for (const flow of value) {
    if (!flow.flow_id || !flow.title || !flow.expected_outcome || !Array.isArray(flow.steps) || flow.steps.some((step) => !step.step_id || !step.text)) {
      throw new Error("Each user flow requires flow_id, title, ordered steps, and expected_outcome.");
    }
    for (const step of flow.steps) for (const reference of step.references ?? []) validateEvidenceReference(reference);
  }
  return value;
}

function validateEvidenceReference(reference: UserPlanEvidenceReference): void {
  if (reference.kind === "url") {
    if (new URL(reference.url).protocol !== "https:") throw new Error("Plan evidence URLs must use HTTPS.");
    return;
  }
  if (reference.kind === "embed") {
    if (!reference.embed_id.trim()) throw new Error("Plan evidence embed IDs must not be empty.");
  } else if (!reference.path || reference.path.startsWith("/") || reference.path.split("/").includes("..")) {
    throw new Error("Plan evidence file paths must be repository-relative.");
  }
  if (reference.start_line !== undefined && (!Number.isInteger(reference.start_line) || reference.start_line < 1)) {
    throw new Error("Plan evidence start_line must be a positive integer.");
  }
  if (reference.end_line !== undefined && (!Number.isInteger(reference.end_line) || reference.end_line < (reference.start_line ?? 1))) {
    throw new Error("Plan evidence end_line must be greater than or equal to start_line.");
  }
}

export interface DecryptedUserPlan {
  planId: string;
  shortId: string;
  slug: string;
  title: string;
  goal: string;
  scopeIn: string;
  scopeOut: string;
  userFlows: UserPlanFlow[];
  assumptions: string;
  openQuestions: string;
  constraints: string;
  decisions: string;
  risks: string;
  referencePatterns: string;
  context: string;
  status: UserPlanStatus;
  primaryChatId: string | null;
  linkedProjectIds: string[];
  plannerFocusId: string | null;
  version: number;
  createdAt: number;
  updatedAt: number;
  completedAt: number | null;
  encrypted: UserPlanRecord;
}

export interface DecryptedPlanLearning {
  learningId: string;
  type: UserPlanLearningType;
  targetKind: UserPlanLearningTargetKind;
  status: UserPlanLearningStatus;
  severity: UserPlanLearningLevel | null;
  confidence: UserPlanLearningLevel | null;
  linkedTaskIds: string[];
  linkedCheckIds: string[];
  appliedTaskId: string | null;
  title: string;
  observation: string;
  rootCause: string;
  suggestedChange: string;
  evidenceSummary: string;
  taskDraft: string;
  rejectionReason: string;
  version: number;
  createdAt: number;
  updatedAt: number;
  encrypted: UserPlanLearningRecord;
}

export interface PlanCreateOptions {
  /** Stable ID is used only by validated local recovery restoration. */
  planId?: string;
  title: string;
  goal: string;
  scopeIn?: string;
  scopeOut?: string;
  userFlows?: UserPlanFlow[];
  assumptions?: string;
  openQuestions?: string;
  constraints?: string;
  decisions?: string;
  risks?: string;
  referencePatterns?: string;
  context?: string;
  status?: UserPlanStatus;
  primaryChatId?: string | null;
  primaryChatKey?: Uint8Array | null;
  linkedProjectIds?: string[];
  linkedProjectKeys?: PlanProjectKey[];
  plannerFocusId?: string | null;
  slug?: string;
}

export interface PlanUpdateOptions {
  title?: string;
  goal?: string;
  scopeIn?: string;
  scopeOut?: string;
  userFlows?: UserPlanFlow[];
  assumptions?: string;
  openQuestions?: string;
  constraints?: string;
  decisions?: string;
  risks?: string;
  referencePatterns?: string;
  context?: string;
  status?: UserPlanStatus;
  primaryChatId?: string | null;
  primaryChatKey?: Uint8Array | null;
  linkedProjectIds?: string[];
  linkedProjectKeys?: PlanProjectKey[];
  plannerFocusId?: string | null;
  slug?: string;
}

export interface PlanProjectKey {
  projectId: string;
  projectKey: Uint8Array;
}

export interface PlanCriterionCreateOptions {
  criterionId?: string;
  text: string;
  type?: string;
  status?: string;
  required?: boolean;
  linkedTaskIds?: string[];
  verificationIds?: string[];
}

export interface PlanVerificationCreateOptions {
  verificationId?: string;
  kind: string;
  phase?: string;
  status?: UserPlanVerificationStatus;
  requiredForDone?: boolean;
  covers?: string[];
  threshold?: number | null;
  score?: number | null;
  confidence?: string | null;
  linkedTaskId?: string | null;
  runId?: string | null;
  command?: string;
  evaluationPrompt?: string;
  expectedResult?: string;
}

export interface PlanVerificationEvidenceOptions {
  status: UserPlanVerificationStatus;
  score?: number | null;
  threshold?: number | null;
  confidence?: string | null;
  runId?: string | null;
  resultSummary?: string;
  requiredFixes?: string;
}

export interface PlanVerificationUpdateOptions {
  kind?: string;
  phase?: string;
  status?: UserPlanVerificationStatus;
  lifecycleStatus?: string | null;
  requiredForDone?: boolean;
  covers?: string[];
  sourceHash?: string | null;
  threshold?: number | null;
  score?: number | null;
  confidence?: string | null;
  linkedSubChatId?: string | null;
  sourceEmbedId?: string | null;
  runnerKind?: string | null;
  description?: string;
  command?: string;
  evaluationPrompt?: string;
  evaluatorInstructions?: string;
  expectedResult?: string;
  sourcePath?: string;
  redPhaseReason?: string;
}

export interface PlanLearningCreateOptions {
  learningId?: string;
  type: UserPlanLearningType;
  targetKind: UserPlanLearningTargetKind;
  status?: UserPlanLearningStatus;
  severity?: UserPlanLearningLevel | null;
  confidence?: UserPlanLearningLevel | null;
  linkedTaskIds?: string[];
  linkedCheckIds?: string[];
  title: string;
  observation?: string;
  rootCause?: string;
  suggestedChange?: string;
  evidenceSummary?: string;
  taskDraft?: string;
  rejectionReason?: string;
}

export interface PlanLearningUpdateOptions {
  status?: UserPlanLearningStatus;
  severity?: UserPlanLearningLevel | null;
  confidence?: UserPlanLearningLevel | null;
  linkedTaskIds?: string[];
  linkedCheckIds?: string[];
  appliedTaskId?: string | null;
  title?: string;
  observation?: string;
  rootCause?: string;
  suggestedChange?: string;
  evidenceSummary?: string;
  taskDraft?: string;
  rejectionReason?: string;
}

export type AssumptionProofInput =
  | { kind: "embed"; embedId: string; startLine?: number; endLine?: number }
  | { kind: "file"; path: string; startLine?: number; endLine?: number }
  | { kind: "url"; url: string };

export function serializeAssumptionProofInputs(inputs: AssumptionProofInput[]): string {
  if (inputs.length === 0) throw new Error("At least one typed assumption proof input is required.");
  const normalized = inputs.map((input) => {
    if (input.kind === "embed") {
      if (!input.embedId.trim()) throw new Error("Assumption proof embed ID must not be empty.");
      validateLineRange(input.startLine, input.endLine, "Assumption proof");
      return { kind: input.kind, embed_id: input.embedId, ...(input.startLine !== undefined ? { start_line: input.startLine } : {}), ...(input.endLine !== undefined ? { end_line: input.endLine } : {}) };
    }
    if (input.kind === "url") {
      const url = new URL(input.url);
      if (url.protocol !== "https:") throw new Error("Assumption proof URLs must use HTTPS.");
      return { kind: input.kind, url: url.toString() };
    }
    if (!input.path || input.path.startsWith("/") || input.path.split("/").includes("..")) {
      throw new Error("Assumption proof file paths must be repository-relative.");
    }
    validateLineRange(input.startLine, input.endLine, "Assumption proof");
    return { kind: input.kind, path: input.path, ...(input.startLine !== undefined ? { start_line: input.startLine } : {}), ...(input.endLine !== undefined ? { end_line: input.endLine } : {}) };
  });
  return JSON.stringify(normalized);
}

function validateLineRange(startLine: number | undefined, endLine: number | undefined, label: string): void {
  if (startLine !== undefined && (!Number.isInteger(startLine) || startLine < 1)) throw new Error(`${label} startLine must be a positive integer.`);
  if (endLine !== undefined && (!Number.isInteger(endLine) || endLine < (startLine ?? 1))) throw new Error(`${label} endLine must be greater than or equal to startLine.`);
}

export function normalizePlanStatus(value: string | undefined): UserPlanStatus | undefined {
  if (value === undefined) return undefined;
  if (PLAN_STATUSES.includes(value as UserPlanStatus)) return value as UserPlanStatus;
  throw new Error(`Unknown plan status '${value}'. Expected one of: ${PLAN_STATUSES.join(", ")}`);
}

export function normalizeLearningType(value: string | undefined): UserPlanLearningType | undefined {
  if (value === undefined) return undefined;
  if (LEARNING_TYPES.includes(value as UserPlanLearningType)) return value as UserPlanLearningType;
  throw new Error(`Unknown learning type '${value}'. Expected one of: ${LEARNING_TYPES.join(", ")}`);
}

export function normalizeLearningTargetKind(value: string | undefined): UserPlanLearningTargetKind | undefined {
  if (value === undefined) return undefined;
  if (LEARNING_TARGET_KINDS.includes(value as UserPlanLearningTargetKind)) return value as UserPlanLearningTargetKind;
  throw new Error(`Unknown learning target '${value}'. Expected one of: ${LEARNING_TARGET_KINDS.join(", ")}`);
}

export function normalizeLearningStatus(value: string | undefined): UserPlanLearningStatus | undefined {
  if (value === undefined) return undefined;
  if (LEARNING_STATUSES.includes(value as UserPlanLearningStatus)) return value as UserPlanLearningStatus;
  throw new Error(`Unknown learning status '${value}'. Expected one of: ${LEARNING_STATUSES.join(", ")}`);
}

export function normalizeLearningLevel(value: string | undefined): UserPlanLearningLevel | undefined {
  if (value === undefined) return undefined;
  if (LEARNING_LEVELS.includes(value as UserPlanLearningLevel)) return value as UserPlanLearningLevel;
  throw new Error(`Unknown learning level '${value}'. Expected one of: ${LEARNING_LEVELS.join(", ")}`);
}

export async function buildCreateUserPlanInput(masterKey: Uint8Array, input: PlanCreateOptions): Promise<UserPlanCreateInput> {
  const planKey = randomBytes(32);
  const timestamp = nowSeconds();
  const linkedProjectIds = input.linkedProjectIds ?? [];
  const slugMetadata = await buildEncryptedObjectSlugMetadata({
    value: input.slug ?? input.title,
    encryptionKey: planKey,
    lookupKey: masterKey,
  });
  const keyWrappers = await buildUserPlanKeyWrappers({
    planKey,
    masterKey,
    createdAt: timestamp,
    primaryChatId: input.primaryChatId ?? null,
    primaryChatKey: input.primaryChatKey ?? null,
    linkedProjectIds,
    linkedProjectKeys: input.linkedProjectKeys ?? [],
  });
  return {
    plan_id: input.planId ?? randomUUIDCompat(),
    version: 1,
    encrypted_slug: slugMetadata.encrypted_slug,
    slug_lookup_hash: slugMetadata.slug_lookup_hash,
    encrypted_title: await encryptWithAesGcmCombined(input.title, planKey),
    encrypted_goal: await encryptWithAesGcmCombined(input.goal ?? "", planKey),
    encrypted_scope_in: await encryptWithAesGcmCombined(input.scopeIn ?? "", planKey),
    encrypted_scope_out: await encryptWithAesGcmCombined(input.scopeOut ?? "", planKey),
    encrypted_user_flows: input.userFlows ? await encryptWithAesGcmCombined(JSON.stringify(validateUserFlows(input.userFlows)), planKey) : undefined,
    encrypted_assumptions: await encryptWithAesGcmCombined(input.assumptions ?? "", planKey),
    encrypted_open_questions: await encryptWithAesGcmCombined(input.openQuestions ?? "", planKey),
    encrypted_constraints: await encryptWithAesGcmCombined(input.constraints ?? "", planKey),
    encrypted_decisions: await encryptWithAesGcmCombined(input.decisions ?? "", planKey),
    encrypted_risks: await encryptWithAesGcmCombined(input.risks ?? "", planKey),
    encrypted_reference_patterns: await encryptWithAesGcmCombined(input.referencePatterns ?? "", planKey),
    encrypted_context: await encryptWithAesGcmCombined(input.context ?? "", planKey),
    encrypted_linked_project_ids: await encryptWithAesGcmCombined(JSON.stringify(linkedProjectIds), planKey),
    status: input.status ?? "draft",
    primary_chat_id: input.primaryChatId ?? null,
    linked_project_ids: linkedProjectIds,
    planner_focus_id: input.plannerFocusId ?? null,
    created_at: timestamp,
    updated_at: timestamp,
    key_wrappers: keyWrappers,
  } as UserPlanCreateInput;
}

export async function buildUpdateUserPlanInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanUpdateOptions): Promise<UserPlanUpdateInput> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const patch: UserPlanUpdateInput = { version: plan.version, updated_at: nowSeconds() };
  if (input.slug !== undefined) {
    const slugMetadata = await buildEncryptedObjectSlugMetadata({
      value: input.slug,
      encryptionKey: planKey,
      lookupKey: masterKey,
    });
    patch.encrypted_slug = slugMetadata.encrypted_slug;
    patch.slug_lookup_hash = slugMetadata.slug_lookup_hash;
  }
  if (input.title !== undefined) patch.encrypted_title = await encryptWithAesGcmCombined(input.title, planKey);
  if (input.goal !== undefined) patch.encrypted_goal = await encryptWithAesGcmCombined(input.goal, planKey);
  if (input.scopeIn !== undefined) patch.encrypted_scope_in = await encryptWithAesGcmCombined(input.scopeIn, planKey);
  if (input.scopeOut !== undefined) patch.encrypted_scope_out = await encryptWithAesGcmCombined(input.scopeOut, planKey);
  if (input.userFlows !== undefined) patch.encrypted_user_flows = await encryptWithAesGcmCombined(JSON.stringify(validateUserFlows(input.userFlows)), planKey);
  if (input.assumptions !== undefined) patch.encrypted_assumptions = await encryptWithAesGcmCombined(input.assumptions, planKey);
  if (input.openQuestions !== undefined) patch.encrypted_open_questions = await encryptWithAesGcmCombined(input.openQuestions, planKey);
  if (input.constraints !== undefined) patch.encrypted_constraints = await encryptWithAesGcmCombined(input.constraints, planKey);
  if (input.decisions !== undefined) patch.encrypted_decisions = await encryptWithAesGcmCombined(input.decisions, planKey);
  if (input.risks !== undefined) patch.encrypted_risks = await encryptWithAesGcmCombined(input.risks, planKey);
  if (input.referencePatterns !== undefined) patch.encrypted_reference_patterns = await encryptWithAesGcmCombined(input.referencePatterns, planKey);
  if (input.context !== undefined) patch.encrypted_context = await encryptWithAesGcmCombined(input.context, planKey);
  if (input.status !== undefined) patch.status = input.status;
  if (input.primaryChatId !== undefined) patch.primary_chat_id = input.primaryChatId;
  if (input.linkedProjectIds !== undefined) {
    patch.linked_project_ids = input.linkedProjectIds;
    patch.encrypted_linked_project_ids = await encryptWithAesGcmCombined(JSON.stringify(input.linkedProjectIds), planKey);
  }
  if (input.primaryChatId !== undefined || input.linkedProjectIds !== undefined) {
    patch.key_wrappers = await buildUserPlanKeyWrappers({
      planKey,
      masterKey,
      createdAt: patch.updated_at ?? nowSeconds(),
      primaryChatId: input.primaryChatId !== undefined ? input.primaryChatId : plan.primaryChatId,
      primaryChatKey: input.primaryChatKey ?? null,
      linkedProjectIds: input.linkedProjectIds ?? plan.linkedProjectIds,
      linkedProjectKeys: input.linkedProjectKeys ?? [],
    });
  }
  if (input.plannerFocusId !== undefined) patch.planner_focus_id = input.plannerFocusId;
  return patch;
}

export async function buildUserPlanKeyWrappers(input: {
  planKey: Uint8Array;
  masterKey: Uint8Array;
  createdAt: number;
  primaryChatId?: string | null;
  primaryChatKey?: Uint8Array | null;
  linkedProjectIds?: string[];
  linkedProjectKeys?: PlanProjectKey[];
}): Promise<Array<Record<string, unknown>>> {
  const wrappers: Array<Record<string, unknown>> = [{
    key_type: "master",
    encrypted_plan_key: await encryptBytesWithAesGcm(input.planKey, input.masterKey),
    created_at: input.createdAt,
  }];
  if (input.primaryChatId) {
    if (!input.primaryChatKey) throw new Error(`Plan chat link requires a locally decrypted chat key for ${input.primaryChatId}.`);
    wrappers.push({
      key_type: "chat",
      hashed_chat_id: sha256Hex(input.primaryChatId),
      encrypted_plan_key: await encryptBytesWithAesGcm(input.planKey, input.primaryChatKey),
      created_at: input.createdAt,
    });
  }
  const projectKeys = new Map((input.linkedProjectKeys ?? []).map((entry) => [entry.projectId, entry.projectKey]));
  for (const projectId of input.linkedProjectIds ?? []) {
    const projectKey = projectKeys.get(projectId);
    if (!projectKey) throw new Error(`Plan project link requires a locally decrypted project key for ${projectId}.`);
    wrappers.push({
      key_type: "project",
      hashed_project_id: sha256Hex(projectId),
      encrypted_plan_key: await encryptBytesWithAesGcm(input.planKey, projectKey),
      created_at: input.createdAt,
    });
  }
  return wrappers;
}

export async function decryptUserPlan(record: UserPlanRecord, masterKey: Uint8Array): Promise<DecryptedUserPlan> {
  if (typeof record.version !== "number") throw new Error(`Plan ${record.plan_id} is missing version.`);
  const planKey = await planKeyFromRecord(record, masterKey);
  const linkedProjectIds = parseStringArray(await decryptOptional(record.encrypted_linked_project_ids, planKey));
  return {
    planId: record.plan_id,
    shortId: deriveShortId(record),
    slug: await decryptObjectSlug(record.encrypted_slug, planKey),
    title: await decryptOptional(record.encrypted_title, planKey) || "(untitled plan)",
    goal: await decryptOptional(record.encrypted_goal, planKey),
    scopeIn: await decryptOptional(record.encrypted_scope_in, planKey),
    scopeOut: await decryptOptional(record.encrypted_scope_out, planKey),
    userFlows: parseUserFlows(await decryptOptional(record.encrypted_user_flows, planKey)),
    assumptions: await decryptOptional(record.encrypted_assumptions, planKey),
    openQuestions: await decryptOptional(record.encrypted_open_questions, planKey),
    constraints: await decryptOptional(record.encrypted_constraints, planKey),
    decisions: await decryptOptional(record.encrypted_decisions, planKey),
    risks: await decryptOptional(record.encrypted_risks, planKey),
    referencePatterns: await decryptOptional(record.encrypted_reference_patterns, planKey),
    context: await decryptOptional(record.encrypted_context, planKey),
    status: record.status,
    primaryChatId: record.primary_chat_id ?? null,
    linkedProjectIds: linkedProjectIds.length > 0 ? linkedProjectIds : (record.linked_project_ids ?? []),
    plannerFocusId: record.planner_focus_id ?? null,
    version: record.version,
    createdAt: record.created_at ?? 0,
    updatedAt: record.updated_at ?? 0,
    completedAt: record.completed_at ?? null,
    encrypted: record,
  };
}

export async function decryptUserPlans(records: UserPlanRecord[], masterKey: Uint8Array): Promise<DecryptedUserPlan[]> {
  const output: DecryptedUserPlan[] = [];
  for (const record of records) output.push(await decryptUserPlan(record, masterKey));
  return output;
}

export async function buildCreatePlanLearningInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanLearningCreateOptions): Promise<UserPlanLearningRecord> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const timestamp = nowSeconds();
  if (input.taskDraft) assertSafeLearningTaskDraft(input.taskDraft);
  return {
    learning_id: input.learningId ?? randomUUIDCompat(),
    type: input.type,
    target_kind: input.targetKind,
    status: input.status ?? "draft",
    severity: input.severity ?? "medium",
    confidence: input.confidence ?? "medium",
    linked_task_ids: input.linkedTaskIds,
    linked_check_ids: input.linkedCheckIds,
    encrypted_title: await encryptWithAesGcmCombined(input.title, planKey),
    encrypted_observation: input.observation !== undefined ? await encryptWithAesGcmCombined(input.observation, planKey) : undefined,
    encrypted_root_cause: input.rootCause !== undefined ? await encryptWithAesGcmCombined(input.rootCause, planKey) : undefined,
    encrypted_suggested_change: input.suggestedChange !== undefined ? await encryptWithAesGcmCombined(input.suggestedChange, planKey) : undefined,
    encrypted_evidence_summary: input.evidenceSummary !== undefined ? await encryptWithAesGcmCombined(input.evidenceSummary, planKey) : undefined,
    encrypted_task_draft: input.taskDraft !== undefined ? await encryptWithAesGcmCombined(input.taskDraft, planKey) : undefined,
    encrypted_rejection_reason: input.rejectionReason !== undefined ? await encryptWithAesGcmCombined(input.rejectionReason, planKey) : undefined,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

export async function buildUpdatePlanLearningInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanLearningUpdateOptions): Promise<Partial<UserPlanLearningRecord>> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const patch: Partial<UserPlanLearningRecord> = { updated_at: nowSeconds() };
  if (input.status !== undefined) patch.status = input.status;
  if (input.severity !== undefined) patch.severity = input.severity;
  if (input.confidence !== undefined) patch.confidence = input.confidence;
  if (input.linkedTaskIds !== undefined) patch.linked_task_ids = input.linkedTaskIds;
  if (input.linkedCheckIds !== undefined) patch.linked_check_ids = input.linkedCheckIds;
  if (input.appliedTaskId !== undefined) patch.applied_task_id = input.appliedTaskId;
  if (input.title !== undefined) patch.encrypted_title = await encryptWithAesGcmCombined(input.title, planKey);
  if (input.observation !== undefined) patch.encrypted_observation = await encryptWithAesGcmCombined(input.observation, planKey);
  if (input.rootCause !== undefined) patch.encrypted_root_cause = await encryptWithAesGcmCombined(input.rootCause, planKey);
  if (input.suggestedChange !== undefined) patch.encrypted_suggested_change = await encryptWithAesGcmCombined(input.suggestedChange, planKey);
  if (input.evidenceSummary !== undefined) patch.encrypted_evidence_summary = await encryptWithAesGcmCombined(input.evidenceSummary, planKey);
  if (input.taskDraft !== undefined) {
    assertSafeLearningTaskDraft(input.taskDraft);
    patch.encrypted_task_draft = await encryptWithAesGcmCombined(input.taskDraft, planKey);
  }
  if (input.rejectionReason !== undefined) patch.encrypted_rejection_reason = await encryptWithAesGcmCombined(input.rejectionReason, planKey);
  return patch;
}

export async function decryptPlanLearning(plan: DecryptedUserPlan, record: UserPlanLearningRecord, masterKey: Uint8Array): Promise<DecryptedPlanLearning> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  return {
    learningId: record.learning_id,
    type: record.type,
    targetKind: record.target_kind,
    status: record.status ?? "draft",
    severity: record.severity ?? null,
    confidence: record.confidence ?? null,
    linkedTaskIds: record.linked_task_ids ?? [],
    linkedCheckIds: record.linked_check_ids ?? [],
    appliedTaskId: record.applied_task_id ?? null,
    title: await decryptOptional(record.encrypted_title, planKey) || "(untitled learning)",
    observation: await decryptOptional(record.encrypted_observation, planKey),
    rootCause: await decryptOptional(record.encrypted_root_cause, planKey),
    suggestedChange: await decryptOptional(record.encrypted_suggested_change, planKey),
    evidenceSummary: await decryptOptional(record.encrypted_evidence_summary, planKey),
    taskDraft: await decryptOptional(record.encrypted_task_draft, planKey),
    rejectionReason: await decryptOptional(record.encrypted_rejection_reason, planKey),
    version: record.version ?? 1,
    createdAt: record.created_at ?? 0,
    updatedAt: record.updated_at ?? 0,
    encrypted: record,
  };
}

export async function decryptPlanLearnings(plan: DecryptedUserPlan, records: UserPlanLearningRecord[], masterKey: Uint8Array): Promise<DecryptedPlanLearning[]> {
  const output: DecryptedPlanLearning[] = [];
  for (const record of records) output.push(await decryptPlanLearning(plan, record, masterKey));
  return output;
}

export function findPlan(plans: DecryptedUserPlan[], id: string): DecryptedUserPlan {
  const planIdMatch = plans.find((candidate) => candidate.planId === id);
  if (planIdMatch) return planIdMatch;
  const slugMatches = plans.filter((candidate) => objectSlugMatches(candidate.slug, id));
  if (slugMatches.length > 1) throw new Error(`Plan slug '${id}' is ambiguous in the current plan list. Use the full plan ID.`);
  if (slugMatches.length === 1) return slugMatches[0];
  const shortIdMatches = plans.filter((candidate) => candidate.shortId === id.toUpperCase());
  if (shortIdMatches.length > 1) throw new Error(`Plan '${id}' is ambiguous in the current plan list. Use the full plan ID.`);
  const plan = shortIdMatches[0];
  if (!plan) throw new Error(`Plan '${id}' was not found in the current plan list.`);
  return plan;
}

export async function buildCreatePlanCriterionInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanCriterionCreateOptions): Promise<UserPlanCriterionRecord> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const timestamp = nowSeconds();
  return {
    criterion_id: input.criterionId ?? randomUUIDCompat(),
    encrypted_text: await encryptWithAesGcmCombined(input.text, planKey),
    type: input.type,
    status: input.status as UserPlanCriterionRecord["status"] | undefined,
    required: input.required,
    linked_task_ids: input.linkedTaskIds,
    verification_ids: input.verificationIds,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

export async function buildCreatePlanVerificationInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanVerificationCreateOptions): Promise<UserPlanVerificationRecord & Record<string, unknown>> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const timestamp = nowSeconds();
  return {
    verification_id: input.verificationId ?? randomUUIDCompat(),
    kind: input.kind,
    phase: input.phase,
    status: input.status ?? "pending",
    required_for_done: input.requiredForDone,
    covers: input.covers,
    threshold: input.threshold,
    score: input.score,
    confidence: input.confidence,
    linked_task_id: input.linkedTaskId,
    run_id: input.runId,
    encrypted_command: input.command !== undefined ? await encryptWithAesGcmCombined(input.command, planKey) : undefined,
    encrypted_evaluation_prompt: input.evaluationPrompt !== undefined ? await encryptWithAesGcmCombined(input.evaluationPrompt, planKey) : undefined,
    encrypted_expected_result: input.expectedResult !== undefined ? await encryptWithAesGcmCombined(input.expectedResult, planKey) : undefined,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

export async function buildPlanVerificationEvidenceInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanVerificationEvidenceOptions): Promise<Partial<UserPlanVerificationRecord>> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  return {
    status: input.status,
    score: input.score,
    threshold: input.threshold,
    confidence: input.confidence,
    run_id: input.runId,
    encrypted_result_summary: input.resultSummary !== undefined ? await encryptWithAesGcmCombined(input.resultSummary, planKey) : undefined,
    encrypted_required_fixes: input.requiredFixes !== undefined ? await encryptWithAesGcmCombined(input.requiredFixes, planKey) : undefined,
    updated_at: nowSeconds(),
  };
}

export async function buildUpdatePlanVerificationInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanVerificationUpdateOptions): Promise<Partial<UserPlanVerificationRecord>> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const patch: Partial<UserPlanVerificationRecord> = { updated_at: nowSeconds() };
  if (input.kind !== undefined) patch.kind = input.kind;
  if (input.phase !== undefined) patch.phase = input.phase;
  if (input.status !== undefined) patch.status = input.status;
  if (input.lifecycleStatus !== undefined) patch.lifecycle_status = input.lifecycleStatus;
  if (input.requiredForDone !== undefined) patch.required_for_done = input.requiredForDone;
  if (input.covers !== undefined) patch.covers = input.covers;
  if (input.sourceHash !== undefined) patch.source_hash = input.sourceHash;
  if (input.threshold !== undefined) patch.threshold = input.threshold;
  if (input.score !== undefined) patch.score = input.score;
  if (input.confidence !== undefined) patch.confidence = input.confidence;
  if (input.linkedSubChatId !== undefined) patch.linked_sub_chat_id = input.linkedSubChatId;
  if (input.sourceEmbedId !== undefined) patch.source_embed_id = input.sourceEmbedId;
  if (input.runnerKind !== undefined) patch.runner_kind = input.runnerKind;
  if (input.description !== undefined) patch.encrypted_description = await encryptWithAesGcmCombined(input.description, planKey);
  if (input.command !== undefined) patch.encrypted_command = await encryptWithAesGcmCombined(input.command, planKey);
  if (input.evaluationPrompt !== undefined) patch.encrypted_evaluation_prompt = await encryptWithAesGcmCombined(input.evaluationPrompt, planKey);
  if (input.evaluatorInstructions !== undefined) patch.encrypted_evaluator_instructions = await encryptWithAesGcmCombined(input.evaluatorInstructions, planKey);
  if (input.expectedResult !== undefined) patch.encrypted_expected_result = await encryptWithAesGcmCombined(input.expectedResult, planKey);
  if (input.sourcePath !== undefined) patch.encrypted_source_path = await encryptWithAesGcmCombined(input.sourcePath, planKey);
  if (input.redPhaseReason !== undefined) patch.encrypted_red_phase_reason = await encryptWithAesGcmCombined(input.redPhaseReason, planKey);
  return patch;
}

export function renderPlanList(plans: DecryptedUserPlan[]): string {
  if (plans.length === 0) return "No plans found.";
  const lines = ["Plans", "Handle              Status                 Chat       Title"];
  for (const plan of plans) {
    lines.push(`${pad(planHandle(plan), 19)} ${pad(plan.status, 22)} ${pad(plan.primaryChatId ?? "-", 10)} ${plan.title}`);
  }
  return lines.join("\n");
}

export function renderPlanDetail(plan: DecryptedUserPlan): string {
  const lines = [
    `Plan ${planHandle(plan)}`,
    `Title: ${plan.title}`,
    ...(plan.slug ? [`Slug: ${plan.slug}`] : []),
    `Status: ${plan.status}`,
    `Plan ID: ${plan.planId}`,
    `Version: ${plan.version}`,
  ];
  if (plan.goal) lines.push(`Goal: ${plan.goal}`);
  if (plan.scopeIn) lines.push(`Scope in: ${plan.scopeIn}`);
  if (plan.scopeOut) lines.push(`Scope out: ${plan.scopeOut}`);
  if (plan.userFlows.length) lines.push(`User flows: ${plan.userFlows.map((flow) => flow.title).join(", ")}`);
  if (plan.assumptions) lines.push(`Assumptions: ${plan.assumptions}`);
  if (plan.openQuestions) lines.push(`Open questions: ${plan.openQuestions}`);
  if (plan.constraints) lines.push(`Constraints: ${plan.constraints}`);
  if (plan.decisions) lines.push(`Decisions: ${plan.decisions}`);
  if (plan.risks) lines.push(`Risks: ${plan.risks}`);
  if (plan.referencePatterns) lines.push(`Reference patterns: ${plan.referencePatterns}`);
  if (plan.context) lines.push(`Context: ${plan.context}`);
  if (plan.primaryChatId) lines.push(`Chat: ${plan.primaryChatId}`);
  if (plan.linkedProjectIds.length > 0) lines.push(`Projects: ${plan.linkedProjectIds.join(", ")}`);
  if (plan.plannerFocusId) lines.push(`Planner focus: ${plan.plannerFocusId}`);
  if (plan.completedAt) lines.push(`Completed at: ${plan.completedAt}`);
  return lines.join("\n");
}

function planHandle(plan: DecryptedUserPlan): string {
  return plan.slug || plan.shortId;
}

export function renderPlanLearningList(learnings: DecryptedPlanLearning[]): string {
  if (learnings.length === 0) return "No plan learnings found.";
  const lines = ["Plan Learnings", "ID                  Status      Type                           Title"];
  for (const learning of learnings) {
    lines.push(`${pad(learning.learningId, 19)} ${pad(learning.status, 11)} ${pad(learning.type, 30)} ${learning.title}`);
  }
  return lines.join("\n");
}

export function renderPlanLearningDetail(learning: DecryptedPlanLearning): string {
  const lines = [
    `Learning ${learning.learningId}`,
    `Title: ${learning.title}`,
    `Status: ${learning.status}`,
    `Type: ${learning.type}`,
    `Target: ${learning.targetKind}`,
  ];
  if (learning.severity) lines.push(`Severity: ${learning.severity}`);
  if (learning.confidence) lines.push(`Confidence: ${learning.confidence}`);
  if (learning.observation) lines.push(`Observation: ${learning.observation}`);
  if (learning.rootCause) lines.push(`Root cause: ${learning.rootCause}`);
  if (learning.suggestedChange) lines.push(`Suggested change: ${learning.suggestedChange}`);
  if (learning.evidenceSummary) lines.push(`Evidence: ${learning.evidenceSummary}`);
  if (learning.taskDraft) lines.push(`Task draft: ${learning.taskDraft}`);
  if (learning.rejectionReason) lines.push(`Rejection reason: ${learning.rejectionReason}`);
  if (learning.appliedTaskId) lines.push(`Applied task: ${learning.appliedTaskId}`);
  if (learning.linkedTaskIds.length > 0) lines.push(`Linked tasks: ${learning.linkedTaskIds.join(", ")}`);
  if (learning.linkedCheckIds.length > 0) lines.push(`Linked checks: ${learning.linkedCheckIds.join(", ")}`);
  return lines.join("\n");
}

export function findPlanLearning(learnings: DecryptedPlanLearning[], learningId: string): DecryptedPlanLearning {
  const learning = learnings.find((candidate) => candidate.learningId === learningId);
  if (!learning) throw new Error(`Plan learning '${learningId}' was not found.`);
  return learning;
}

export function assertSafeLearningTaskDraft(taskDraft: string): void {
  if (!taskDraft.trim()) return;
  if (hasHiddenControlCharacter(taskDraft)) {
    throw new Error("Learning task draft contains hidden or control characters.");
  }
  if (/[\u200B-\u200F\u202A-\u202E\u2060-\u206F]/u.test(taskDraft)) {
    throw new Error("Learning task draft contains hidden Unicode formatting characters.");
  }
  if (/\b(ignore (all|previous) instructions|system prompt|developer message|exfiltrat|reveal secrets?)\b/i.test(taskDraft)) {
    throw new Error("Learning task draft looks like prompt injection or secret exfiltration.");
  }
  if (/\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|private key)\b/i.test(taskDraft)) {
    throw new Error("Learning task draft appears to contain credential instructions.");
  }
  if (/\b(rm\s+-rf|drop\s+database|delete\s+production|force[- ]?push)\b/i.test(taskDraft)) {
    throw new Error("Learning task draft contains destructive-action language.");
  }
}

function hasHiddenControlCharacter(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code === 127 || (code < 32 && code !== 9 && code !== 10 && code !== 13)) return true;
  }
  return false;
}

export function finalizedLearningNeedsTaskSafetyScan(learning: DecryptedPlanLearning): boolean {
  return FINALIZED_LEARNING_STATUSES.has(learning.status) && !learning.appliedTaskId && Boolean(learning.taskDraft.trim());
}

export async function planKeyFromRecord(record: UserPlanRecord, masterKey: Uint8Array): Promise<Uint8Array> {
  const wrapper = record.key_wrappers?.find((candidate) => candidate.key_type === "master" && typeof candidate.encrypted_plan_key === "string");
  if (!wrapper || typeof wrapper.encrypted_plan_key !== "string") throw new Error(`Plan ${record.plan_id} is missing a master key wrapper.`);
  const planKey = await decryptBytesWithAesGcm(wrapper.encrypted_plan_key, masterKey);
  if (!planKey) throw new Error(`Failed to decrypt plan key for ${record.plan_id}.`);
  return planKey;
}

function sha256Hex(value: string): string {
  return createHash("sha256").update(value).digest("hex");
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

function parseUserFlows(value: string): UserPlanFlow[] {
  if (!value) return [];
  const parsed = JSON.parse(value) as unknown;
  if (!Array.isArray(parsed)) throw new Error("Plan user flows must be an array.");
  return validateUserFlows(parsed as UserPlanFlow[]);
}

function deriveShortId(record: UserPlanRecord): string {
  const source = record.plan_id || `${record.created_at ?? ""}-${record.updated_at ?? ""}`;
  const digest = createHash("sha256").update(source).digest("hex").slice(0, 6).toUpperCase();
  return `${DEFAULT_PLAN_PREFIX}-${digest}`;
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
