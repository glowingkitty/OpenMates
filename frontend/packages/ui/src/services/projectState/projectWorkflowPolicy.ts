// frontend/packages/ui/src/services/projectState/projectWorkflowPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Workflow-in-Project and Project authoring decisions: which existing item and
// connected source a saved workflow binds to (projectCreationNavigation.ts), when a
// remote workflow file stays pending, the bounded authoring transcript and the
// authoring catalog (projectAuthoringClientService.ts). Fetch, IndexedDB, stores and
// the approval dialog stay in those services; with VITE_OPENMATES_RUST_CORE=1 the
// shared Rust core decides (web_projects/workflow.rs). No imports.

const HISTORY_BUDGET_CHARS = 12_000;
const MAX_AUTHORING_CATALOG = 40;

export interface WorkflowTargetSource { source_id: string; source_type: string; sourceSessionId?: string | null }
export interface WorkflowTargetItem { item_type: string; target_id: string; metadata: Record<string, unknown> }

/**
 * Binding plan of a workflow saved into a Project. `binding.mode === "prior"` keeps the
 * stored binding object unchanged (the page reuses it so its key order is preserved).
 */
export function projectWorkflowTarget(input: {
  projectId: string; workflowId: string; targetSourceId: string | null; folderPath: string | null;
  sources: WorkflowTargetSource[]; items: WorkflowTargetItem[];
}): {
  existingIndex: number | null; sourceIndex: number | null; remote: boolean;
  binding: { mode: "prior" } | { mode: "new"; project_id: string; source_id: string; folder_path: string } | null;
} {
  const remoteSources = input.sources
    .map((source, index) => ({ source, index }))
    .filter(({ source }) => source.source_type.startsWith("remote_") || source.sourceSessionId);
  const existingIndex = input.items.findIndex((item) => item.item_type === "workflow" && item.target_id === input.workflowId);
  const prior = existingIndex >= 0
    ? input.items[existingIndex].metadata.remote_workflow_file as { source_id?: string } | undefined
    : undefined;
  const sourceId = prior?.source_id || input.targetSourceId;
  const found = sourceId ? input.sources.findIndex((source) => source.source_id === sourceId) : -1;
  const sourceIndex = sourceId ? (found >= 0 ? found : null) : remoteSources.length === 1 ? remoteSources[0].index : null;
  const remote = Boolean(sourceIndex !== null || remoteSources.length || input.targetSourceId || prior);
  return {
    existingIndex: existingIndex >= 0 ? existingIndex : null,
    sourceIndex,
    remote,
    binding: !remote ? null : prior?.source_id ? { mode: "prior" } : {
      mode: "new",
      project_id: input.projectId,
      source_id: sourceIndex !== null ? input.sources[sourceIndex].source_id : "",
      folder_path: input.folderPath ?? "",
    },
  };
}

/**
 * Why a bound remote workflow file stays pending before any write is attempted.
 * Phase `source` runs before the active focus is read; phase `focus` after it.
 */
export function projectWorkflowRemoteGate(input: {
  phase: "source" | "focus"; projectId: string; bindingProjectId: string; sourceFound: boolean;
  sourceStatus: string | null; chatId: string | null; focusProjectId: string | null;
}): { pending: "source_offline" | "project_focus_required" | null } {
  if (input.phase === "source") {
    if (input.sourceStatus === "offline") return { pending: "source_offline" };
    if (input.bindingProjectId !== input.projectId) return { pending: "project_focus_required" };
    return { pending: null };
  }
  if (!input.sourceFound || !input.chatId || input.focusProjectId !== input.projectId) return { pending: "project_focus_required" };
  return { pending: null };
}

export interface AuthoringHistoryMessage { role: string; content?: string | null; status: string; created_at: number }

/** The newest completed user/assistant turns (oldest first) within a 12,000-character budget. */
export function projectAuthoringHistory(input: {
  messages: AuthoringHistoryMessage[]; anchorCreatedAt: number | null;
}): { rows: Array<{ role: "user" | "assistant"; content: string }> } {
  const rows: Array<{ role: "user" | "assistant"; content: string }> = [];
  let remaining = HISTORY_BUDGET_CHARS;
  for (const message of [...input.messages].reverse()) {
    if (input.anchorCreatedAt !== null && message.created_at > input.anchorCreatedAt) continue;
    if ((message.role !== "user" && message.role !== "assistant") || !message.content?.trim()
      || ["streaming", "processing", "failed"].includes(message.status)) continue;
    const content = message.content.slice(-remaining);
    if (content) rows.unshift({ role: message.role, content });
    remaining -= content.length;
    if (remaining <= 0) break;
  }
  if (!rows.length) throw new Error("project_authoring_history_unavailable");
  return { rows };
}

export interface AuthoringFocusEntry { kind: string; id: string; title: string; summary: string; revision: string }
export interface AuthoringWorkflowSummary {
  id: string; title: string; version?: unknown; description?: string | null; trigger_summary?: string | null;
}

/**
 * Catalog sent to the authoring assessment: focuses plus the Project's linked
 * workflows. Null when the workflow catalog is unavailable while workflows are
 * linked (non-overlap is never inferred) or the catalog exceeds 40 entries.
 */
export function projectAuthoringCatalog(input: {
  focuses: AuthoringFocusEntry[]; workflows: AuthoringWorkflowSummary[]; linkedIds: string[]; workflowsOk: boolean;
}): { catalog: AuthoringFocusEntry[] | null } {
  const linked = new Set(input.linkedIds);
  if (!input.workflowsOk && linked.size) return { catalog: null };
  const workflows = input.workflowsOk ? input.workflows : [];
  const catalog = [
    ...input.focuses.map(({ kind, id, title, summary, revision }) => ({ kind, id, title, summary, revision })),
    ...workflows.filter((item) => linked.has(item.id) && Number.isInteger(item.version)).map((item) => ({
      kind: "workflow", id: item.id, title: item.title.slice(0, 200),
      summary: (item.description ?? item.trigger_summary ?? "").slice(0, 2_000), revision: String(item.version),
    })),
  ];
  return { catalog: catalog.length > MAX_AUTHORING_CATALOG ? null : catalog };
}

export const WORKFLOW_OPS = {
  projectWorkflowTarget, projectWorkflowRemoteGate, projectAuthoringHistory, projectAuthoringCatalog,
};
