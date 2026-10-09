/** Bounded first-party context snapshots; discovery metadata never grants Project file access. */
import type { OpenMatesClient, TeamContextOptions, UserPlanRecord, UserTaskRecord } from "./client.js";
import { decryptWithAesGcmCombined } from "./crypto.js";
import { parseDocument, isAlias, visit } from "yaml";
import { projectFocusDocumentFromMetadata, type ProjectFocusDocument } from "../../projectFocusDocument.js";
import { createHash } from "node:crypto";

export interface CustomRuleDocument { id: string; source: "personal" | "project"; project_id?: string; document: string; item_revision?: string }
export interface ProjectContextDocument { item_id: string; kind: "spec" | "memory" | "fact" | "folder"; title: string; description: string; document: string; revision: string }
export interface ProjectFocusCatalogEntry { id: string; title: string; summary: string; revision: string }
export interface ProjectFocusDocumentInput { item_id: string; document: string; revision: string }
export interface RelatedTaskCandidate { task_id: string; title: string; summary: string; project_id: string | null; status: string; changed_at: number; revision: string; explicit_dependency: boolean }
export interface AcceptedPlanContext {
  plan_id: string; version: number; approved_revision_id: string; summary: string; linked_task_id?: string;
}
export interface CliJevContext {
  /** Fresh server-approved current Plan, derived from existing chat/Task linkage. */
  accepted_plan_context?: AcceptedPlanContext | null;
  project_focus_candidates?: Array<{ project_id: string; name: string; summary: string; auto_selection: boolean; focus_activation_policy: "delayed" | "immediate" | "approval" }>;
  custom_memory_documents?: CustomRuleDocument[];
  /** Legacy input alias, never a personal consent bypass. */
  custom_rule_documents?: CustomRuleDocument[];
  project_focus_catalog?: ProjectFocusCatalogEntry[];
  project_focus_documents?: ProjectFocusDocumentInput[];
  project_context_documents?: ProjectContextDocument[];
  related_task_candidates?: RelatedTaskCandidate[];
}
export type FocusAuthoringDocument = ProjectFocusDocument;

export function parseFocusAuthoringDocument(document: string): FocusAuthoringDocument {
  if (document.length > 96_000) throw new Error("invalid_focus_document");
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)([\s\S]*)$/.exec(document);
  if (!match) throw new Error("invalid_focus_document");
  try {
    const parsed = parseDocument(match[1], { schema: "core", uniqueKeys: true });
    if (parsed.errors.length) throw new Error("invalid_focus_document");
    visit(parsed, (_key, node) => { if (isAlias(node)) throw new Error("invalid_focus_document"); });
    return projectFocusDocumentFromMetadata(parsed.toJS({ maxAliasCount: 0 }), match[2]);
  } catch { throw new Error("invalid_focus_document"); }
}

export async function discoverCliProjectCandidates(client: OpenMatesClient, options: TeamContextOptions): Promise<NonNullable<CliJevContext["project_focus_candidates"]>> {
  const records = (await client.listProjects(options)).filter(record => !record.archived).slice(0, 40);
  const entries = await Promise.all(records.map(async record => {
    try {
      const [key, settings] = await Promise.all([client.decryptProjectKey(record, options), client.getProjectSettings(record.project_id, options)]);
      const [name, summary] = await Promise.all([
        typeof record.encrypted_name === "string" ? decryptWithAesGcmCombined(record.encrypted_name, key) : null,
        typeof record.encrypted_description === "string" ? decryptWithAesGcmCombined(record.encrypted_description, key) : null,
      ]);
      return name ? { project_id: record.project_id, name: name.slice(0, 160), summary: (summary ?? "").slice(0, 640),
        auto_selection: settings.auto_selection !== false,
        focus_activation_policy: (settings.focus_activation_policy === "immediate" || settings.focus_activation_policy === "approval" ? settings.focus_activation_policy : "delayed") as "delayed" | "immediate" | "approval" } : null;
    } catch { return null; }
  }));
  return entries.filter((entry): entry is NonNullable<typeof entry> => entry !== null);
}

