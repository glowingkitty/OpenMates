// frontend/packages/ui/src/services/projectPresentationService.ts
// spec: specifications/features/projects#projects.presentation.manual-lock
// Project tile presentation (one-line description, icon, category; TASK-1807).
// Contract: docs/plans/project-presentation/contract.md. The shared Rust core decides
// every write (`projectPresentationPlan`, `projectBackfillPick`: who may write which
// field, manual-edit locks, one-time refresh, dominant category); this shell only
// gathers the decrypted context, asks the suggest route for a proposal, and encrypts
// and sends what the core answers. Flag-on (VITE_OPENMATES_RUST_CORE) only.

import { getApiEndpoint, storageArchiveFetch } from "../config/api";
import { getProjectContents, patchProjectPresentation, type ProjectViewModel } from "./projectService";
import { WorkspaceCacheDiscardedError } from "./workspaceQueryCache";

export interface ProjectPresentationFields {
  description?: string;
  icon?: string;
  category?: string;
}

type PresentationOrigin = "specification_approval" | "backfill" | "user";

interface PresentationPlan {
  write: boolean;
  fields: ProjectPresentationFields;
  state: Record<string, unknown> | null;
}

interface PresentationChat {
  category: string | null;
  updatedAt: number;
}

/** Same bounds as `PresentationSuggestRequest` on the server. */
const MAX_CHAT_TITLES = 20;
const MAX_ITEM_NAMES = 40;
const BACKFILL_PER_VISIT = 5;

/** Presentation writes need the shared Rust core; flag-off builds only display stored values. */
export const PROJECT_PRESENTATION_AVAILABLE = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";

// Projects already tried in this page session: a failed suggestion is not retried in a
// loop on every Projects visit; the next page load tries again.
const backfillAttempted = new Set<string>();

async function decidePresentation<T>(op: "projectPresentationPlan" | "projectBackfillPick", input: unknown): Promise<T> {
  const { chatStateCall } = await import("./rustCore/chatState/chatListUnitClient");
  const wire = JSON.parse(JSON.stringify(input)) as unknown;
  const answer = await chatStateCall("projectDecide", { op, input: wire });
  if (answer && typeof answer === "object" && typeof (answer as { error?: unknown }).error === "string") {
    throw new Error((answer as { error: string }).error);
  }
  return answer as T;
}

async function applyPlan(
  project: ProjectViewModel,
  origin: PresentationOrigin,
  proposal: ProjectPresentationFields,
  itemCount = 0,
  chats: PresentationChat[] = [],
): Promise<ProjectViewModel> {
  const plan = await decidePresentation<PresentationPlan>("projectPresentationPlan", {
    origin,
    state: project.presentationState ?? null,
    current: { description: project.description, icon: project.icon, category: project.category ?? "" },
    proposal,
    itemCount,
    chats,
  });
  if (!plan.write || !plan.state) return project;
  return patchProjectPresentation(project, plan.fields, plan.state);
}

/**
 * Plaintext proposal from `POST /v1/projects/presentation/suggest` (one small model
 * call, nothing stored server-side). The context is decrypted Project data the user
 * already sees; it leaves the device only for this request.
 */
async function suggestPresentation(body: {
  purpose: "specification_approval" | "backfill";
  name: string;
  description: string;
  specification: { title: string; summary: string } | null;
  chat_titles: string[];
  item_names: string[];
}): Promise<ProjectPresentationFields> {
  const response = await storageArchiveFetch(getApiEndpoint("/v1/projects/presentation/suggest"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, name: body.name.slice(0, 200) || "Untitled project", description: body.description.slice(0, 2000) }),
  });
  if (!response.ok) throw new Error(`Project presentation suggestion failed (${response.status})`);
  const data = (await response.json()) as { presentation?: ProjectPresentationFields };
  return data.presentation ?? {};
}

/** Saves fields the user changed by hand; the core marks them as the user's so no automatic step overwrites them. */
export async function saveProjectPresentationByUser(
  project: ProjectViewModel,
  changed: ProjectPresentationFields,
): Promise<ProjectViewModel> {
  return applyPlan(project, "user", changed);
}

