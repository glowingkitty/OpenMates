// frontend/packages/ui/src/services/projectCheckService.ts
// Page IO for Project Checks. The Rust core owns the definition hash check, the
// aggregate status, staleness, the create document and the run/result/confirm bodies
// (web_work `check*` ops); this adapter builds the `/v1/user-checks` routes, unwraps the
// Check key with the Project key, decrypts the ciphertext members, seals the create
// document and performs the HTTP calls. Every failure throws; callers show it.
// spec: specifications/features/checks

import { getApiEndpoint } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import {
  encryptWithEmbedKey, generateEmbedKey, unwrapEmbedKeyWithEmbedKey, wrapEmbedKeyWithMasterKey,
} from "./cryptoService";
import type { ProjectViewModel } from "./projectService";
import { decryptWorkFields, workClient, workDecide } from "./work/workRust";
import type {
  CheckAggregate, CheckView, HumanDecision, RunView, SourceKind, SourceResultStatus, SourceView,
} from "../components/embeds/checks/checkTypes";

interface WrapperRecord { key_type: string; hashed_project_id?: string | null; encrypted_check_key: string }
interface HeadRecord {
  check_id: string; status: string; current_revision_id: string; current_revision_number: number;
  key_wrappers?: WrapperRecord[]; encrypted_title: string; encrypted_description?: string | null;
}
interface RevisionRecord { revision_id: string; revision_number: number; definition_hash: string; encrypted_definition: string; sources: unknown; created_at: number }
interface ResultRecord { source_binding_id: string; status: string; test_result_embed_id?: string | null; human_decision?: string | null; confirmed_at?: number | null; encrypted_result?: string | null }
interface RunRecord { run_id: string; check_id: string; check_revision_id: string; status: string; created_at: number; finished_at?: number | null; encrypted_summary?: string | null; source_results: ResultRecord[] }
interface Definition { sources: Array<{ source_binding_id: string; source_kind: SourceKind; role: "required" | "supporting"; title: string; ref: string }> }
interface RunViewOut { aggregateStatus: CheckAggregate; stale: boolean; sourceResults: Array<ResultRecord & { detail: string | null }> }

/** A draft source as the plans.check skill result carries it, already mapped to a definition source. */
export interface DraftCheckSource { source_kind: SourceKind; role: "required" | "supporting"; title: string; ref: string }
/** A draft Check (assistant-drafted in chat) to save into a Project. */
export interface DraftCheck { title: string; description: string; requires_deterministic: boolean; sources: DraftCheckSource[] }

function client() {
  const work = workClient();
  if (!work) throw new Error("Checks need the Rust core, which is not available.");
  return work;
}

