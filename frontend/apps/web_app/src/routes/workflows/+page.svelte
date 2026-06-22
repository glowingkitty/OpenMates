<!--
  Workflows route for the authenticated web app.
  Provides the V1 server-backed workflow list, Shortcuts-style detail/editor
  shell, example workflow creation, manual runs, and run history.

  Native Swift counterparts: none yet; Apple V1 parity currently covers the
  shared workflow API models and request contract.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { Header, Settings, Notification, authStore, initialize, notificationStore, panelState, featureAvailabilityStore, initializeFeatureAvailability } from '@repo/ui';
  import { getApiEndpoint } from '@repo/ui/config/api';

  type WorkflowNodeType = 'schedule_trigger' | 'manual_trigger' | 'app_skill_action' | 'decision' | 'repeat' | 'create_chat_report' | 'send_notification' | 'send_email_notification' | 'end';

  type WorkflowGraph = {
    version: number;
    trigger_node_id: string;
    nodes: Array<{ id: string; type: WorkflowNodeType; title?: string; config?: Record<string, unknown> }>;
    edges: Array<{ from: string; to: string; branch?: string }>;
    limits?: Record<string, unknown>;
  };

  type WorkflowSummary = {
    id: string;
    title: string;
    status: string;
    enabled: boolean;
    trigger_summary?: string | null;
    last_run_status?: string | null;
    run_content_retention?: 'last_5' | 'none';
    current_version_id: string;
  };

  type WorkflowDetail = WorkflowSummary & { graph: WorkflowGraph };
  type WorkflowRun = {
    id: string;
    status: string;
    trigger_type: string;
    started_at?: number | null;
    content_retention_mode?: 'last_5' | 'none';
    content_available?: boolean;
    content_storage?: 'durable' | 'ephemeral' | 'deleted' | null;
    content_expires_at?: number | null;
    node_runs?: Array<{ node_id: string; status: string; output_summary?: Record<string, unknown> }>;
  };

  type WorkflowRequestInit = {
    method?: string;
    body?: string;
  };

  let workflows = $state<WorkflowSummary[]>([]);
  let selectedWorkflow = $state<WorkflowDetail | null>(null);
  let runs = $state<WorkflowRun[]>([]);
  let loading = $state(true);
  let saving = $state(false);
  let running = $state(false);
  let error = $state<string | null>(null);
  let runContentRetention = $state<'last_5' | 'none'>('last_5');
  let selectedRunContentRetention = $state<'last_5' | 'none'>('last_5');

  let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
  let workflowsEnabled = $derived($featureAvailabilityStore.disabledById?.['platform:workflows'] !== true && $featureAvailabilityStore.disabledById !== null);

  onMount(() => {
    void initializeWorkflowsRoute();
  });

  async function initializeWorkflowsRoute() {
    try {
      await initialize();
      await initializeFeatureAvailability();
      if ($authStore.isAuthenticated && $featureAvailabilityStore.disabledById?.['platform:workflows'] !== true) {
        await loadWorkflows();
      }
    } catch (routeError) {
      console.error('[WorkflowsRoute] Failed to initialize:', routeError);
      error = routeError instanceof Error ? routeError.message : 'Failed to load workflows.';
    } finally {
      loading = false;
    }
  }

  async function workflowRequest<T>(path: string, init: WorkflowRequestInit = {}): Promise<T> {
    const headers = new Headers();
    headers.set('Accept', 'application/json');
    headers.set('Content-Type', 'application/json');
    const response = await fetch(getApiEndpoint(path), {
      ...init,
      credentials: 'include',
      headers
    });
    if (!response.ok) {
      throw new Error(`Workflow request failed with HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  }

  async function loadWorkflows() {
    error = null;
    const data = await workflowRequest<{ workflows: WorkflowSummary[] }>('/v1/workflows');
    workflows = data.workflows;
    if (workflows.length > 0) {
      await selectWorkflow(workflows[0].id);
    } else {
      selectedWorkflow = null;
      runs = [];
    }
  }

  async function selectWorkflow(workflowId: string) {
    error = null;
    const [workflowData, runsData] = await Promise.all([
      workflowRequest<{ workflow: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}`),
      workflowRequest<{ runs: WorkflowRun[] }>(`/v1/workflows/${encodeURIComponent(workflowId)}/runs`)
    ]);
    selectedWorkflow = workflowData.workflow;
    selectedRunContentRetention = workflowData.workflow.run_content_retention ?? 'last_5';
    runs = runsData.runs;
  }

  async function createRainWorkflow() {
    await createWorkflow('Daily rain alert', rainAlertGraph(), true);
  }

  async function createNewsWorkflow() {
    await createWorkflow('Twice-weekly AI news brief', newsBriefGraph(), true);
  }

  async function createWorkflow(title: string, graph: WorkflowGraph, enabled: boolean) {
    saving = true;
    error = null;
    try {
      const data = await workflowRequest<{ workflow: WorkflowDetail }>('/v1/workflows', {
        method: 'POST',
        body: JSON.stringify({ title, graph, enabled, run_content_retention: runContentRetention })
      });
      workflows = [data.workflow, ...workflows];
      await selectWorkflow(data.workflow.id);
    } catch (createError) {
      error = createError instanceof Error ? createError.message : 'Failed to create workflow.';
    } finally {
      saving = false;
    }
  }

  async function setSelectedWorkflowEnabled(enabled: boolean) {
    if (!selectedWorkflow) return;
    saving = true;
    error = null;
    try {
      const action = enabled ? 'enable' : 'disable';
      const data = await workflowRequest<{ workflow: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(selectedWorkflow.id)}/${action}`, {
        method: 'POST',
        body: JSON.stringify({})
      });
      selectedWorkflow = data.workflow;
      workflows = workflows.map((workflow) => workflow.id === data.workflow.id ? data.workflow : workflow);
    } catch (saveError) {
      error = saveError instanceof Error ? saveError.message : 'Failed to update workflow.';
    } finally {
      saving = false;
    }
  }

  async function updateSelectedWorkflowRetention() {
    if (!selectedWorkflow) return;
    saving = true;
    error = null;
    try {
      const data = await workflowRequest<{ workflow: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(selectedWorkflow.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ run_content_retention: selectedRunContentRetention })
      });
      selectedWorkflow = data.workflow;
      workflows = workflows.map((workflow) => workflow.id === data.workflow.id ? data.workflow : workflow);
    } catch (saveError) {
      error = saveError instanceof Error ? saveError.message : 'Failed to update workflow retention.';
    } finally {
      saving = false;
    }
  }

  async function deleteSelectedWorkflow() {
    if (!selectedWorkflow) return;
    saving = true;
    error = null;
    try {
      const workflowId = selectedWorkflow.id;
      await workflowRequest<{ deleted: boolean }>(`/v1/workflows/${encodeURIComponent(workflowId)}`, {
        method: 'DELETE'
      });
      workflows = workflows.filter((workflow) => workflow.id !== workflowId);
      if (workflows.length > 0) {
        await selectWorkflow(workflows[0].id);
      } else {
        selectedWorkflow = null;
        runs = [];
      }
    } catch (deleteError) {
      error = deleteError instanceof Error ? deleteError.message : 'Failed to delete workflow.';
    } finally {
      saving = false;
    }
  }

  async function runSelectedWorkflow() {
    if (!selectedWorkflow) return;
    running = true;
    error = null;
    try {
      const data = await workflowRequest<{ run: WorkflowRun }>(`/v1/workflows/${encodeURIComponent(selectedWorkflow.id)}/run`, {
        method: 'POST',
        body: JSON.stringify({ mode: 'test', input: {} })
      });
      runs = [data.run, ...runs];
      workflows = workflows.map((workflow) => workflow.id === selectedWorkflow?.id ? { ...workflow, last_run_status: data.run.status } : workflow);
    } catch (runError) {
      error = runError instanceof Error ? runError.message : 'Failed to run workflow.';
    } finally {
      running = false;
    }
  }

  function rainAlertGraph(): WorkflowGraph {
    return {
      version: 1,
      trigger_node_id: 'trigger',
      nodes: [
        { id: 'trigger', type: 'schedule_trigger', title: 'Every morning', config: { schedule: { type: 'daily', time: '07:00', timezone: 'Europe/Berlin' } } },
        { id: 'weather', type: 'app_skill_action', title: 'Check weather', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin', days: 1 } } },
        { id: 'decision', type: 'decision', title: 'Decision: rain likely?', config: { predicate: { left: '$nodes.weather.output.rain_probability', op: 'gte', right: 60 } } },
        { id: 'notify', type: 'send_notification', title: 'Push reminder', config: { title: 'Rain today', body: 'Take an umbrella.' } },
        { id: 'email', type: 'send_email_notification', title: 'Email reminder', config: { title: 'Rain today', body: 'Take an umbrella.' } },
        { id: 'end', type: 'end', title: 'Done', config: {} }
      ],
      edges: [
        { from: 'trigger', to: 'weather' },
        { from: 'weather', to: 'decision' },
        { from: 'decision', to: 'notify', branch: 'yes' },
        { from: 'notify', to: 'email' },
        { from: 'email', to: 'end' }
      ]
    };
  }

  function newsBriefGraph(): WorkflowGraph {
    return {
      version: 1,
      trigger_node_id: 'trigger',
      nodes: [
        { id: 'trigger', type: 'schedule_trigger', title: 'Monday and Thursday', config: { schedule: { type: 'weekly', weekdays: ['monday', 'thursday'], time: '09:00' } } },
        { id: 'news', type: 'app_skill_action', title: 'Search AI news', config: { app_id: 'news', skill_id: 'search', input: { requests: [{ query: 'OpenAI news' }, { query: 'Anthropic news' }, { query: 'Google Gemini news' }] } } },
        { id: 'report', type: 'create_chat_report', title: 'Create brief', config: { summary: 'AI news brief report' } },
        { id: 'notify', type: 'send_notification', title: 'Push alert', config: { title: 'AI news brief', body: 'Your AI news brief is ready.' } },
        { id: 'email', type: 'send_email_notification', title: 'Email alert', config: { title: 'AI news brief', body: 'Your AI news brief is ready.' } },
        { id: 'end', type: 'end', title: 'Done', config: {} }
      ],
      edges: [
        { from: 'trigger', to: 'news' },
        { from: 'news', to: 'report' },
        { from: 'report', to: 'notify' },
        { from: 'notify', to: 'email' },
        { from: 'email', to: 'end' }
      ]
    };
  }
</script>

{#if !$authStore.isInitialized || !featureAvailabilityLoaded || loading}
  <main class="workflows-route-state" data-testid="workflows-auth-loading">Loading workflows...</main>
{:else if !workflowsEnabled}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="workflows-route-state" data-testid="workflows-feature-disabled">
    <h1>Workflows unavailable</h1>
    <p>Workflows are disabled on this server.</p>
  </main>
{:else if $authStore.isAuthenticated}
  <div class="main-content" class:menu-closed={!$panelState.isActivityHistoryOpen}>
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="workflows-container" class:menu-open={$panelState.isSettingsOpen}>
      <main class="workflows-board" data-testid="workflows-page">
        <aside class="workflow-list" data-testid="workflows-list">
          <div class="section-heading">
            <p>Automations</p>
            <h1>Workflows</h1>
          </div>
            <div class="create-actions">
              <label class="retention-picker" for="workflow-retention">
                <span>Run content retention</span>
                <select id="workflow-retention" data-testid="workflow-retention-select" bind:value={runContentRetention}>
                  <option value="last_5">Keep latest 5 encrypted runs</option>
                  <option value="none">No durable run content</option>
                </select>
              </label>
              <button type="button" data-testid="create-rain-workflow" onclick={createRainWorkflow} disabled={saving}>Daily rain alert</button>
              <button type="button" data-testid="create-news-workflow" onclick={createNewsWorkflow} disabled={saving}>AI news brief</button>
          </div>
          {#if workflows.length === 0}
            <p class="empty-copy">Create one of the starter workflows to test the server-side runner.</p>
          {:else}
            {#each workflows as workflow (workflow.id)}
              <button
                type="button"
                class="workflow-row"
                class:active={selectedWorkflow?.id === workflow.id}
                data-testid="workflow-row"
                onclick={() => selectWorkflow(workflow.id)}
              >
                <strong>{workflow.title}</strong>
                <span>{workflow.enabled ? 'Enabled' : 'Disabled'} - {workflow.trigger_summary ?? 'Manual'} - {workflow.run_content_retention ?? 'last_5'}</span>
              </button>
            {/each}
          {/if}
        </aside>

        <section class="workflow-detail" data-testid="workflow-detail">
          {#if error}
            <div class="error-banner" data-testid="workflows-error">{error}</div>
          {/if}

          {#if selectedWorkflow}
            <div class="detail-header">
              <div>
                <p>{selectedWorkflow.status}</p>
                <h2>{selectedWorkflow.title}</h2>
                <span class="retention-chip" data-testid="selected-workflow-retention">Run content: {selectedWorkflow.run_content_retention ?? 'last_5'}</span>
              </div>
              <div class="detail-actions">
                <label class="inline-retention" for="selected-workflow-retention-select">
                  <span>Edit retention</span>
                  <select id="selected-workflow-retention-select" data-testid="selected-workflow-retention-select" bind:value={selectedRunContentRetention}>
                    <option value="last_5">Keep latest 5</option>
                    <option value="none">No durable content</option>
                  </select>
                </label>
                <button type="button" data-testid="save-workflow-retention" onclick={updateSelectedWorkflowRetention} disabled={saving}>Save</button>
                <button type="button" data-testid="toggle-workflow" onclick={() => setSelectedWorkflowEnabled(!selectedWorkflow?.enabled)} disabled={saving}>
                  {selectedWorkflow.enabled ? 'Disable' : 'Enable'}
                </button>
                <button type="button" data-testid="run-workflow" onclick={runSelectedWorkflow} disabled={running}>{running ? 'Running...' : 'Run test'}</button>
                <button type="button" data-testid="delete-workflow" onclick={deleteSelectedWorkflow} disabled={saving}>Delete</button>
              </div>
            </div>

            <div class="node-stack" data-testid="workflow-node-stack">
              {#each selectedWorkflow.graph.nodes as node, index (node.id)}
                <article class="node-card" data-node-type={node.type}>
                  <span class="step-number">{index + 1}</span>
                  <div>
                    <h3>{node.title ?? node.type}</h3>
                    <p>{node.type.replaceAll('_', ' ')}</p>
                  </div>
                </article>
              {/each}
            </div>

            <div class="runs-panel" data-testid="workflow-runs">
              <h3>Run history</h3>
              {#if runs.length === 0}
                <p class="empty-copy">No runs yet. Use "Run test" to execute this workflow on the server.</p>
              {:else}
                {#each runs as run (run.id)}
                  <div class="run-row" data-testid="workflow-run-row">
                    <strong>{run.status}</strong>
                    <span>{run.trigger_type} - {run.node_runs?.length ?? 0} nodes - {run.content_available === false ? 'content unavailable' : `${run.content_storage ?? 'unknown'} ${run.content_retention_mode ?? 'last_5'}`}</span>
                  </div>
                {/each}
              {/if}
            </div>
          {:else}
            <div class="empty-detail">
              <h2>Build your first workflow</h2>
              <p>Choose a starter workflow to create a durable server-side automation.</p>
            </div>
          {/if}
        </section>
      </main>
      <div class="settings-wrapper">
        <Settings isLoggedIn={$authStore.isAuthenticated} />
      </div>
    </div>
  </div>
{:else}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="workflows-route-state" data-testid="workflows-auth-required">
    <h1>Workflows</h1>
    <p>Please log in to create, manage, and run server-side workflows.</p>
  </main>
{/if}

<div class="notification-container">
  {#each $notificationStore.notifications as notification (notification.id)}
    <Notification {notification} />
  {/each}
</div>

<style>
  .workflows-route-state {
    min-height: calc(100vh - 90px);
    display: grid;
    place-content: center;
    gap: var(--spacing-8, 16px);
    padding: var(--spacing-20, 40px);
    text-align: center;
    color: var(--color-font-primary);
  }

  .main-content {
    position: fixed;
    inset-inline-start: var(--sidebar-margin, 10px);
    inset-inline-end: 0;
    top: 0;
    bottom: 0;
    background: var(--color-grey-0);
    z-index: 10;
  }

  .workflows-container {
    display: flex;
    height: calc(100vh - 82px);
    height: calc(100dvh - 82px);
    gap: 0;
    padding: 10px 20px 10px 10px;
  }

  @media (min-width: 1100px) {
    .workflows-container.menu-open {
      gap: 20px;
    }
  }

  .workflows-board {
    flex: 1;
    min-width: 0;
    display: grid;
    grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
    gap: 16px;
    color: var(--color-font-primary);
  }

  .workflow-list,
  .workflow-detail {
    min-width: 0;
    overflow: auto;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-16, 32px);
    background: var(--color-grey-0);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.08);
  }

  .workflow-list {
    padding: 18px;
  }

  .section-heading p,
  .detail-header p {
    margin: 0 0 4px;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.75rem;
  }

  .section-heading h1,
  .detail-header h2,
  .empty-detail h2 {
    margin: 0;
  }

  .create-actions {
    display: grid;
    gap: 8px;
    margin: 18px 0;
  }

  .retention-picker {
    display: grid;
    gap: 6px;
    color: var(--color-font-secondary);
    font-size: 0.9rem;
  }

  .retention-picker select {
    width: 100%;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-8, 20px);
    padding: 10px 12px;
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    font: inherit;
  }

  .retention-chip {
    display: inline-flex;
    margin-block-start: 8px;
    padding: 5px 9px;
    border-radius: var(--radius-full, 999px);
    color: var(--color-font-primary);
    background: var(--color-grey-10);
    font-size: 0.85rem;
  }

  button {
    border: 0;
    border-radius: var(--radius-8, 20px);
    padding: 10px 14px;
    cursor: pointer;
    font: inherit;
  }

  button:disabled {
    opacity: 0.6;
    cursor: wait;
  }

  .create-actions button,
  .detail-actions button[data-testid="run-workflow"] {
    color: var(--color-font-button);
    background: var(--color-button-primary);
  }

  .workflow-row {
    width: 100%;
    display: grid;
    gap: 4px;
    margin-block-end: 8px;
    text-align: start;
    color: var(--color-font-primary);
    background: var(--color-grey-10);
  }

  .workflow-row.active {
    outline: 2px solid var(--color-button-primary);
    background: var(--color-grey-blue);
  }

  .workflow-row span,
  .empty-copy,
  .node-card p,
  .run-row span {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: 0.9rem;
  }

  .workflow-detail {
    padding: 22px;
  }

  .detail-header {
    display: flex;
    gap: 16px;
    align-items: flex-start;
    justify-content: space-between;
    margin-block-end: 18px;
  }

  .detail-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: flex-end;
  }

  .inline-retention {
    display: grid;
    gap: 4px;
    color: var(--color-font-secondary);
    font-size: 0.85rem;
  }

  .inline-retention select {
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-8, 20px);
    padding: 9px 10px;
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    font: inherit;
  }

  .detail-actions button:not([data-testid="run-workflow"]) {
    color: var(--color-font-primary);
    background: var(--color-grey-20);
  }

  .node-stack {
    display: grid;
    gap: 10px;
    max-width: 620px;
  }

  .node-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-12, 24px);
    background: var(--color-grey-10);
  }

  .step-number {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    color: var(--color-font-button);
    background: var(--color-button-primary);
    font-weight: 700;
    flex: 0 0 auto;
  }

  .node-card h3 {
    margin: 0 0 2px;
    font-size: 1rem;
  }

  .runs-panel {
    margin-block-start: 22px;
    padding-block-start: 18px;
    border-block-start: 1px solid var(--color-grey-20);
  }

  .run-row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 0;
    border-block-end: 1px solid var(--color-grey-10);
  }

  .error-banner {
    margin-block-end: 14px;
    padding: 10px 12px;
    border-radius: var(--radius-8, 20px);
    color: var(--color-error, #b00020);
    background: color-mix(in srgb, var(--color-error, #b00020) 10%, transparent);
  }

  .empty-detail {
    min-height: 100%;
    display: grid;
    place-content: center;
    text-align: center;
    gap: 8px;
  }

  .settings-wrapper {
    display: flex;
    align-items: flex-start;
    min-width: fit-content;
  }

  .notification-container {
    position: fixed;
    top: 0;
    inset-inline-start: 0;
    inset-inline-end: 0;
    z-index: 10000;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 20px;
    gap: 10px;
  }

  .notification-container :global(.notification) {
    pointer-events: auto;
  }

  @media (max-width: 760px) {
    .workflows-container {
      height: calc(100vh - 75px);
      height: calc(100dvh - 75px);
      padding-inline-end: 10px;
    }

    .workflows-board {
      grid-template-columns: 1fr;
    }

    .workflow-list,
    .workflow-detail {
      border-radius: var(--radius-10, 24px);
    }

    .detail-header {
      display: grid;
    }
  }
</style>
