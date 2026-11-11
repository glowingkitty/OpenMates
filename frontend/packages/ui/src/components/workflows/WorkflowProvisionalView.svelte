<!--
  WorkflowProvisionalView — read-only view of a workflow that AI authoring is
  still creating: provisional detail header (Close only), the processing
  status, validated-step count and the read-only pending graph.
  Used by the /workflows route while a single new workflow streams in.
-->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { WorkflowDetail } from '../../stores/workflowWorkspaceStore';
  import { workflowIcon } from './workflowBuilder';
  import WorkflowDetailPage from './WorkflowDetailPage.svelte';
  import WorkflowGraphRenderer from './WorkflowGraphRenderer.svelte';

  let { workflow, pendingMessage, phase, acceptedNodeCount, onClose }: {
    workflow: WorkflowDetail;
    /** Server status message of the pending save, when there is one. */
    pendingMessage: string | null;
    phase: 'planning' | 'validating' | 'retrying_node' | 'saving' | null;
    acceptedNodeCount: number;
    onClose: () => void;
  } = $props();
</script>

<WorkflowDetailPage
  state="provisional"
  title={workflow.title}
  description={workflow.description ?? ''}
  category={workflow.category ?? 'general_knowledge'}
  icon={workflowIcon(workflow.title, workflow.icon, workflow.graph)}
  onOpenHome={onClose}
/>
<div id="tabpanel-template" data-testid="workflow-template-panel" role="tabpanel" aria-label="Workflow template">
  <div data-testid="workflow-editor">
    <div class="workflow-ai-pending" data-testid="workflow-ai-processing" role="status">{pendingMessage || (phase === 'saving' ? $text('workflows.builder.ai_preview_saving') : $text('workflows.builder.processing'))}</div>
    <div class="workflow-authoring-info" data-testid="workflow-authoring-info" role="status">
      {#if acceptedNodeCount > 0}<p data-testid="workflow-ai-accepted-nodes">{$text(acceptedNodeCount === 1 ? 'workflows.builder.ai_validated_step' : 'workflows.builder.ai_validated_steps', { values: { count: acceptedNodeCount } })}</p>{/if}
      <p>{$text('workflows.builder.ai_preview_pending')}</p>
    </div>
    <div data-testid="workflow-ai-pending-preview" data-disabled="true" data-save-status={phase ?? 'saving'}>
      <WorkflowGraphRenderer graph={workflow.graph} readOnly onChange={() => undefined} onSave={null}/>
    </div>
  </div>
</div>

<style>
  .workflow-ai-pending{display:flex;justify-content:center;align-items:center;gap:.75rem;max-width:42rem;margin:.75rem auto;color:var(--color-font-secondary);pointer-events:auto}
  .workflow-authoring-info{box-sizing:border-box;width:min(42rem,calc(100% - 2rem));margin:1rem auto;padding:.75rem 1rem;border-radius:var(--radius-8,20px);color:var(--color-font-secondary);background:var(--color-grey-10);font-size:var(--font-size-small,.875rem)}
  .workflow-authoring-info p{margin:.25rem 0}
  #tabpanel-template {
    box-sizing: border-box;
    width: min(60rem, calc(100% - 4rem));
    margin: 0 auto;
    padding-top: 2.5rem;
    border-radius: var(--radius-16);
    background: var(--color-grey-0);
  }
  #tabpanel-template :global(.graph-panel) {
    width: 100%;
    margin-block: 0;
  }
  @media (max-width: 730px) {
    #tabpanel-template {
      width: calc(100% - 1rem);
    }
  }
</style>
