/*
 * OpenMates work-control YAML recovery helpers.
 *
 * Purpose: create an explicit, deterministic cleartext recovery projection.
 * Architecture: recovery stays local, outside Git/worktrees, and is never watched.
 * Security: callers decrypt work records before writing; this module never contacts APIs.
 * Spec: docs/specs/opencode-openmates-work-control/spec.yml.
 */

import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { stringify } from "yaml";

import type { UserPlanAssumptionRecord, UserPlanRevisionRecord } from "./client.js";
import { decryptWithAesGcmCombined } from "./crypto.js";
import { type DecryptedUserPlan, planKeyFromRecord } from "./plansCli.js";

export interface WorkRecoveryDocument {
  schema_version: 1;
  project: { project_id: string; [key: string]: unknown };
  plans: Array<Record<string, unknown>>;
  tasks: Array<Record<string, unknown>>;
  dependencies: Array<{ source_ref: string; target_ref: string }>;
  assumptions: Array<Record<string, unknown>>;
  revisions: Array<Record<string, unknown>>;
}

export type WorkRecoveryConflict = { kind: "plan" | "task"; id: string; reason: "already_exists" | "wrong_project" };

export async function projectPlanAssumption(plan: DecryptedUserPlan, masterKey: Uint8Array, assumption: UserPlanAssumptionRecord): Promise<Record<string, unknown>> {
  const key = await planKeyFromRecord(plan.encrypted, masterKey);
  const decrypt = async (value: string | null | undefined): Promise<string> => value ? (await decryptWithAesGcmCombined(value, key)) ?? "" : "";
  const sourcesText = await decrypt(assumption.encrypted_sources);
  const encryptedSources = sourcesText ? parseTypedSources(sourcesText) : [];
  return {
    plan_id: plan.planId,
    assumption_id: assumption.assumption_id,
    text: await decrypt(assumption.encrypted_text),
    category: assumption.category ?? null,
    status: assumption.status ?? null,
    required_before: assumption.required_before ?? null,
    linked_sub_chat_id: assumption.linked_sub_chat_id ?? null,
    linked_task_id: assumption.linked_task_id ?? null,
    linked_step_ids: assumption.linked_step_ids ?? [],
    linked_criterion_ids: assumption.linked_criterion_ids ?? [],
    corrected_text: await decrypt(assumption.encrypted_corrected_text),
    evidence_summary: await decrypt(assumption.encrypted_evidence_summary),
    blocker_reason: await decrypt(assumption.encrypted_blocker_reason),
    waiver_reason: await decrypt(assumption.encrypted_waiver_reason),
    sources: encryptedSources,
    created_at: assumption.created_at ?? null,
    updated_at: assumption.updated_at ?? null,
  };
}

export async function projectPlanRevision(plan: DecryptedUserPlan, masterKey: Uint8Array, revision: UserPlanRevisionRecord): Promise<Record<string, unknown>> {
  const key = await planKeyFromRecord(plan.encrypted, masterKey);
  const snapshot = await decryptWithAesGcmCombined(revision.encrypted_snapshot, key);
  if (!snapshot) throw new Error(`Revision ${revision.revision_id} could not be decrypted.`);
  const canonicalPlan = JSON.parse(snapshot) as unknown;
  if (!canonicalPlan || typeof canonicalPlan !== "object" || Array.isArray(canonicalPlan)) throw new Error(`Revision ${revision.revision_id} has an invalid plan snapshot.`);
  assertNoCiphertext(canonicalPlan);
  return { plan_id: plan.planId, revision_id: revision.revision_id, fingerprint: revision.fingerprint, snapshot: canonicalPlan, created_at: revision.created_at };
}

