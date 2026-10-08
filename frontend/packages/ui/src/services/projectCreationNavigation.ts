/**
 * Coordinates creation flows launched from a selected Project location.
 * New chats receive a structured Project mention through the composer store.
 * New workflows consume a one-shot in-memory target on the Workflows route.
 * New plans use the encrypted Plan service with the selected Project linked.
 * Completed workflows are linked through the existing encrypted Project service.
 * Decrypted Project names and folder paths remain client-side inputs.
 */
import { get, writable } from "svelte/store";
import { stringify } from 'yaml';
import { activeChatStore } from "../stores/activeChatStore";
import { pendingMentionStore } from "../stores/pendingMentionStore";
import {
  NEW_CHAT_SENTINEL,
  phasedSyncState,
} from "../stores/phasedSyncStateStore";
import { addExistingTargetToProject, getProject, getProjectContents, listProjectSources, listProjects,
  getActiveProjectFocus, getProjectSettings, approveProjectWrite, requestProjectRemoteAccess, updateProjectItemMetadata, type ProjectViewModel } from "./projectService";
import { userProfile } from '../stores/userProfile';
import { workflowApiRequest, type WorkflowDetail } from '../stores/workflowWorkspaceStore';
import { persistWorkflowRemoteFile, type WorkflowRemoteFileBinding } from '../../../workflowRemoteFile';
import { projectFileMutationDigest } from '../utils/projectFileMutationProtocol';
import { getHashParam } from '../utils/settingsHashUtils';
import { requestProjectWriteApproval, recordProjectFileChange } from '../stores/projectFileApprovalStore';
import { text } from '../i18n/translations';
import { chatSyncService } from "./chatSyncService";
import { createUserPlan, type UserPlanViewModel } from "./userPlanService";
import { buildProjectMentionSyntax } from "../components/enter_message/services/projectMentionSyntax";

export interface ProjectCreationTarget {
  projectId: string;
  projectName: string;
  folderId?: string | null;
  folderPath?: string | null;
  sourceId?: string | null;
  teamId?: string | null;
}

const pendingWorkflowTarget = writable<ProjectCreationTarget | null>(null);

function targetLabel(target: ProjectCreationTarget): string {
  const folderName = target.folderPath?.split("/").filter(Boolean).pop();
  return [target.projectName, folderName].filter(Boolean).join("-");
}

export function projectWorkflowAssociationWarning(
  target: ProjectCreationTarget,
  error: unknown,
): string {
  if (error instanceof WorkflowRemoteFilePendingError) return error.message;
  const location = target.folderPath
    ? `${target.projectName} / ${target.folderPath}`
    : target.projectName;
  const reason = error instanceof Error ? ` ${error.message}` : "";
  return `Workflow created, but it could not be added to ${location}.${reason}`;
}

/** Prepare the root route to mount a fresh composer with Project focus selected. */
export function prepareProjectChatNavigation(
  target: ProjectCreationTarget,
): void {
  const isFolder = Boolean(target.folderId || target.folderPath);
  const type = isFolder ? "project_folder" : "project";
  const folderPath = isFolder ? target.folderPath || "/" : undefined;

  pendingMentionStore.set({
    syntax: buildProjectMentionSyntax(
      type,
      target.projectId,
      "read",
      folderPath,
      target.sourceId ?? undefined,
    ),
    type,
    displayName: targetLabel(target),
    projectId: target.projectId,
    projectSourceId: target.sourceId ?? undefined,
    projectPath: folderPath,
    projectAccessMode: "read",
  });
  activeChatStore.clearActiveChat();
  phasedSyncState.setCurrentActiveChatId(NEW_CHAT_SENTINEL);
  phasedSyncState.markUserMadeExplicitChoice();
  void chatSyncService.sendSetActiveChat(null).catch((error) => {
    console.warn(
      "[ProjectCreationNavigation] Could not clear the server active chat:",
      error,
    );
  });
}

