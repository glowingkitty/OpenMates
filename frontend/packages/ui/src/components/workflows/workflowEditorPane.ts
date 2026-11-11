// frontend/packages/ui/src/components/workflows/workflowEditorPane.ts
//
// Types and pure helpers for WorkflowEditorPane.svelte, the regular editor for
// one workflow used by the /workflows route and beside a chat (WorkflowChatPane.svelte). The pane
// edits either a saved workflow (persisted through workflowWorkspaceStore) or an
// unsaved draft owned by the caller.

import type { WorkflowDetail, WorkflowGraph } from '../../stores/workflowWorkspaceStore';
import { upsertWorkflowTemplateProjection } from '../../services/workflowTemplateService';
import type { WorkflowAiChangeReview, WorkflowAuthoringInfo } from './WorkflowAuthoringNotices.svelte';
import type { WorkflowEditorPreview } from './WorkflowEditorWorkspace.svelte';
import type { WorkflowPanelDraft } from './workflowChatDraft';

/** Unsaved workflow content the caller owns in draft mode. */
export type WorkflowEditorDraft = WorkflowPanelDraft;

/**
 * AI-authoring extras the /workflows route passes for a saved workflow. The
 * pane reports saves through `onSaved` so the caller can clear its AI review.
 */
export interface WorkflowEditorAuthoring {
  /** A caller-owned operation (AI authoring, import, undo) is running: show saving. */
  busy: boolean;
  /** Do not re-hydrate the editor from the store while authoring is pending. */
  hydrationPaused: boolean;
  /** Read-only AI preview shown instead of the editor. */
  preview: WorkflowEditorPreview | null;
  /** Hide "Test now" while any authoring preview is active. */
  testNowHidden: boolean;
  partialNotice: string | null;
  /** Authoring info without the reminder; the pane adds save-time reminders itself. */
  info: Omit<WorkflowAuthoringInfo, 'reminder'>;
  review: WorkflowAiChangeReview | null;
  aiAddedNodeIds: string[];
  aiEditedNodeIds: string[];
  onSaved: (workflow: WorkflowDetail) => void;
}

/** Saved workflow source: persisted edits, enable toggle, runs, test run. */
export interface WorkflowEditorSavedSource {
  kind: 'saved';
  workflow: WorkflowDetail;
  activeTab: 'template' | 'runs';
  selectedRunId: string | null;
  runsHref: string;
  editorHref: string;
  /** Tab change from the header; the caller guards unsaved changes. */
  onTabChange: (tab: 'template' | 'runs') => void;
  /** Open the runs view (a selected run, or null for the list); not guarded. */
  onOpenRun: (runId: string | null) => void;
  /** Back to the editor from the runs view; not guarded. */
  onOpenEditor: () => void;
  onShare: () => void;
  onDeleted: () => void;
  onRequestNavigation: (action: () => void | Promise<void>) => void;
  authoring: WorkflowEditorAuthoring | null;
}

/** Unsaved draft source: node saves and identity edits change only the caller's draft. */
export interface WorkflowEditorDraftSource {
  kind: 'draft';
  draft: WorkflowEditorDraft;
  saving: boolean;
  preview: WorkflowEditorPreview | null;
  partialNotice: string | null;
  info: WorkflowAuthoringInfo | null;
  aiAddedNodeIds: string[];
  aiEditedNodeIds: string[];
  onChange: (draft: WorkflowEditorDraft) => void;
  onSave: (draft: WorkflowEditorDraft) => void | Promise<void>;
  onDraftStateChange: (hasDraft: boolean) => void;
}

export type WorkflowEditorSource = WorkflowEditorSavedSource | WorkflowEditorDraftSource;

/** Editor state the pane reports to its caller after every change. */
export interface WorkflowEditorPaneState {
  /** The editable graph is hydrated (the editor surface is shown). */
  graphReady: boolean;
  /** Identity or graph edits are not saved yet. */
  dirty: boolean;
  /** The pane's own save/enable/run/delete request is running. */
  saving: boolean;
}

/** True when every binding requirement of the workflow has been confirmed. */
export function bindingRequirementsComplete(workflow: WorkflowDetail): boolean {
  return workflow.binding_requirements?.every(requirement =>
    workflow.completed_binding_requirements?.some(completed => completed.type === requirement.type && completed.node_id === requirement.node_id)
  ) !== false;
}

export function cloneGraph(graph: WorkflowGraph): WorkflowGraph {
  return JSON.parse(JSON.stringify(graph)) as WorkflowGraph;
}

/**
 * Refresh the encrypted shareable template of a saved workflow. Returns the
 * user-facing warning when the projection failed (the workflow itself is saved).
 */
export async function maintainTemplateProjection(workflow: WorkflowDetail): Promise<string | null> {
  try {
    await upsertWorkflowTemplateProjection(workflow);
    return null;
  } catch (projectionError) {
    const message =
      projectionError instanceof Error
        ? projectionError.message
        : 'Could not update the encrypted workflow template projection.';
    return `Workflow saved, but its shareable template was not updated: ${message}`;
  }
}
