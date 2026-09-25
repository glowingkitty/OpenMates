/**
 * Coordinates creation flows launched from a selected Project location.
 * New chats receive a structured Project mention through the composer store.
 * New workflows consume a one-shot in-memory target on the Workflows route.
 * New plans use the encrypted Plan service with the selected Project linked.
 * Completed workflows are linked through the existing encrypted Project service.
 * Decrypted Project names and folder paths remain client-side inputs.
 */
import { writable } from "svelte/store";
import { activeChatStore } from "../stores/activeChatStore";
import { pendingMentionStore } from "../stores/pendingMentionStore";
import {
  NEW_CHAT_SENTINEL,
  phasedSyncState,
} from "../stores/phasedSyncStateStore";
import { addExistingTargetToProject, getProject } from "./projectService";
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
): Promise<void> {
  const context = { teamId: target.teamId ?? null };
  const project = await getProject(target.projectId, context);
  await addExistingTargetToProject(
    project,
    workflowId,
    "workflow",
    workflowTitle,
    target.folderId ?? undefined,
    target.folderPath || target.sourceId
      ? {
          source: "workflow_target",
          path: target.folderPath ?? undefined,
          source_id: target.sourceId ?? undefined,
        }
      : undefined,
    context,
  );
}
