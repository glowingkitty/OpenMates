<!--
  WorkflowRunHistory.svelte
  Presents upcoming and persisted runs on one horizontally reachable timeline.
  Selected executions load their pinned definition and retained node detail.
  Expired content and cancellation remain explicit owner-scoped API states.
-->

<script lang="ts">
  import { untrack } from 'svelte';
  import { text } from '../../i18n/translations';
  import { record } from './workflowBuilder';
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
  let deleting = $state(false);
  let statusOverrides = $state<Record<string, string>>({});

  const RUN_POLL_INTERVAL_MS = 2_000;
  const MAX_RUN_POLL_ATTEMPTS = 60;
  const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'skipped']);

  const selectedRun = $derived(runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null);
  const selectedStatus = $derived(selectedRunDetail?.status ?? (selectedRun ? statusOverrides[selectedRun.id] ?? selectedRun.status : ''));
  const canCancel = $derived(['queued', 'running', 'waiting'].includes(selectedStatus));
  const Clock = getLucideIcon('clock');
  const Trash = getLucideIcon('trash-2');
  const Back = getLucideIcon('chevron-left');
  const tr = (key: string) => $text(`workflows.runs.${key}`);
  const nextRunAt = $derived(workflow.enabled && workflow.next_run_at && workflow.next_run_at > Date.now() / 1000 ? workflow.next_run_at : null);
  const timelineRuns = $derived([...runs].sort((left, right) => (right.started_at ?? 0) - (left.started_at ?? 0)));
  const selectedDeliveryPending = $derived(selectedRunDetail ? hasPendingDelivery(selectedRunDetail) : false);
  const timezone = $derived(String(record(workflow.graph.nodes.find(node => node.type === 'schedule_trigger')?.config?.schedule).timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone));
  function hasPendingDelivery(run: WorkflowRunDetail): boolean {
    return Object.values(record(run.output_summary?.deliveries)).some(value => ['delivery_pending', 'claimed'].includes(String(record(value).status)));
  }
  function statusIcon(status: string) {
    return getLucideIcon(status === 'completed' ? 'circle-check' : status === 'failed' ? 'triangle-alert' : status === 'cancelled' ? 'circle-x' : 'clock');
  }

  const selectedRunKey = $derived(`${workflow.id}/${selectedRun?.id ?? ''}`);
  $effect(() => {
    const [workflowId, runId] = selectedRunKey.split('/');
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
      if (disposed || !detail || (TERMINAL_RUN_STATUSES.has(detail.status) && !hasPendingDelivery(detail)) || attempts >= MAX_RUN_POLL_ATTEMPTS) return;
      timeoutId = setTimeout(() => void refreshRun(), Math.min(RUN_POLL_INTERVAL_MS + attempts * 500, 8000));
    }

    untrack(() => void refreshRun());
    return () => {
      disposed = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  });

  async function deleteRun(): Promise<void> {
    if (!selectedRun || !window.confirm($text('workflows.builder.delete_run_confirm'))) return;
    deleting = true;
    try {
      const status = await workflowWorkspaceStore.deleteWorkflowRun(workflow.id, selectedRun.id);
      if (status === 'deletion_pending') errorMessage = $text('workflows.builder.deletion_pending');
      else { selectedRunDetail = null; selectedGraph = null; const next = runs.find(run => run.id !== selectedRun?.id); if (next) onSelectRun(next.id); }
    } catch (error) { console.error('[WorkflowRunHistory] Delete failed', error); errorMessage = tr('delete_failed'); }
    finally { deleting = false; }
  }

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
        console.error('[WorkflowRunHistory] Loading failed', error);
        errorMessage = tr('load_failed');
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
      console.error('[WorkflowRunHistory] Cancellation failed', error);
      errorMessage = tr('cancel_failed');
    } finally {
      cancelling = false;
    }
  }

  function formatStatus(status: string): string {
    const key = ['completed','failed','cancelled','skipped','queued','running','waiting','cancellation_requested'].includes(status) ? status : 'unavailable';
    return tr(`status_${key}`);
  }

  function formatDay(timestampSeconds?: number | null): string {
    if (!timestampSeconds) return tr('time_unavailable');
    const date = new Date(timestampSeconds * 1000);
    const calendar = new Intl.DateTimeFormat('en-CA', { year:'numeric', month:'2-digit', day:'2-digit', timeZone:timezone });
    for (const offset of [0, -1, 1]) {
      if (calendar.format(date) === calendar.format(new Date(Date.now() + offset * 86400000))) {
        const relative = new Intl.RelativeTimeFormat(undefined, { numeric:'auto' }).format(offset,'day');
        return relative.charAt(0).toUpperCase() + relative.slice(1);
      }
    }
    return new Intl.DateTimeFormat(undefined, { month:'short', day:'numeric', timeZone:timezone }).format(date);
  }
  function formatTime(timestampSeconds?: number | null): string {
    return timestampSeconds ? new Intl.DateTimeFormat(undefined, { hour:'numeric', minute:'2-digit', hour12:false, timeZone:timezone }).format(new Date(timestampSeconds * 1000)) : '';
  }
  function formatTimestamp(timestampSeconds?: number | null): string { return `${formatDay(timestampSeconds)}${timestampSeconds ? ', ' + formatTime(timestampSeconds) : ''}`; }

  function ignoreGraphChange(_graph: WorkflowGraph): void {}
