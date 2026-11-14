// frontend/packages/ui/src/services/projectSpecificationService.ts
// Page IO for Project Specifications. The Rust core owns the views, the content-hash
// check and the exact-approval body (web_work `specification*` ops); this adapter only
// builds the `/v1/projects/{p}/specifications` routes, unwraps the Specification key
// with the Project key, decrypts the ciphertext members and performs the HTTP calls.
// Every failure throws; callers show it.
// spec: specifications/features/specifications/specification.yml

import { getApiEndpoint } from "../config/api";
import { computeSHA256 } from "../message_parsing/utils";
import {
  encryptWithEmbedKey,
  generateEmbedKey,
  unwrapEmbedKeyWithEmbedKey,
  wrapEmbedKeyWithChatKey,
  wrapEmbedKeyWithMasterKey,
} from "./cryptoService";
import { getTeamKey } from "./teamService";
import type { ProjectViewModel } from "./projectService";
import { decryptWorkFields, workClient, workDecide } from "./work/workRust";
import type { SpecificationDocument } from "../components/embeds/specifications/SpecificationDocument";
import type {
  SpecificationApproval,
  SpecificationListItem,
  SpecificationRevisionSummary,
} from "../components/embeds/specifications/SpecificationRevision";

interface WrapperRecord { key_type: string; hashed_project_id?: string | null; encrypted_specification_key: string }
interface HeadRecord { specification_id: string; current_revision_id: string | null; key_wrappers?: WrapperRecord[]; updated_at?: number | string }
interface RevisionRecord { revision_id: string; revision_number: number; approval_state?: string | null; approved_at?: number | string | null }

interface RevisionView {
  revision_id: string;
  revisionNumber: number;
  contentHash: string;
  approvalState: string | null;
  approvedAt: number | string | null;
  title: string;
  summary: string;
  createdAt: number | string;
  document: SpecificationDocument;
  error?: string;
}
interface HeadView { specification_id: string; title: string; summary: string; currentRevisionId: string | null; currentRevisionNumber: number; updatedAt: number | string }

/** One opened Specification: the viewed document plus the revision history. */
export interface OpenedSpecification {
  id: string;
  document: SpecificationDocument;
  revisions: SpecificationRevisionSummary[];
  currentRevisionId: string;
  viewedRevisionId: string;
  viewedContentHash: string;
  approval: SpecificationApproval;
}

function client() {
  const work = workClient();
  if (!work) throw new Error("Specifications need the Rust core, which is not available.");
  return work;
}

