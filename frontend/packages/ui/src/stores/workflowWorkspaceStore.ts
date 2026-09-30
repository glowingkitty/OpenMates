// frontend/packages/ui/src/stores/workflowWorkspaceStore.ts
// Shared client-side cache for the Workflows workspace.
// Route components render immediately from this memory store, then refresh the
// encrypted workflow list, selected detail, and run history in the background.
// This keeps workspace tab switches warm without moving workflow loading into
// the chat-critical phased sync path.

import { get, writable } from "svelte/store";
import { getApiEndpoint } from "../config/api";
import { registerWorkspaceCacheClear } from "../services/workspaceCacheLifecycle";

export type WorkflowNodeType =
  | "schedule_trigger"
  | "manual_trigger"
  | "webhook_trigger"
  | "event_trigger"
  | "app_skill_action"
  | "decision"
  | "check"
  | "send_chat_message"
  | "repeat"
  | "create_chat_report"
  | "start_new_chat"
  | "send_notification"
  | "send_email_notification"
  | "ask_user"
  | "wait"
  | "custom_code"
  | "end";

export type WorkflowNode = {
  id: string;
  type: WorkflowNodeType;
  title?: string;
  config?: Record<string, unknown>;
};

export type WorkflowGraph = {
  version: number;
  trigger_node_id: string | null;
  nodes: WorkflowNode[];
  edges: Array<{ from: string; to: string; branch?: string }>;
  limits?: Record<string, unknown>;
};

export type WorkflowSummary = {
  id: string;
  title: string;
  description?: string | null;
  category?: string;
  icon?: string;
  status: string;
  enabled: boolean;
  trigger_summary?: string | null;
  next_run_at?: number | null;
  last_run_status?: string | null;
  run_content_retention?: "last_5" | "none";
  current_version_id: string;
  created_at?: number | null;
  updated_at?: number | null;
  version?: number;
};

export type WorkflowAuthoringWarning = {
  code: string;
  message: string;
};

export type WorkflowBindingRequirement = {
  type: "schedule" | "app_skill" | "notification_preferences" | "chat_destination";
  node_id: string;
  app_id?: string;
  skill_id?: string;
};

export type WorkflowDetail = WorkflowSummary & {
  graph: WorkflowGraph;
  authoring_warnings?: WorkflowAuthoringWarning[];
  binding_requirements?: WorkflowBindingRequirement[];
  completed_binding_requirements?: WorkflowBindingRequirement[];
};

export type WorkflowVersionSummary = {
  version_id: string;
  version_number: number;
  created_at: number;
  created_by_client: string;
  graph_hash: string;
  restored_from_version_id?: string | null;
  current: boolean;
  change_summary?: Record<string, unknown> | null;
};

export type WorkflowVersionDetail = WorkflowVersionSummary & {
  graph: WorkflowGraph;
};

export type WorkflowVersionHistory = {
  versions: WorkflowVersionSummary[];
  current_version_id: string;
  retention: {
    mode: string;
    max_versions: number;
  };
};

export type WorkflowNodeRun = {
  id: string;
  run_id: string;
  workflow_id: string;
  node_id: string;
  node_type: WorkflowNodeType;
  status: string;
  started_at?: number | null;
  finished_at?: number | null;
  skipped_reason?: string | null;
  error_code?: string | null;
  error_summary?: string | null;
  input_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
  credit_cost?: number;
};

export type WorkflowRun = {
  id: string;
  workflow_id: string;
  version_id: string;
  status: string;
  trigger_type: string;
  started_at?: number | null;
  finished_at?: number | null;
  error_summary?: string | null;
  content_retention_mode?: "last_5" | "none";
  content_available?: boolean;
  content_storage?: "durable" | "ephemeral" | "deleted" | null;
  content_expires_at?: number | null;
  cancellation_requested_at?: number | null;
  cancelled_at?: number | null;
  node_runs?: WorkflowNodeRun[];
};

export type WorkflowRunDetail = WorkflowRun & {
  output_summary?: Record<string, unknown>;
};

export type WorkflowRequestInit = {
  method?: string;
  body?: string;
  headers?: Record<string, string>;
};

type WorkspaceLoadStatus = "idle" | "loading" | "refreshing" | "ready" | "error";

