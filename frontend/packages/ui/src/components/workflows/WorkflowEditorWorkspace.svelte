<!--
  WorkflowEditorWorkspace — the editable workflow surface shared by the
  /workflows route (saved workflows) and the chat side panel (unsaved AI drafts).
  Renders AI authoring notices, then either the read-only pending AI preview or
  the editable WorkflowGraphRenderer, and an optional "Test now" row.
  The caller owns persistence: onSave decides whether a node save is persisted
  (route) or only kept in the local draft (side panel).
-->
<script lang="ts">
  import type { WorkflowDetail, WorkflowGraph } from '../../stores/workflowWorkspaceStore';
  import { workflowNodeChanges } from '../../services/workflowInputService';
  import WorkflowGraphRenderer from './WorkflowGraphRenderer.svelte';
  import WorkflowPendingPreview from './WorkflowPendingPreview.svelte';
  import WorkflowAuthoringNotices, { type WorkflowAiChangeReview, type WorkflowAuthoringInfo } from './WorkflowAuthoringNotices.svelte';

  /** Read-only AI preview shown instead of the editor while authoring runs. */
  export interface WorkflowEditorPreview {
    workflow: WorkflowDetail;
    phase: 'planning' | 'validating' | 'retrying_node' | 'saving';
    acceptedNodeCount: number;
    /** Graph the proposed changes are compared against (null for a new workflow). */
    baseGraph: WorkflowGraph | null;
  }

  /** "Test now" row for scheduled workflows; null hides it. */
  export interface WorkflowEditorTestNow {
    disabled: boolean;
    label: string;
    onRun: () => void;
  }

  let {
    workflowId,
    graph,
    saving,
    preview,
    partialNotice,
    info,
    review,
    testNow,
    aiAddedNodeIds,
    aiEditedNodeIds,
    onChange,
    onSave,
    onDraftStateChange
  }: {
    /** Saved workflow id; null for an unsaved draft (disables server-side step tests). */
    workflowId: string | null;
    graph: WorkflowGraph;
    saving: boolean;
    preview: WorkflowEditorPreview | null;
    partialNotice: string | null;
    info: WorkflowAuthoringInfo | null;
    review: WorkflowAiChangeReview | null;
    testNow: WorkflowEditorTestNow | null;
    aiAddedNodeIds: string[];
    aiEditedNodeIds: string[];
    onChange: (graph: WorkflowGraph) => void;
    onSave: (graph: WorkflowGraph) => Promise<void>;
    onDraftStateChange: (hasDraft: boolean) => void;
  } = $props();

  let renderer = $state<WorkflowGraphRenderer | null>(null);

  /** True while a node editor holds unsaved step changes. */
  export function hasPendingDraft(): boolean { return renderer?.hasPendingDraft() ?? false; }
  export function savePendingDraft(): Promise<boolean> { return renderer ? renderer.savePendingDraft() : Promise.resolve(true); }
  export function discardPendingDraft(): void { renderer?.discardPendingDraft(); }
  export function openNodeEditor(nodeId: string): void { renderer?.openNodeEditor(nodeId); }
</script>

<div data-testid="workflow-editor">
  <WorkflowAuthoringNotices {partialNotice} {info} {review} {saving} />
  {#if preview}
    <WorkflowPendingPreview workflow={preview.workflow} mode="editor" phase={preview.phase} acceptedNodeCount={preview.acceptedNodeCount} changes={preview.baseGraph ? workflowNodeChanges(preview.baseGraph.nodes, preview.workflow.graph.nodes) : null}/>
  {:else}
    <WorkflowGraphRenderer
      bind:this={renderer}
      {graph}
      {aiAddedNodeIds}
      {aiEditedNodeIds}
      {workflowId}
      {onChange}
      {onSave}
      {onDraftStateChange}
    />
  {/if}
  {#if testNow && !preview}
    <div class="workflow-test-now-row">
      <button type="button" class="workflow-test-now" data-testid="workflow-template-test-now" disabled={testNow.disabled} onclick={() => testNow.onRun()}>
        <span class="workflow-icon icon-play size-20" aria-hidden="true"></span>
        {testNow.label}
      </button>
    </div>
  {/if}
</div>

<style>
  .workflow-test-now-row { display: flex; justify-content: center; padding: 0 1rem 2rem; }
  .workflow-test-now { display: inline-flex; align-items: center; justify-content: center; gap: 0.55rem; min-width: 12rem; min-height: 3rem; padding: 0.6rem 1.4rem; border: 0; border-radius: var(--radius-7); background: var(--color-button-primary); color: var(--color-font-button); box-shadow: var(--shadow-sm); font: inherit; font-weight: 650; cursor: pointer; }
  .workflow-test-now:disabled { opacity: 0.55; cursor: not-allowed; }
</style>
