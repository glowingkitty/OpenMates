<script lang="ts">
  import type { WorkflowBindingRequirement, WorkflowGraph } from '../../stores/workflowWorkspaceStore';
  import { text } from '../../i18n/translations';

  let { requirements, completed = [], graph, saving, hasUnsavedChanges, onEdit, onConfirm }: {
    requirements: WorkflowBindingRequirement[];
    completed?: WorkflowBindingRequirement[];
    graph: WorkflowGraph;
    saving: boolean;
    hasUnsavedChanges: boolean;
    onEdit: (nodeId: string) => void;
    onConfirm: (requirement: WorkflowBindingRequirement) => void | Promise<void>;
  } = $props();

  const nameKeys: Record<WorkflowBindingRequirement['type'], string> = {
    schedule: 'file_binding_schedule',
    app_skill: 'file_binding_app',
    notification_preferences: 'file_binding_notification',
    chat_destination: 'file_binding_chat',
  };
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const done = (requirement: WorkflowBindingRequirement) => completed.some(item => item.type === requirement.type && item.node_id === requirement.node_id);
  const node = (requirement: WorkflowBindingRequirement) => graph.nodes.find(item => item.id === requirement.node_id);
</script>

{#if requirements.length}
  <section class="binding-review" data-testid="workflow-binding-review" aria-labelledby="workflow-binding-title">
    <h2 id="workflow-binding-title">{tr('file_binding_title')}</h2>
    <p>{tr('file_binding_description')}</p>
    <ul>
      {#each requirements as requirement (`${requirement.type}:${requirement.node_id}`)}
        <li data-testid="workflow-binding-item" data-binding-type={requirement.type}>
          <div class="binding-copy">
            <strong>{tr(nameKeys[requirement.type])}</strong>
            <span>{node(requirement)?.title || node(requirement)?.type.replaceAll('_', ' ') || requirement.node_id}</span>
            {#if requirement.type === 'chat_destination'}<small>{tr('file_binding_chat_hint')}</small>{/if}
          </div>
          <div class="binding-actions">
            {#if done(requirement)}<span class="confirmed">{tr('file_binding_confirmed')}</span>{:else}
              <button type="button" data-testid="workflow-binding-edit" disabled={saving || hasUnsavedChanges} onclick={() => onEdit(requirement.node_id)}>{tr('file_binding_edit')}</button>
              <button type="button" class="confirm" data-testid="workflow-binding-confirm" disabled={saving || hasUnsavedChanges} onclick={() => void onConfirm(requirement)}>{tr('file_binding_confirm')}</button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
    {#if hasUnsavedChanges}<p role="status">{tr('file_binding_save_first')}</p>{/if}
  </section>
{/if}

<style>
  .binding-review{box-sizing:border-box;width:min(42rem,calc(100% - 2rem));margin:1rem auto;padding:1rem 1.25rem;border:1px solid var(--color-grey-25);border-radius:var(--radius-5);background:var(--color-grey-10);color:var(--color-font-primary)}
  h2{margin:0 0 .45rem;font-size:var(--font-size-h3)}p{margin:.25rem 0 .75rem;font-size:var(--font-size-small);line-height:1.5;color:var(--color-font-secondary)}ul{list-style:none;margin:0;padding:0}li{display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:.75rem 0;border-top:1px solid var(--color-grey-25)}.binding-copy{display:grid;gap:.15rem}.binding-copy strong{font-size:var(--font-size-small)}.binding-copy span,.binding-copy small{font-size:var(--font-size-small);color:var(--color-font-secondary)}.binding-actions{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}.binding-actions button{border:1px solid var(--color-grey-30);border-radius:var(--radius-3);padding:.45rem .7rem;background:var(--color-grey-0);color:var(--color-font-primary);font:inherit;font-size:var(--font-size-small);cursor:pointer}.binding-actions .confirm{border-color:var(--color-button-primary);background:var(--color-button-primary);color:var(--color-font-button)}.binding-actions button:disabled{opacity:.5;cursor:default}.binding-actions button:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}.confirmed{font-size:var(--font-size-small);color:var(--color-primary)}@media(max-width:520px){li{align-items:flex-start;flex-direction:column}}
</style>