/** Metadata selection precedes private file reads; fresh accepted specialists are retained. */
export async function loadActiveCliProjectContext(client: OpenMatesClient, chatId: string, text?: string): Promise<CliJevContext & { projectId?: string; focusCatalogComplete?: boolean }> {
  const active = await client.getActiveProjectFocus(chatId);
  if (!active) return {};
  const options = { teamId: active.team_id, personal: !active.team_id };
  const detail = await client.getProject(active.project_id, options);
  const key = await client.decryptProjectKey(detail.project, options);
  const result: CliJevContext & { projectId: string; focusCatalogComplete: boolean } = { projectId: active.project_id, focusCatalogComplete: true,
    custom_rule_documents: [], project_focus_catalog: [], project_focus_documents: [], project_context_documents: [] };
  const revision = (item: Record<string, unknown>) => createHash("sha256").update(["updated_at", "encrypted_metadata", "encrypted_note", "target_id_hash", "deleted_target_state"].map(field => item[field] ? String(item[field]) : "").join("\0")).digest("hex");
  const candidates: Array<{ kind: "focus" | "memory" | "rule" | "spec" | "fact" | "folder"; id: string; title: string; description: string; when_to_use: string; revision: string }> = [];
  const targets = new Map<string, { item: typeof detail.items[number]; metadata: Record<string, unknown> }>();
  for (const item of detail.items) {
    if (!["embed", "upload"].includes(item.item_type) || !item.encrypted_metadata || item.deleted_target_state) continue;
    const metadataText = await decryptWithAesGcmCombined(item.encrypted_metadata, key);
    const metadata = metadataText ? JSON.parse(metadataText) as Record<string, unknown> : {};
    const path = typeof (metadata.path ?? metadata.display_path) === "string" ? String(metadata.path ?? metadata.display_path) : "";
    const match = /^\.openmates\/(memories|rules|focuses|specs|facts)\/[^\0]+(?:\.md|\/SKILL\.md)$/.exec(path);
    if (!match || path.split("/").some(part => part === ".." || part === "." || !part)) continue;
    const kind = ({ memories: "memory", rules: "rule", focuses: "focus", specs: "spec", facts: "memory" } as const)[match[1] as "memories" | "rules" | "focuses" | "specs" | "facts"];
    const title = metadata.focus_title ?? metadata.title ?? metadata.name;
    const description = metadata.focus_description ?? metadata.summary ?? metadata.description;
    const currentRevision = revision(item);
    if (typeof title !== "string" || typeof description !== "string") { if (kind === "focus") result.focusCatalogComplete = false; continue; }
    if (kind === "focus") {
      if (result.project_focus_catalog!.length >= 20) { result.focusCatalogComplete = false; continue; }
      result.project_focus_catalog!.push({ id: item.project_item_id, title: title.slice(0, 200), summary: description.slice(0, 640), revision: currentRevision });
    }
    candidates.push({ kind, id: item.project_item_id, title: title.slice(0, 200), description: description.slice(0, 640),
      when_to_use: typeof metadata.focus_when_to_use === "string" ? metadata.focus_when_to_use.slice(0, 640) : "", revision: currentRevision });
    targets.set(item.project_item_id, { item, metadata });
  }
  for (const folder of detail.folders) {
    if (typeof folder.folder_id !== "string" || typeof folder.encrypted_name !== "string") continue;
    const title = await decryptWithAesGcmCombined(folder.encrypted_name, key);
    const description = typeof folder.encrypted_description === "string" ? await decryptWithAesGcmCombined(folder.encrypted_description, key) : "";
    if (title && description) candidates.push({ kind: "folder", id: folder.folder_id, title: title.slice(0, 200), description: description.slice(0, 640), when_to_use: "", revision: revision(folder) });
  }
  let selected: Array<{ id: string; kind: string; revision: string }> = [];
  if (text?.trim() && candidates.length) selected = await client.selectProjectContext(active.project_id,
    { chat_id: chatId, text: text.slice(0, 8000), candidates: candidates.slice(0, 24) }, options);
  const specialistId = active.specialist_focus_id?.startsWith(`project-focus:${active.project_id}:`) ? active.specialist_focus_id.split(":")[2] : active.specialist_focus_id;
  const specialist = candidates.find(candidate => candidate.kind === "focus" && candidate.id === specialistId);
  if (specialist && !selected.some(candidate => candidate.id === specialist.id)) selected.push(specialist);
  let totalChars = 0;
  for (const choice of selected.slice(0, 5)) {
    const candidate = candidates.find(row => row.id === choice.id && row.kind === choice.kind && row.revision === choice.revision);
    if (!candidate) continue;
    const current = await client.getActiveProjectFocus(chatId);
    if (current?.project_id !== active.project_id || current.team_id !== active.team_id || current.focus_id !== active.focus_id
        || current.specialist_focus_id !== active.specialist_focus_id || current.activated_at !== active.activated_at) return {};
    if (candidate.kind === "folder") {
      const folder = detail.folders.find(row => row.folder_id === candidate.id);
      if (!folder) continue;
      const document = typeof folder.encrypted_description === "string" ? await decryptWithAesGcmCombined(folder.encrypted_description, key) : null;
      if (document && document.length <= 24_000) result.project_context_documents!.push({ item_id: candidate.id, kind: "folder", title: candidate.title, description: candidate.description, document, revision: candidate.revision });
      continue;
    }
    const target = targets.get(candidate.id); if (!target) continue;
    const embedId = await decryptWithAesGcmCombined(target.item.target_id_encrypted, key); if (!embedId) continue;
    const head = await client.readEncryptedProjectFile(active.project_id, embedId, key, options);
    const document = [head.content.code, head.content.content, head.content.markdown, head.content.text].find(value => typeof value === "string");
    if (typeof document !== "string" || document.length > (candidate.kind === "focus" ? 60_000 : 24_000) || totalChars + document.length > 64_000) continue;
    totalChars += document.length;
    if (candidate.kind === "focus") result.project_focus_documents!.push({ item_id: candidate.id, document, revision: candidate.revision });
    else if (candidate.kind === "rule") result.custom_rule_documents!.push({ id: candidate.id, source: "project", project_id: active.project_id, document, item_revision: candidate.revision });
    else result.project_context_documents!.push({ item_id: candidate.id, kind: candidate.kind, title: candidate.title, description: candidate.description, document, revision: candidate.revision });
  }
  const [fresh, latest] = await Promise.all([client.getActiveProjectFocus(chatId), client.getProject(active.project_id, options)]);
  if (fresh?.project_id !== active.project_id || fresh.team_id !== active.team_id || fresh.focus_id !== active.focus_id || fresh.specialist_focus_id !== active.specialist_focus_id || fresh.activated_at !== active.activated_at) return {};
  const unchanged = (id: string, oldRevision: string) => { const row = latest.items.find(item => item.project_item_id === id) ?? latest.folders.find(folder => folder.folder_id === id); return row && revision(row) === oldRevision; };
  result.project_focus_documents = result.project_focus_documents!.filter(document => unchanged(document.item_id, document.revision));
  result.project_context_documents = result.project_context_documents!.filter(document => unchanged(document.item_id, document.revision));
  result.custom_rule_documents = result.custom_rule_documents!.filter(document => { const candidate = candidates.find(row => row.id === document.id); return candidate && unchanged(document.id, candidate.revision); });
  return result;
}

