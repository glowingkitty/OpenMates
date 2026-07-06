// frontend/packages/ui/src/services/workspacePrefetchService.ts
// Lightweight intent/idle prefetch coordinator for web app workspaces.
// Keeps non-chat workspace data off the chat-critical sync path while warming
// shared workspace stores before users click a tab. Each workspace prefetch is
// best-effort and must not block navigation, auth, or chat rendering.

import { get } from "svelte/store";
import { authStore } from "../stores/authStore";
import { featureAvailabilityStore } from "../stores/appSkillsStore";
import { workflowWorkspaceStore } from "../stores/workflowWorkspaceStore";

export type WorkspacePrefetchTarget = "workflows";

const PREFETCH_DELAY_MS = 800;
let idlePrefetchQueued = false;

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
    workflowWorkspaceStore.loadWorkflows().catch((error) => {
      console.debug("[workspacePrefetchService] Workflow prefetch skipped:", error);
    });
  }
}

export function prefetchWorkspaceForHref(href: string): void {
  if (href.startsWith("/workflows")) {
    prefetchWorkspace("workflows");
  }
}

export function scheduleIdleWorkspacePrefetch(): void {
  if (idlePrefetchQueued || !canPrefetchAuthenticatedWorkspace()) return;
  idlePrefetchQueued = true;

  const runPrefetch = () => {
    idlePrefetchQueued = false;
    prefetchWorkspace("workflows");
  };

  if (typeof window !== "undefined" && "requestIdleCallback" in window) {
    window.requestIdleCallback(runPrefetch, { timeout: 3_000 });
    return;
  }

  setTimeout(runPrefetch, PREFETCH_DELAY_MS);
}
