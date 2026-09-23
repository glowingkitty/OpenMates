import {
  activateProjectFocus,
  deactivateProjectFocus,
  getProject,
  getProjectSettings,
  type ActiveProjectFocus,
  type ProjectSettingsViewModel,
  type ProjectViewModel,
} from "./projectService";

const PROJECT_MENTION_TYPES = new Set([
  "project",
  "project_folder",
  "project_file",
]);

interface ComposerNode {
  type?: string;
  attrs?: Record<string, unknown>;
  content?: ComposerNode[];
}

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
  getProject(projectId: string, context?: { teamId?: string | null }): Promise<ProjectViewModel>;
  getProjectSettings(
    project: ProjectViewModel,
    context?: { teamId?: string | null },
  ): Promise<ProjectSettingsViewModel>;
  activateProjectFocus(
    projectId: string,
    input: { chat_id: string; focus_id: string; instruction: string },
    context?: { teamId?: string | null },
  ): Promise<ActiveProjectFocus>;
}

interface ProjectFocusDeactivateDependencies {
  deactivateProjectFocus(chatId: string): Promise<void>;
}

const defaultDependencies: ProjectFocusSendDependencies = {
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
 */
export function extractProjectFocusSendIntent(document: unknown): ProjectFocusSendIntent | null {
  const projectIds = new Set<string>();

  const visit = (node: ComposerNode): void => {
    if (
      node.type === "genericMention"
      && PROJECT_MENTION_TYPES.has(String(node.attrs?.mentionType ?? ""))
    ) {
      const projectId = node.attrs?.projectId;
      if (typeof projectId === "string" && projectId.trim()) {
        projectIds.add(projectId.trim());
      }
    }
    for (const child of node.content ?? []) visit(child);
  };

  if (document && typeof document === "object") visit(document as ComposerNode);
  if (projectIds.size === 0) return null;
  if (projectIds.size > 1) {
    throw new ProjectFocusSendPreflightError("MULTIPLE_PROJECTS");
  }
  return {
    projectId: Array.from(projectIds)[0],
    source: "composer_project_mention",
  };
}

function readDefaultFocus(settings: ProjectSettingsViewModel): ProjectDefaultFocus {
  const candidate = settings.settings.default_focus;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
    throw new ProjectFocusSendPreflightError("PROJECT_FOCUS_UNAVAILABLE");
  }
  const focusId = (candidate as Record<string, unknown>).focus_id;
  const instructions = (candidate as Record<string, unknown>).instructions;
  if (
    typeof focusId !== "string"
    || !focusId.trim()
    || typeof instructions !== "string"
    || !instructions.trim()
  ) {
    throw new ProjectFocusSendPreflightError("PROJECT_FOCUS_UNAVAILABLE");
  }
  return { focus_id: focusId.trim(), instructions: instructions.trim() };
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
  const context = { teamId: input.teamId ?? null };
  const project = await dependencies.getProject(intent.projectId, context);
  const settings = await dependencies.getProjectSettings(project, context);
  const focus = readDefaultFocus(settings);
  const activation = await dependencies.activateProjectFocus(
    intent.projectId,
    {
      chat_id: input.chatId,
      focus_id: focus.focus_id,
      instruction: focus.instructions,
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