const CURRENT_PLAN_STATES = new Set(["active", "executing", "running_checks", "blocked"]);
const OPEN_LINKED_TASK_STATES = new Set(["todo", "backlog", "in_progress", "blocked", "pending"]);
function approvedCurrentPlan(plan: UserPlanRecord): boolean {
  return typeof plan.plan_id === "string" && Boolean(plan.plan_id) && plan.plan_id.length <= 128 && CURRENT_PLAN_STATES.has(plan.status) && Number.isSafeInteger(plan.version) && Number(plan.version) >= 1
    && plan.approval_state === "approved" && typeof plan.approved_revision_id === "string" && Boolean(plan.approved_revision_id)
    && plan.approved_revision_id.length <= 128 && plan.submitted_revision_id === plan.approved_revision_id;
}
function linkedOpenTask(task: UserTaskRecord | null, chatId: string, planId: string): task is UserTaskRecord {
  return Boolean(task && task.primary_chat_id === chatId && task.plan_id === planId && OPEN_LINKED_TASK_STATES.has(task.status)
    && Number.isSafeInteger(task.version) && Number(task.version) >= 1);
}

/** Plan state is context only. Approval and chat linkage always come from fresh server records. */
export async function collectAcceptedCliPlanContext(client: OpenMatesClient, chatId: string, options: TeamContextOptions,
  ownedTaskRecords: UserTaskRecord[] = []): Promise<AcceptedPlanContext | null> {
  const candidates = new Map<string, string[]>();
  try {
    const plans = await client.listUserPlans({ ...options, chatId, activeOnly: false });
    for (const plan of plans.filter(plan => plan.primary_chat_id === chatId && approvedCurrentPlan(plan))
      .sort((a, b) => Number(b.updated_at ?? 0) - Number(a.updated_at ?? 0) || a.plan_id.localeCompare(b.plan_id))) candidates.set(plan.plan_id, []);
  } catch { /* Task-linked Plan discovery can still use owned current Task records. */ }
  for (const task of ownedTaskRecords.filter(task => task && typeof task.task_id === "string" && task.primary_chat_id === chatId).sort((a, b) => a.task_id.localeCompare(b.task_id)).slice(0, 60)) {
    if (!task.plan_id || !linkedOpenTask(task, chatId, task.plan_id)) continue;
    const refs = candidates.get(task.plan_id) ?? []; refs.push(task.task_id); candidates.set(task.plan_id, refs);
  }
  for (const [planId, taskIds] of [...candidates].slice(0, 8)) {
    try {
      const plan = await client.getUserPlan(planId, options);
      if (plan.plan_id !== planId || !approvedCurrentPlan(plan)) continue;
      let linkedTaskId: string | undefined;
      if (plan.primary_chat_id !== chatId) {
        for (const id of taskIds.slice(0, 4)) {
          const task = await client.getUserTask(id, options);
          if (task?.task_id === id && linkedOpenTask(task, chatId, planId)) { linkedTaskId = id; break; }
        }
        if (!linkedTaskId) continue;
      }
      const version = plan.version!, approvedRevision = plan.approved_revision_id!, submittedRevision = plan.submitted_revision_id, primaryChatId = plan.primary_chat_id;
      const summary = await client.decryptPlanContextSummary(plan, options);
      if (!summary.trim() || summary.length > 4000) continue;
      const latest = await client.getUserPlan(planId, options);
      if (!approvedCurrentPlan(latest) || latest.plan_id !== planId || latest.version !== version
          || latest.approved_revision_id !== approvedRevision || latest.submitted_revision_id !== submittedRevision
          || latest.primary_chat_id !== primaryChatId) continue;
      if (linkedTaskId) {
        const latestTask = await client.getUserTask(linkedTaskId, options);
        if (latestTask?.task_id !== linkedTaskId || !linkedOpenTask(latestTask, chatId, planId)) continue;
      }
      return { plan_id: planId, version, approved_revision_id: approvedRevision, summary,
        ...(linkedTaskId ? { linked_task_id: linkedTaskId } : {}) };
    } catch { /* Inaccessible or stale Plan context grants no authority and is omitted. */ }
  }
  return null;
}

