<!--
  WorkflowVersionHistory.svelte
  Renders the capped immutable definition history for one Workflow.
  Historical graphs are read-only and restores always create a new current version.
  The owning route resets its editor from the returned workflow after restoration.
  Spec: docs/specs/workflows-v1/spec.yml
-->

<script lang="ts">
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
  }: {
    workflow: WorkflowDetail;
    disabled?: boolean;
    onRequestNavigation: (action: () => void | Promise<void>) => void;
    onRestored: (workflow: WorkflowDetail) => void | Promise<void>;
  } = $props();

  let versions = $state<WorkflowVersionSummary[]>([]);
  let currentVersionId = $state<string | null>(null);
  let selectedVersionId = $state<string | null>(null);
  let inspectedGraph = $state<WorkflowGraph | null>(null);
  let maxVersions = $state<number | null>(null);
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
    void loadHistory(workflowId, workflow.graph);
  });

  async function loadHistory(workflowId: string, currentGraph: WorkflowGraph) {
    loading = true;
    errorMessage = null;
    try {
      const history = await workflowWorkspaceStore.getWorkflowVersions(workflowId);
      if (workflow.id !== workflowId) return;
      versions = history.versions;
      currentVersionId = history.current_version_id;
      maxVersions = history.retention.max_versions;
      selectedVersionId = history.current_version_id;
      inspectedGraph = currentGraph;
      restoreConfirmationVersionId = null;
    } catch (error) {
      if (workflow.id !== workflowId) return;
      errorMessage = error instanceof Error ? error.message : $text('workflows.version_history.load_failed');
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
        errorMessage = error instanceof Error ? error.message : $text('workflows.version_history.inspect_failed');
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
      errorMessage = error instanceof Error ? error.message : $text('workflows.version_history.restore_failed');
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

<section class="version-history" data-testid="workflow-version-history" aria-label={$text('workflows.version_history.title')}>
  <div class="history-heading">
    <div>
      <h2>{$text('workflows.version_history.title')}</h2>
      <p data-testid="workflow-version-history-retention">
        {maxVersions
          ? $text('workflows.version_history.retention', { values: { max: maxVersions } })
          : $text('workflows.version_history.retention_loading')}
      </p>
    </div>
  </div>

  {#if loading}
    <p data-testid="workflow-version-history-loading">{$text('workflows.version_history.loading')}</p>
  {:else if versions.length === 0}
    <p data-testid="workflow-version-history-empty">{$text('workflows.version_history.empty')}</p>
  {:else}
    <div class="version-selector" data-testid="workflow-version-selector" aria-label="Selected Workflow version">
      {selectedVersion ? formatVersionDate(selectedVersion.created_at) : $text('workflows.version_history.title')}
      <span aria-hidden="true">⌄</span>
    </div>
    <div class="version-list" role="list" data-testid="workflow-version-timeline">
      {#each versions as version (version.version_id)}
        <button
          type="button"
          class:selected={selectedVersionId === version.version_id}
          class:current={version.current}
          data-testid="workflow-version-row"
          data-current={version.current ? 'true' : 'false'}
          data-version-number={version.version_number}
          disabled={restoring}
          onclick={() => requestVersionInspection(version)}
        >
          <span class="version-label">{$text('workflows.version_history.version', { values: { version: version.version_number } })}</span>
          <span>{formatVersionDate(version.created_at)}</span>
          {#if version.current}<span class="current-marker">Active</span>{/if}
          {#if version.restored_from_version_id}<span>{$text('workflows.version_history.restored')}</span>{/if}
        </button>
      {/each}
    </div>

    <section class="graph-inspection" data-testid="workflow-version-graph-inspection" data-read-only="true" aria-live="polite">
      {#if inspecting}
        <p data-testid="workflow-version-inspection-loading">{$text('workflows.version_history.inspecting')}</p>
      {:else if selectedVersion && inspectedGraph}
        <div class="inspection-heading">
          <h3>{$text('workflows.version_history.inspecting_version', { values: { version: selectedVersion.version_number } })}</h3>
          <span>{inspectedGraph.nodes.length} {$text('workflows.version_history.nodes')}</span>
        </div>
        <div class="inspection-node-count" data-testid="workflow-version-inspection-nodes" aria-hidden="true">
          {#each inspectedGraph.nodes as node (node.id)}
            <span data-testid="workflow-version-inspection-node">{node.title ?? node.type}</span>
          {/each}
        </div>
        <WorkflowGraphRenderer graph={inspectedGraph} readOnly testId="workflow-version-graph" onChange={ignoreGraphChange} />
      {/if}
    </section>

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
  {/if}

  {#if restoredMessage}
    <p class="success-message" role="status" data-testid="workflow-version-restored">{restoredMessage}</p>
  {/if}
  {#if errorMessage}
    <p class="error-message" role="alert" data-testid="workflow-version-error">{errorMessage}</p>
  {/if}
</section>

<style>
  .version-history {
    display: grid;
    gap: var(--spacing-5);
    margin-block: var(--spacing-8);
    padding: var(--spacing-6);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-8);
    background: var(--color-grey-0);
  }

  .history-heading,
  .inspection-heading,
  .version-list button,
  .restore-confirmation {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-4);
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 { font-size: var(--font-size-h4); }
  h3 { font-size: var(--font-size-p); }

  .history-heading p,
  .inspection-heading span,
  .version-list button span:not(.version-label),
  .restore-confirmation p {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .version-list {
    position: relative;
    display: flex;
    gap: var(--spacing-4);
    overflow-x: auto;
    padding: var(--spacing-6) var(--spacing-2) var(--spacing-3);
    scrollbar-width: thin;
  }

  .version-list::before { content: ''; position: absolute; inset: 31px var(--spacing-5) auto; height: 2px; background: var(--color-grey-30); }

  .version-list button {
    position: relative;
    z-index: 1;
    flex: 0 0 190px;
    border: 1px solid transparent;
    border-radius: var(--radius-4);
    padding: var(--spacing-4);
    color: var(--color-font-primary);
    background: var(--color-grey-10);
    text-align: left;
    cursor: pointer;
  }

  .version-list button:hover,
  .version-list button.selected {
    border-color: var(--color-button-primary);
    background: color-mix(in srgb, var(--color-button-primary) 8%, var(--color-grey-0));
  }

  .version-label { font-weight: 800; }
  .current-marker { color: var(--color-button-primary) !important; font-weight: 700; }

  .version-selector {
    justify-self: center;
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    border: 0;
    border-radius: var(--radius-full);
    padding: var(--spacing-3) var(--spacing-5);
    color: var(--color-font-primary);
    background: var(--color-grey-20);
    font: inherit;
    font-weight: 700;
  }

  .graph-inspection,
  .restore-confirmation {
    display: grid;
    gap: var(--spacing-4);
    padding: var(--spacing-4);
    border-radius: var(--radius-4);
    background: var(--color-grey-10);
  }

  .inspection-node-count { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }

  .restore-action,
  .restore-confirmation button {
    width: fit-content;
    border: 0;
    border-radius: var(--radius-4);
    padding: var(--spacing-4) var(--spacing-5);
    color: var(--color-font-button);
    background: var(--color-button-primary);
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }

  .restore-confirmation .secondary {
    color: var(--color-font-primary);
    background: var(--color-grey-20);
  }

  .error-message { color: var(--color-danger); }
  .success-message { color: var(--color-success, #067647); }

  @media (max-width: 600px) {
    .version-list button,
    .restore-confirmation { align-items: flex-start; flex-direction: column; }
  }
</style>
