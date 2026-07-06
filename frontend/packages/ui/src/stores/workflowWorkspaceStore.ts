// frontend/packages/ui/src/stores/workflowWorkspaceStore.ts
// Shared client-side cache for the Workflows workspace.
// Route components render immediately from this memory store, then refresh the
// encrypted workflow list, selected detail, and run history in the background.
// This keeps workspace tab switches warm without moving workflow loading into
// the chat-critical phased sync path.

import { get, writable } from "svelte/store";
import { getApiEndpoint } from "../config/api";

export type WorkflowNodeType =
  | "schedule_trigger"
  | "manual_trigger"
  | "app_skill_action"
  | "decision"
  | "repeat"
  | "create_chat_report"
  | "send_notification"
  | "send_email_notification"
  | "end";

export type WorkflowNode = {
  id: string;
  type: WorkflowNodeType;
  title?: string;
  config?: Record<string, unknown>;
};

export type WorkflowGraph = {
  version: number;
  trigger_node_id: string;
  nodes: WorkflowNode[];
  edges: Array<{ from: string; to: string; branch?: string }>;
  limits?: Record<string, unknown>;
};

export type WorkflowSummary = {
  id: string;
  title: string;
  status: string;
  enabled: boolean;
  trigger_summary?: string | null;
  last_run_status?: string | null;
  run_content_retention?: "last_5" | "none";
  current_version_id: string;
};

export type WorkflowDetail = WorkflowSummary & { graph: WorkflowGraph };

export type WorkflowRun = {
  id: string;
  status: string;
  trigger_type: string;
  started_at?: number | null;
  content_retention_mode?: "last_5" | "none";
  content_available?: boolean;
  content_storage?: "durable" | "ephemeral" | "deleted" | null;
  content_expires_at?: number | null;
  node_runs?: Array<{
    node_id: string;
    status: string;
    output_summary?: Record<string, unknown>;
  }>;
};

export type WorkflowRequestInit = {
  method?: string;
  body?: string;
};

type WorkspaceLoadStatus = "idle" | "loading" | "refreshing" | "ready" | "error";

export type WorkflowWorkspaceState = {
  workflows: WorkflowSummary[];
  selectedWorkflow: WorkflowDetail | null;
  selectedWorkflowId: string | null;
  runs: WorkflowRun[];
  detailsById: Record<string, WorkflowDetail>;
  runsByWorkflowId: Record<string, WorkflowRun[]>;
  listStatus: WorkspaceLoadStatus;
  detailStatus: WorkspaceLoadStatus;
  runsStatus: WorkspaceLoadStatus;
  error: string | null;
  lastLoadedAt: number | null;
};

const WORKFLOW_CACHE_STALE_MS = 60_000;

const initialState: WorkflowWorkspaceState = {
  workflows: [],
  selectedWorkflow: null,
  selectedWorkflowId: null,
  runs: [],
  detailsById: {},
  runsByWorkflowId: {},
  listStatus: "idle",
  detailStatus: "idle",
  runsStatus: "idle",
  error: null,
  lastLoadedAt: null,
};

const store = writable<WorkflowWorkspaceState>(initialState);
let workflowsInFlight: Promise<WorkflowSummary[]> | null = null;
const detailsInFlight = new Map<string, Promise<WorkflowDetail>>();
const runsInFlight = new Map<string, Promise<WorkflowRun[]>>();
let cacheRevision = 0;
let cacheGeneration = 0;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function isFresh(lastLoadedAt: number | null): boolean {
  return lastLoadedAt !== null && Date.now() - lastLoadedAt < WORKFLOW_CACHE_STALE_MS;
}

function assertCurrentGeneration(requestGeneration: number): void {
  if (requestGeneration !== cacheGeneration) {
    throw new Error("Workflow request was cancelled because the workspace cache reset.");
  }
}

