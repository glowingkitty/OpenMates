<!--
  WorkflowAuthoringNotices — status notices shown above a workflow editor after
  AI authoring: a partial-save warning, authoring info (created-disabled note,
  reminders, assumptions, created-batch undo) and the AI change review with undo.
  Used by WorkflowEditorWorkspace for the /workflows route and the chat side panel.
-->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { WorkflowInputChange } from '../../services/workflowInputService';

  /** Info block; `onUndoCreated` is null when the created batch cannot be undone. */
  export interface WorkflowAuthoringInfo {
    createdDisabled: boolean;
    reminder: string | null;
    assumptions: string[];
    onUndoCreated: (() => void) | null;
  }

  /** Review of AI changes that were applied to this workflow. */
  export interface WorkflowAiChangeReview {
    change: WorkflowInputChange;
    savedLabel: string;
    undoAvailable: boolean;
    undoConflict: boolean;
    onUndo: () => void;
    onOpenHistory: () => void;
  }

  let { partialNotice, info, review, saving }: {
    partialNotice: string | null;
    info: WorkflowAuthoringInfo | null;
    review: WorkflowAiChangeReview | null;
    saving: boolean;
  } = $props();
</script>

{#if partialNotice}<p class="workflow-ai-partial-warning" data-testid="workflow-ai-partial-warning" role="status">{partialNotice}</p>{/if}
{#if info && (info.createdDisabled || info.reminder || info.assumptions.length)}
  <div class="workflow-authoring-info" data-testid="workflow-authoring-info" role="status">
    {#if info.createdDisabled}<p>{$text('workflows.builder.ai_created_disabled')}</p>{/if}
    {#if info.reminder}<p data-testid="workflow-authoring-reminder">{info.reminder}</p>{/if}
    {#each info.assumptions as assumption}<p>{assumption}</p>{/each}
    {#if info.onUndoCreated}{@const undoCreated = info.onUndoCreated}<button type="button" data-testid="workflow-ai-created-undo" disabled={saving} onclick={() => undoCreated()}>{$text('workflows.builder.ai_undo')}</button>{/if}
  </div>
{/if}
{#if review}
  <div class="workflow-ai-changes" data-testid="workflow-ai-changes" role="status">
    <strong>{review.savedLabel}</strong>
    {#if review.change.removed_nodes.length}<p>{$text('workflows.builder.ai_removed')} {review.change.removed_nodes.map(node => node.title).join(', ')}</p>{/if}
    {#if review.change.added_node_ids.length}<p>{review.change.added_node_ids.length} {$text('workflows.builder.ai_added_nodes')}</p>{/if}
    {#if review.change.edited_node_ids.length}<p>{review.change.edited_node_ids.length} {$text('workflows.builder.ai_edited_nodes')}</p>{/if}
    <button type="button" data-testid="workflow-ai-undo" disabled={saving || !review.undoAvailable} onclick={() => review.onUndo()}>{$text('workflows.builder.ai_undo')}</button>
    {#if review.undoConflict}<button type="button" data-testid="workflow-ai-open-history" onclick={() => review.onOpenHistory()}>{$text('workflows.version_history.title')}</button>{/if}
  </div>
{/if}

<style>
  .workflow-ai-partial-warning { max-width: 56rem; margin: 0.75rem auto; padding: 0.75rem 1rem; border: 1px solid var(--color-warning, var(--color-button-primary)); border-radius: var(--radius-5); background: var(--color-grey-10); color: var(--color-font-primary); }
  .workflow-ai-changes { box-sizing: border-box; width: min(42rem, calc(100% - 2rem)); margin: 1rem auto; padding: 1rem 1.25rem; border: 1px solid var(--color-button-primary); border-radius: var(--radius-7); background: var(--color-grey-10); color: var(--color-font-primary); }
  .workflow-ai-changes p { margin: 0.45rem 0; }
  .workflow-authoring-info { box-sizing: border-box; width: min(42rem, calc(100% - 2rem)); margin: 1rem auto; padding: 0.75rem 1rem; border-radius: var(--radius-8, 20px); color: var(--color-font-secondary); background: var(--color-grey-10); font-size: var(--font-size-small); }
  .workflow-authoring-info p { margin: 0.25rem 0; }
  .workflow-authoring-info button,
  .workflow-ai-changes button { margin-top: 0.5rem; border: 0; border-radius: var(--radius-5); padding: 0.55rem 0.9rem; background: var(--color-button-primary); color: var(--color-font-button); font: inherit; cursor: pointer; }
  .workflow-authoring-info button { padding: 0.5rem 0.8rem; }
  .workflow-authoring-info button:disabled,
  .workflow-ai-changes button:disabled { opacity: 0.6; cursor: wait; }
</style>
