/** Project-only recommendations and independent, click-started authoring jobs. */
import { get, writable } from 'svelte/store';
import { getApiEndpoint } from '../config/api';
import { authStore } from '../stores/authStore';
import { userProfile } from '../stores/userProfile';
import { chatDB } from './db';
import { getActiveProjectFocus, getProject, getProjectContents, getProjectSettings, type ProjectItemViewModel } from './projectService';
import { collectProjectFocusCatalog, loadSelectedProjectFocusDocuments, projectItemRevision, type ProjectFocusDocument } from './agenticProjectContextService';
import { saveProjectMarkdownDocument, type SavedProjectMarkdownDocument } from './ruleDocumentService';
import type { ProjectAuthoringRecommendation as DisplayRecommendation } from '../utils/agentContextEvents';
import { encryptWithEmbedKey } from './cryptoService';
import { registerWorkspaceCacheClear, getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';
import { broadcastProjectFilesChanged } from './projectBrowserEvents';
import type { WorkflowSummary } from '../stores/workflowWorkspaceStore';

export interface ProjectAuthoringRecommendation {
  recommendation_id: string; chat_id: string; project_id: string;
  kind: 'focus' | 'workflow'; action: 'create' | 'update' | 'inspect';
  target_id: string | null; expected_revision: string | null; expires_at: number;
  created_at?: number;
}
export type ProjectAuthoringReceipt = ProjectAuthoringRecommendation & {
  event_id: string; created_at: number; type: 'project_authoring_recommendation';
};
export interface ProjectAuthoringAvailable {
  chat_id: string; project_id: string; user_message_id: string; assistant_message_id: string;
}
export interface ProjectAuthoringJob {
  job_id: string; recommendation_id: string; chat_id: string; project_id: string; kind: 'focus' | 'workflow';
  action: 'create' | 'update'; status: string; target_id: string | null; expected_revision: string | null;
  result_id?: string; result_revision?: string; workflow_version_id?: string;
  project_item_id?: string; expected_item_revision?: string; error_code?: string;
  draft?: { document?: ProjectFocusDocument; markdown?: string; path?: string; question?: string;
    save_operation_id?: string; expected_embed_revision?: number; remote_binding?: Record<string, unknown> };
}
const state = writable<Record<string, ProjectAuthoringJob>>({});
export const projectAuthoringJobs = { subscribe: state.subscribe };
const polling = new Set<string>();
const saves = new Map<string, Promise<ProjectAuthoringJob>>();
const savedFiles = new Map<string, { owner: string; receipt: SavedProjectMarkdownDocument }>();
const timers = new Set<ReturnType<typeof setTimeout>>();
registerWorkspaceCacheClear(() => { state.set({}); polling.clear(); saves.clear(); savedFiles.clear(); timers.forEach(clearTimeout); timers.clear(); });

function owner(): string {
  const id = get(userProfile).user_id;
  if (!id || !get(authStore).isAuthenticated) throw new Error('project_authoring_auth_required');
  return id;
}
async function workspace(chatId: string, projectId: string, expectedOwner = owner()) {
  if (owner() !== expectedOwner) throw new Error('project_authoring_auth_changed');
  const focus = await getActiveProjectFocus(chatId);
  if (focus?.project_id !== projectId) throw new Error('project_authoring_project_changed');
  const context = { teamId: focus.team_id };
  const project = await getProject(projectId, context);
  const contents = await getProjectContents(project, context);
  const fresh = await getActiveProjectFocus(chatId);
  if (owner() !== expectedOwner || fresh?.project_id !== projectId || fresh?.team_id !== focus.team_id) throw new Error('project_authoring_project_changed');
  return { owner: expectedOwner, focus, context, project, contents };
}
async function api<T>(chatId: string, projectId: string, path: string, body?: unknown, expectedOwner = owner()): Promise<T> {
  await workspace(chatId, projectId, expectedOwner);
  const response = await fetch(getApiEndpoint(`/v1/projects/${encodeURIComponent(projectId)}/authoring${path}`), {
    method: body === undefined ? 'GET' : 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) throw new Error(`project_authoring_request_${response.status}`);
  const result = await response.json() as T;
  await workspace(chatId, projectId, expectedOwner);
  return result;
}
async function history(chatId: string, assistantId?: string) {
  const anchor = assistantId ? await chatDB.getMessage(assistantId) : null;
  const page = await chatDB.getMessageWindowForChat(chatId, { direction: anchor ? 'before' : 'latest', limit: 60,
    ...(anchor ? { beforeTimestamp: anchor.created_at + 1 } : {}) });
  const rows: Array<{ role: 'user' | 'assistant'; content: string }> = [];
  let remaining = 12_000;
  for (const message of [...page.messages].reverse()) {
    if (anchor && message.created_at > anchor.created_at) continue;
    if ((message.role !== 'user' && message.role !== 'assistant') || !message.content?.trim()
      || ['streaming', 'processing', 'failed'].includes(message.status)) continue;
    const content = message.content.slice(-remaining);
    if (content) rows.unshift({ role: message.role, content });
    remaining -= content.length;
    if (remaining <= 0) break;
  }
  if (!rows.length) throw new Error('project_authoring_history_unavailable');
  return rows;
}
function record(job: ProjectAuthoringJob) {
  state.update(jobs => ({ ...jobs, [job.job_id]: job }));
  return job;
}

/** Metadata assessment may read only the selected Focus after the first Jev pass. */
export async function assessProjectAuthoring(event: ProjectAuthoringAvailable): Promise<ProjectAuthoringReceipt[] | null> {
  const current = await workspace(event.chat_id, event.project_id);
  const focuses = await collectProjectFocusCatalog({ chatId: event.chat_id, projectId: event.project_id });
  // Default Workflow listing is the existing personal-owner catalog, including disabled entries.
  // Team-owned graphs cannot be mutated by the reused authoring engine.
  await workspace(event.chat_id, event.project_id, current.owner);
  const response = await fetch(getApiEndpoint('/v1/workflows'), { credentials: 'include' });
  const linked = new Set(current.contents.items.filter(item => item.item_type === 'workflow').map(item => item.target_id));
  const workflows: WorkflowSummary[] = response.ok ? (await response.json()).workflows ?? [] : [];
  if (!response.ok && linked.size) return null; // Never infer non-overlap from an unavailable catalog.
  const catalog = [
    ...focuses.map(({ kind, id, title, summary, revision }) => ({ kind, id, title, summary, revision })),
    ...workflows.filter(item => linked.has(item.id) && Number.isInteger(item.version)).map(item => ({
      kind: 'workflow' as const, id: item.id, title: item.title.slice(0, 200),
      summary: (item.description ?? item.trigger_summary ?? '').slice(0, 2_000), revision: String(item.version),
    })),
  ];
  if (catalog.length > 40) return null;
  const transcript = await history(event.chat_id, event.assistant_message_id);
  const result = await api<{ recommendations: ProjectAuthoringRecommendation[] }>(event.chat_id, event.project_id, '/recommend', {
    chat_id: event.chat_id, message_id: event.user_message_id, team_id: current.focus.team_id, catalog, history: transcript,
  }, current.owner);
  const confirmed: ProjectAuthoringRecommendation[] = [];
  for (const proposal of result.recommendations) {
    if (proposal.chat_id !== event.chat_id || proposal.project_id !== event.project_id) continue;
    if (proposal.action !== 'inspect') { confirmed.push(proposal); continue; }
    if (proposal.kind !== 'focus' || !proposal.target_id) continue;
    const selected = await loadSelectedProjectFocusDocuments(event.chat_id, event.project_id, [proposal.target_id]);
    if (selected.length !== 1 || selected[0].revision !== proposal.expected_revision) continue;
    const inspected = await api<{ recommendation: ProjectAuthoringRecommendation | null }>(event.chat_id, event.project_id, '/inspect', {
      assessment_id: proposal.recommendation_id, document: selected[0].document, history: await history(event.chat_id, event.assistant_message_id),
    }, current.owner);
    if (inspected.recommendation) confirmed.push(inspected.recommendation);
  }
  await workspace(event.chat_id, event.project_id, current.owner);
  return confirmed.map(proposal => ({ ...proposal, type: 'project_authoring_recommendation',
    event_id: proposal.recommendation_id, created_at: proposal.created_at ?? proposal.expires_at - 1_200 }));
}

/** Invoked only by the user's Create/Update button. Never creates a chat. */
export async function startProjectAuthoring(recommendation: DisplayRecommendation): Promise<ProjectAuthoringJob> {
  if (!recommendation.expires_at || recommendation.expires_at <= Date.now() / 1_000) throw new Error('project_authoring_recommendation_expired');
  const current = await workspace(recommendation.chat_id, recommendation.project_id);
  let target: ProjectFocusDocument | undefined;
  let remote_binding: Record<string, unknown> | undefined;
  if (recommendation.kind === 'focus' && recommendation.action === 'update') {
    const selected = await loadSelectedProjectFocusDocuments(recommendation.chat_id, recommendation.project_id, [recommendation.target_id!]);
    if (selected.length !== 1 || selected[0].revision !== recommendation.expected_revision) throw new Error('project_authoring_revision_conflict');
    target = selected[0].document;
  } else if (recommendation.kind === 'workflow') {
    const item = current.contents.items.find(item => item.item_type === 'workflow' && item.target_id === recommendation.target_id);
    if (!item) throw new Error('project_authoring_target_unavailable');
    const binding = item.metadata.remote_workflow_file;
    if (binding && typeof binding === 'object' && !Array.isArray(binding)) remote_binding = binding as Record<string, unknown>;
  }
  const { job } = await api<{ job: ProjectAuthoringJob }>(recommendation.chat_id, recommendation.project_id, '/jobs', {
    recommendation_id: recommendation.recommendation_id, expected_revision: recommendation.expected_revision ?? null,
    history: await history(recommendation.chat_id), ...(target ? { target } : {}), ...(remote_binding ? { remote_binding } : {}),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  }, current.owner);
  record(job);
  poll(job, current.owner);
  return job;
}

function poll(initial: ProjectAuthoringJob, expectedOwner: string) {
  if (polling.has(initial.job_id)) return;
  polling.add(initial.job_id);
  const epoch = getWorkspaceCacheEpoch();
  const tick = async () => {
    if (getWorkspaceCacheEpoch() !== epoch) return;
    let again = false;
    try {
      const { job } = await api<{ job: ProjectAuthoringJob }>(initial.chat_id, initial.project_id, `/jobs/${encodeURIComponent(initial.job_id)}`, undefined, expectedOwner);
      record(job);
      if (job.status === 'needs_binding_save') await save(job, false, expectedOwner);
      else if (job.status === 'needs_save') {
        const current = await workspace(job.chat_id, job.project_id, expectedOwner);
        const settings = await getProjectSettings(current.project, current.context);
        if (settings.writeMode === 'apply_and_show') await save(job, false, expectedOwner);
      }
      again = ['running', 'pending_file'].includes(job.status);
    } catch { // Keep the recoverable job/draft visible; do not synthesize a ready state.
      const existing = get(state)[initial.job_id];
      if (existing) record({ ...existing, error_code: 'project_authoring_refresh_failed' });
    } finally {
      if (again && getWorkspaceCacheEpoch() === epoch) {
        const timer = setTimeout(() => { timers.delete(timer); void tick(); }, 2_000);
        timers.add(timer);
      } else polling.delete(initial.job_id);
    }
  };
  void tick();
}

/** An explicit Save click approves only the exact generated document currently displayed. */
export async function saveProjectAuthoring(jobId: string): Promise<ProjectAuthoringJob> {
  const job = get(state)[jobId];
  if (!job) throw new Error('project_authoring_job_unavailable');
  return save(job, true, owner());
}
function save(job: ProjectAuthoringJob, explicitApproval: boolean, expectedOwner: string): Promise<ProjectAuthoringJob> {
  const existing = saves.get(job.job_id);
  if (existing) return existing;
  const operation = saveDraft(job, explicitApproval, expectedOwner).finally(() => saves.delete(job.job_id));
  saves.set(job.job_id, operation);
  return operation;
}
async function saveDraft(job: ProjectAuthoringJob, explicitApproval: boolean, expectedOwner: string): Promise<ProjectAuthoringJob> {
  const refreshed = await api<{ job: ProjectAuthoringJob }>(job.chat_id, job.project_id, `/jobs/${encodeURIComponent(job.job_id)}`, undefined, expectedOwner);
  if (refreshed.job.status === 'ready') return record(refreshed.job);
  if (job.status !== refreshed.job.status || job.draft?.markdown !== refreshed.job.draft?.markdown
    || job.draft?.save_operation_id !== refreshed.job.draft?.save_operation_id) {
    record(refreshed.job);
    throw new Error('project_authoring_draft_changed');
  }
  job = refreshed.job;
  const current = await workspace(job.chat_id, job.project_id, expectedOwner);
  if (job.status === 'needs_save' && job.kind === 'focus') {
    const draft = job.draft;
    if (!draft?.document || !draft.markdown || !draft.path || !draft.save_operation_id || draft.expected_embed_revision === undefined) throw new Error('project_authoring_draft_unavailable');
    const item = job.action === 'update' ? current.contents.items.find(item => item.project_item_id === job.target_id) : undefined;
    const previous = savedFiles.get(job.job_id);
    if (!previous && job.action === 'update' && (!item || await projectItemRevision(item) !== job.expected_revision)) throw new Error('project_authoring_revision_conflict');
    if (previous && previous.owner !== expectedOwner) throw new Error('project_authoring_auth_changed');
    const saved = previous?.receipt ?? await saveProjectMarkdownDocument({ chatId: job.chat_id, projectId: job.project_id,
      path: item ? String(item.metadata.display_path) : draft.path, document: draft.markdown,
      metadata: { focus_title: draft.document.name, focus_description: draft.document.description,
        focus_when_to_use: draft.document.when_to_use },
      ...(item ? { itemId: item.project_item_id, expectedItemRevision: job.expected_revision! } : {}),
      operationId: draft.save_operation_id, expectedEmbedRevision: draft.expected_embed_revision,
      ...(explicitApproval ? { saveApproved: true } : {}),
    });
    savedFiles.set(job.job_id, { owner: expectedOwner, receipt: saved });
    const result = await api<{ job: ProjectAuthoringJob }>(job.chat_id, job.project_id, `/jobs/${encodeURIComponent(job.job_id)}/saved`, {
      save_operation_id: saved.file_operation_id, project_item_id: saved.project_item_id, embed_id: saved.embed_id,
      saved_revision: saved.item_revision, expected_revision: job.expected_revision,
    }, expectedOwner);
    savedFiles.delete(job.job_id);
    return record(result.job);
  }
  if (job.status === 'needs_binding_save' && job.kind === 'workflow') {
    const binding = job.draft?.remote_binding;
    const item = current.contents.items.find(item => item.project_item_id === job.project_item_id);
    if (!binding || !item || item.target_id !== job.result_id) throw new Error('project_authoring_revision_conflict');
    if (JSON.stringify(item.metadata.remote_workflow_file) !== JSON.stringify(binding) || item.metadata.remote_file_status !== 'saved') {
      if (await projectItemRevision(item) !== job.expected_item_revision) throw new Error('project_authoring_revision_conflict');
      await saveBinding(current, item, binding, job);
    }
    const fresh = await workspace(job.chat_id, job.project_id, expectedOwner);
    const saved = fresh.contents.items.find(candidate => candidate.project_item_id === item.project_item_id);
    if (!saved) throw new Error('project_authoring_binding_unavailable');
    const result = await api<{ job: ProjectAuthoringJob }>(job.chat_id, job.project_id, `/jobs/${encodeURIComponent(job.job_id)}/workflow-saved`, {
      project_item_id: saved.project_item_id, saved_item_revision: await projectItemRevision(saved), workflow_version_id: job.workflow_version_id,
    }, expectedOwner);
    return record(result.job);
  }
  throw new Error('project_authoring_save_not_available');
}
async function saveBinding(current: Awaited<ReturnType<typeof workspace>>, item: ProjectItemViewModel,
  binding: Record<string, unknown>, job: ProjectAuthoringJob) {
  const encrypted_metadata = await encryptWithEmbedKey(JSON.stringify({ ...item.metadata,
    remote_workflow_file: binding, remote_file_status: 'saved' }), current.project.projectKey);
  await workspace(job.chat_id, job.project_id, current.owner);
  const team = current.focus.team_id ? `?team_id=${encodeURIComponent(current.focus.team_id)}` : '';
  const response = await fetch(getApiEndpoint(`/v1/projects/${encodeURIComponent(job.project_id)}/items/${encodeURIComponent(item.project_item_id)}${team}`), {
    method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ encrypted_metadata, updated_at: Math.floor(Date.now() / 1_000), expected_item_revision: job.expected_item_revision }),
  });
  if (!response.ok) throw new Error('project_authoring_binding_save_failed');
  broadcastProjectFilesChanged(job.project_id);
}