/** Current chat work precedes general discovery; dependency references never grant Task authority. */
export async function collectRelatedCliTaskContext(client: OpenMatesClient, chatId: string, options: TeamContextOptions,
  records: UserTaskRecord[], nowSeconds = Date.now() / 1000): Promise<RelatedTaskCandidate[]> {
  const owned = records.filter(record => typeof record.task_id === "string" && record.task_id.length > 0 && record.task_id.length <= 128
    && Number.isSafeInteger(record.version) && Number(record.version) >= 1);
  const linked = owned.filter(record => record.primary_chat_id === chatId && OPEN_LINKED_TASK_STATES.has(record.status)).sort((a, b) => a.task_id.localeCompare(b.task_id));
  const dependencies = new Set<string>();
  if (typeof client.getTaskDependencies === "function") await Promise.all(linked.slice(0, 4).map(async task => {
    try {
      const result = await client.getTaskDependencies(task.task_id, options);
      const ref = `task:${task.task_id}`;
      for (const edge of [...result.dependencies, ...result.blockers].slice(0, 40)) {
        const other = edge.source_ref === ref ? edge.target_ref : edge.target_ref === ref ? edge.source_ref : null;
        if (typeof other === "string" && other.startsWith("task:")) dependencies.add(other.slice(5));
      }
    } catch { /* Missing dependency discovery leaves actual chat-linked work available. */ }
  }));
  const changedAt = (record: UserTaskRecord) => Number(record.updated_at ?? record.created_at ?? 0);
  const priority = (record: UserTaskRecord): number => {
    if (record.primary_chat_id === chatId && OPEN_LINKED_TASK_STATES.has(record.status)) return 0;
    if (dependencies.has(record.task_id)) return 1;
    if (record.status === "in_progress") return 2;
    if (["blocked", "done"].includes(record.status) && changedAt(record) >= nowSeconds - 1800) return 3;
    return 4;
  };
  const selected = owned.filter(record => priority(record) < 4).sort((a, b) => priority(a) - priority(b)
    || changedAt(b) - changedAt(a) || a.task_id.localeCompare(b.task_id)).slice(0, 24);
  const candidates: RelatedTaskCandidate[] = [];
  for (const record of selected) {
    try {
      const task = await client.decryptTaskContextRecord(record, options);
      candidates.push({ task_id: record.task_id, title: task.title.slice(0, 200), summary: task.description.slice(0, 1000),
        project_id: task.linkedProjectIds[0] ?? null, status: record.status, changed_at: changedAt(record),
        revision: String(record.version), explicit_dependency: dependencies.has(record.task_id) });
    } catch { /* Unavailable private summary is omitted. The server validates current ownership and version. */ }
  }
  return candidates;
}