/** Carry a private, decrypted target across the client-side Projects → Workflows navigation. */
export function prepareProjectWorkflowNavigation(
  target: ProjectCreationTarget,
): void {
  pendingWorkflowTarget.set({ ...target });
}

/** Consume the target once so later workflow creations are not linked accidentally. */
export function consumeProjectWorkflowTarget(): ProjectCreationTarget | null {
  let target: ProjectCreationTarget | null = null;
  pendingWorkflowTarget.update((current) => {
    target = current;
    return null;
  });
  return target;
}

/** Create an editable draft whose key is wrapped for the selected Project. */
export async function createPlanForProjectTarget(
  target: ProjectCreationTarget,
): Promise<UserPlanViewModel> {
  return createUserPlan({
    title: "Untitled plan",
    goal: `Plan work for ${target.projectName}`,
    status: "draft",
    linkedProjectIds: [target.projectId],
  });
}

/** Persist the created workflow in its selected encrypted Project folder. */
export async function saveWorkflowToProjectTarget(
  target: ProjectCreationTarget,
  workflowId: string,
  workflowTitle: string,
  isCurrent: () => boolean = () => true,
): Promise<void> {
  const assertCurrent = () => {
    if (!isCurrent()) throw new Error('Workflow context changed before Project association.');
  };
  assertCurrent();
  const context = { teamId: target.teamId ?? null };
  const project = await getProject(target.projectId, context);
  assertCurrent();
  const sources = await listProjectSources(project, context);
  assertCurrent();
  const remoteSources = sources.filter(source => source.source_type.startsWith('remote_') || source.sourceSessionId);
  const contents = await getProjectContents(project, context);
  assertCurrent();
  const existing = contents.items.find(item => item.item_type === 'workflow' && item.target_id === workflowId);
  const priorBinding = existing?.metadata.remote_workflow_file as WorkflowRemoteFileBinding | undefined;
  const sourceId = priorBinding?.source_id || target.sourceId;
  const source = sourceId ? sources.find(source => source.source_id === sourceId)
    : remoteSources.length === 1 ? remoteSources[0] : null;
  let metadata: Record<string, unknown> = { ...existing?.metadata, source: 'workflow_target',
    path: target.folderPath ?? undefined, source_id: target.sourceId ?? undefined };
  let pending: string | null = null;
  if (source || remoteSources.length || target.sourceId || priorBinding) {
    const binding = priorBinding?.source_id ? priorBinding : { project_id: project.project_id, source_id: source?.source_id ?? '', folder_path: target.folderPath ?? '' };
    metadata = { ...metadata, remote_workflow_file: binding, remote_file_status: 'pending' };
    if (source) {
      const workflowPath = `/v1/workflows/${encodeURIComponent(workflowId)}`;
      const scopedWorkflowPath = target.teamId ? `${workflowPath}?team_id=${encodeURIComponent(target.teamId)}` : workflowPath;
      const { workflow } = await workflowApiRequest<{ workflow: WorkflowDetail }>(scopedWorkflowPath);
      assertCurrent();
      const result = await saveRemote(project, workflow, binding, target.teamId, assertCurrent);
      assertCurrent();
      metadata = { ...metadata, remote_workflow_file: result.binding, remote_file_status: result.status, remote_file_error: result.error };
      if (result.status !== 'saved') pending = result.error ?? result.status;
    } else pending = 'source_selection_required';
  }
  assertCurrent();
  if (existing) await updateProjectItemMetadata(project, existing.project_item_id, metadata, context);
  else await addExistingTargetToProject(
    project,
    workflowId,
    "workflow",
    workflowTitle,
    target.folderId ?? undefined,
    metadata,
    context,
  );
  if (pending) throw new WorkflowRemoteFilePendingError(pending);
}

export class WorkflowRemoteFilePendingError extends Error {
  constructor(public code: string) {
    const conflict = code.includes('conflict') || ['file_changed', 'file_exists', 'workflow_version_changed'].includes(code);
    super(get(text)(conflict ? 'workflows.builder.remote_file_conflict' : 'workflows.builder.remote_file_pending'));
    this.name = 'WorkflowRemoteFilePendingError';
  }
}