</script>

<div id="tabpanel-runs" class="runs-panel" data-testid="workflow-runs" role="tabpanel" aria-label={tr('history')}>
  <h2 class="sr-only" data-testid="workflow-run-history-title">{tr('history')}</h2>
  <div class="run-toolbar">
    <a class="context-action editor-link" href={editorHref} aria-label={tr('back_to_workflow')} title={tr('back_to_workflow')} data-testid="workflow-runs-back-to-editor" onclick={event => { event.preventDefault(); onOpenEditor(); }}><Back size={18}/></a>
    {#if selectedRun}
      <label class="run-selector" data-testid="workflow-run-selector"><span>{tr('run')}:</span><select aria-label={tr('select_run')} value={selectedRun.id} onchange={event => onSelectRun(event.currentTarget.value)}>{#each timelineRuns as run (run.id)}<option value={run.id}>{formatTimestamp(run.started_at)}</option>{/each}</select></label>
    {:else if nextRunAt}<span class="run-selector" data-testid="workflow-run-selector">{tr('run')}: {formatTimestamp(nextRunAt)}</span>{/if}
    <div class="run-actions">
      {#if canCancel}<button type="button" class="context-action cancel-action" data-testid="workflow-run-cancel" onclick={() => cancelConfirmationOpen = true}>{tr('cancel')}</button>{/if}
      {#if selectedRun}<button type="button" class="context-action" data-testid="workflow-delete-run" aria-label={$text('workflows.builder.delete_run')} title={$text('workflows.builder.delete_run')} disabled={deleting || !TERMINAL_RUN_STATUSES.has(selectedStatus)} onclick={() => void deleteRun()}><Trash size={17}/></button>{/if}
    </div>
  </div>

  {#if nextRunAt || runs.length > 0}
    <div class="run-timeline" data-testid="workflow-run-timeline" aria-label={tr('timeline')}>
      <div class="timeline-track">
        {#if nextRunAt}
          <div class="run-marker next" data-testid="workflow-next-run-marker">
            <span class="status-pill next-status"><Clock size={12}/><strong>{tr('next')}</strong></span><span class="marker-date">{formatDay(nextRunAt)}</span><span class="marker-time">{formatTime(nextRunAt)}</span>
          </div>
        {/if}
        {#each timelineRuns as run (run.id)}
          {@const status = statusOverrides[run.id] ?? run.status}
          {@const pending = selectedRun?.id === run.id && selectedDeliveryPending}
          {@const Icon = statusIcon(pending ? 'waiting' : status)}
          <button type="button" class="run-marker" class:selected={selectedRun?.id === run.id} data-testid="workflow-run-marker" data-run-id={run.id} data-run-status={status} aria-pressed={selectedRun?.id === run.id} aria-label={`${formatTimestamp(run.started_at)}: ${pending ? tr('delivery_pending') : formatStatus(status)}`} onclick={() => onSelectRun(run.id)}>
            <span class="status-pill" class:complete={status === 'completed' && !pending} class:failed={status === 'failed'}><Icon size={status === 'completed' && !pending ? 18 : 13}/><strong class:sr-only={status === 'completed' && !pending}>{formatStatus(pending ? 'waiting' : status)}</strong></span>
            <span class="marker-date">{formatDay(run.started_at)}</span><span class="marker-time">{formatTime(run.started_at)}</span>
          </button>
        {/each}
      </div>
    </div>
  {:else}<p class="empty-copy" data-testid="workflow-runs-empty">{tr('empty')}</p>{/if}

  {#if loading}<p class="loading" data-testid="workflow-run-loading">{tr('loading')}</p>
  {:else if selectedRun && selectedRunDetail}
    <section class="run-detail" data-testid="workflow-run-detail">
      {#if selectedDeliveryPending}<p class="delivery-status" role="status"><Clock size={14}/>{tr('delivery_pending')}</p>{/if}
      {#if selectedRunDetail.content_available === false}<p class="unavailable" data-testid="workflow-run-content-unavailable">{tr('content_unavailable')}</p>{/if}
      {#if selectedGraph}<WorkflowGraphRenderer graph={selectedGraph} readOnly nodeRuns={selectedRunDetail.node_runs ?? []} testId="workflow-run-graph" onChange={ignoreGraphChange} onSave={null}/>{/if}
      {#if selectedRunDetail.error_summary}<p class="run-error" role="alert">{tr('execution_failed')}</p>{/if}
    </section>
  {/if}

  {#if cancelConfirmationOpen}
    <div class="confirmation-backdrop" role="presentation"><div class="cancel-confirmation" data-testid="workflow-run-cancel-confirmation" role="dialog" aria-modal="true" aria-label={tr('cancel_title')} use:focusTrap={{ onEscape: () => cancelConfirmationOpen = false }}>
      <h3>{tr('cancel_title')}</h3><p>{tr('cancel_explanation')}</p>
      <div><button type="button" onclick={() => cancelConfirmationOpen = false}>{tr('keep_running')}</button><button type="button" class="danger" data-testid="workflow-run-cancel-confirm" disabled={cancelling} onclick={() => void cancelSelectedRun()}>{tr(cancelling ? 'cancelling' : 'cancel')}</button></div>
    </div></div>
  {/if}
  {#if errorMessage}<p class="run-error" role="alert" data-testid="workflow-run-error">{errorMessage}</p>{/if}
</div>

<style>
  .runs-panel { position:relative; display:grid; font-size:var(--font-size-p); gap:0; width:min(960px,calc(100% - 4rem)); margin:0 auto 2rem; padding:2.3rem 0 2rem; box-sizing:border-box; border-radius:.75rem; color:var(--color-font-primary); background:var(--color-grey-0); }
  .run-toolbar { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; min-height:2rem; padding:0 1rem .3rem; gap:.35rem; }
  .run-selector { grid-column:2; display:flex; align-items:center; justify-content:center; gap:.4rem; font-size:var(--font-size-p); font-weight:650; color:var(--color-font-secondary); white-space:nowrap; }
  .run-selector select { max-width:14rem; width:auto; padding:.2rem .4rem; min-height:1.5rem; border:0; border-radius:.6rem; font:inherit; color:inherit; background:var(--color-grey-10); cursor:pointer; }
  .context-action { display:inline-flex; align-items:center; justify-content:center; gap:.3rem; width:auto; min-width:1.8rem; min-height:1.8rem; padding:.2rem; border:0; border-radius:50%; background:transparent; color:var(--color-font-secondary); font:inherit; font-size:var(--font-size-p); text-decoration:none; cursor:pointer; box-shadow:none; }
  .context-action:hover { color:var(--color-primary); background:var(--color-grey-10); } .context-action:disabled { opacity:.4; cursor:default; }
  .editor-link { justify-self:start; } .run-actions { grid-column:3; display:flex; justify-content:flex-end; gap:.25rem; } .cancel-action { border-radius:.6rem; padding-inline:.4rem; }
  .run-timeline { overflow-x:auto; overflow-y:hidden; scrollbar-width:thin; background:var(--color-grey-10); }
  .timeline-track { position:relative; display:flex; justify-content:center; width:max-content; min-width:100%; padding:0 .8rem 0; box-sizing:border-box; }
  .timeline-track::after { content:''; position:absolute; inset:auto .8rem .9rem; height:.65rem; background:repeating-linear-gradient(to right,var(--color-grey-40) 0 1px,transparent 1px 8px); opacity:.5; pointer-events:none; }
  .run-marker { position:relative; flex:0 0 7rem; min-height:6.25rem; display:flex; flex-direction:column; align-items:center; justify-content:flex-start; gap:.12rem; padding:.45rem .25rem 1.7rem; border:0; border-radius:0; color:var(--color-font-secondary); background:transparent; box-shadow:none; font:inherit; font-size:var(--font-size-small); line-height:1.15; cursor:pointer; }
  .run-marker::after { content:''; position:absolute; bottom:.5rem; height:1.55rem; width:1px; background:var(--color-font-primary); z-index:1; }
  .run-marker.selected { color:var(--color-primary); } .run-marker.selected::after { background:var(--color-primary); width:2px; }
  .run-marker.next { cursor:default; } .marker-date,.marker-time { font-weight:650; }
  .status-pill { max-width:100%; line-height:1.2; display:inline-flex; align-items:center; justify-content:center; gap:.2rem; min-height:1.5rem; box-sizing:border-box; border-radius:1rem; padding:.08rem .38rem; color:var(--color-font-secondary); font-size:var(--font-size-small); }
  .status-pill strong { min-width:0; overflow-wrap:anywhere; }
  .status-pill.complete { padding:0; color:var(--color-success); } .status-pill.failed { background:var(--color-error); color:var(--color-font-button); } .next-status { background:var(--color-primary); color:var(--color-font-button); }
  .run-detail { min-width:0; display:grid; gap:.5rem; padding-top:1rem; }
  .run-detail :global([data-testid='workflow-run-graph']) { width:100%; max-width:none; margin:0; padding-bottom:1rem; }
  .run-detail :global(.graph-canvas) { background:transparent; border-radius:0; padding-top:.25rem; }
  .delivery-status { display:flex; align-items:center; justify-content:center; gap:.35rem; margin:.25rem 1rem; color:var(--color-font-secondary); font-size:var(--font-size-small); }
  .unavailable,.run-error { margin:.5rem 1.25rem; padding:.6rem; border-radius:.5rem; color:var(--color-font-secondary); font-size:var(--font-size-p); text-align:center; }
  .run-error { color:var(--color-error); }
  .empty-copy,.loading { margin:2rem 1rem; color:var(--color-font-secondary); text-align:center; font-size:var(--font-size-p); }
  .confirmation-backdrop { position:fixed; inset:0; display:grid; place-items:center; padding:1rem; background:#0005; z-index:var(--z-index-modal,1000); }
  .cancel-confirmation { display:grid; gap:1rem; width:min(24rem,100%); box-sizing:border-box; padding:1.5rem; border-radius:1rem; color:var(--color-font-primary); background:var(--color-grey-0); box-shadow:var(--shadow-lg); }
  .cancel-confirmation h3,.cancel-confirmation p { margin:0; } .cancel-confirmation p { font-size:var(--font-size-small); color:var(--color-font-secondary); }
  .cancel-confirmation div { display:flex; justify-content:flex-end; gap:.75rem; }
  .cancel-confirmation button { border:0; border-radius:1rem; padding:.6rem .8rem; background:var(--color-grey-20); color:var(--color-font-primary); font:inherit; font-size:var(--font-size-small); cursor:pointer; }
  .cancel-confirmation .danger { background:var(--color-error); color:var(--color-font-button); }
  .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
  button:focus-visible,a:focus-visible,select:focus-visible { outline:2px solid var(--color-primary); outline-offset:2px; }
  @media(max-width:730px) { .runs-panel { width:calc(100% - 1rem); } .run-toolbar { padding-inline:.5rem; } .run-selector select { max-width:10rem; } .run-marker { flex-basis:6rem; } .timeline-track { justify-content:flex-start; } }
</style>
