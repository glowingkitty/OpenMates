import {
  activateProjectFocus,
  confirmProjectFocusCountdown,
  deactivateProjectFocus,
  getProject,
  getProjectSettings,
  type ActiveProjectFocus,
  type ProjectSettingsViewModel,
  type ProjectViewModel,
} from "./projectService";
import { PROJECT_RUST_CORE, decideProject, projectRule, type ProjectStateOutput } from "./projectState/decide";
import { projectFocusIntent } from "./projectState/projectFocusPolicy";

interface ProjectDefaultFocus {
  focus_id: string;
  instructions: string;
}

export interface ProjectFocusSendIntent {
  projectId: string;
  source: "composer_project_mention";
}

export interface ProjectFocusActivationPresentation extends ActiveProjectFocus {
  project_name: string;
}

const PROJECT_FOCUS_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isProjectFocusId(focusId: string | null | undefined): focusId is string {
  return typeof focusId === "string" && PROJECT_FOCUS_ID_PATTERN.test(focusId);
}

interface ProjectFocusSendDependencies {
  confirmProjectFocusCountdown?(projectId: string, input: { chat_id: string; activation_request_id: string; approved?: boolean }, context?: { teamId?: string | null }): Promise<void>;
  getProject(projectId: string, context?: { teamId?: string | null }): Promise<ProjectViewModel>;
  getProjectSettings(
    project: ProjectViewModel,
    context?: { teamId?: string | null },
  ): Promise<ProjectSettingsViewModel>;
  activateProjectFocus(
    projectId: string,
    input: { chat_id: string; focus_id: string; instruction: string; activation_request_id?: string },
    context?: { teamId?: string | null },
  ): Promise<ActiveProjectFocus>;
}

interface ProjectFocusDeactivateDependencies {
  deactivateProjectFocus(chatId: string): Promise<void>;
}

const defaultDependencies: ProjectFocusSendDependencies = {
  confirmProjectFocusCountdown,
  getProject,
  getProjectSettings,
  activateProjectFocus,
};

const defaultDeactivateDependencies: ProjectFocusDeactivateDependencies = {
  deactivateProjectFocus,
};

export class ProjectFocusSendPreflightError extends Error {
  constructor(
    public readonly code:
      | "MULTIPLE_PROJECTS"
      | "PROJECT_FOCUS_UNAVAILABLE"
      | "CHAT_PREFLIGHT_REQUIRED",
  ) {
    super(code);
    this.name = "ProjectFocusSendPreflightError";
  }
}

/**
 * Capture current composer consent for one Project. Only structured mention nodes
 * qualify; plaintext copied from message history cannot recreate this intent.
 * Stays synchronous TypeScript in every build: `handleSend` captures the composer
 * document before its first await (the Rust twin serves vectors and other clients).
 */
export function extractProjectFocusSendIntent(document: unknown): ProjectFocusSendIntent | null {
  const answer = projectFocusIntent({ document });
  if ("focusError" in answer) throw new ProjectFocusSendPreflightError(answer.focusError);
  return answer.intent;
}

function defaultFocusAnswer(answer: ProjectStateOutput<"projectDefaultFocusRead">): ProjectDefaultFocus {
  if ("focusError" in answer) throw new ProjectFocusSendPreflightError(answer.focusError);
  return answer.focus;
}

/** Flag-on: the shared Rust core reads the default focus. */
async function readDefaultFocus(settings: ProjectSettingsViewModel): Promise<ProjectDefaultFocus> {
  return defaultFocusAnswer(await decideProject("projectDefaultFocusRead", { settings: settings.settings }));
}

function readDefaultFocusSync(settings: ProjectSettingsViewModel): ProjectDefaultFocus {
  return defaultFocusAnswer(projectRule("projectDefaultFocusRead", { settings: settings.settings }));
}

/**
 * Activate only after the durable chat preflight has created/confirmed the chat.
 * Re-loading encrypted settings here makes Project switches use the current
 * default focus instead of stale mention or historical message data.
 */
export async function activateProjectFocusForSend(
  intent: ProjectFocusSendIntent,
  input: { chatId: string; preflightId: string; teamId?: string | null },
  dependencies: ProjectFocusSendDependencies = defaultDependencies,
): Promise<ProjectFocusActivationPresentation> {
  if (!input.preflightId.trim()) {
    throw new ProjectFocusSendPreflightError("CHAT_PREFLIGHT_REQUIRED");
  }
  return activateProjectDefaultFocus(intent.projectId, input, dependencies);
}

export async function activateProjectFocusAfterConsent(
  input: { projectId: string; chatId: string; requestId: string; teamId?: string | null; approved?: boolean },
  dependencies: ProjectFocusSendDependencies = defaultDependencies,
): Promise<ProjectFocusActivationPresentation> {
  if (!input.requestId.trim()) throw new ProjectFocusSendPreflightError("CHAT_PREFLIGHT_REQUIRED");
  return activateProjectDefaultFocus(input.projectId, input, dependencies, input.requestId, input.approved);
}

async function activateProjectDefaultFocus(
  projectId: string,
  input: { chatId: string; teamId?: string | null },
  dependencies: ProjectFocusSendDependencies,
  requestId?: string,
  approved = false,
): Promise<ProjectFocusActivationPresentation> {
  const context = { teamId: input.teamId ?? null };
  if (requestId) {
    if (!dependencies.confirmProjectFocusCountdown) throw new ProjectFocusSendPreflightError("PROJECT_FOCUS_UNAVAILABLE");
    await dependencies.confirmProjectFocusCountdown(projectId, { chat_id: input.chatId, activation_request_id: requestId,
      ...(approved ? { approved: true } : {}) }, context);
  }
  const project = await dependencies.getProject(projectId, context);
  const settings = await dependencies.getProjectSettings(project, context);
  const focus = PROJECT_RUST_CORE ? await readDefaultFocus(settings) : readDefaultFocusSync(settings);
  const activation = await dependencies.activateProjectFocus(
    projectId,
    {
      chat_id: input.chatId,
      focus_id: focus.focus_id,
      instruction: focus.instructions,
      ...(requestId ? { activation_request_id: requestId } : {}),
    },
    context,
  );
  return { ...activation, project_name: project.name };
}

/** Revoke Project authority before clearing the catalog focus lifecycle. */
export async function deactivateFocusForChat(
  input: {
    chatId: string;
    focusId: string;
    sendCatalogDeactivation: (payload: { chat_id: string; focus_id: string }) => Promise<void>;
  },
  dependencies: ProjectFocusDeactivateDependencies = defaultDeactivateDependencies,
): Promise<void> {
  await dependencies.deactivateProjectFocus(input.chatId);
  await input.sendCatalogDeactivation({
    chat_id: input.chatId,
    focus_id: input.focusId,
  });
}