function route(project: ProjectViewModel, suffix = "", params: Record<string, string> = {}): string {
  const query = new URLSearchParams(params);
  if (project.teamId) query.set("team_id", project.teamId);
  const text = query.toString();
  return `/v1/projects/${encodeURIComponent(project.project_id)}/specifications${suffix}${text ? `?${text}` : ""}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(getApiEndpoint(path), {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) throw new Error(`Specifications API failed (${response.status}): ${await response.text()}`);
  return (await response.json()) as T;
}

async function specificationKey(project: ProjectViewModel, head: HeadRecord): Promise<Uint8Array> {
  const wanted = await computeSHA256(project.project_id);
  const wrappers = (head.key_wrappers ?? []).filter((wrapper) => wrapper.key_type === "project" && wrapper.hashed_project_id === wanted);
  if (wrappers.length !== 1) throw new Error(`Specification ${head.specification_id} has no unique Project key wrapper`);
  return unwrapEmbedKeyWithEmbedKey(wrappers[0].encrypted_specification_key, project.projectKey);
}

async function revisionView(record: RevisionRecord, key: Uint8Array): Promise<RevisionView> {
  const fields = await decryptWorkFields(record, key);
  const view = await workDecide<RevisionView>(client(), "specificationRevisionView", { record, fields });
  if (view.error) throw new Error(view.error);
  return view;
}

function iso(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  return typeof value === "number" ? new Date(value * 1000).toISOString() : String(value);
}

/** Lists a Project's Specifications as card items (head title plus current-revision document facts). */
export async function listProjectSpecifications(project: ProjectViewModel): Promise<SpecificationListItem[]> {
  const page = await request<{ specifications: HeadRecord[] }>(route(project, "", { limit: "100" }));
  return Promise.all(page.specifications.map(async (head) => {
    const key = await specificationKey(project, head);
    const headView = await workDecide<HeadView>(client(), "specificationView", { record: head, fields: await decryptWorkFields(head, key) });
    const detail = await request<{ revision: RevisionRecord }>(route(project, `/${encodeURIComponent(head.specification_id)}`));
    const revision = await revisionView(detail.revision, key);
    const requirements = revision.document.requirements ?? [];
    return {
      id: head.specification_id,
      title: headView.title,
      kind: revision.document.category ?? "",
      status: revision.approvalState === "approved" ? "approved" : "draft",
      revisionNumber: headView.currentRevisionNumber,
      updatedAt: iso(headView.updatedAt),
      requirementCount: requirements.length,
      proof: {
        passed: requirements.filter((item) => item.proof?.state === "passed").length,
        open: requirements.filter((item) => item.proof?.state === "open").length,
        stale: requirements.filter((item) => item.proof?.state === "stale").length,
      },
    } satisfies SpecificationListItem;
  }));
}

/** Opens one Specification at a revision (default: the head revision) with its history. */
export async function openProjectSpecification(project: ProjectViewModel, specificationId: string, revisionId?: string): Promise<OpenedSpecification> {
  const base = `/${encodeURIComponent(specificationId)}`;
  const detail = await request<{ specification: HeadRecord; revision: RevisionRecord }>(
    route(project, base, revisionId ? { revision_id: revisionId } : {}));
  const key = await specificationKey(project, detail.specification);
  const history = await request<{ revisions: RevisionRecord[] }>(route(project, `${base}/revisions`, { limit: "100" }));
  const viewed = await revisionView(detail.revision, key);
  const views = await Promise.all(history.revisions.map((record) => revisionView(record, key)));
  const currentRevisionId = detail.specification.current_revision_id ?? viewed.revision_id;
  const revisions: SpecificationRevisionSummary[] = views.map((view) => ({
    revision_id: view.revision_id,
    revision_number: view.revisionNumber,
    created_at: iso(view.createdAt),
    author_label: "",
    summary: view.summary,
    status: view.approvalState === "approved" ? "approved" : view.revision_id === currentRevisionId ? "draft" : "superseded",
    content_hash: view.contentHash,
  }));
  const approvedView = views.filter((view) => view.approvalState === "approved").sort((a, b) => b.revisionNumber - a.revisionNumber)[0];
  const approval: SpecificationApproval = !approvedView
    ? { state: "draft", approved_revision_id: null, approved_at: null }
    : { state: approvedView.revision_id === currentRevisionId ? "approved" : "stale", approved_revision_id: approvedView.revision_id, approved_at: iso(approvedView.approvedAt) };
  return {
    id: specificationId,
    document: viewed.document,
    revisions,
    currentRevisionId,
    viewedRevisionId: viewed.revision_id,
    viewedContentHash: viewed.contentHash,
    approval,
  };
}

/** Approves exactly the given revision and content hash (the server refuses a mismatch). */
export async function approveProjectSpecification(project: ProjectViewModel, specificationId: string, revisionId: string, contentHash: string): Promise<void> {
  const body = await workDecide<Record<string, unknown>>(client(), "specificationApproveBody", {
    revision: { revision_id: revisionId, content_hash: contentHash },
  });
  await request(route(project, `/${encodeURIComponent(specificationId)}/approve`), { method: "POST", body: JSON.stringify(body) });
}

interface CreatePlan {
  specification_id: string;
  revision_id: string;
  content_hash: string;
  catalog_revision_id: string;
  title: string;
  summary: string;
  document_text: string;
  error?: string;
}

/**
 * Saves a drafted Specification as the first revision of a new Specification in the Project.
 * The Rust core validates the document and fixes the committed plaintext; this seals it with a
 * fresh key wrapped for the Project and for the owner (master key, or the team key in a Team).
 * Returns the new Specification id.
 */
export async function createProjectSpecification(project: ProjectViewModel, document: SpecificationDocument): Promise<string> {
  const plan = await workDecide<CreatePlan>(client(), "specificationCreatePlan", {
    document, specification_id: crypto.randomUUID(), revision_id: crypto.randomUUID(),
  });
  if (plan.error) throw new Error(plan.error);
  const key = generateEmbedKey();
  const wrappers: Array<Record<string, unknown>> = [{
    key_type: "project",
    hashed_project_id: await computeSHA256(project.project_id),
    encrypted_specification_key: await wrapEmbedKeyWithChatKey(key, project.projectKey),
  }];
  if (project.teamId) {
    wrappers.push({
      key_type: "team",
      hashed_team_id: await computeSHA256(project.teamId),
      team_key_epoch: 1,
      encrypted_specification_key: await wrapEmbedKeyWithChatKey(key, await getTeamKey(project.teamId)),
    });
  } else {
    const master = await wrapEmbedKeyWithMasterKey(key);
    if (!master) throw new Error("Could not wrap the Specification key with the master key");
    wrappers.push({ key_type: "master", encrypted_specification_key: master });
  }
  await request(route(project), {
    method: "POST",
    body: JSON.stringify({
      specification_id: plan.specification_id,
      revision_id: plan.revision_id,
      content_hash: plan.content_hash,
      project_surface_catalog_revision_id: plan.catalog_revision_id,
      encrypted_title: await encryptWithEmbedKey(plan.title, key),
      encrypted_summary: await encryptWithEmbedKey(plan.summary, key),
      encrypted_specification_document: await encryptWithEmbedKey(plan.document_text, key),
      key_wrappers: wrappers,
    }),
  });
  return plan.specification_id;
}