function route(project: ProjectViewModel, suffix = "", params: Record<string, string> = {}): string {
  const query = new URLSearchParams(params);
  if (project.teamId) query.set("team_id", project.teamId);
  const text = query.toString();
  return `/v1/user-checks${suffix}${text ? `?${text}` : ""}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(getApiEndpoint(path), {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) throw new Error(`Checks API failed (${response.status}): ${await response.text()}`);
  return (await response.json()) as T;
}

async function checkKey(project: ProjectViewModel, head: HeadRecord): Promise<Uint8Array> {
  const wanted = await computeSHA256(project.project_id);
  const wrappers = (head.key_wrappers ?? []).filter((wrapper) => wrapper.key_type === "project" && wrapper.hashed_project_id === wanted);
  if (wrappers.length !== 1) throw new Error(`Check ${head.check_id} has no unique Project key wrapper`);
  const key = await unwrapEmbedKeyWithEmbedKey(wrappers[0].encrypted_check_key, project.projectKey);
  if (!key) throw new Error(`Check ${head.check_id} key could not be unwrapped`);
  return key;
}

const iso = (value: number | string | null | undefined): string =>
  value === null || value === undefined || value === "" ? "" : typeof value === "number" ? new Date(value * 1000).toISOString() : String(value);

function resultStatus(kind: SourceKind, result: ResultRecord): SourceResultStatus {
  switch (result.status) {
    case "pending": return kind === "human_confirmation" ? "waiting_for_confirmation" : "queued";
    case "waived": return "passed";
    case "skipped": return "cancelled";
    case "blocked": return "error";
    default: return result.status as SourceResultStatus;
  }
}

async function toView(project: ProjectViewModel, head: HeadRecord, revisions: RevisionRecord[], runs: RunRecord[]): Promise<CheckView> {
  const key = await checkKey(project, head);
  const work = client();
  const headView = await workDecide<{ title: string; description: string }>(work, "checkView", { record: head, fields: await decryptWorkFields(head, key) });
  const current = revisions.find((revision) => revision.revision_id === head.current_revision_id);
  if (!current) throw new Error(`Check ${head.check_id} has no current revision`);
  const revision = await workDecide<{ definition?: Definition; requiresDeterministic?: boolean | null; error?: string }>(work, "checkRevisionView",
    { record: current, fields: await decryptWorkFields(current, key) });
  if (revision.error || !revision.definition) throw new Error(revision.error ?? "Check definition is missing");
  const definition = revision.definition;
  const bindings = definition.sources.map(({ source_binding_id, source_kind, role }) => ({ source_binding_id, source_kind, role }));
  const views = await Promise.all(runs.map(async (run) => ({
    run,
    view: await workDecide<RunViewOut>(work, "checkRunView", {
      record: run, fields: await decryptWorkFields(run, key), sources: bindings, currentRevisionId: head.current_revision_id,
    }),
  })));
  const latest = views.find((item) => item.run.check_revision_id === head.current_revision_id);
  const sources: SourceView[] = definition.sources.map((source) => {
    const result = latest?.view.sourceResults.find((item) => item.source_binding_id === source.source_binding_id);
    return {
      binding_id: source.source_binding_id, kind: source.source_kind, role: source.role, title: source.title, ref_label: source.ref,
      ...(result ? { latest_result: {
        status: resultStatus(source.source_kind, result),
        summary: result.detail ?? "",
        ...(result.test_result_embed_id ? { test_result_embed_id: result.test_result_embed_id } : {}),
        ...(source.source_kind === "human_confirmation" ? { human: {
          instruction: source.ref,
          ...(result.human_decision === "confirmed" || result.human_decision === "rejected" ? { decision: result.human_decision as HumanDecision } : {}),
          ...(result.confirmed_at ? { confirmed_at: iso(result.confirmed_at) } : {}),
        } } : {}),
      } } : {}),
    };
  });
  const runViews: RunView[] = views.map(({ run, view }) => ({
    run_id: run.run_id,
    revision_number: revisions.find((item) => item.revision_id === run.check_revision_id)?.revision_number ?? head.current_revision_number,
    subject_label: "", status: view.aggregateStatus, started_at: iso(run.created_at),
    ...(run.finished_at ? { finished_at: iso(run.finished_at) } : {}), stale: view.stale,
  }));
  const claims = new Set<string>();
  return {
    id: head.check_id, title: headView.title, description: headView.description,
    status: head.status as CheckView["status"], revision_number: head.current_revision_number,
    aggregate: latest ? latest.view.aggregateStatus : "never_run", stale: views.length > 0 && !latest,
    requires_deterministic: revision.requiresDeterministic === true, covered_claims: [...claims],
    sources, runs: runViews,
  };
}

/** Reads one Check with its current revision and runs, as the shared Check view. */
export async function openProjectCheck(project: ProjectViewModel, head: HeadRecord): Promise<CheckView> {
  const id = encodeURIComponent(head.check_id);
  const [revisions, runs] = await Promise.all([
    request<{ revisions: RevisionRecord[] }>(route(project, `/${id}/revisions`, { limit: "100" })),
    request<{ runs: RunRecord[] }>(route(project, `/${id}/runs`, { limit: "20" })),
  ]);
  return toView(project, head, revisions.revisions, runs.runs);
}

/** Lists a Project's Checks (`project_hash` filter) as Check views. */
export async function listProjectChecks(project: ProjectViewModel): Promise<CheckView[]> {
  const page = await request<{ checks: HeadRecord[] }>(route(project, "", { project_hash: await computeSHA256(project.project_id), limit: "100" }));
  return Promise.all(page.checks.map((head) => openProjectCheck(project, head)));
}

/** Reloads one Check by id (after a run or a confirmation). */
export async function reloadProjectCheck(project: ProjectViewModel, checkId: string): Promise<CheckView> {
  const detail = await request<{ check: HeadRecord }>(route(project, `/${encodeURIComponent(checkId)}`));
  return openProjectCheck(project, detail.check);
}

/** Records the human decision of the latest run's pending source; the core builds the body. */
export async function confirmProjectCheckSource(project: ProjectViewModel, check: CheckView, bindingId: string, decision: HumanDecision): Promise<void> {
  const run = [...check.runs].sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
  if (!run) throw new Error("This Check has no run to confirm.");
  const body = await workDecide<{ error?: string }>(client(), "checkConfirmBody", { decision });
  if (body.error) throw new Error(body.error);
  await request(route(project, `/runs/${encodeURIComponent(run.run_id)}/sources/${encodeURIComponent(bindingId)}/confirm`), { method: "POST", body: JSON.stringify(body) });
}

/** Starts a new run on the current revision. */
export async function startProjectCheckRun(project: ProjectViewModel, checkId: string): Promise<void> {
  const body = await workDecide<Record<string, unknown>>(client(), "checkStartRunBody", {});
  await request(route(project, `/${encodeURIComponent(checkId)}/runs`), { method: "POST", body: JSON.stringify(body) });
}

/** AES-GCM wrap of the Check key under the Project key (IV + ciphertext, base64), like the core's wrapper. */
async function wrapKey(key: Uint8Array, wrapping: Uint8Array): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const aes = await crypto.subtle.importKey("raw", new Uint8Array(wrapping), { name: "AES-GCM" }, false, ["encrypt"]);
  const sealed = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, aes, new Uint8Array(key)));
  const joined = new Uint8Array(iv.length + sealed.length);
  joined.set(iv);
  joined.set(sealed, iv.length);
  let binary = "";
  for (const byte of joined) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** Saves a drafted Check (head plus first revision) into the Project; returns its id. */
export async function createProjectCheck(project: ProjectViewModel, draft: DraftCheck): Promise<string> {
  if (project.teamId) throw new Error("Saving a Check into a team Project is not available yet.");
  const plan = await workDecide<{
    error?: string; title: string; description?: string; definition_text: string; hashed_project_id: string;
    body: { check_id: string; revision: Record<string, unknown> } & Record<string, unknown>;
  }>(client(), "checkCreateBody", {
    check_id: crypto.randomUUID(), revision_id: crypto.randomUUID(), project_id: project.project_id, status: "draft",
    title: draft.title, description: draft.description, requires_deterministic: draft.requires_deterministic,
    sources: draft.sources.map((source) => ({ source_binding_id: "", covers: [], ...source })),
  });
  if (plan.error) throw new Error(plan.error);
  const key = generateEmbedKey();
  const master = await wrapEmbedKeyWithMasterKey(key);
  if (!master) throw new Error("The master key is not available to wrap the Check key.");
  const body: Record<string, unknown> = {
    ...plan.body,
    encrypted_title: await encryptWithEmbedKey(plan.title, key),
    key_wrappers: [
      { key_type: "project", hashed_project_id: plan.hashed_project_id, encrypted_check_key: await wrapKey(key, project.projectKey) },
      { key_type: "master", encrypted_check_key: master },
    ],
    revision: { ...plan.body.revision, encrypted_definition: await encryptWithEmbedKey(plan.definition_text, key) },
  };
  if (plan.description) body.encrypted_description = await encryptWithEmbedKey(plan.description, key);
  await request(route(project), { method: "POST", body: JSON.stringify(body) });
  return plan.body.check_id;
}