export type WorkflowWorkspaceState = {
  generation: number;
  workflows: WorkflowSummary[];
  selectedWorkflow: WorkflowDetail | null;
  selectedWorkflowId: string | null;
  runs: WorkflowRun[];
  detailsById: Record<string, WorkflowDetail>;
  runsByWorkflowId: Record<string, WorkflowRun[]>;
  detailLoadedAtById: Record<string, number>;
  runsLoadedAtById: Record<string, number>;
  listStatus: WorkspaceLoadStatus;
  detailStatus: WorkspaceLoadStatus;
  runsStatus: WorkspaceLoadStatus;
  error: string | null;
  lastLoadedAt: number | null;
};

const WORKFLOW_CACHE_STALE_MS = 60_000;

const initialState: WorkflowWorkspaceState = {
  generation: 0,
  workflows: [],
  selectedWorkflow: null,
  selectedWorkflowId: null,
  runs: [],
  detailsById: {},
  runsByWorkflowId: {},
  detailLoadedAtById: {},
  runsLoadedAtById: {},
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
const detailRevisions = new Map<string, number>();
const runRevisions = new Map<string, number>();
let cacheRevision = 0;
let cacheGeneration = 0;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function isFresh(lastLoadedAt: number | null): boolean {
  return lastLoadedAt !== null && Date.now() - lastLoadedAt < WORKFLOW_CACHE_STALE_MS;
}

function bumpRevision(revisions: Map<string, number>, workflowId: string): void {
  revisions.set(workflowId, (revisions.get(workflowId) ?? 0) + 1);
  // A request started before a local write must not be reused by a later read.
  if (revisions === detailRevisions) detailsInFlight.delete(workflowId);
  if (revisions === runRevisions) runsInFlight.delete(workflowId);
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
  for (const [name, value] of Object.entries(init.headers ?? {})) {
    headers.set(name, value);
  }
  const requestInit = { method: init.method, body: init.body };

  const response = await fetch(getApiEndpoint(path), {
    ...requestInit,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail?.message ?? data?.message;
    throw new Error(message || (response.status === 429 ? "Too many requests. Please wait a moment and try again." : `Workflow request failed with HTTP ${response.status}`));
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
      return { ...state, selectedWorkflowId: null, selectedWorkflow: null, runs: [], detailStatus: "idle", runsStatus: "idle" };
    }
    return {
      ...state,
      selectedWorkflowId: workflowId,
      selectedWorkflow: state.detailsById[workflowId] ?? null,
      runs: state.runsByWorkflowId[workflowId] ?? [],
      detailStatus: state.detailsById[workflowId] ? "ready" : "idle",
      runsStatus: Object.hasOwn(state.runsByWorkflowId, workflowId) ? "ready" : "idle",
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
    if (!options.force && current.lastLoadedAt !== null && isFresh(current.lastLoadedAt)) {
      return current.workflows;
    }
    if (!options.force && current.lastLoadedAt !== null) {
      void this.loadWorkflows({ force: true }).catch(() => undefined);
      return current.workflows;
    }
    if (workflowsInFlight) return workflowsInFlight;
    const requestRevision = cacheRevision;
    const requestGeneration = cacheGeneration;

    store.update((state) => ({
      ...state,
      listStatus: state.lastLoadedAt !== null ? "refreshing" : "loading",
      error: null,
    }));

    const requestPromise = workflowApiRequest<{ workflows: WorkflowSummary[] }>("/v1/workflows")
      .then((data) => {
        if (requestGeneration !== cacheGeneration) return get(store).workflows;
        store.update((state) => {
          if (requestRevision !== cacheRevision) {
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
        if (requestGeneration !== cacheGeneration) throw error;
        store.update((state) => ({
          ...state,
          listStatus: requestRevision !== cacheRevision ? state.listStatus : "error",
          error: requestRevision !== cacheRevision
            ? state.error
            : errorMessage(error, "Failed to load workflows."),
        }));
        throw error;
      })
      .finally(() => {
        if (workflowsInFlight === requestPromise) workflowsInFlight = null;
      });
    workflowsInFlight = requestPromise;

    return workflowsInFlight;
  },

  async selectWorkflow(workflowId: string, options: { force?: boolean } = {}): Promise<WorkflowDetail> {
    setSelectedFromCaches(workflowId);
    const requestGeneration = cacheGeneration;
    const current = get(store);
    const cachedDetail = current.detailsById[workflowId];
    const detailFresh = !!cachedDetail && isFresh(current.detailLoadedAtById[workflowId] ?? null);
    const runsFresh = Object.hasOwn(current.runsByWorkflowId, workflowId)
      && isFresh(current.runsLoadedAtById[workflowId] ?? null);
    if (!options.force && cachedDetail && !detailFresh) {
      void this.selectWorkflow(workflowId, { force: true }).catch(() => undefined);
      return cachedDetail;
    }

    if (options.force || !runsFresh) {
      const requestRevision = runRevisions.get(workflowId) ?? 0;
      store.update((state) => ({
        ...state,
        runsStatus: state.selectedWorkflowId === workflowId
          ? (Object.hasOwn(state.runsByWorkflowId, workflowId) ? "refreshing" : "loading")
          : state.runsStatus,
      }));
      let pending = runsInFlight.get(workflowId);
      if (!pending) {
        pending = workflowApiRequest<{ runs: WorkflowRun[] }>(
          `/v1/workflows/${encodeURIComponent(workflowId)}/runs`,
        ).then((data) => data.runs);
        runsInFlight.set(workflowId, pending);
      }
      const runsPromise = pending;
      void runsPromise.then((runs) => {
        if (requestGeneration !== cacheGeneration || requestRevision !== (runRevisions.get(workflowId) ?? 0)) return;
        store.update((state) => ({
          ...state,
          runs: state.selectedWorkflowId === workflowId ? runs : state.runs,
          runsByWorkflowId: { ...state.runsByWorkflowId, [workflowId]: runs },
          runsLoadedAtById: { ...state.runsLoadedAtById, [workflowId]: Date.now() },
          runsStatus: state.selectedWorkflowId === workflowId ? "ready" : state.runsStatus,
        }));
      }).catch((error) => {
        if (requestGeneration !== cacheGeneration) return;
        store.update((state) => state.selectedWorkflowId === workflowId
          ? { ...state, runsStatus: "error", error: errorMessage(error, "Failed to load workflow runs.") }
          : state);
      }).finally(() => {
        if (runsInFlight.get(workflowId) === runsPromise) runsInFlight.delete(workflowId);
      });
    }

    if (!options.force && detailFresh) return cachedDetail;

    const requestRevision = detailRevisions.get(workflowId) ?? 0;
    store.update((state) => ({
      ...state,
      detailStatus: state.selectedWorkflowId === workflowId ? (cachedDetail ? "refreshing" : "loading") : state.detailStatus,
      error: state.selectedWorkflowId === workflowId ? null : state.error,
    }));
    let pending = detailsInFlight.get(workflowId);
    if (!pending) {
      pending = workflowApiRequest<{ workflow: WorkflowDetail }>(
        `/v1/workflows/${encodeURIComponent(workflowId)}`,
      ).then((data) => data.workflow);
      detailsInFlight.set(workflowId, pending);
    }
    const detailPromise = pending;
    try {
      const workflow = await detailPromise;
      assertCurrentGeneration(requestGeneration);
      if (requestRevision !== (detailRevisions.get(workflowId) ?? 0)) {
        const latest = get(store).detailsById[workflowId];
        if (!latest) throw new Error("Workflow changed while its detail was loading.");
        return latest;
      }
      store.update((state) => {
        const isStillSelected = state.selectedWorkflowId === workflowId;
        return {
          ...state,
          workflows: replaceWorkflow(state.workflows, workflow),
          selectedWorkflow: isStillSelected ? workflow : state.selectedWorkflow,
          detailsById: { ...state.detailsById, [workflowId]: workflow },
          detailLoadedAtById: { ...state.detailLoadedAtById, [workflowId]: Date.now() },
          detailStatus: isStillSelected ? "ready" : state.detailStatus,
          error: isStillSelected ? null : state.error,
        };
      });
      return workflow;
    } catch (error) {
      store.update((state) => requestGeneration === cacheGeneration && state.selectedWorkflowId === workflowId
        ? { ...state, detailStatus: "error", error: errorMessage(error, "Failed to load workflow.") }
        : state);
      throw error;
    } finally {
      if (detailsInFlight.get(workflowId) === detailPromise) detailsInFlight.delete(workflowId);
    }
  },

  upsertWorkflow(workflow: WorkflowDetail): void {
    cacheRevision += 1;
    bumpRevision(detailRevisions, workflow.id);
    store.update((state) => ({
      ...state,
      workflows: replaceWorkflow(state.workflows, workflow),
      selectedWorkflow: state.selectedWorkflowId === workflow.id ? workflow : state.selectedWorkflow,
      detailsById: { ...state.detailsById, [workflow.id]: workflow },
      detailLoadedAtById: { ...state.detailLoadedAtById, [workflow.id]: Date.now() },
      detailStatus: state.selectedWorkflowId === workflow.id ? "ready" : state.detailStatus,
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
    const data = await workflowApiRequest<{ workflow: WorkflowDetail; warnings?: WorkflowAuthoringWarning[] }>("/v1/workflows", {
      method: "POST",
      body: JSON.stringify({
        title: input.title,
        graph: input.graph,
        enabled: input.enabled,
        run_content_retention: input.runContentRetention,
      }),
    });
    assertCurrentGeneration(requestGeneration);
    const workflow = { ...data.workflow, authoring_warnings: data.warnings ?? [] };
    this.upsertWorkflow(workflow);
    setSelectedFromCaches(workflow.id);
    return workflow;
  },

  async importWorkflowFile(document: unknown): Promise<WorkflowDetail> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ workflow: WorkflowDetail }>("/v1/workflows/file-import", {
      method: "POST",
      body: JSON.stringify(document),
    });
    assertCurrentGeneration(requestGeneration);
    this.upsertWorkflow(data.workflow);
    setSelectedFromCaches(data.workflow.id);
    return data.workflow;
  },

  async completeBindingRequirement(workflowId: string, input: WorkflowBindingRequirement & { chat_id?: string; new_chat?: boolean }): Promise<WorkflowDetail> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ workflow: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/binding-requirements/complete`,
      { method: "POST", body: JSON.stringify(input) },
    );
    assertCurrentGeneration(requestGeneration);
    this.upsertWorkflow(data.workflow);
    return data.workflow;
  },

  async patchWorkflow(workflowId: string, payload: Record<string, unknown>): Promise<WorkflowDetail> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ workflow: WorkflowDetail; warnings?: WorkflowAuthoringWarning[] }>(`/v1/workflows/${encodeURIComponent(workflowId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    assertCurrentGeneration(requestGeneration);
    const workflow = { ...data.workflow, authoring_warnings: data.warnings ?? [] };
    this.upsertWorkflow(workflow);
    return workflow;
  },

  async getWorkflowVersions(workflowId: string): Promise<WorkflowVersionHistory> {
    return workflowApiRequest<WorkflowVersionHistory>(`/v1/workflows/${encodeURIComponent(workflowId)}/versions`);
  },

  async getWorkflowVersion(workflowId: string, versionId: string): Promise<WorkflowVersionDetail> {
    const data = await workflowApiRequest<{ version: WorkflowVersionDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/versions/${encodeURIComponent(versionId)}`,
    );
    return data.version;
  },

  async restoreWorkflowVersion(workflowId: string, versionId: string): Promise<WorkflowDetail> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ workflow: WorkflowDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/versions/${encodeURIComponent(versionId)}/restore`,
      { method: "POST", body: JSON.stringify({}) },
    );
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
    bumpRevision(detailRevisions, workflowId);
    bumpRevision(runRevisions, workflowId);
    store.update((state) => {
      const { [workflowId]: _removedDetail, ...detailsById } = state.detailsById;
      const { [workflowId]: _removedRuns, ...runsByWorkflowId } = state.runsByWorkflowId;
      const { [workflowId]: _removedDetailLoadedAt, ...detailLoadedAtById } = state.detailLoadedAtById;
      const { [workflowId]: _removedRunsLoadedAt, ...runsLoadedAtById } = state.runsLoadedAtById;
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
        detailLoadedAtById,
        runsLoadedAtById,
        lastLoadedAt: Date.now(),
      };
    });
  },

  async runWorkflow(workflowId: string): Promise<WorkflowRun> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ run: WorkflowRun }>(`/v1/workflows/${encodeURIComponent(workflowId)}/run`, {
      method: "POST",
      body: JSON.stringify({ mode: "test", input: {} }),
      headers: { "Idempotency-Key": `${workflowId}-${crypto.randomUUID()}` },
    });
    assertCurrentGeneration(requestGeneration);
    cacheRevision += 1;
    bumpRevision(runRevisions, workflowId);
    store.update((state) => {
      const runs = [data.run, ...(state.runsByWorkflowId[workflowId] ?? [])];
      return {
        ...state,
        workflows: state.workflows.map((workflow) => (
          workflow.id === workflowId ? { ...workflow, last_run_status: data.run.status } : workflow
        )),
        runs: state.selectedWorkflowId === workflowId ? runs : state.runs,
        runsByWorkflowId: { ...state.runsByWorkflowId, [workflowId]: runs },
        runsLoadedAtById: { ...state.runsLoadedAtById, [workflowId]: Date.now() },
        runsStatus: state.selectedWorkflowId === workflowId ? "ready" : state.runsStatus,
      };
    });
    return data.run;
  },

  async getWorkflowRun(workflowId: string, runId: string): Promise<WorkflowRunDetail> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ run: WorkflowRunDetail }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}`,
    );
    assertCurrentGeneration(requestGeneration);
    bumpRevision(runRevisions, workflowId);
    store.update((state) => {
      const existingRuns = state.runsByWorkflowId[workflowId] ?? [];
      const hasRun = existingRuns.some((run) => run.id === runId);
      const workflowRuns = hasRun
        ? existingRuns.map((run) => run.id === runId ? data.run : run)
        : [data.run, ...existingRuns];
      return {
        ...state,
        workflows: state.workflows.map((workflow) => (
          workflow.id === workflowId ? { ...workflow, last_run_status: data.run.status } : workflow
        )),
        runs: state.selectedWorkflowId === workflowId ? workflowRuns : state.runs,
        runsByWorkflowId: { ...state.runsByWorkflowId, [workflowId]: workflowRuns },
        runsLoadedAtById: { ...state.runsLoadedAtById, [workflowId]: Date.now() },
        runsStatus: state.selectedWorkflowId === workflowId ? "ready" : state.runsStatus,
      };
    });
    return data.run;
  },

  async cancelWorkflowRun(workflowId: string, runId: string): Promise<"cancellation_requested" | "cancelled"> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ run_id: string; status: "cancellation_requested" | "cancelled" }>(
      `/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/cancel`,
      { method: "POST", body: JSON.stringify({}) },
    );
    assertCurrentGeneration(requestGeneration);
    cacheRevision += 1;
    bumpRevision(runRevisions, workflowId);
    store.update((state) => {
      const updateRuns = (items: WorkflowRun[]) => items.map((run) => (
        run.id === runId ? { ...run, status: data.status } : run
      ));
      const workflowRuns = updateRuns(state.runsByWorkflowId[workflowId] ?? []);
      return {
        ...state,
        runs: state.selectedWorkflowId === workflowId ? workflowRuns : state.runs,
        runsByWorkflowId: { ...state.runsByWorkflowId, [workflowId]: workflowRuns },
        runsLoadedAtById: { ...state.runsLoadedAtById, [workflowId]: Date.now() },
        runsStatus: state.selectedWorkflowId === workflowId ? "ready" : state.runsStatus,
      };
    });
    return data.status;
  },

  async deleteWorkflowRun(workflowId: string, runId: string): Promise<"deleted" | "deletion_pending"> {
    const requestGeneration = cacheGeneration;
    const data = await workflowApiRequest<{ status: "deleted" | "deletion_pending" }>(`/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    assertCurrentGeneration(requestGeneration);
    if (data.status === "deleted") {
      cacheRevision += 1;
      bumpRevision(runRevisions, workflowId);
      store.update(state => {
        const remaining = (state.runsByWorkflowId[workflowId] ?? []).filter(run => run.id !== runId);
        return { ...state, runs: state.selectedWorkflowId === workflowId ? remaining : state.runs, runsByWorkflowId: { ...state.runsByWorkflowId, [workflowId]: remaining }, runsLoadedAtById: { ...state.runsLoadedAtById, [workflowId]: Date.now() }, runsStatus: state.selectedWorkflowId === workflowId ? "ready" : state.runsStatus };
      });
    }
    return data.status;
  },

  reset(): void {
    cacheRevision += 1;
    cacheGeneration += 1;
    workflowsInFlight = null;
    detailsInFlight.clear();
    runsInFlight.clear();
    detailRevisions.clear();
    runRevisions.clear();
    store.set({ ...initialState, generation: cacheGeneration });
  },
};

registerWorkspaceCacheClear(() => workflowWorkspaceStore.reset());