export async function prepareCliJevContext(client: OpenMatesClient, chatId: string, options: TeamContextOptions, supplied: CliJevContext = {}, text?: string): Promise<CliJevContext> {
  let candidates: CliJevContext["project_focus_candidates"] = [];
  let active: Awaited<ReturnType<typeof loadActiveCliProjectContext>> = {};
  let tasks: RelatedTaskCandidate[] = [];
  let ownedTaskRecords: UserTaskRecord[] = [];
  await Promise.all([
    discoverCliProjectCandidates(client, options).then(value => { candidates = value; }).catch(() => {}),
    loadActiveCliProjectContext(client, chatId, text).then(value => { active = value; }).catch(() => {}),
    (async () => {
      const records = await client.listUserTasks({ ...options, limit: 500 });
      ownedTaskRecords = records;
      tasks = await collectRelatedCliTaskContext(client, chatId, options, records);
    })().catch(() => {}),
  ]);
  const acceptedPlan = await collectAcceptedCliPlanContext(client, chatId, options, ownedTaskRecords).catch(() => null);
  const { projectId, focusCatalogComplete: _complete, ...loaded } = active;
  const current = await client.getActiveProjectFocus(chatId).catch(() => null);
  if (current?.project_id !== projectId) {
    delete loaded.project_focus_catalog; delete loaded.project_focus_documents;
    delete loaded.project_context_documents; delete loaded.custom_rule_documents;
  }
  const customDocuments: CustomRuleDocument[] = [];
  let documentChars = 0; const documentIds = new Set<string>();
  for (const rule of [...(loaded.custom_rule_documents ?? []), ...(supplied.custom_memory_documents ?? supplied.custom_rule_documents ?? [])]) {
    const identity = `${rule.source}:${rule.project_id ?? ""}:${rule.id}`;
    if (rule.source !== "project" || rule.project_id !== current?.project_id || typeof rule.document !== "string"
        || rule.document.length > 24_000 || documentChars + rule.document.length > 64_000 || documentIds.has(identity) || customDocuments.length >= 24) continue;
    documentChars += rule.document.length; documentIds.add(identity); customDocuments.push(rule);
  }
  return {
    accepted_plan_context: acceptedPlan,
    project_focus_candidates: (supplied.project_focus_candidates ?? candidates).slice(0, 40),
    related_task_candidates: (supplied.related_task_candidates ?? tasks).slice(0, 24),
    custom_memory_documents: customDocuments,
    project_focus_catalog: current ? (supplied.project_focus_catalog ?? loaded.project_focus_catalog ?? []).slice(0, 20) : [],
    project_focus_documents: current ? (supplied.project_focus_documents ?? loaded.project_focus_documents ?? []).slice(0, 20) : [],
    project_context_documents: current ? (supplied.project_context_documents ?? loaded.project_context_documents ?? []).slice(0, 20) : [],
  };
}
