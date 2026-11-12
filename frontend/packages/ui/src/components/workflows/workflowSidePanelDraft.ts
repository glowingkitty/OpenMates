// frontend/packages/ui/src/components/workflows/workflowSidePanelDraft.ts
//
// Pure helpers for the chat workflow side panel (WorkflowSidePanel.svelte):
// turning a draft-only authoring session or stream preview into an editable,
// unsaved draft, and deciding how a save is persisted and reported.

import type { WorkflowDetail, WorkflowGraph } from '../../stores/workflowWorkspaceStore';
import type { WorkflowAcceptedPreview, WorkflowInputSession } from '../../services/workflowInputService';
import type { WorkflowSidePanelRequest } from '../../stores/workflowSidePanelStore';

/** Editable, unsaved workflow content held only in the panel. */
export interface WorkflowPanelDraft {
  title: string;
  description: string;
  category: string;
  icon: string;
  graph: WorkflowGraph;
}

export type WorkflowPanelDraftResult =
  | { kind: 'draft'; draft: WorkflowPanelDraft; assumptions: string[] }
  | { kind: 'error'; message: string | null };

export function cloneWorkflowGraph(graph: WorkflowGraph): WorkflowGraph {
  return JSON.parse(JSON.stringify(graph)) as WorkflowGraph;
}

export function blankWorkflowGraph(): WorkflowGraph {
  return { version: 2, trigger_node_id: null, nodes: [], edges: [] };
}

/** Draft content of a saved workflow (update mode, or after the first save). */
export function draftFromWorkflow(workflow: WorkflowDetail): WorkflowPanelDraft {
  return {
    title: workflow.title,
    description: workflow.description ?? '',
    category: workflow.category ?? 'general_knowledge',
    icon: workflow.icon ?? 'workflow',
    graph: cloneWorkflowGraph(workflow.graph)
  };
}

/** Provisional preview workflow for a validated stream checkpoint. */
export function previewFromStreamEvent(event: WorkflowAcceptedPreview, base: WorkflowDetail | null): WorkflowDetail {
  return {
    id: base?.id ?? `provisional-${event.workflow_index}`,
    title: event.metadata.title,
    description: event.metadata.description ?? null,
    category: event.metadata.category ?? base?.category,
    icon: event.metadata.icon ?? base?.icon,
    status: 'provisional',
    enabled: base?.enabled ?? false,
    current_version_id: '',
    graph: event.graph
  };
}

/**
 * Read the settled draft-only session. Only status `draft` is accepted: any other
 * status means the server did not honor draft_only or the authoring failed.
 */
export function draftFromSession(session: WorkflowInputSession, base: WorkflowDetail | null): WorkflowPanelDraftResult {
  if (session.status === 'needs_clarification') return { kind: 'error', message: session.message ?? null };
  if (session.status !== 'draft') return { kind: 'error', message: session.error ?? session.message ?? null };
  const previewWorkflow = session.preview_workflow ?? session.preview_workflows?.[0] ?? null;
  if (!previewWorkflow || previewWorkflow.graph?.version !== 2) return { kind: 'error', message: session.message ?? null };
  return {
    kind: 'draft',
    draft: {
      title: previewWorkflow.title || base?.title || '',
      description: previewWorkflow.description ?? base?.description ?? '',
      category: previewWorkflow.category ?? base?.category ?? 'general_knowledge',
      icon: previewWorkflow.icon ?? base?.icon ?? 'workflow',
      graph: cloneWorkflowGraph(previewWorkflow.graph)
    },
    assumptions: session.assumptions ?? []
  };
}

/** True when opening the panel should start AI authoring (an empty instruction only shows the editor). */
export function shouldStartAuthoring(request: WorkflowSidePanelRequest): boolean {
  return request.instruction.trim().length > 0;
}

/** The workflow a save targets: update an existing one, or create a new one. */
export function saveTarget(request: WorkflowSidePanelRequest, savedWorkflowId: string | null): { action: 'created' | 'updated'; workflowId: string | null } {
  if (savedWorkflowId) return { action: request.mode === 'update' ? 'updated' : 'created', workflowId: savedWorkflowId };
  if (request.mode === 'update' && request.workflowId) return { action: 'updated', workflowId: request.workflowId };
  return { action: 'created', workflowId: null };
}
