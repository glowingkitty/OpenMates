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

const PLAN_STATUSES: UserPlanStatus[] = ["draft", "awaiting_confirmation", "active", "executing", "blocked", "completed", "archived"];
const DEFAULT_PLAN_PREFIX = "PLAN";

export interface DecryptedUserPlan {
  planId: string;
  shortId: string;
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
  encrypted: UserPlanRecord;
}

export interface PlanCreateOptions {
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

export interface PlanUpdateOptions {
  title?: string;
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

export interface PlanCriterionCreateOptions {
  criterionId?: string;
  text: string;
  type?: string;
  status?: string;
  required?: boolean;
  linkedStepIds?: string[];
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

export function normalizePlanStatus(value: string | undefined): UserPlanStatus | undefined {
  if (value === undefined) return undefined;
  if (PLAN_STATUSES.includes(value as UserPlanStatus)) return value as UserPlanStatus;
  throw new Error(`Unknown plan status '${value}'. Expected one of: ${PLAN_STATUSES.join(", ")}`);
}

export async function buildCreateUserPlanInput(masterKey: Uint8Array, input: PlanCreateOptions): Promise<UserPlanCreateInput> {
  const planKey = randomBytes(32);
  const encryptedPlanKey = await encryptBytesWithAesGcm(planKey, masterKey);
  const timestamp = nowSeconds();
  const linkedProjectIds = input.linkedProjectIds ?? [];
  return {
    plan_id: randomUUIDCompat(),
    version: 1,
    encrypted_plan_key: encryptedPlanKey,
    encrypted_title: await encryptWithAesGcmCombined(input.title, planKey),
    encrypted_summary: await encryptWithAesGcmCombined(input.summary ?? "", planKey),
    encrypted_goal: await encryptWithAesGcmCombined(input.goal ?? "", planKey),
    encrypted_scope_in: await encryptWithAesGcmCombined(input.scopeIn ?? "", planKey),
    encrypted_scope_out: await encryptWithAesGcmCombined(input.scopeOut ?? "", planKey),
    encrypted_assumptions: await encryptWithAesGcmCombined(input.assumptions ?? "", planKey),
    encrypted_open_questions: await encryptWithAesGcmCombined(input.openQuestions ?? "", planKey),
    encrypted_constraints: await encryptWithAesGcmCombined(input.constraints ?? "", planKey),
    encrypted_decisions: await encryptWithAesGcmCombined(input.decisions ?? "", planKey),
    encrypted_risks: await encryptWithAesGcmCombined(input.risks ?? "", planKey),
    encrypted_linked_project_ids: await encryptWithAesGcmCombined(JSON.stringify(linkedProjectIds), planKey),
    status: input.status ?? "draft",
    primary_chat_id: input.primaryChatId ?? null,
    linked_project_ids: linkedProjectIds,
    current_phase_id: input.currentPhaseId ?? null,
    current_step_id: input.currentStepId ?? null,
    current_task_id: input.currentTaskId ?? null,
    planner_focus_id: input.plannerFocusId ?? null,
    created_at: timestamp,
    updated_at: timestamp,
    key_wrappers: [{ key_type: "master", encrypted_plan_key: encryptedPlanKey, created_at: timestamp }],
  } as UserPlanCreateInput;
}

export async function buildUpdateUserPlanInput(plan: DecryptedUserPlan, masterKey: Uint8Array, input: PlanUpdateOptions): Promise<UserPlanUpdateInput> {
  const planKey = await planKeyFromRecord(plan.encrypted, masterKey);
  const patch: UserPlanUpdateInput = { version: plan.version, updated_at: nowSeconds() };
  if (input.title !== undefined) patch.encrypted_title = await encryptWithAesGcmCombined(input.title, planKey);
  if (input.summary !== undefined) patch.encrypted_summary = await encryptWithAesGcmCombined(input.summary, planKey);
  if (input.goal !== undefined) patch.encrypted_goal = await encryptWithAesGcmCombined(input.goal, planKey);
  if (input.scopeIn !== undefined) patch.encrypted_scope_in = await encryptWithAesGcmCombined(input.scopeIn, planKey);
  if (input.scopeOut !== undefined) patch.encrypted_scope_out = await encryptWithAesGcmCombined(input.scopeOut, planKey);
  if (input.assumptions !== undefined) patch.encrypted_assumptions = await encryptWithAesGcmCombined(input.assumptions, planKey);
  if (input.openQuestions !== undefined) patch.encrypted_open_questions = await encryptWithAesGcmCombined(input.openQuestions, planKey);
  if (input.constraints !== undefined) patch.encrypted_constraints = await encryptWithAesGcmCombined(input.constraints, planKey);
  if (input.decisions !== undefined) patch.encrypted_decisions = await encryptWithAesGcmCombined(input.decisions, planKey);
  if (input.risks !== undefined) patch.encrypted_risks = await encryptWithAesGcmCombined(input.risks, planKey);
  if (input.status !== undefined) patch.status = input.status;
  if (input.primaryChatId !== undefined) patch.primary_chat_id = input.primaryChatId;
  if (input.linkedProjectIds !== undefined) {
    patch.linked_project_ids = input.linkedProjectIds;
    patch.encrypted_linked_project_ids = await encryptWithAesGcmCombined(JSON.stringify(input.linkedProjectIds), planKey);
  }
  if (input.currentPhaseId !== undefined) patch.current_phase_id = input.currentPhaseId;
  if (input.currentStepId !== undefined) patch.current_step_id = input.currentStepId;
  if (input.currentTaskId !== undefined) patch.current_task_id = input.currentTaskId;
  if (input.plannerFocusId !== undefined) patch.planner_focus_id = input.plannerFocusId;
  return patch;
}

export async function decryptUserPlan(record: UserPlanRecord, masterKey: Uint8Array): Promise<DecryptedUserPlan> {
  if (typeof record.version !== "number") throw new Error(`Plan ${record.plan_id} is missing version.`);
  const planKey = await planKeyFromRecord(record, masterKey);
  const linkedProjectIds = parseStringArray(await decryptOptional(record.encrypted_linked_project_ids, planKey));
  return {
    planId: record.plan_id,
    shortId: deriveShortId(record),
    title: await decryptOptional(record.encrypted_title, planKey) || "(untitled plan)",
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
    linkedProjectIds: linkedProjectIds.length > 0 ? linkedProjectIds : (record.linked_project_ids ?? []),
    currentPhaseId: record.current_phase_id ?? null,
    currentStepId: record.current_step_id ?? null,
    currentTaskId: record.current_task_id ?? null,
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

export function findPlan(plans: DecryptedUserPlan[], id: string): DecryptedUserPlan {
  const planIdMatch = plans.find((candidate) => candidate.planId === id);
  if (planIdMatch) return planIdMatch;
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
    linked_step_ids: input.linkedStepIds,
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

export function renderPlanList(plans: DecryptedUserPlan[]): string {
  if (plans.length === 0) return "No plans found.";
  const lines = ["Plans", "ID          Status                 Chat       Title"];
  for (const plan of plans) {
    lines.push(`${pad(plan.shortId, 11)} ${pad(plan.status, 22)} ${pad(plan.primaryChatId ?? "-", 10)} ${plan.title}`);
  }
  return lines.join("\n");
}

export function renderPlanDetail(plan: DecryptedUserPlan): string {
  const lines = [
    `Plan ${plan.shortId}`,
    `Title: ${plan.title}`,
    `Status: ${plan.status}`,
    `Plan ID: ${plan.planId}`,
    `Version: ${plan.version}`,
  ];
  if (plan.summary) lines.push(`Summary: ${plan.summary}`);
  if (plan.goal) lines.push(`Goal: ${plan.goal}`);
  if (plan.scopeIn) lines.push(`Scope in: ${plan.scopeIn}`);
  if (plan.scopeOut) lines.push(`Scope out: ${plan.scopeOut}`);
  if (plan.assumptions) lines.push(`Assumptions: ${plan.assumptions}`);
  if (plan.openQuestions) lines.push(`Open questions: ${plan.openQuestions}`);
  if (plan.constraints) lines.push(`Constraints: ${plan.constraints}`);
  if (plan.decisions) lines.push(`Decisions: ${plan.decisions}`);
  if (plan.risks) lines.push(`Risks: ${plan.risks}`);
  if (plan.primaryChatId) lines.push(`Chat: ${plan.primaryChatId}`);
  if (plan.linkedProjectIds.length > 0) lines.push(`Projects: ${plan.linkedProjectIds.join(", ")}`);
  if (plan.currentPhaseId) lines.push(`Current phase: ${plan.currentPhaseId}`);
  if (plan.currentStepId) lines.push(`Current step: ${plan.currentStepId}`);
  if (plan.currentTaskId) lines.push(`Current task: ${plan.currentTaskId}`);
  if (plan.plannerFocusId) lines.push(`Planner focus: ${plan.plannerFocusId}`);
  if (plan.completedAt) lines.push(`Completed at: ${plan.completedAt}`);
  return lines.join("\n");
}

async function planKeyFromRecord(record: UserPlanRecord, masterKey: Uint8Array): Promise<Uint8Array> {
  if (!record.encrypted_plan_key) throw new Error(`Plan ${record.plan_id} is missing encrypted plan key.`);
  const planKey = await decryptBytesWithAesGcm(record.encrypted_plan_key, masterKey);
  if (!planKey) throw new Error(`Failed to decrypt plan key for ${record.plan_id}.`);
  return planKey;
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
