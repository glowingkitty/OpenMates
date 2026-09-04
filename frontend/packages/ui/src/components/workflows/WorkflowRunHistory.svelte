<!--
  WorkflowRunHistory.svelte
  Presents upcoming and persisted runs on one horizontally reachable timeline.
  Selected executions load their pinned definition and retained node detail.
  Expired content and cancellation remain explicit owner-scoped API states.
-->

<script lang="ts">
  import WorkflowGraphRenderer from './WorkflowGraphRenderer.svelte';
  import { focusTrap } from '../../actions/focusTrap';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import {
    workflowWorkspaceStore,
    type WorkflowDetail,
    type WorkflowGraph,
    type WorkflowRun,
    type WorkflowRunDetail,
  } from '../../stores/workflowWorkspaceStore';

  let {
    workflow,
    runs,
    selectedRunId = null,
    onSelectRun,
    editorHref,
    onOpenEditor,
  }: {
    workflow: WorkflowDetail;
    runs: WorkflowRun[];
    selectedRunId?: string | null;
    onSelectRun: (runId: string) => void;
    editorHref: string;
    onOpenEditor: () => void;
  } = $props();

  let selectedRunDetail = $state<WorkflowRunDetail | null>(null);
  let selectedGraph = $state<WorkflowGraph | null>(null);
  let loading = $state(false);
  let errorMessage = $state<string | null>(null);
  let cancelConfirmationOpen = $state(false);
  let cancelling = $state(false);
  let statusOverrides = $state<Record<string, string>>({});

  const RUN_POLL_INTERVAL_MS = 2_000;
  const MAX_RUN_POLL_ATTEMPTS = 60;
  const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'skipped']);

  const selectedRun = $derived(runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null);
  const selectedStatus = $derived(selectedRunDetail?.status ?? (selectedRun ? statusOverrides[selectedRun.id] ?? selectedRun.status : ''));
  const canCancel = $derived(['queued', 'running', 'waiting'].includes(selectedStatus));
  const StatusIcon = getLucideIcon('activity');

  $effect(() => {
    const workflowId = workflow.id;
    const runId = selectedRun?.id;
    if (!runId) {
      selectedRunDetail = null;
      selectedGraph = null;
      return;
    }
    let disposed = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;

    async function refreshRun(): Promise<void> {
      const detail = await loadRun(workflowId, runId, attempts > 0);
      attempts += 1;
      if (disposed || !detail || TERMINAL_RUN_STATUSES.has(detail.status) || attempts >= MAX_RUN_POLL_ATTEMPTS) return;
      timeoutId = setTimeout(() => void refreshRun(), RUN_POLL_INTERVAL_MS);
    }

    void refreshRun();
    return () => {
      disposed = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  });

  async function loadRun(workflowId: string, runId: string, preserveExisting = false): Promise<WorkflowRunDetail | null> {
    if (!preserveExisting) loading = true;
    errorMessage = null;
    cancelConfirmationOpen = false;
    if (!preserveExisting) {
      selectedRunDetail = null;
      selectedGraph = null;
    }
    try {
      const detail = await workflowWorkspaceStore.getWorkflowRun(workflowId, runId);
      if (workflow.id !== workflowId || selectedRun?.id !== runId) return null;
      selectedRunDetail = detail;
      statusOverrides = { ...statusOverrides, [runId]: detail.status };
      if (!selectedGraph && detail.version_id === workflow.current_version_id) {
        selectedGraph = workflow.graph;
      } else if (!selectedGraph) {
        const version = await workflowWorkspaceStore.getWorkflowVersion(workflowId, detail.version_id);
        if (workflow.id !== workflowId || selectedRun?.id !== runId) return null;
        selectedGraph = version.graph;
      }
      return detail;
    } catch (error) {
      if (workflow.id === workflowId && selectedRun?.id === runId) {
        errorMessage = error instanceof Error ? error.message : 'Failed to load this Workflow run.';
      }
      return null;
    } finally {
      if (!preserveExisting && workflow.id === workflowId && selectedRun?.id === runId) loading = false;
    }
  }

  async function cancelSelectedRun(): Promise<void> {
    if (!selectedRun || !canCancel || cancelling) return;
    const workflowId = workflow.id;
    const runId = selectedRun.id;
    cancelling = true;
    errorMessage = null;
    try {
      const status = await workflowWorkspaceStore.cancelWorkflowRun(workflowId, runId);
      if (workflow.id !== workflowId || selectedRun?.id !== runId) return;
      statusOverrides = { ...statusOverrides, [runId]: status };
      if (selectedRunDetail?.id === runId) selectedRunDetail = { ...selectedRunDetail, status };
      cancelConfirmationOpen = false;
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : 'Failed to cancel this Workflow run.';
    } finally {
      cancelling = false;
    }
  }

  function formatStatus(status: string): string {
    return status.replaceAll('_', ' ');
  }

  function formatTimestamp(timestampSeconds?: number | null): string {
    if (!timestampSeconds) return 'Time unavailable';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(timestampSeconds * 1000));
  }

  function ignoreGraphChange(_graph: WorkflowGraph): void {}
