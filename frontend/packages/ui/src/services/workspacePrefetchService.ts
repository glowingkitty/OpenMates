// frontend/packages/ui/src/services/workspacePrefetchService.ts
// Lightweight intent/idle prefetch coordinator for web app workspaces.
// Keeps non-chat workspace data off the chat-critical sync path while warming
// shared workspace stores before users click a tab. Each workspace prefetch is
// best-effort and must not block navigation, auth, or chat rendering.

import { get } from "svelte/store";
import { authStore } from "../stores/authStore";
import { featureAvailabilityStore } from "../stores/appSkillsStore";
import { workflowWorkspaceStore } from "../stores/workflowWorkspaceStore";
import { listTaskBoardItems } from "./userTaskService";
import { listUserPlans } from "./userPlanService";
import { listProjects } from "./projectService";
import { getWorkspaceCacheIdentity } from "./workspaceQueryCache";
import { registerWorkspaceCacheClear } from "./workspaceCacheLifecycle";

export type WorkspacePrefetchTarget = "workflows" | "tasks" | "projects";

const PREFETCH_DELAY_MS = 800;
let idlePrefetchQueued = false;
let activeJobs = 0;
const pendingJobs = new Map<string, { identity: string | null; run: () => Promise<unknown> }>();
const runningJobs = new Set<string>();
registerWorkspaceCacheClear(() => { pendingJobs.clear(); idlePrefetchQueued = false; });

function runQueuedPrefetch(): void {
  while (activeJobs < 2 && pendingJobs.size > 0) {
    const [key, job] = pendingJobs.entries().next().value!;
    pendingJobs.delete(key);
    if (!canPrefetchAuthenticatedWorkspace() || job.identity !== getWorkspaceCacheIdentity()) continue;
    activeJobs += 1;
    runningJobs.add(key);
    void job.run().catch((error) => {
      console.debug('[workspacePrefetchService] Prefetch skipped:', error);
    }).finally(() => {
      activeJobs -= 1;
      runningJobs.delete(key);
      runQueuedPrefetch();
    });
  }
}

function queuePrefetch(key: string, run: () => Promise<unknown>): void {
  const identity = getWorkspaceCacheIdentity();
  const jobKey = JSON.stringify([identity, key]);
  if (pendingJobs.has(jobKey) || runningJobs.has(jobKey)) return;
  pendingJobs.set(jobKey, { identity, run });
  runQueuedPrefetch();
}

function featureEnabled(featureId: string): boolean {
  const state = get(featureAvailabilityStore);
  return state.disabledById !== null && state.disabledById?.[featureId] !== true;
}

function canPrefetchAuthenticatedWorkspace(): boolean {
  return get(authStore).isAuthenticated === true;
}

export function prefetchWorkspace(target: WorkspacePrefetchTarget): void {
  if (!canPrefetchAuthenticatedWorkspace()) return;

  if (target === "workflows") {
    if (!featureEnabled("platform:workflows")) return;
    queuePrefetch('workflows', () => workflowWorkspaceStore.loadWorkflows());
  } else if (target === 'tasks') {
    if (featureEnabled('platform:tasks')) queuePrefetch('tasks', () => listTaskBoardItems());
    if (featureEnabled('platform:plans')) queuePrefetch('plans', () => listUserPlans());
  } else if (target === 'projects' && featureEnabled('platform:projects')) {
    queuePrefetch('projects', () => listProjects());
  }
}

export function prefetchWorkspaceForHref(href: string): void {
  if (href.startsWith("/workflows") || href.startsWith("/#workflows")) {
    prefetchWorkspace("workflows");
  } else if (href.startsWith('/tasks') || href.startsWith('/#tasks')) {
    prefetchWorkspace('tasks');
  } else if (href.startsWith('/projects') || href.startsWith('/#projects')) {
    prefetchWorkspace('projects');
  }
}

export function scheduleIdleWorkspacePrefetch(): void {
  if (idlePrefetchQueued || !canPrefetchAuthenticatedWorkspace()) return;
  // A direct entity route must remain an ID-scoped read. Warming whole boards
  // here would quietly undo the single-task fix during a cold deep-link login.
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.hash.slice(1));
    if (['task-id', 'plan-id', 'project-id', 'workflow-id'].some((key) => params.has(key))
      || /^\/(?:tasks|plans|projects|workflows)\/[^/]+/.test(window.location.pathname)) return;
  }
  idlePrefetchQueued = true;
  const identity = getWorkspaceCacheIdentity();

  const runPrefetch = () => {
    idlePrefetchQueued = false;
    if (identity !== getWorkspaceCacheIdentity()) return;
    if (typeof window !== 'undefined' && /(?:task|plan|project|workflow)-id=/.test(window.location.hash)) return;
    prefetchWorkspace("workflows");
    prefetchWorkspace('tasks');
    prefetchWorkspace('projects');
  };

  if (typeof window !== "undefined" && "requestIdleCallback" in window) {
    window.requestIdleCallback(runPrefetch, { timeout: 3_000 });
    return;
  }

  setTimeout(runPrefetch, PREFETCH_DELAY_MS);
}