/**
 * After the user approves a Specification: refreshes description, icon and category
 * from it once per Project (the core answers no write once the refresh ran, and skips
 * fields the user set by hand).
 */
export async function refreshPresentationAfterSpecificationApproval(
  project: ProjectViewModel,
  specification: { title: string; summary: string },
): Promise<ProjectViewModel> {
  if (!PROJECT_PRESENTATION_AVAILABLE || project.presentationState?.specification_refreshed === true) return project;
  const proposal = await suggestPresentation({
    purpose: "specification_approval",
    name: project.name,
    description: project.description,
    specification: { title: specification.title.slice(0, 300), summary: specification.summary.slice(0, 4000) },
    chat_titles: [],
    item_names: [],
  });
  return applyPlan(project, "specification_approval", proposal);
}

async function backfillContext(project: ProjectViewModel): Promise<{
  chatTitles: string[]; itemNames: string[]; chats: PresentationChat[]; itemCount: number;
}> {
  const { items } = await getProjectContents(project);
  const chatItems = items.filter((item) => item.item_type === "chat")
    .sort((a, b) => (b.encrypted.updated_at || 0) - (a.encrypted.updated_at || 0))
    .slice(0, MAX_CHAT_TITLES);
  // Loaded on demand: a static import pulls chatSyncService into the Settings module graph
  // (SettingsProjects imports this file) and breaks app startup with a circular-import TDZ.
  const { loadProjectChatPresentation } = await import("./projectChatPreviewService");
  const presentations = await Promise.all(chatItems.map((item) => loadProjectChatPresentation(item.target_id)));
  const chats: PresentationChat[] = [];
  const chatTitles: string[] = [];
  presentations.forEach((presentation, index) => {
    if (!presentation) return;
    if (presentation.title) chatTitles.push(presentation.title.slice(0, 200));
    chats.push({ category: presentation.category || null, updatedAt: chatItems[index].encrypted.updated_at || 0 });
  });
  const itemNames = items.filter((item) => item.item_type !== "chat" && item.displayName)
    .slice(0, MAX_ITEM_NAMES).map((item) => item.displayName.slice(0, 200));
  return { chatTitles, itemNames, chats, itemCount: items.length };
}

/**
 * One-time backfill for Projects from before TASK-1807: the core picks at most five
 * Projects without presentation state that have items; each is described in turn
 * from its name, chat titles and item names. `onUpdated` receives each written Project.
 */
export async function backfillProjectPresentations(
  projects: ProjectViewModel[],
  onUpdated: (project: ProjectViewModel) => void,
): Promise<void> {
  if (!PROJECT_PRESENTATION_AVAILABLE) return;
  const candidates = projects.filter((project) => !backfillAttempted.has(project.project_id));
  if (candidates.length === 0) return;
  const pick = await decidePresentation<{ projectIds: string[] }>("projectBackfillPick", {
    projects: candidates.map((project) => ({
      projectId: project.project_id,
      hasState: project.presentationState != null,
      itemCount: project.encrypted.item_count ?? 0,
    })),
    limit: BACKFILL_PER_VISIT,
  });
  for (const projectId of pick.projectIds) {
    const project = candidates.find((candidate) => candidate.project_id === projectId);
    if (!project) continue;
    backfillAttempted.add(projectId);
    try {
      const context = await backfillContext(project);
      const proposal = await suggestPresentation({
        purpose: "backfill",
        name: project.name,
        description: project.description,
        specification: null,
        chat_titles: context.chatTitles,
        item_names: context.itemNames,
      });
      const updated = await applyPlan(project, "backfill", proposal, context.itemCount, context.chats);
      if (updated !== project) onUpdated(updated);
    } catch (error) {
      if (error instanceof WorkspaceCacheDiscardedError) return;
      // One Project failing (rate limit, model error, version conflict) must not stop
      // the others; it is reported and retried on the next page load.
      console.error(`[projectPresentation] Backfill failed for Project ${projectId}:`, error);
    }
  }
}
