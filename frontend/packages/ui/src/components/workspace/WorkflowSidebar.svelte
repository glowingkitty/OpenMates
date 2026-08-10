<!--
  WorkflowSidebar.svelte

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Workflows/Views/WorkflowSidebarView.swift

  Renders the active Workflows workspace navigator. It deliberately owns no chat
  state so the shell can swap workspace lists without leaking chat navigation.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { workflowWorkspaceStore, type WorkflowSummary } from '../../stores/workflowWorkspaceStore';

  interface Props {
    onSelect: (workflow: WorkflowSummary) => void;
  }

  let { onSelect }: Props = $props();
  let workflows = $derived($workflowWorkspaceStore.workflows);
  let loading = $derived($workflowWorkspaceStore.listStatus === 'loading');

  onMount(() => {
    void workflowWorkspaceStore.loadWorkflows().catch(() => undefined);
  });
</script>

<aside class="workflow-sidebar" data-testid="workflows-sidebar" aria-label="Workflows">
  <div class="workflow-sidebar-heading">
    <p>Workflows</p>
    <span>{workflows.length}</span>
  </div>
  {#if loading}
    <p class="workflow-sidebar-state">Loading workflows...</p>
  {:else if workflows.length === 0}
    <p class="workflow-sidebar-state">No workflows yet.</p>
  {:else}
    <div class="workflow-sidebar-list">
      {#each workflows as workflow (workflow.id)}
        <button type="button" data-testid="workflow-sidebar-row" onclick={() => onSelect(workflow)}>
          <strong>{workflow.title}</strong>
          <span>{workflow.enabled ? 'Enabled' : 'Draft'} · {workflow.trigger_summary ?? 'Manual'}</span>
        </button>
      {/each}
    </div>
  {/if}
</aside>

<style>
  .workflow-sidebar {
    display: grid;
    align-content: start;
    gap: var(--spacing-5);
    min-width: 0;
    height: 100%;
    padding: var(--spacing-6);
    overflow: auto;
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    border-radius: var(--radius-10);
  }

  .workflow-sidebar-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-3);
  }

  .workflow-sidebar-heading p,
  .workflow-sidebar-heading span,
  .workflow-sidebar-state,
  .workflow-sidebar-list span {
    margin: 0;
    color: var(--color-font-secondary);
  }

  .workflow-sidebar-heading p {
    font-size: var(--font-size-small);
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .workflow-sidebar-heading span {
    display: grid;
    place-items: center;
    min-width: 1.8rem;
    min-height: 1.8rem;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
  }

  .workflow-sidebar-list {
    display: grid;
    gap: var(--spacing-3);
  }

  .workflow-sidebar-list button {
    display: grid;
    gap: var(--spacing-2);
    width: 100%;
    padding: var(--spacing-4);
    text-align: start;
    color: var(--color-font-primary);
    background: var(--color-grey-10);
    border: 0;
    border-radius: var(--radius-8);
    cursor: pointer;
  }

  .workflow-sidebar-list button:hover,
  .workflow-sidebar-list button:focus-visible {
    outline: 2px solid var(--color-button-primary);
    background: var(--color-grey-blue);
  }

  .workflow-sidebar-list span,
  .workflow-sidebar-state {
    font-size: var(--font-size-small);
  }
</style>
