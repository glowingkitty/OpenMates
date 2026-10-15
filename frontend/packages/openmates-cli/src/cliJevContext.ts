/** Bounded first-party context snapshots; discovery metadata never grants Project file access. */
import type { OpenMatesClient, TeamContextOptions, UserPlanRecord, UserTaskRecord } from "./client.js";
import { decryptWithAesGcmCombined } from "./crypto.js";
import { parseDocument, isAlias, visit } from "yaml";
import { projectFocusDocumentFromMetadata, type ProjectFocusDocument } from "../../projectFocusDocument.js";
import { createHash } from "node:crypto";
import type { OpenMatesWsClient } from "./ws.js";

export interface CustomRuleDocument { id: string; source: "personal" | "project"; project_id?: string; document: string; item_revision?: string }
export interface ProjectContextDocument { item_id: string; kind: "spec" | "memory" | "fact" | "folder"; title: string; description: string; document: string; revision: string }
export interface ProjectFocusCatalogEntry { id: string; title: string; summary: string; revision: string }
export interface SelectedProjectFocusMetadata { item_id: string; revision: string; title: string; description: string; when_to_use: string }
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

/** One server-selected Project's Focus metadata, before consent or file access. */
export async function collectSelectedCliProjectFocusRoutingCatalog(client: OpenMatesClient, projectId: string,
  options: TeamContextOptions): Promise<SelectedProjectFocusMetadata[]> {
  const detail = await client.getProject(projectId, options);
  if (detail.project.project_id !== projectId || detail.project.archived) throw new Error("Project catalog unavailable.");
  const key = await client.decryptProjectKey(detail.project, options);
  const focuses: SelectedProjectFocusMetadata[] = [];
  for (const item of detail.items) {
    if (!(["embed", "upload"].includes(item.item_type) && item.target_id_hash && !item.deleted_target_state
      && typeof item.encrypted_metadata === "string")) continue;
    const decrypted = await decryptWithAesGcmCombined(item.encrypted_metadata, key);
    if (!decrypted) throw new Error("Project catalog metadata unavailable.");
    const metadata = JSON.parse(decrypted) as Record<string, unknown>;
    const path = metadata.display_path;
    if (typeof path !== "string" || !/^\.openmates\/focuses\/[a-zA-Z0-9_-]+\/SKILL\.md$/.test(path)
      || typeof metadata.focus_title !== "string" || typeof metadata.focus_description !== "string"
      || typeof metadata.focus_when_to_use !== "string") continue;
    focuses.push({ item_id: item.project_item_id,
      revision: createHash("sha256").update(["updated_at", "encrypted_metadata", "encrypted_note", "target_id_hash", "deleted_target_state"]
        .map(field => item[field] ? String(item[field]) : "").join("\0")).digest("hex"),
      title: metadata.focus_title.slice(0, 180), description: metadata.focus_description.slice(0, 640),
      when_to_use: metadata.focus_when_to_use.slice(0, 640) });
    if (focuses.length >= 20) break;
  }
  return focuses;
}

/** This live turn's executor responds to one pre-activation catalog handoff. */
export function registerCliProjectFocusCatalogResponder(input: {
  ws: Pick<OpenMatesWsClient, "onMessageType" | "onClose" | "isOpen" | "sendAsync">;
  client: OpenMatesClient; chatId: string; teamId: string | null;
  isCurrent: () => boolean; isOfferedProject: (projectId: string) => boolean;
  onDeliveryFailure: (error: Error) => void;
}): () => void {
  let active = true;
  const answered = new Set<string>();
  const stopEvent = input.ws.onMessageType<Record<string, unknown>>("project_focus_catalog_requested", event => {
    if (!active || !input.ws.isOpen() || !input.isCurrent()
      || event.chat_id !== input.chatId || typeof event.request_id !== "string" || !event.request_id
      || event.request_id.length > 128 || typeof event.project_id !== "string" || !event.project_id
      || event.project_id.length > 128 || event.team_id !== input.teamId
      || !input.isOfferedProject(event.project_id) || answered.has(event.request_id)) return;
    answered.add(event.request_id);
    void (async () => {
      let focuses: SelectedProjectFocusMetadata[] | null;
      try { focuses = await collectSelectedCliProjectFocusRoutingCatalog(input.client, event.project_id as string,
        { teamId: input.teamId, personal: !input.teamId }); }
      catch { focuses = null; }
      if (!active || !input.ws.isOpen() || !input.isCurrent()) return;
      await input.ws.sendAsync("project_focus_catalog_result", {
        chat_id: input.chatId, request_id: event.request_id, project_id: event.project_id, focuses,
      });
    })().catch(error => {
      if (!active || !input.ws.isOpen() || !input.isCurrent()) return;
      input.onDeliveryFailure(error instanceof Error ? error : new Error("Project catalog delivery failed."));
    });
  });
  const stopClose = input.ws.onClose(() => { active = false; stopEvent(); });
  return () => { active = false; stopEvent(); stopClose(); };
}

