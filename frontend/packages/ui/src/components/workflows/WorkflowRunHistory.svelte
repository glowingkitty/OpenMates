<!--
  WorkflowRunHistory.svelte
  Displays persisted workflow runs without owning workflow fetch or mutation state.
  The routed web workspace supplies the selected workflow's cached run list.
  Node statuses remain visible even when run content has expired.
-->

<script lang="ts">
  import type { WorkflowRun } from '../../stores/workflowWorkspaceStore';

  let {
    runs,
    editorHref,
  }: {
    runs: WorkflowRun[];
    editorHref: string;
  } = $props();

  function formatStatus(status: string): string {
    return status.replaceAll('_', ' ');
  }

  function formatStartedAt(timestampSeconds?: number | null): string {
    if (!timestampSeconds) return 'Started time unavailable';
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(timestampSeconds * 1000));
  }
</script>

<section class="workflow-run-history" data-testid="workflow-runs">
  <header class="run-history-header">
    <div>
      <p>Workflow runs</p>
      <h2 data-testid="workflow-run-history-title">Run history</h2>
    </div>
    <a href={editorHref} data-testid="workflow-runs-back-to-editor">Back to editor</a>
  </header>

  {#if runs.length === 0}
    <p class="empty-copy" data-testid="workflow-runs-empty">No workflow runs yet.</p>
  {:else}
    <ol class="run-list">
      {#each runs as run (run.id)}
        <li class="run-card" data-testid="workflow-run-row" data-run-status={run.status}>
          <div class="run-summary">
            <div>
              <strong>{formatStatus(run.status)}</strong>
              <span>{run.trigger_type} · {formatStartedAt(run.started_at)}</span>
            </div>
            <span class="run-content-status">
              {run.content_available === false ? 'Run content unavailable' : `${run.content_storage ?? 'unknown'} content`}
            </span>
          </div>

          <div class="node-statuses" data-testid="workflow-run-node-statuses">
            <h3>Node status</h3>
            {#if run.node_runs?.length}
              <ul>
                {#each run.node_runs as nodeRun (nodeRun.node_id)}
                  <li data-testid="workflow-run-node-status" data-node-id={nodeRun.node_id} data-node-status={nodeRun.status}>
                    <span>{nodeRun.node_id}</span>
                    <strong>{formatStatus(nodeRun.status)}</strong>
                  </li>
                {/each}
              </ul>
            {:else}
              <p>No node statuses were recorded for this run.</p>
            {/if}
          </div>
        </li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  .workflow-run-history {
    display: grid;
    gap: var(--spacing-6);
    padding: var(--spacing-8);
  }

  .run-history-header,
  .run-summary,
  .node-statuses li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-5);
  }

  .run-history-header p,
  .run-history-header h2,
  .run-summary strong,
  .run-summary span,
  .node-statuses h3,
  .node-statuses p,
  .node-statuses ul {
    margin: 0;
  }

  .run-history-header p,
  .run-summary span,
  .run-content-status,
  .node-statuses p {
    color: var(--color-font-secondary);
  }

  .run-history-header p {
    font-size: var(--font-size-small);
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .run-history-header a {
    border-radius: var(--radius-8);
    padding: var(--spacing-4) var(--spacing-6);
    color: var(--color-font-button);
    background: var(--color-button-primary);
    font-weight: 800;
    text-decoration: none;
  }

  .run-list,
  .node-statuses ul {
    display: grid;
    gap: var(--spacing-4);
    padding: 0;
    list-style: none;
  }

  .run-card {
    display: grid;
    gap: var(--spacing-5);
    padding: var(--spacing-6);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-10);
    background: var(--color-grey-0);
  }

  .run-summary > div,
  .node-statuses {
    display: grid;
    gap: var(--spacing-2);
  }

  .run-summary strong,
  .node-statuses li strong {
    text-transform: capitalize;
  }

  .run-content-status {
    text-align: end;
  }

  .node-statuses {
    padding-block-start: var(--spacing-5);
    border-block-start: 1px solid var(--color-grey-20);
  }

  .node-statuses li {
    padding: var(--spacing-3) var(--spacing-4);
    border-radius: var(--radius-8);
    background: var(--color-grey-10);
  }

  .empty-copy {
    margin: 0;
    color: var(--color-font-secondary);
  }

  @media (max-width: 560px) {
    .run-history-header,
    .run-summary {
      align-items: flex-start;
      flex-direction: column;
    }

    .run-content-status {
      text-align: start;
    }
  }
</style>
