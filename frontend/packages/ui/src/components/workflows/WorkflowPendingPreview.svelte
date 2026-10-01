<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { WorkflowDetail } from '../../stores/workflowWorkspaceStore';
  import WorkflowGraphRenderer from './WorkflowGraphRenderer.svelte';

  let { workflow, mode, phase = 'saving', changes = null, isNew = false, acceptedNodeCount = 0 }: { workflow: WorkflowDetail; mode: 'landing' | 'editor'; phase?: 'planning' | 'validating' | 'retrying_node' | 'saving'; changes?: { added_node_ids: string[]; edited_node_ids: string[]; removed_nodes: Array<{ id: string; title: string }> } | null; isNew?: boolean; acceptedNodeCount?: number } = $props();
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const phaseLabel = $derived(phase === 'saving' ? tr('ai_preview_saving') : phase === 'retrying_node' ? 'Correcting step...' : phase === 'validating' ? 'Validating...' : 'Preparing...');
  const steps = $derived(workflow.graph.nodes.filter(node => node.type !== 'end'));
</script>

<section class="pending-preview" class:editor={mode === 'editor'} data-testid="workflow-ai-pending-preview" data-save-status={phase} data-disabled="true" aria-label={tr('ai_preview_label')}>
  <div class="preview-heading">
    <span class="saving-pill" data-testid="workflow-ai-saving-pill">{phaseLabel}</span>
    <span class="preview-label">{tr('ai_preview_label')}</span>
  </div>
  <h2 data-testid="workflow-ai-preview-title">{workflow.title}</h2>
  {#if acceptedNodeCount > 0}<p class="preview-count" data-testid="workflow-ai-accepted-nodes">{acceptedNodeCount} {acceptedNodeCount === 1 ? 'step' : 'steps'} validated</p>{/if}
  {#if workflow.description}<p class="description" data-testid="workflow-ai-preview-description">{workflow.description}</p>{/if}
  <p class="preview-state" data-testid="workflow-ai-preview-enabled-state">{isNew ? 'New workflow · Paused until enabled' : workflow.enabled ? 'Existing workflow · Enabled' : 'Existing workflow · Paused'}</p>
  <p class="pending-note">{phase === 'saving' ? tr('ai_preview_pending') : 'Preview only. You can edit it after it is saved, and run it once it is enabled.'}</p>
  {#if steps.length}<ol class="steps" data-testid="workflow-ai-preview-steps">{#each steps as node (node.id)}<li>{node.title || node.type.replaceAll('_', ' ')}</li>{/each}</ol>{/if}
  {#if changes && (changes.removed_nodes.length || changes.added_node_ids.length || changes.edited_node_ids.length)}
    <div class="preview-changes" data-testid="workflow-ai-preview-changes">
      <strong>Proposed changes</strong>
      {#if changes.removed_nodes.length}<p>Removed: {changes.removed_nodes.map(node => node.title).join(', ')}</p>{/if}
      {#if changes.added_node_ids.length}<p>{changes.added_node_ids.length} added</p>{/if}
      {#if changes.edited_node_ids.length}<p>{changes.edited_node_ids.length} edited</p>{/if}
    </div>
  {/if}
  <div class="preview-graph" data-testid="workflow-ai-preview-graph">
    <WorkflowGraphRenderer graph={workflow.graph} readOnly aiAddedNodeIds={changes?.added_node_ids ?? []} aiEditedNodeIds={changes?.edited_node_ids ?? []} onChange={() => undefined} onSave={null}/>
  </div>
</section>

<style>
  .pending-preview{box-sizing:border-box;width:min(42rem,calc(100% - 2rem));margin:1rem auto;padding:1rem 1.25rem;border:1px solid var(--color-button-primary);border-radius:1rem;background:var(--color-grey-10);color:var(--color-font-primary)}
  .pending-preview.editor{width:min(56rem,calc(100% - 2rem))}
  .preview-heading{display:flex;align-items:center;gap:.65rem;flex-wrap:wrap}
  .saving-pill{display:inline-flex;align-items:center;border-radius:999px;padding:.3rem .75rem;background:var(--color-button-primary);color:var(--color-font-button);font-size:var(--font-size-small);font-weight:700}
  .preview-label{color:var(--color-font-secondary);font-size:var(--font-size-small)}
  h2{margin:.75rem 0 .25rem;font-size:1.25rem;line-height:1.3}
  .description,.pending-note{margin:.35rem 0;color:var(--color-font-secondary)}
  .preview-state,.preview-count{margin:.35rem 0;color:var(--color-font-secondary);font-size:var(--font-size-small)}
  .preview-changes{margin-top:.9rem}
  .steps{margin:.9rem 0 0;padding-left:1.4rem}
  .preview-changes p{margin:.35rem 0}
  .preview-graph{margin-top:1rem}
</style>