export function validateWorkRecoveryDocument(value: unknown): asserts value is WorkRecoveryDocument {
  if (!value || typeof value !== "object") throw new Error("Work recovery document must be an object.");
  const document = value as Partial<WorkRecoveryDocument>;
  if (document.schema_version !== 1) throw new Error("Unsupported work recovery schema_version.");
  if (!document.project?.project_id) throw new Error("Work recovery document requires project.project_id.");
  for (const field of ["plans", "tasks", "dependencies", "assumptions", "revisions"] as const) {
    if (!Array.isArray(document[field])) throw new Error(`Work recovery document requires ${field}.`);
  }
  const plans = document.plans;
  const tasks = document.tasks;
  const dependencies = document.dependencies;
  const assumptions = document.assumptions;
  const revisions = document.revisions;
  if (!plans || !tasks || !dependencies || !assumptions || !revisions) throw new Error("Work recovery document requires all top-level arrays.");
  assertNoCiphertext(document);
  const planIds = new Set<string>();
  const taskIds = new Set<string>();
  for (const plan of plans) addStableId(plan, "plan_id", planIds, "plan");
  for (const task of tasks) addStableId(task, "task_id", taskIds, "task");
  for (const plan of plans) assertProjectLink(plan, document.project.project_id, "plan");
  for (const task of tasks) assertProjectLink(task, document.project.project_id, "task");
  for (const task of tasks) {
    if (task.plan_id !== null && task.plan_id !== undefined && (typeof task.plan_id !== "string" || !planIds.has(task.plan_id))) {
      throw new Error(`Task references missing plan ${String(task.plan_id)}.`);
    }
  }
  for (const assumption of assumptions) {
    const planId = readId(assumption, "plan_id", "assumption");
    if (!planIds.has(planId)) throw new Error(`Assumption references missing plan ${planId}.`);
    readId(assumption, "assumption_id", "assumption");
    if (!Array.isArray(assumption.sources)) throw new Error("Assumption sources must be a typed cleartext proof list.");
  }
  for (const revision of revisions) {
    const planId = readId(revision, "plan_id", "revision");
    if (!planIds.has(planId)) throw new Error(`Revision references missing plan ${planId}.`);
    readId(revision, "revision_id", "revision");
    if (!revision.snapshot || typeof revision.snapshot !== "object" || Array.isArray(revision.snapshot)) throw new Error("Revision requires a canonical plan snapshot.");
  }
  const graph = new Map<string, string[]>();
  for (const dependency of dependencies) {
    if (!dependency?.source_ref || !dependency.target_ref) throw new Error("Work recovery dependencies require source_ref and target_ref.");
    for (const ref of [dependency.source_ref, dependency.target_ref]) {
      const [kind, id] = ref.split(":", 2);
      if ((kind !== "plan" && kind !== "task") || !id || !(kind === "plan" ? planIds : taskIds).has(id)) throw new Error(`Work recovery dependency references missing object ${ref}.`);
    }
    graph.set(dependency.source_ref, [...(graph.get(dependency.source_ref) ?? []), dependency.target_ref]);
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (node: string): void => {
    if (visiting.has(node)) throw new Error(`Work recovery dependency cycle includes ${node}.`);
    if (visited.has(node)) return;
    visiting.add(node);
    for (const next of graph.get(node) ?? []) visit(next);
    visiting.delete(node);
    visited.add(node);
  };
  for (const node of graph.keys()) visit(node);
}

export function findRecoveryConflicts(document: WorkRecoveryDocument, projectId: string, current: { planIds: Iterable<string>; taskIds: Iterable<string> }): WorkRecoveryConflict[] {
  if (document.project.project_id !== projectId) return [{ kind: "plan", id: document.project.project_id, reason: "wrong_project" }];
  const plans = new Set(current.planIds);
  const tasks = new Set(current.taskIds);
  return [
    ...document.plans.filter((plan) => plans.has(readId(plan, "plan_id", "plan"))).map((plan) => ({ kind: "plan" as const, id: readId(plan, "plan_id", "plan"), reason: "already_exists" as const })),
    ...document.tasks.filter((task) => tasks.has(readId(task, "task_id", "task"))).map((task) => ({ kind: "task" as const, id: readId(task, "task_id", "task"), reason: "already_exists" as const })),
  ];
}

/** Compare restored content while ignoring server-generated lifecycle metadata. */
export function recoveryDocumentsSemanticallyEqual(left: WorkRecoveryDocument, right: WorkRecoveryDocument): boolean {
  return recoveryDocumentSemanticMismatchPaths(left, right).length === 0;
}

export function recoveryDocumentSemanticMismatchPaths(left: WorkRecoveryDocument, right: WorkRecoveryDocument): string[] {
  const mismatches: string[] = [];
  collectMismatchPaths(normalizeForComparison(left), normalizeForComparison(right), "$", mismatches);
  return mismatches;
}

function parseTypedSources(value: string): Array<Record<string, unknown>> {
  let parsed: unknown;
  try { parsed = JSON.parse(value); } catch { throw new Error("Assumption encrypted_sources was not valid JSON after decryption."); }
  if (!Array.isArray(parsed) || !parsed.every(isTypedSource)) throw new Error("Assumption encrypted_sources must contain typed proof records.");
  return parsed;
}

function isTypedSource(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const source = value as Record<string, unknown>;
  return (source.kind === "embed" && typeof source.embed_id === "string")
    || (source.kind === "url" && typeof source.url === "string")
    || (source.kind === "file" && typeof source.path === "string");
}

function assertNoCiphertext(value: unknown): void {
  if (Array.isArray(value)) return value.forEach(assertNoCiphertext);
  if (!value || typeof value !== "object") return;
  for (const [key, nested] of Object.entries(value)) {
    if (key.startsWith("encrypted_")) throw new Error(`Recovery projection must not contain ciphertext field ${key}.`);
    assertNoCiphertext(nested);
  }
}

function readId(value: Record<string, unknown>, key: string, type: string): string {
  if (typeof value[key] !== "string" || !value[key]) throw new Error(`Recovery ${type} requires ${key}.`);
  return value[key] as string;
}

function addStableId(value: Record<string, unknown>, key: string, ids: Set<string>, type: string): void {
  const id = readId(value, key, type);
  if (ids.has(id)) throw new Error(`Recovery document has duplicate ${type} ID ${id}.`);
  ids.add(id);
}

function assertProjectLink(value: Record<string, unknown>, projectId: string, type: string): void {
  if (!Array.isArray(value.linked_project_ids) || value.linked_project_ids.length !== 1 || value.linked_project_ids[0] !== projectId) {
    throw new Error(`Recovery ${type} must be scoped only to project ${projectId}.`);
  }
}

function normalizeForComparison(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeForComparison);
  if (!value || typeof value !== "object") return value;
  const normalized: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(value)) {
    if (["short_id", "revision_id", "version", "created_at", "updated_at", "completed_at", "position", "queue_state", "priority_level"].includes(key)) continue;
    normalized[key] = normalizeForComparison(nested);
  }
  return normalized;
}