export async function discoverCliProjectCandidates(client: OpenMatesClient, options: TeamContextOptions,
  requireComplete = false): Promise<NonNullable<CliJevContext["project_focus_candidates"]>> {
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
    } catch (error) { if (requireComplete) throw error; return null; }
  }));
  if (requireComplete && entries.some(entry => entry === null)) throw new Error("Project directory is incomplete.");
  return entries.filter((entry): entry is NonNullable<typeof entry> => entry !== null);
}


export interface EncryptedPersonalProjectCandidate {
  project_id: string; encrypted_project_key: string; encrypted_name: string; encrypted_description: string | null;
  auto_selection: true; focus_activation_policy: "delayed" | "immediate" | "approval";
}

/** Decrypt only the server-filtered, send-time Personal routing directory. */
export async function decodePersonalProjectCandidates(client: OpenMatesClient,
  rows: EncryptedPersonalProjectCandidate[]): Promise<NonNullable<CliJevContext["project_focus_candidates"]>> {
  if (rows.length > 40) throw new Error("Personal Project directory is too large.");
  return Promise.all(rows.map(async row => {
    if (row.auto_selection !== true) throw new Error("Disabled Project in Personal routing directory.");
    const key = await client.decryptProjectKey({ ...row }, { personal: true });
    const [name, summary] = await Promise.all([
      decryptWithAesGcmCombined(row.encrypted_name, key),
      row.encrypted_description ? decryptWithAesGcmCombined(row.encrypted_description, key) : Promise.resolve(""),
    ]);
    if (!name || summary === null) throw new Error("Personal Project directory is incomplete.");
    return { project_id: row.project_id, name: name.slice(0, 160), summary: summary.slice(0, 640),
      auto_selection: true, focus_activation_policy: row.focus_activation_policy };
  }));
}

