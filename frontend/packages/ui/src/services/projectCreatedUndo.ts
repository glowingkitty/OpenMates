// frontend/packages/ui/src/services/projectCreatedUndo.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Undo of an assistant-created Project (the "Created project" card in chat). The Rust
// core decides (`projectUndoCreatedGuard`, same rule as `Projects::undo_created`);
// this shell only performs the Project API calls it names: deactivate the chat's
// focus, then delete the Project. The chat and its embeds stay intact.

import { chatStateCall } from "./rustCore/chatState/chatListUnitClient";
import { isRustCoreRegistered } from "./rustCore/host/workerFactoryRegistry";
import { deactivateProjectFocus, deleteProject, getActiveProjectFocus, getProject, getProjectSettings } from "./projectService";

/** Undo needs the shared Rust core; flag-off builds do not offer it. */
export function createdProjectUndoAvailable(): boolean {
  return import.meta.env.VITE_OPENMATES_RUST_CORE === "1" && isRustCoreRegistered();
}

/**
 * Undoes the Project the assistant created for `chatId`.
 * @throws when the core refuses (`Forbidden`: not this chat's assistant-created Project) or an API call fails.
 */
export async function undoCreatedProject(chatId: string, projectId: string): Promise<void> {
  const [focus, project] = await Promise.all([getActiveProjectFocus(chatId), getProject(projectId)]);
  const { settings } = await getProjectSettings(project);
  const wire = JSON.parse(JSON.stringify({ chatId, projectId, activeProjectId: focus?.project_id ?? null, settings })) as unknown;
  const answer = (await chatStateCall("projectDecide", { op: "projectUndoCreatedGuard", input: wire })) as { error?: string };
  if (typeof answer?.error === "string") throw new Error(answer.error);
  await deactivateProjectFocus(chatId);
  await deleteProject(projectId, { teamId: project.teamId });
}

/** True when the Project no longer exists (the undo already ran, here or on another device). */
export async function createdProjectIsGone(projectId: string): Promise<boolean> {
  try {
    await getProject(projectId);
    return false;
  } catch (error) {
    if (error instanceof Error && /\((404)\)/.test(error.message)) return true;
    console.debug("[projectCreatedUndo] Could not check Project existence:", error);
    return false;
  }
}