function workflowRouteChatId(workflowId: string): string | null {
  if (typeof window === 'undefined') return null;
  const { pathname, hash } = window.location;
  if (pathname !== '/' && pathname !== '/workflows' && pathname !== '/workflows/') return null;
  const marker = hash.replace(/^#\/?/, '').split('&', 1)[0];
  if (['projects', 'plans', 'tasks', 'apps'].includes(marker) || marker.startsWith('apps/')) return null;
  if (getHashParam(hash, 'workflow-id') !== workflowId
    || ['project-id', 'plan-id', 'task-id'].some(key => getHashParam(hash, key))) return null;
  return getHashParam(hash, 'chat-id') || null;
}

async function saveRemote(project: ProjectViewModel, workflow: WorkflowDetail, binding: WorkflowRemoteFileBinding, teamId?: string | null, assertCurrent: () => void = () => undefined) {
  const context = { teamId: teamId ?? null };
  const source = (await listProjectSources(project, context)).find(item => item.source_id === binding.source_id);
  assertCurrent();
  if (source?.status === 'offline') return { status: 'pending' as const, binding, error: 'source_offline' };
  if (binding.project_id !== project.project_id) return { status: 'pending' as const, binding, error: 'project_focus_required' };
  const chatId = activeChatStore.get() || workflowRouteChatId(workflow.id);
  const focus = chatId ? await getActiveProjectFocus(chatId) : null;
  assertCurrent();
  if (!source || !chatId || focus?.project_id !== project.project_id) return { status: 'pending' as const, binding, error: 'project_focus_required' };
  return persistWorkflowRemoteFile({ workflow, binding, expectedVersionId: workflow.current_version_id,
    serialize: stringify,
    operationId: crypto.randomUUID(),
    currentVersion: async () => {
      assertCurrent();
      const path = `/v1/workflows/${encodeURIComponent(workflow.id)}`;
      return (await workflowApiRequest<{ workflow: WorkflowDetail }>(teamId ? `${path}?team_id=${encodeURIComponent(teamId)}` : path)).workflow.current_version_id;
    },
    execute: async mutation => {
      assertCurrent();
      const settings = await getProjectSettings(project, context);
      assertCurrent();
      if (!settings.writeMode) return { status: 'failed', error: 'write_policy_required' };
      const approval = { projectId: project.project_id, chatId, mutation };
      if (settings.writeMode === 'always_ask') {
        if (!await requestProjectWriteApproval(approval)) return { status: 'failed', error: 'write_denied' };
        assertCurrent();
        await approveProjectWrite(project.project_id, { chat_id: chatId, operation_id: mutation.operation_id,
          proposal_digest: await projectFileMutationDigest(project.projectKey, project.project_id, chatId, mutation) }, context);
      }
      assertCurrent();
      const result = await requestProjectRemoteAccess<Record<string, unknown>>(project, source,
        { ownerId: get(userProfile).user_id ?? '', teamId }, mutation.operation, { chat_id: chatId, mutation });
      recordProjectFileChange(approval);
      return result;
    },
  });
}

/** Explicit saved edits refresh bound files; remote file changes never trigger this. */
export async function syncBoundWorkflowRemoteFiles(workflow: WorkflowDetail): Promise<void> {
  let pending: string | null = null;
  for (const project of await listProjects()) {
    const contents = await getProjectContents(project);
    for (const item of contents.items.filter(item => item.item_type === 'workflow' && item.target_id === workflow.id)) {
      const binding = item.metadata.remote_workflow_file as WorkflowRemoteFileBinding | undefined;
      if (!binding) continue;
      const result = await saveRemote(project, workflow, binding);
      await updateProjectItemMetadata(project, item.project_item_id, { ...item.metadata,
        remote_workflow_file: result.binding, remote_file_status: result.status, remote_file_error: result.error });
      if (result.status !== 'saved') pending = result.error ?? result.status;
    }
  }
  if (pending) throw new WorkflowRemoteFilePendingError(pending);
}
