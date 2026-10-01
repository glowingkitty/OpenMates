<!-- Native Swift counterpart: apple/OpenMates/Sources/Features/Workflows/Views/WorkflowSidebarView.swift -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { workflowWorkspaceStore, type WorkflowSummary } from '../../stores/workflowWorkspaceStore';
  import { getCategoryGradientColors, getLucideIcon, getValidIconName } from '../../utils/categoryUtils';
  import { text } from '../../i18n/translations';
  import { workflowIcon } from '../workflows/workflowBuilder';

  interface Props {
    onSelect: (workflow: WorkflowSummary) => void;
    onClose: () => void;
    /** Static data for the isolated component preview. */
    previewWorkflows?: WorkflowSummary[];
    previewSelectedId?: string | null;
  }

  let { onSelect, onClose, previewWorkflows, previewSelectedId }: Props = $props();
  let workflows = $derived(previewWorkflows ?? $workflowWorkspaceStore.workflows);
  let loading = $derived(previewWorkflows === undefined && $workflowWorkspaceStore.listStatus === 'loading');
  let selectedId = $derived(previewSelectedId ?? $workflowWorkspaceStore.selectedWorkflowId);

  onMount(() => {
    if (previewWorkflows === undefined) void workflowWorkspaceStore.loadWorkflows().catch(() => undefined);
  });

  function iconFor(workflow: WorkflowSummary) {
    return getLucideIcon(getValidIconName(workflowIcon(workflow.title, workflow.icon), workflow.category ?? 'general_knowledge'));
  }

  function gradientFor(workflow: WorkflowSummary): string {
    const colors = getCategoryGradientColors(workflow.category ?? 'openmates_official')
      ?? getCategoryGradientColors('openmates_official');
    return `background: linear-gradient(135deg, ${colors!.start}, ${colors!.end})`;
  }
</script>

<aside class="workflow-sidebar" data-testid="workflows-sidebar" aria-label="Workflows">
  <div class="workflow-sidebar-topbar">
    <button type="button" class="sidebar-close" data-testid="workflow-sidebar-close" aria-label={$text('common.close')} onclick={onClose}>
      <span class="clickable-icon icon_close" aria-hidden="true"></span>
    </button>
  </div>
  <div class="workflow-sidebar-heading">
    <h2>Workflows</h2>
    <span>{workflows.length}</span>
  </div>
  {#if loading}
    <p class="workflow-sidebar-state">Loading workflows...</p>
  {:else if workflows.length === 0}
    <p class="workflow-sidebar-state">No workflows yet.</p>
  {:else}
    <nav class="workflow-sidebar-list" aria-label="Workflow list">
      {#each workflows as workflow (workflow.id)}
        {@const Icon = iconFor(workflow)}
        <button
          type="button"
          class="workflow-sidebar-row"
          class:active={selectedId === workflow.id}
          data-testid="workflow-sidebar-row"
          aria-current={selectedId === workflow.id ? 'page' : undefined}
          onclick={() => onSelect(workflow)}
        >
          <span class="workflow-sidebar-icon" style={gradientFor(workflow)} aria-hidden="true"><Icon size={16} color="white" /></span>
          <span class="workflow-sidebar-copy">
            <span class="workflow-sidebar-title">{workflow.title}</span>
            <span class="workflow-sidebar-meta">{workflow.enabled ? 'Enabled' : 'Draft'} · {workflow.trigger_summary ?? 'Manual'}</span>
          </span>
        </button>
      {/each}
    </nav>
  {/if}
</aside>

<style>
  .workflow-sidebar {
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
    width: 100%;
    min-width: 0;
    height: 100%;
    overflow: hidden;
    color: var(--color-font-primary);
    background: var(--color-grey-20);
  }
  .workflow-sidebar-topbar {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    flex: 0 0 auto;
    height: 48px;
    padding: var(--spacing-6) var(--spacing-8);
    border-bottom: 1px solid var(--color-grey-30);
  }
  .sidebar-close {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-3);
    color: var(--color-font-primary);
    background: transparent;
    cursor: pointer;
  }
  .sidebar-close .clickable-icon { width: 20px; height: 20px; }
  @media (hover: hover) { .sidebar-close:hover { background: var(--color-grey-30); } }
  .sidebar-close:focus-visible,
  .workflow-sidebar-row:focus-visible { outline: 2px solid var(--color-primary-focus); outline-offset: -2px; }
  .workflow-sidebar-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-3);
    padding: var(--spacing-8) var(--spacing-8) var(--spacing-3);
  }
  .workflow-sidebar-heading h2 {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: 0.85em;
    font-weight: 500;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  .workflow-sidebar-heading > span { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .workflow-sidebar-state { margin: 0; padding: var(--spacing-6) var(--spacing-8); color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .workflow-sidebar-list { flex: 1; min-height: 0; overflow-y: auto; padding: 0 var(--spacing-4) var(--spacing-4); scrollbar-width: thin; }
  .workflow-sidebar-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-8);
    box-sizing: border-box;
    width: 100%;
    min-height: 56px;
    padding: var(--spacing-5) var(--spacing-8);
    border: 0;
    border-radius: var(--radius-3);
    text-align: start;
    color: var(--color-font-primary);
    background: transparent;
    cursor: pointer;
    transition: background-color var(--duration-fast) var(--easing-default);
  }
  @media (hover: hover) { .workflow-sidebar-row:hover:not(.active) { background: var(--color-grey-10); } }
  .workflow-sidebar-row.active { background: var(--color-grey-0); }
  .workflow-sidebar-icon {
    display: grid;
    place-items: center;
    flex: 0 0 28px;
    width: 28px;
    height: 28px;
    border: 2px solid var(--color-background);
    border-radius: 50%;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  }
  .workflow-sidebar-copy { display: flex; flex-direction: column; min-width: 0; line-height: 1.3; }
  .workflow-sidebar-title,
  .workflow-sidebar-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .workflow-sidebar-title { font-size: var(--font-size-p); font-weight: 500; }
  .workflow-sidebar-meta { color: var(--color-font-secondary); font-size: var(--font-size-small); }
</style>