/** Metadata selection precedes private file reads; fresh accepted specialists are retained. */
export async function loadActiveCliProjectContext(client: OpenMatesClient, chatId: string, text?: string, onCatalog?: (catalog: ProjectFocusCatalogEntry[]) => void,
  prefetched?: PrefetchedDiscoveryReads): Promise<CliJevContext & { projectId?: string; focusCatalogComplete?: boolean }> {
  const active = await (prefetched?.activeFocusRead ?? client.getActiveProjectFocus(chatId));
  prefetched?.assertCurrent();
  if (!active) return {};
  const options = { teamId: active.team_id, personal: !active.team_id };
  const detail = prefetched ? await prefetched.projectRead : await client.getProject(active.project_id, options);
  prefetched?.assertCurrent();
  if (!detail) throw new Error("Active Project discovery unavailable.");
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
  onCatalog?.(result.project_focus_catalog ?? []);
  let selected: Array<{ id: string; kind: string; revision: string }> = [];
  prefetched?.assertCurrent();
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
  ownedTaskRecords: UserTaskRecord[] = [], plansRead?: Promise<UserPlanRecord[]>): Promise<AcceptedPlanContext | null> {
  const candidates = new Map<string, string[]>();
  try {
    const plans = await (plansRead ?? client.listUserPlans({ ...options, chatId, activeOnly: false }));
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

/** Snapshot ownership only: discovered Task rows never become cached permissions. */
function taskContextOwner(client: OpenMatesClient): () => void {
  // Structural unit doubles predate the session API; production clients always have it.
  if (typeof client.getSession !== "function") return () => {};
  const identity = () => {
    const session = client.getSession();
    return createHash("sha256").update(JSON.stringify([session.apiUrl, session.hashedEmail,
      session.sessionId, session.createdAt, session.masterKeyExportedB64, session.activeTeamId])).digest("hex");
  };
  const owner = identity();
  return () => {
    try { if (identity() === owner) return; } catch { /* Logout invalidates in-flight context. */ }
    throw new Error("Task context workspace changed");
  };
}

interface PrefetchedDiscoveryReads {
  assertCurrent: () => void;
  plansRead: Promise<UserPlanRecord[]>;
  directoryRead: Promise<UserTaskRecord[]>;
  linkedRead: Promise<UserTaskRecord[]>;
  activeFocusRead: ReturnType<OpenMatesClient["getActiveProjectFocus"]>;
  projectRead: Promise<Awaited<ReturnType<OpenMatesClient["getProject"]>> | null>;
}
/** Opaque, one-send metadata reads; never a permission or private-context cache. */
export type CliJevDiscoveryTicket = object;
const prefetchedDiscovery = new WeakMap<CliJevDiscoveryTicket, PrefetchedDiscoveryReads & {
  client: OpenMatesClient; chatId: string; scope: string;
}>();
const discoveryScope = (options: TeamContextOptions) => JSON.stringify([options.teamId ?? null, options.personal === true]);

export function prefetchCliJevDiscovery(client: OpenMatesClient, chatId: string, options: TeamContextOptions): CliJevDiscoveryTicket {
  const assertCurrent = taskContextOwner(client);
  const activeFocusRead = client.getActiveProjectFocus(chatId);
  const projectRead = activeFocusRead.then(active => {
    assertCurrent();
    return active ? client.getProject(active.project_id, { teamId: active.team_id, personal: !active.team_id }) : null;
  });
  // Optional discovery can fail before the consuming preparation starts.
  void activeFocusRead.catch(() => {}); void projectRead.catch(() => {});
  const ticket = Object.freeze({});
  prefetchedDiscovery.set(ticket, {
    client, chatId, scope: discoveryScope(options), assertCurrent, activeFocusRead, projectRead,
    plansRead: client.listUserPlans({ ...options, chatId, activeOnly: false }).catch(() => []),
    directoryRead: client.listUserTaskDiscoveryPage(options).catch(() => []),
    linkedRead: client.listUserTasks({ ...options, chatId, limit: 100 }).catch(() => []),
  });
  return ticket;
}

function consumeDiscovery(client: OpenMatesClient, chatId: string, options: TeamContextOptions,
  ticket?: CliJevDiscoveryTicket): PrefetchedDiscoveryReads | undefined {
  if (!ticket) return;
  const reads = prefetchedDiscovery.get(ticket);
  prefetchedDiscovery.delete(ticket);
  if (!reads || reads.client !== client || reads.chatId !== chatId || reads.scope !== discoveryScope(options)) {
    throw new Error("Invalid same-send context discovery ticket.");
  }
  reads.assertCurrent();
  return reads;
}

/** Current chat work precedes general discovery; dependency references never grant Task authority. */
export async function collectRelatedCliTaskContext(client: OpenMatesClient, chatId: string, options: TeamContextOptions,
  records: UserTaskRecord[], nowSeconds = Date.now() / 1000, requiredIds: ReadonlySet<string> = new Set()): Promise<RelatedTaskCandidate[]> {
  const assertTaskOwner = taskContextOwner(client);
  const owned = records.filter(record => typeof record.task_id === "string" && record.task_id.length > 0 && record.task_id.length <= 128
    && Number.isSafeInteger(record.version) && Number(record.version) >= 1);
  const linked = owned.filter(record => record.primary_chat_id === chatId && OPEN_LINKED_TASK_STATES.has(record.status)).sort((a, b) => a.task_id.localeCompare(b.task_id));
  const dependencies = new Set<string>();
  const dependencySeeds = [...new Map([...linked, ...owned.filter(task => requiredIds.has(task.task_id))]
    .map(task => [task.task_id, task])).values()].slice(0, 4);
  if (typeof client.getTaskDependencies === "function") await Promise.all(dependencySeeds.map(async task => {
    try {
      const result = await client.getTaskDependencies(task.task_id, options);
      const ref = `task:${task.task_id}`;
      for (const edge of [...result.dependencies, ...result.blockers].slice(0, 40)) {
        const other = edge.source_ref === ref ? edge.target_ref : edge.target_ref === ref ? edge.source_ref : null;
        if (typeof other === "string" && other.startsWith("task:")) dependencies.add(other.slice(5));
      }
    } catch { /* Missing dependency discovery leaves actual chat-linked work available. */ }
  }));
  assertTaskOwner();
  // Dependency targets may be older than, or absent from, the bounded directory.
  const presentIds = new Set(owned.map(task => task.task_id));
  if (typeof client.getUserTask === "function") {
    await Promise.all([...dependencies].filter(id => !presentIds.has(id)).sort().slice(0, 24).map(async id => {
      try {
        const row = await client.getUserTask(id, options);
        assertTaskOwner();
        if (row?.task_id === id && Number.isSafeInteger(row.version) && Number(row.version) >= 1) owned.push(row);
      } catch { /* An inaccessible dependency never grants context or authority. */ }
    }));
  }
  assertTaskOwner();
  const changedAt = (record: UserTaskRecord) => Number(record.updated_at ?? record.created_at ?? 0);
  const priority = (record: UserTaskRecord): number => {
    if (record.primary_chat_id === chatId && OPEN_LINKED_TASK_STATES.has(record.status)) return 0;
    if (dependencies.has(record.task_id) || requiredIds.has(record.task_id)) return 1;
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
  assertTaskOwner();
  return candidates;
}

export async function prepareCliJevContext(client: OpenMatesClient, chatId: string, options: TeamContextOptions, supplied: CliJevContext = {}, text?: string,
  discovery: { sdkMintedChatId?: boolean; onRouting?: (context: CliJevContext) => void;
    onProjectRouting?: (context: CliJevContext) => void; onProjectRoutingError?: (error: unknown) => void;
    verifiedProjectCandidates?: NonNullable<CliJevContext["project_focus_candidates"]>;
    usePersonalRoutingDirectory?: boolean; prefetchedDiscovery?: CliJevDiscoveryTicket } = {}): Promise<CliJevContext> {
  const prefetched = consumeDiscovery(client, chatId, options, discovery.prefetchedDiscovery);
  const currentOwner = taskContextOwner(client);
  const assertTaskOwner = () => { currentOwner(); prefetched?.assertCurrent(); };
  // Start independent Plan discovery alongside Task and Project reads. Existing
  // approved revision/linkage checks below still run against fresh exact records.
  const plansRead = prefetched?.plansRead ?? (discovery.sdkMintedChatId ? Promise.resolve([] as UserPlanRecord[])
    : typeof client.listUserPlans === "function"
      ? client.listUserPlans({ ...options, chatId, activeOnly: false }).catch(() => []) : Promise.resolve([] as UserPlanRecord[]));
  let candidates: CliJevContext["project_focus_candidates"] = [];
  let active: Awaited<ReturnType<typeof loadActiveCliProjectContext>> = {};
  let tasks: RelatedTaskCandidate[] = [];
  let ownedTaskRecords: UserTaskRecord[] = [];
  let resolveCatalog!: (catalog: ProjectFocusCatalogEntry[]) => void;
  const catalogReady = new Promise<ProjectFocusCatalogEntry[]>(resolve => { resolveCatalog = resolve; });
  const activeReady = discovery.sdkMintedChatId ? Promise.resolve().then(() => resolveCatalog([]))
    : loadActiveCliProjectContext(client, chatId, text, resolveCatalog, prefetched)
      .then(value => { active = value; }).catch(() => {}).finally(() => resolveCatalog([]));
  await Promise.all([
    (discovery.verifiedProjectCandidates
      ? Promise.resolve(discovery.verifiedProjectCandidates)
      : discovery.usePersonalRoutingDirectory
        ? client.listPersonalProjectRoutingDirectory().then(rows => decodePersonalProjectCandidates(client, rows))
      : discoverCliProjectCandidates(client, options, Boolean(discovery.onProjectRouting))).then(value => {
      assertTaskOwner();
      candidates = value;
      discovery.onProjectRouting?.({ project_focus_candidates: (discovery.verifiedProjectCandidates ?? supplied.project_focus_candidates ?? value).slice(0, 40) });
    }).catch(error => { discovery.onProjectRoutingError?.(error); }),
    (async () => {
      const taskClient = client as OpenMatesClient & {
        listUserTaskDiscoveryPage?: (scope: TeamContextOptions) => Promise<UserTaskRecord[]>;
      };
      const [directory, linked] = await Promise.all([
        prefetched?.directoryRead ?? taskClient.listUserTaskDiscoveryPage?.(options).catch(() => []) ?? Promise.resolve([]),
        prefetched?.linkedRead ?? (discovery.sdkMintedChatId ? Promise.resolve([]) : client.listUserTasks({ ...options, chatId, limit: 100 }).catch(() => [])),
      ]);
      assertTaskOwner();
      const records = new Map<string, UserTaskRecord>();
      // The one fresh authorized directory page is only candidate inventory.
      for (const record of [...directory.slice(0, 100), ...linked]) records.set(record.task_id, record);
      const requiredIds = new Set([
        ...(supplied.related_task_candidates ?? []).map(row => row.task_id),
      ].filter(id => typeof id === "string" && id.length > 0 && id.length <= 128).slice(0, 24));
      if (typeof client.getUserTask === "function") await Promise.all([...requiredIds].filter(id => !records.has(id)).map(async id => {
        try {
          const record = await client.getUserTask(id, options);
          assertTaskOwner();
          if (record?.task_id === id) records.set(id, record);
        } catch { /* Supplied references are hints, never a permission bypass. */ }
      }));
      assertTaskOwner();
      ownedTaskRecords = [...records.values()];
      tasks = await collectRelatedCliTaskContext(client, chatId, options, ownedTaskRecords, Date.now() / 1000, requiredIds);
    })().catch(() => {}),
  ]);
  assertTaskOwner();
  const acceptedPlan = discovery.sdkMintedChatId ? null
    : await collectAcceptedCliPlanContext(client, chatId, options, ownedTaskRecords, plansRead).catch(() => null);
  assertTaskOwner();
  const catalog = await catalogReady;
  discovery.onRouting?.({ accepted_plan_context: acceptedPlan,
    project_focus_candidates: (discovery.verifiedProjectCandidates ?? supplied.project_focus_candidates ?? candidates).slice(0, 40),
    related_task_candidates: tasks.slice(0, 24),
    project_focus_catalog: catalog.slice(0, 20) });
  await activeReady;
  const { projectId, focusCatalogComplete: _complete, ...loaded } = active;
  const current = discovery.sdkMintedChatId ? null : await client.getActiveProjectFocus(chatId).catch(() => null);
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
  assertTaskOwner();
  return {
    accepted_plan_context: acceptedPlan,
    project_focus_candidates: (discovery.verifiedProjectCandidates ?? supplied.project_focus_candidates ?? candidates).slice(0, 40),
    related_task_candidates: tasks.slice(0, 24),
    custom_memory_documents: customDocuments,
    project_focus_catalog: current ? (supplied.project_focus_catalog ?? loaded.project_focus_catalog ?? []).slice(0, 20) : [],
    project_focus_documents: current ? (supplied.project_focus_documents ?? loaded.project_focus_documents ?? []).slice(0, 20) : [],
    project_context_documents: current ? (supplied.project_context_documents ?? loaded.project_context_documents ?? []).slice(0, 20) : [],
  };
}
