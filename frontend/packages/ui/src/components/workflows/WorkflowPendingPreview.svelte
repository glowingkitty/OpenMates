<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { WorkflowDetail } from '../../stores/workflowWorkspaceStore';
  import WorkflowGraphRenderer from './WorkflowGraphRenderer.svelte';

  let { workflow, mode }: { workflow: WorkflowDetail; mode: 'landing' | 'editor' } = $props();
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const steps = $derived(workflow.graph.nodes.filter(node => node.type !== 'end'));
</script>

<section class="pending-preview" class:editor={mode === 'editor'} data-testid="workflow-ai-pending-preview" data-save-status="saving" data-disabled="true" aria-label={tr('ai_preview_label')}>
  <div class="preview-heading">
    <span class="saving-pill" data-testid="workflow-ai-saving-pill">{tr('ai_preview_saving')}</span>
    <span class="preview-label">{tr('ai_preview_label')}</span>
  </div>
  <h2 data-testid="workflow-ai-preview-title">{workflow.title}</h2>
  {#if workflow.description}<p class="description" data-testid="workflow-ai-preview-description">{workflow.description}</p>{/if}
  <p class="pending-note">{tr('ai_preview_pending')}</p>
  {#if steps.length}
    <div class="steps">
      <strong>{tr('ai_preview_steps')}</strong>
      <ol data-testid="workflow-ai-preview-steps">
        {#each steps as node (node.id)}<li>{node.title || node.type.replaceAll('_', ' ')}</li>{/each}
      </ol>
    </div>
  {/if}
  {#if mode === 'editor'}
    <div class="preview-graph" data-testid="workflow-ai-preview-graph">
      <WorkflowGraphRenderer graph={workflow.graph} readOnly onChange={() => undefined} onSave={null}/>
    </div>
  {/if}
</section>

<style>
  .pending-preview{box-sizing:border-box;width:min(42rem,calc(100% - 2rem));margin:1rem auto;padding:1rem 1.25rem;border:1px solid var(--color-button-primary);border-radius:1rem;background:var(--color-grey-10);color:var(--color-font-primary)}
  .pending-preview.editor{width:min(56rem,calc(100% - 2rem))}
  .preview-heading{display:flex;align-items:center;gap:.65rem;flex-wrap:wrap}
  .saving-pill{display:inline-flex;align-items:center;border-radius:999px;padding:.3rem .75rem;background:var(--color-button-primary);color:var(--color-font-button);font-size:var(--font-size-small);font-weight:700}
  .preview-label{color:var(--color-font-secondary);font-size:var(--font-size-small)}
  h2{margin:.75rem 0 .25rem;font-size:1.25rem;line-height:1.3}
  .description,.pending-note{margin:.35rem 0;color:var(--color-font-secondary)}
  .steps{margin-top:.9rem}
  ol{margin:.4rem 0 0;padding-left:1.4rem}
  li{padding:.18rem 0}
  .preview-graph{margin-top:1rem}
</style>