function collectMismatchPaths(left: unknown, right: unknown, path: string, mismatches: string[]): void {
  if (mismatches.length >= 20) return;
  if (Object.is(left, right)) return;
  if (Array.isArray(left) && Array.isArray(right)) {
    if (left.length !== right.length) mismatches.push(`${path}.length`);
    for (let index = 0; index < Math.min(left.length, right.length); index += 1) collectMismatchPaths(left[index], right[index], `${path}[${index}]`, mismatches);
    return;
  }
  if (left && right && typeof left === "object" && typeof right === "object") {
    const leftRecord = left as Record<string, unknown>;
    const rightRecord = right as Record<string, unknown>;
    for (const key of new Set([...Object.keys(leftRecord), ...Object.keys(rightRecord)])) {
      if (!(key in leftRecord) || !(key in rightRecord)) mismatches.push(`${path}.${key}`);
      else collectMismatchPaths(leftRecord[key], rightRecord[key], `${path}.${key}`, mismatches);
    }
    return;
  }
  mismatches.push(path);
}

export function writeWorkRecoveryAtomically(path: string, document: WorkRecoveryDocument): void {
  validateWorkRecoveryDocument(document);
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporaryPath = `${path}.tmp`;
  writeFileSync(temporaryPath, stringify(document, { sortMapEntries: true, lineWidth: 0 }), { encoding: "utf8", mode: 0o600 });
  renameSync(temporaryPath, path);
}