</script>

<div id="tabpanel-runs" class="runs-panel" data-testid="workflow-runs" role="tabpanel" aria-label="Workflow runs">
  <header>
    <div><p>Workflow runs</p><h2 data-testid="workflow-run-history-title">Execution history</h2></div>
    <a href={editorHref} data-testid="workflow-runs-back-to-editor" onclick={(event) => { event.preventDefault(); onOpenEditor(); }}>Back to Template</a>
  </header>

  {#if workflow.next_run_at || runs.length > 0}
    <div class="run-selector" data-testid="workflow-run-selector" aria-label="Selected Workflow run">
      {selectedRun ? formatTimestamp(selectedRun.started_at) : formatTimestamp(workflow.next_run_at)}
      <span aria-hidden="true">⌄</span>
    </div>
    <div class="run-timeline" data-testid="workflow-run-timeline" aria-label="Workflow run timeline">
      {#if workflow.next_run_at}
        <article class="run-marker next" data-testid="workflow-next-run-marker">
          <StatusIcon size={18} /><strong>Next</strong><span>{formatTimestamp(workflow.next_run_at)}</span>
        </article>
      {/if}
      {#each runs as run (run.id)}
        {@const status = statusOverrides[run.id] ?? run.status}
        <button
          type="button"
          class="run-marker"
          class:selected={selectedRun?.id === run.id}
          data-testid="workflow-run-marker"
          data-run-id={run.id}
          data-run-status={status}
          onclick={() => onSelectRun(run.id)}
        >
          <StatusIcon size={18} /><strong>{formatStatus(status)}</strong><span>{formatTimestamp(run.started_at)}</span>
        </button>
      {/each}
    </div>
  {:else}
    <p class="empty-copy" data-testid="workflow-runs-empty">No Workflow runs yet.</p>
  {/if}

  {#if loading}
    <p class="loading" data-testid="workflow-run-loading">Loading execution detail...</p>
  {:else if selectedRun && selectedRunDetail}
    <section class="run-detail" data-testid="workflow-run-detail">
      <div class="run-detail-heading">
        <div><span>Executed definition</span><h3>{formatStatus(selectedRunDetail.status)}</h3></div>
        {#if canCancel}
          <button type="button" class="cancel-action" data-testid="workflow-run-cancel" onclick={() => (cancelConfirmationOpen = true)}>Cancel run</button>
        {/if}
      </div>

      {#if selectedRunDetail.content_available === false}
        <div class="unavailable" data-testid="workflow-run-content-unavailable">
          Retained input and output are no longer available. Execution and node statuses remain visible.
        </div>
      {/if}

      {#if selectedGraph}
        <WorkflowGraphRenderer
          graph={selectedGraph}
          readOnly
          nodeRuns={selectedRunDetail.node_runs ?? []}
          testId="workflow-run-graph"
          onChange={ignoreGraphChange}
        />
      {/if}

      {#if selectedRunDetail.error_summary}
        <p class="run-error" role="alert">{selectedRunDetail.error_summary}</p>
      {/if}
    </section>
  {/if}

  {#if cancelConfirmationOpen}
    <div class="cancel-confirmation" data-testid="workflow-run-cancel-confirmation" role="dialog" aria-modal="true" aria-label="Cancel Workflow run" use:focusTrap={{ onEscape: () => (cancelConfirmationOpen = false) }}>
      <h3>Cancel this run?</h3>
      <p>The current execution will stop at the next safe boundary.</p>
      <div>
        <button type="button" onclick={() => (cancelConfirmationOpen = false)}>Keep running</button>
        <button type="button" class="danger" data-testid="workflow-run-cancel-confirm" disabled={cancelling} onclick={() => void cancelSelectedRun()}>{cancelling ? 'Cancelling...' : 'Cancel run'}</button>
      </div>
    </div>
  {/if}

  {#if errorMessage}<p class="run-error" role="alert" data-testid="workflow-run-error">{errorMessage}</p>{/if}
</div>

<style>
  .runs-panel { display: grid; gap: var(--spacing-6); margin: var(--spacing-8); padding: var(--spacing-8); border-radius: var(--radius-12); background: var(--color-grey-10); }
  header { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-5); text-align: start; }
  header p, header h2, .run-detail-heading h3, .run-detail-heading span, .cancel-confirmation h3, .cancel-confirmation p { margin: 0; }
  header p { color: var(--color-font-secondary); font-size: var(--font-size-xs); font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
  header a { border-radius: var(--radius-full); padding: var(--spacing-3) var(--spacing-5); color: var(--color-font-button); background: var(--color-button-primary); font-weight: 800; text-decoration: none; }
  .run-selector { justify-self: center; display: flex; align-items: center; gap: var(--spacing-3); border: 0; border-radius: var(--radius-full); padding: var(--spacing-3) var(--spacing-5); color: var(--color-font-primary); background: var(--color-grey-20); font: inherit; font-weight: 700; }
  .run-timeline { position: relative; display: flex; gap: var(--spacing-4); overflow-x: auto; padding: var(--spacing-6) var(--spacing-2) var(--spacing-3); scrollbar-width: thin; }
  .run-timeline::before { content: ''; position: absolute; inset: 31px var(--spacing-5) auto; height: 2px; background: var(--color-grey-30); }
  .run-marker { position: relative; z-index: 1; box-sizing: border-box; display: grid; min-height: 96px; flex: 0 0 190px; align-content: center; justify-items: center; gap: var(--spacing-2); padding: var(--spacing-4); border: 1px solid transparent; border-radius: var(--radius-8); color: var(--color-font-primary); background: var(--color-grey-0); font: inherit; text-transform: capitalize; cursor: pointer; }
  .run-marker span { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .run-marker.selected { border-color: var(--color-button-primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-button-primary) 16%, transparent); }
  .run-marker.next { color: var(--color-button-primary); }
  .run-marker[data-run-status='completed'] strong { color: var(--color-success); }
  .run-marker[data-run-status='failed'] strong { color: var(--color-danger); }
  .run-detail { display: grid; gap: var(--spacing-5); border-radius: var(--radius-10); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .run-detail-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-5); padding: var(--spacing-6) var(--spacing-8) 0; }
  .run-detail-heading span { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .cancel-action, .cancel-confirmation button { border: 0; border-radius: var(--radius-full); padding: var(--spacing-3) var(--spacing-5); color: var(--color-font-primary); background: var(--color-grey-20); font: inherit; font-weight: 800; cursor: pointer; }
  .unavailable { margin-inline: var(--spacing-8); padding: var(--spacing-5); border-radius: var(--radius-6); color: var(--color-font-secondary); background: var(--color-grey-10); }
  .cancel-confirmation { display: grid; gap: var(--spacing-4); padding: var(--spacing-6); border-radius: var(--radius-8); color: var(--color-font-primary); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .cancel-confirmation div { display: flex; justify-content: flex-end; gap: var(--spacing-3); }
  .cancel-confirmation .danger { color: var(--color-grey-0); background: var(--color-danger); }
  .run-error { margin: 0; color: var(--color-danger); }
  .empty-copy, .loading { margin: 0; color: var(--color-font-secondary); text-align: center; }
  @media (max-width: 600px) { .runs-panel { margin: var(--spacing-4); padding: var(--spacing-5); } header, .run-detail-heading { align-items: flex-start; flex-direction: column; } .cancel-action { width: 100%; } .cancel-confirmation div { display: grid; grid-template-columns: 1fr; } }
</style>
