<!--
  WorkflowRunTaskDetail.svelte
  Read-only Tasks-owned detail for one exact Workflow run projection.
  The parent keeps the Kanban board mounted while this surface is open.
  Live run and node statuses poll only until a terminal state or retry cap.
-->

<script lang="ts">
  import WorkflowGraphRenderer from '../workflows/WorkflowGraphRenderer.svelte';
  import {
    workflowWorkspaceStore,
    type WorkflowDetail,
    type WorkflowGraph,
    type WorkflowRunDetail,
  } from '../../stores/workflowWorkspaceStore';
  import type { WorkflowRunTaskProjectionViewModel } from '../../services/userTaskService';

  let {
    projection,
    presentation,
    onClose,
  }: {
    projection: WorkflowRunTaskProjectionViewModel;
    presentation: 'split' | 'overlay';
    onClose: () => void;
  } = $props();

  let workflow = $state<WorkflowDetail | null>(null);
  let executedGraph = $state<WorkflowGraph | null>(null);
  let run = $state<WorkflowRunDetail | null>(null);
  let loading = $state(true);
  let errorMessage = $state<string | null>(null);

  const POLL_INTERVAL_MS = 1_000;
  const MAX_POLL_ATTEMPTS = 90;
  const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled']);
  const live = $derived(run ? !TERMINAL_RUN_STATUSES.has(run.status) : true);

  $effect(() => {
    const workflowId = projection.workflowId;
    const runId = projection.workflowRunId;
    let disposed = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let loadedWorkflow: WorkflowDetail | null = null;

    if (!runId) {
      loading = false;
      errorMessage = 'This projection does not reference a Workflow run.';
      return;
    }

    async function refresh(): Promise<void> {
      try {
        if (!loadedWorkflow) {
          loadedWorkflow = await workflowWorkspaceStore.selectWorkflow(workflowId);
          workflow = loadedWorkflow;
        }
        const detail = await workflowWorkspaceStore.getWorkflowRun(workflowId, runId);
        if (disposed || projection.workflowId !== workflowId || projection.workflowRunId !== runId) return;
        run = detail;
        if (!executedGraph && loadedWorkflow) {
          executedGraph = detail.version_id === loadedWorkflow.current_version_id
            ? loadedWorkflow.graph
            : (await workflowWorkspaceStore.getWorkflowVersion(workflowId, detail.version_id)).graph;
        }
        errorMessage = null;
        attempts += 1;
        if (!TERMINAL_RUN_STATUSES.has(detail.status) && attempts < MAX_POLL_ATTEMPTS) {
          timeoutId = setTimeout(() => void refresh(), POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (!disposed) errorMessage = error instanceof Error ? error.message : 'Failed to load Workflow run detail.';
      } finally {
        if (!disposed) loading = false;
      }
    }

    workflow = null;
    executedGraph = null;
    run = null;
    loading = true;
    errorMessage = null;
    void refresh();

    return () => {
      disposed = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  });

  function formatStatus(status: string): string {
    return status.replaceAll('_', ' ');
  }

  function ignoreGraphChange(_graph: WorkflowGraph): void {}
</script>

<aside
  class="workflow-run-task-detail"
  class:overlay={presentation === 'overlay'}
  data-testid="workflow-run-projection-detail"
  data-presentation={presentation}
  aria-label="Workflow run task detail"
>
  <header>
    <div>
      <span>Workflow run</span>
      <h2>{projection.title}</h2>
    </div>
    <button type="button" data-testid="task-detail-close" aria-label="Close Workflow run detail" onclick={onClose}>Close</button>
  </header>

  <section class="run-identity">
    <span>Exact run ID</span>
    <code data-testid="workflow-run-detail-id">{projection.workflowRunId}</code>
    <strong
      data-testid="workflow-run-detail-live-status"
      data-live={live ? 'true' : 'false'}
      data-status={run?.status ?? 'queued'}
    >{formatStatus(run?.status ?? 'queued')}</strong>
  </section>

  {#if loading}
    <p class="state-copy">Loading live execution...</p>
  {:else if errorMessage}
    <p class="error-copy" role="alert">{errorMessage}</p>
  {:else if run}
    <section class="node-statuses" aria-label="Workflow node statuses">
      <h3>Live node status</h3>
      {#each run.node_runs ?? [] as nodeRun (nodeRun.id)}
        <div data-testid="workflow-run-detail-node-status" data-status={nodeRun.status}>
          <span>{nodeRun.node_id}</span><strong>{formatStatus(nodeRun.status)}</strong>
        </div>
      {:else}
        <div data-testid="workflow-run-detail-node-status" data-status={run.status}>
          <span>Definition queued</span><strong>{formatStatus(run.status)}</strong>
        </div>
      {/each}
    </section>

    {#if workflow && executedGraph}
      <WorkflowGraphRenderer
        graph={executedGraph}
        readOnly
        nodeRuns={run.node_runs ?? []}
        testId="workflow-run-task-graph"
        onChange={ignoreGraphChange}
      />
    {/if}
  {/if}
</aside>

<style>
  .workflow-run-task-detail { box-sizing: border-box; display: grid; align-content: start; gap: var(--spacing-6); min-width: 0; max-height: 100%; overflow: auto; padding: var(--spacing-7); border: 1px solid var(--color-grey-20); border-radius: var(--radius-12); color: var(--color-font-primary); background: var(--color-grey-0); box-shadow: var(--shadow-xl); }
  .workflow-run-task-detail.overlay { position: fixed; z-index: var(--z-index-modal, 1000); inset: 0; max-height: none; border: 0; border-radius: 0; padding: var(--spacing-6); }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--spacing-4); }
  header span, .run-identity span { color: var(--color-font-secondary); font-size: var(--font-size-xs); font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
  header h2, .node-statuses h3, .state-copy, .error-copy { margin: 0; }
  header button { border: 0; border-radius: var(--radius-full); padding: var(--spacing-3) var(--spacing-5); color: var(--color-font-primary); background: var(--color-grey-20); font: inherit; font-weight: 800; cursor: pointer; }
  .run-identity { display: grid; gap: var(--spacing-2); padding: var(--spacing-5); border-radius: var(--radius-8); background: var(--color-grey-10); }
  .run-identity code { overflow-wrap: anywhere; color: var(--color-font-primary); }
  .run-identity strong { width: fit-content; text-transform: capitalize; }
  .run-identity strong[data-status='completed'] { color: var(--color-success); }
  .run-identity strong[data-status='failed'], .error-copy { color: var(--color-danger); }
  .node-statuses { display: grid; gap: var(--spacing-3); }
  .node-statuses > div { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-4); padding: var(--spacing-4); border-radius: var(--radius-6); background: var(--color-grey-10); }
  .node-statuses span { overflow-wrap: anywhere; }
  .node-statuses strong { text-transform: capitalize; }
</style>