export async function workflowApiRequest<T>(
  path: string,
  init: WorkflowRequestInit = {},
): Promise<T> {
  const headers = new Headers();
  headers.set("Accept", "application/json");
  headers.set("Content-Type", "application/json");

  const response = await fetch(getApiEndpoint(path), {
    ...init,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    throw new Error(`Workflow request failed with HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

function replaceWorkflow(
  workflows: WorkflowSummary[],
  workflow: WorkflowSummary,
): WorkflowSummary[] {
  const existingIndex = workflows.findIndex((item) => item.id === workflow.id);
  if (existingIndex < 0) return [workflow, ...workflows];
  return workflows.map((item) => (item.id === workflow.id ? workflow : item));
}

function setSelectedFromCaches(workflowId: string | null): void {
  store.update((state) => {
    if (!workflowId) {
      return { ...state, selectedWorkflowId: null, selectedWorkflow: null, runs: [] };
    }
    return {
      ...state,
      selectedWorkflowId: workflowId,
      selectedWorkflow: state.detailsById[workflowId] ?? state.selectedWorkflow,
      runs: state.runsByWorkflowId[workflowId] ?? state.runs,
    };
  });
}

export const workflowWorkspaceStore = {
  subscribe: store.subscribe,

  getGeneration(): number {
    return cacheGeneration;
  },

  isCurrentGeneration(generation: number): boolean {
    return generation === cacheGeneration;
  },

  async loadWorkflows(options: { force?: boolean } = {}): Promise<WorkflowSummary[]> {
    const current = get(store);
    if (!options.force && current.workflows.length > 0 && isFresh(current.lastLoadedAt)) {
      return current.workflows;
    }
    if (workflowsInFlight) return workflowsInFlight;
    const requestRevision = cacheRevision;
    const requestGeneration = cacheGeneration;

    store.update((state) => ({
      ...state,
      listStatus: state.workflows.length > 0 ? "refreshing" : "loading",
      error: null,
    }));

    workflowsInFlight = workflowApiRequest<{ workflows: WorkflowSummary[] }>("/v1/workflows")
      .then((data) => {
        store.update((state) => {
          if (requestGeneration !== cacheGeneration || requestRevision !== cacheRevision) {
            return {
              ...state,
              listStatus: "ready",
              error: null,
            };
          }
          const selectedWorkflowStillExists = state.selectedWorkflowId
            ? data.workflows.some((workflow) => workflow.id === state.selectedWorkflowId)
            : true;
          return {
            ...state,
            workflows: data.workflows,
            selectedWorkflowId: selectedWorkflowStillExists ? state.selectedWorkflowId : null,
            selectedWorkflow: selectedWorkflowStillExists ? state.selectedWorkflow : null,
            runs: selectedWorkflowStillExists ? state.runs : [],
            listStatus: "ready",
            error: null,
            lastLoadedAt: Date.now(),
          };
        });
        return data.workflows;
      })
      .catch((error) => {
        store.update((state) => ({
          ...state,
          listStatus: requestGeneration !== cacheGeneration || requestRevision !== cacheRevision ? state.listStatus : "error",
          error: requestGeneration !== cacheGeneration || requestRevision !== cacheRevision
            ? state.error
            : errorMessage(error, "Failed to load workflows."),
        }));
        throw error;
      })
      .finally(() => {
        workflowsInFlight = null;
      });

    return workflowsInFlight;
  },

  async selectWorkflow(workflowId: string, options: { force?: boolean } = {}): Promise<WorkflowDetail> {
    setSelectedFromCaches(workflowId);
    const requestGeneration = cacheGeneration;
    const current = get(store);
    const cachedDetail = current.detailsById[workflowId];
    const cachedRuns = current.runsByWorkflowId[workflowId];
    if (!options.force && cachedDetail && cachedRuns) return cachedDetail;

    store.update((state) => ({
      ...state,
      selectedWorkflowId: workflowId,
      detailStatus: cachedDetail ? "refreshing" : "loading",
      runsStatus: cachedRuns ? "refreshing" : "loading",
      error: null,
    }));

    const detailPromise = detailsInFlight.get(workflowId) ?? workflowApiRequest<{ workflow: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}`,
    ).then((data) => data.workflow);
    detailsInFlight.set(workflowId, detailPromise);

    const runsPromise = runsInFlight.get(workflowId) ?? workflowApiRequest<{ runs: WorkflowRun[] }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs`,
    ).then((data) => data.runs);
    runsInFlight.set(workflowId, runsPromise);

    try {
      const [workflow, runs] = await Promise.all([detailPromise, runsPromise]);
      assertCurrentGeneration(requestGeneration);
      store.update((state) => {
        const isStillSelected = state.selectedWorkflowId === workflow.id;
        return {
          ...state,
          workflows: replaceWorkflow(state.workflows, workflow),
          selectedWorkflow: isStillSelected ? workflow : state.selectedWorkflow,
          runs: isStillSelected ? runs : state.runs,
          detailsById: { ...state.detailsById, [workflow.id]: workflow },
          runsByWorkflowId: { ...state.runsByWorkflowId, [workflow.id]: runs },
          detailStatus: isStillSelected ? "ready" : state.detailStatus,
          runsStatus: isStillSelected ? "ready" : state.runsStatus,
          error: isStillSelected ? null : state.error,
        };
      });
      return workflow;
    } catch (error) {
      store.update((state) => {
        if (requestGeneration !== cacheGeneration || state.selectedWorkflowId !== workflowId) return state;
        return {
          ...state,
          detailStatus: "error",
          runsStatus: "error",
          error: errorMessage(error, "Failed to load workflow."),
        };
      });
      throw error;
    } finally {
      detailsInFlight.delete(workflowId);
      runsInFlight.delete(workflowId);
    }
  },

  upsertWorkflow(workflow: WorkflowDetail): void {
    cacheRevision += 1;
    store.update((state) => ({
      ...state,
      workflows: replaceWorkflow(state.workflows, workflow),
      selectedWorkflow: state.selectedWorkflowId === workflow.id ? workflow : state.selectedWorkflow,
      detailsById: { ...state.detailsById, [workflow.id]: workflow },
      error: null,
      lastLoadedAt: Date.now(),
    }));
  },

  async createWorkflow(input: {
    title: string;
    graph: WorkflowGraph;
    enabled: boolean;
    runContentRetention: "last_5" | "none";
  }): Promise<WorkflowDetail> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ workflow: WorkflowDetail }>("/v1/workflows", {
      method: "POST",
      body: JSON.stringify({
        title: input.title,
        graph: input.graph,
        enabled: input.enabled,
        run_content_retention: input.runContentRetention,
      }),
    });
    assertCurrentGeneration(requestGeneration);
    this.upsertWorkflow(data.workflow);
    setSelectedFromCaches(data.workflow.id);
    return data.workflow;
  },

  async patchWorkflow(workflowId: string, payload: Record<string, unknown>): Promise<WorkflowDetail> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ workflow: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    assertCurrentGeneration(requestGeneration);
    this.upsertWorkflow(data.workflow);
    return data.workflow;
  },

  async setWorkflowEnabled(workflowId: string, enabled: boolean): Promise<WorkflowDetail> {
    const action = enabled ? "enable" : "disable";
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ workflow: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/${action}`,
      { method: "POST", body: JSON.stringify({}) },
    );
    assertCurrentGeneration(requestGeneration);
    this.upsertWorkflow(data.workflow);
    return data.workflow;
  },

  async deleteWorkflow(workflowId: string): Promise<void> {
    const requestGeneration = cacheGeneration;
    await workflowApiRequest<{ deleted: boolean }>(`/v1/workflows/${encodeURIComponent(workflowId)}`, {
      method: "DELETE",
    });
    assertCurrentGeneration(requestGeneration);
    cacheRevision += 1;
    store.update((state) => {
      const { [workflowId]: _removedDetail, ...detailsById } = state.detailsById;
      const { [workflowId]: _removedRuns, ...runsByWorkflowId } = state.runsByWorkflowId;
      const workflows = state.workflows.filter((workflow) => workflow.id !== workflowId);
      const selectedWorkflowId = state.selectedWorkflowId === workflowId ? null : state.selectedWorkflowId;
      return {
        ...state,
        workflows,
        selectedWorkflowId,
        selectedWorkflow: selectedWorkflowId ? state.selectedWorkflow : null,
        runs: selectedWorkflowId ? state.runs : [],
        detailsById,
        runsByWorkflowId,
        lastLoadedAt: Date.now(),
      };
    });
  },

  async runWorkflow(workflowId: string): Promise<WorkflowRun> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ run: WorkflowRun }>(`/v1/workflows/${encodeURIComponent(workflowId)}/run`, {
      method: "POST",
      body: JSON.stringify({ mode: "test", input: {} }),
    });
    assertCurrentGeneration(requestGeneration);
    cacheRevision += 1;
    store.update((state) => {
      const runs = [data.run, ...(state.runsByWorkflowId[workflowId] ?? [])];
      return {
        ...state,
        workflows: state.workflows.map((workflow) => (
          workflow.id === workflowId ? { ...workflow, last_run_status: data.run.status } : workflow
        )),
        runs: state.selectedWorkflowId === workflowId ? runs : state.runs,
        runsByWorkflowId: { ...state.runsByWorkflowId, [workflowId]: runs },
      };
    });
    return data.run;
  },

  reset(): void {
    cacheRevision += 1;
    cacheGeneration += 1;
    workflowsInFlight = null;
    detailsInFlight.clear();
    runsInFlight.clear();
    store.set({ ...initialState });
  },
};
