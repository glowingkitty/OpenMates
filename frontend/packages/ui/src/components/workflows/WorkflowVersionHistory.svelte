<!--
  WorkflowVersionHistory.svelte
  Renders the capped immutable definition history for one Workflow.
  Historical graphs are read-only and restores always create a new current version.
  The owning route resets its editor from the returned workflow after restoration.
  Spec: docs/specs/workflows-v1/spec.yml
-->

<script lang="ts">
  import type { Snippet } from 'svelte';
  import { text } from '../../i18n/translations';
  import WorkflowGraphRenderer from './WorkflowGraphRenderer.svelte';
  import {
    workflowWorkspaceStore,
    type WorkflowDetail,
    type WorkflowGraph,
    type WorkflowVersionSummary,
  } from '../../stores/workflowWorkspaceStore';

  let {
    workflow,
    disabled = false,
    onRequestNavigation,
    onRestored,
    children,
  }: {
    workflow: WorkflowDetail;
    children: Snippet;
    disabled?: boolean;
    onRequestNavigation: (action: () => void | Promise<void>) => void;
    onRestored: (workflow: WorkflowDetail) => void | Promise<void>;
  } = $props();

  let versions = $state<WorkflowVersionSummary[]>([]);
  let currentVersionId = $state<string | null>(null);
  let selectedVersionId = $state<string | null>(null);
  let inspectedGraph = $state<WorkflowGraph | null>(null);
  let expanded = $state(false);
  let loading = $state(true);
  let inspecting = $state(false);
  let restoring = $state(false);
  let restoreConfirmationVersionId = $state<string | null>(null);
  let errorMessage = $state<string | null>(null);
  let restoredMessage = $state<string | null>(null);
  let inspectionRequest = 0;

  let selectedVersion = $derived(versions.find((version) => version.version_id === selectedVersionId) ?? null);
  let canRestoreSelected = $derived(!!selectedVersion && !selectedVersion.current && !disabled && !restoring);

  $effect(() => {
    const workflowId = workflow.id;
    if (workflow.version > 1) void loadHistory(workflowId, workflow.graph);
    else { versions = []; loading = false; inspectedGraph = null; selectedVersionId = null; }
  });

  async function loadHistory(workflowId: string, currentGraph: WorkflowGraph) {
    loading = true;
    errorMessage = null;
    try {
      const history = await workflowWorkspaceStore.getWorkflowVersions(workflowId);
      if (workflow.id !== workflowId) return;
      versions = history.versions;
      currentVersionId = history.current_version_id;

      selectedVersionId = history.current_version_id;
      inspectedGraph = currentGraph;
      restoreConfirmationVersionId = null;
    } catch (error) {
      if (workflow.id !== workflowId) return;
      console.error('[WorkflowVersions] Failed to load history', error);
      errorMessage = $text('workflows.version_history.load_failed');
    } finally {
      if (workflow.id === workflowId) loading = false;
    }
  }

  async function inspectVersion(version: WorkflowVersionSummary) {
    const request = ++inspectionRequest;
    selectedVersionId = version.version_id;
    inspectedGraph = version.version_id === currentVersionId ? workflow.graph : null;
    restoreConfirmationVersionId = null;
    errorMessage = null;
    restoredMessage = null;
    if (version.version_id === currentVersionId) {
      inspectedGraph = workflow.graph;
      return;
    }

    inspecting = true;
    try {
      const detail = await workflowWorkspaceStore.getWorkflowVersion(workflow.id, version.version_id);
      if (request === inspectionRequest && selectedVersionId === version.version_id) inspectedGraph = detail.graph;
    } catch (error) {
      if (selectedVersionId === version.version_id) {
        inspectedGraph = null;
        console.error('[WorkflowVersions] Failed to inspect version', error);
        errorMessage = $text('workflows.version_history.inspect_failed');
      }
    } finally {
      if (request === inspectionRequest) inspecting = false;
    }
  }

  function requestVersionInspection(version: WorkflowVersionSummary): void {
    onRequestNavigation(() => inspectVersion(version));
  }

  function requestRestore() {
    if (!selectedVersion || !canRestoreSelected) return;
    restoreConfirmationVersionId = selectedVersion.version_id;
  }

  async function restoreSelectedVersion() {
    if (!selectedVersion || restoreConfirmationVersionId !== selectedVersion.version_id || !canRestoreSelected) return;
    const versionId = selectedVersion.version_id;
    const versionNumber = selectedVersion.version_number;
    restoring = true;
    errorMessage = null;
    restoredMessage = null;
    try {
      const restoredWorkflow = await workflowWorkspaceStore.restoreWorkflowVersion(workflow.id, versionId);
      await onRestored(restoredWorkflow);
      restoredMessage = $text('workflows.version_history.restore_success', { values: { version: versionNumber } });
      await loadHistory(workflow.id, restoredWorkflow.graph);
    } catch (error) {
      console.error('[WorkflowVersions] Failed to restore version', error);
      errorMessage = $text('workflows.version_history.restore_failed');
    } finally {
      restoring = false;
    }
  }

  function formatVersionDate(timestamp: number): string {
    return new Date(timestamp * 1000).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function ignoreGraphChange(_graph: WorkflowGraph): void {}
</script>

{#if workflow.version > 1}
<section class="version-history" data-testid="workflow-version-history" aria-label={$text('workflows.version_history.title')}>
  <button type="button" class="version-selector" data-testid="workflow-version-selector" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
    <span>{$text('workflows.version_history.version', { values: { version: selectedVersion?.version_number ?? workflow.version } })}:</span>
    <span>{formatVersionDate(selectedVersion?.created_at ?? workflow.updated_at)}</span>
    <span aria-hidden="true">{expanded ? '⌃' : '⌄'}</span>
  </button>
  {#if expanded}
    {#if loading}<p data-testid="workflow-version-history-loading">{$text('workflows.version_history.loading')}</p>{/if}
    <div class="version-list" data-testid="workflow-version-timeline" aria-label={$text('workflows.version_history.title')}>
      {#each versions as version (version.version_id)}
        <button type="button" class:selected={selectedVersionId === version.version_id} class:current={version.current}
          aria-pressed={selectedVersionId === version.version_id} data-testid="workflow-version-row" data-current={version.current ? 'true' : 'false'}
          data-version-number={version.version_number} disabled={restoring} onclick={() => requestVersionInspection(version)}>
          <span class="version-label">{$text('workflows.version_history.version', { values: { version: version.version_number } })}</span>
          <span>{formatVersionDate(version.created_at)}</span>
          {#if version.current}<span class="current-marker">{$text('workflows.version_history.current')}</span>{/if}
        </button>
      {/each}
    </div>
  {/if}
    {#if canRestoreSelected}
      {#if restoreConfirmationVersionId === selectedVersion?.version_id}
        <div class="restore-confirmation" data-testid="workflow-version-restore-confirmation">
          <p>{$text('workflows.version_history.restore_explanation')}</p>
          <button type="button" data-testid="workflow-version-restore-confirm" disabled={restoring} onclick={() => void restoreSelectedVersion()}>
            {restoring ? $text('workflows.version_history.restoring') : $text('workflows.version_history.confirm_restore')}
          </button>
          <button type="button" class="secondary" disabled={restoring} onclick={() => (restoreConfirmationVersionId = null)}>{$text('common.cancel')}</button>
        </div>
      {:else}
        <button type="button" class="restore-action" data-testid="workflow-version-restore" onclick={requestRestore}>
          {$text('workflows.version_history.restore_as_new', { values: { version: selectedVersion?.version_number ?? 0 } })}
        </button>
      {/if}
    {/if}

  {#if restoredMessage}
    <p class="success-message" role="status" data-testid="workflow-version-restored">{restoredMessage}</p>
  {/if}
  {#if errorMessage}
    <p class="error-message" role="alert" data-testid="workflow-version-error">{errorMessage}</p>
  {/if}
</section>
{/if}

{#if inspecting || (selectedVersion && !selectedVersion.current)}
    <section class="graph-inspection" data-testid="workflow-version-graph-inspection" data-read-only="true" aria-live="polite">
      {#if inspecting}
        <p data-testid="workflow-version-inspection-loading">{$text('workflows.version_history.inspecting')}</p>
      {:else if selectedVersion && !selectedVersion.current && inspectedGraph}
        <div class="inspection-heading">
          <h3>{$text('workflows.version_history.inspecting_version', { values: { version: selectedVersion.version_number } })}</h3>
          <span>{inspectedGraph.nodes.length} {$text('workflows.version_history.nodes')}</span>
        </div>
        <div class="inspection-node-count" data-testid="workflow-version-inspection-nodes" aria-hidden="true">
          {#each inspectedGraph.nodes as node (node.id)}
            <span data-testid="workflow-version-inspection-node">{node.title ?? node.type}</span>
          {/each}
        </div>
        <WorkflowGraphRenderer graph={inspectedGraph} readOnly testId="workflow-version-graph" onChange={ignoreGraphChange} onSave={null} />
      {/if}
    </section>


{:else}
  {@render children()}
{/if}

<style>
  .version-history { display:grid; gap:var(--spacing-3); margin:0 auto var(--spacing-6); width:100%; font-size:var(--font-size-p); }
  .version-selector { justify-self:center; display:flex; align-items:center; gap:var(--spacing-2); border:0; border-radius:var(--radius-full); padding:var(--spacing-2) var(--spacing-4); color:var(--color-font-secondary); background:var(--color-grey-10); font:inherit; font-weight:700; cursor:pointer; }
  .version-list { position:relative; display:flex; justify-content:safe center; gap:var(--spacing-4); overflow-x:auto; padding:var(--spacing-3) var(--spacing-4) var(--spacing-6); scrollbar-width:thin; background:var(--color-grey-10); }
  .version-list::after { content:''; position:absolute; bottom:0; left:0; right:0; height:1rem; background:repeating-linear-gradient(to right,transparent 0,transparent 7px,var(--color-grey-30) 7px,var(--color-grey-30) 8px); pointer-events:none; }
  .version-list button { flex:0 0 7rem; display:grid; gap:var(--spacing-1); position:relative; padding:var(--spacing-2); border:0; background:transparent; color:var(--color-font-secondary); font:inherit; font-size:var(--font-size-small); text-align:center; cursor:pointer; }
  .version-list button::after { content:''; position:absolute; bottom:-1.3rem; left:50%; height:1.1rem; width:2px; background:var(--color-font-secondary); z-index:1; }
  .version-list button.selected,.current-marker { color:var(--color-primary); } .version-list button.selected::after { background:var(--color-primary); }
  .version-label { font-weight:700; } p,h3 { margin:0; } h3 { font-size:var(--font-size-p); }
  .graph-inspection { display:grid; gap:var(--spacing-4); } .inspection-heading { display:flex; justify-content:center; gap:var(--spacing-4); color:var(--color-font-secondary); font-size:var(--font-size-small); }
  .inspection-node-count { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
  .restore-action,.restore-confirmation button { justify-self:center; width:fit-content; border:0; border-radius:var(--radius-full); padding:var(--spacing-3) var(--spacing-5); background:var(--color-button-primary); color:var(--color-font-button); font:inherit; cursor:pointer; }
  .restore-confirmation { display:flex; justify-content:center; flex-wrap:wrap; gap:var(--spacing-3); font-size:var(--font-size-p); } .restore-confirmation p { flex-basis:100%; text-align:center; } .restore-confirmation .secondary { background:var(--color-grey-20); color:var(--color-font-primary); }
  .error-message { color:var(--color-error); } .success-message { color:var(--color-primary); }
  button:focus-visible { outline:2px solid var(--color-primary); outline-offset:2px; } button:disabled { opacity:.5; cursor:default; }
</style>
