<!--
  Workflows route for the authenticated web app.
  Provides the V1 server-backed workflow list, Shortcuts-style detail/editor
  shell, example workflow creation, manual runs, and run history.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Workflows/WorkflowStore.swift
  - apple/OpenMates/Sources/Features/Workflows/WorkflowViews.swift
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { replaceState } from '$app/navigation';
  import { Header, Settings, NotificationStack, WorkspaceHomeShell, WorkflowDetailPage, WorkflowGraphRenderer, WorkflowTemplateShare, WorkflowSidebar, authStore, focusTrap, initialize, notificationStore, panelState, featureAvailabilityStore, initializeFeatureAvailability, upsertWorkflowTemplateProjection, workflowWorkspaceStore } from '@repo/ui';
  import WorkspacePromptComposer from '@repo/ui/components/workspace/WorkspacePromptComposer.svelte';
  import WorkflowRunHistory from '@repo/ui/components/workflows/WorkflowRunHistory.svelte';
  import WorkflowVersionHistory from '@repo/ui/components/workflows/WorkflowVersionHistory.svelte';
  import { userProfile } from '@repo/ui/stores/userProfile';
  import type { DailyInspiration, ImportedWorkflowTemplate, WorkflowDetail, WorkflowGraph, WorkflowRun, WorkflowSummary, WorkflowTemplateBindingRequirement } from '@repo/ui';

  type WorkflowContinueItem = {
    id: string;
    title: string;
    summary?: string | null;
    badge?: string | null;
    category?: string | null;
    appId?: string | null;
    icon?: string | null;
    source?: 'recent' | 'example';
  };

  type WorkflowTab = 'details' | 'runs';

  type WorkflowHashState = {
    workflowId: string | null;
    tab: WorkflowTab;
    runId: string | null;
  };

  const WORKFLOWS_ROUTE = '/workflows';
  const WORKFLOW_ID_HASH_PARAM = 'workflow-id';
  const WORKFLOW_TAB_HASH_PARAM = 'workflow-tab';
  const WORKFLOW_RUN_ID_HASH_PARAM = 'run-id';

  let workflows = $derived<WorkflowSummary[]>($workflowWorkspaceStore.workflows);
  let selectedWorkflow = $derived<WorkflowDetail | null>($workflowWorkspaceStore.selectedWorkflow);
  let runs = $derived<WorkflowRun[]>($workflowWorkspaceStore.runs);
  let saving = $state(false);
  let routeError = $state<string | null>(null);
  let error = $derived(routeError ?? $workflowWorkspaceStore.error);
  let runContentRetention = $state<'last_5' | 'none'>('last_5');
  let selectedRunContentRetention = $state<'last_5' | 'none'>('last_5');
  let editorTitle = $state('');
  let editorDescription = $state('');
  let editorGraph = $state<WorkflowGraph | null>(null);
  let editorDirty = $state(false);
  let hydratedEditorWorkflowId = $state<string | null>(null);
  let pendingNavigation = $state<{ action: () => void | Promise<void> } | null>(null);
  let showAllWorkflows = $state(false);
  let workflowInputText = $state('');
  let observedWorkflowGeneration = $state(workflowWorkspaceStore.getGeneration());
  let workflowHashState = $state<WorkflowHashState>({ workflowId: null, tab: 'details', runId: null });
  let blankCreatorOpen = $state(false);
  let blankWorkflowTitle = $state('');
  let lastStartedRunId = $state<string | null>(null);

  let recentWorkflows = $derived([...workflows].sort((left, right) => (right.updated_at ?? 0) - (left.updated_at ?? 0)).slice(0, 6));
  let workflowStarterItems: WorkflowContinueItem[] = [
    {
      id: 'starter-rain',
      title: 'Tell me if it will rain tomorrow',
      summary: 'Weather check plus notification',
      badge: 'Starter',
      category: 'weather',
      appId: 'weather',
      icon: 'cloud-rain',
      source: 'example',
    },
    {
      id: 'starter-news',
      title: 'Send me an AI news brief twice a week',
      summary: 'Research, summarize, and notify',
      badge: 'Starter',
      category: 'technology',
      appId: 'news',
      icon: 'newspaper',
      source: 'example',
    },
    {
      id: 'starter-blank',
      title: 'Start from a blank workflow',
      summary: 'Open the visual builder',
      badge: 'Blank',
      category: 'productivity',
      appId: 'workflows',
      icon: 'workflow',
      source: 'example',
    },
  ];
  let recentWorkflowContinueItems = $derived<WorkflowContinueItem[]>(recentWorkflows.map(workflowSummaryToContinueItem));
  let allWorkflowContinueItems = $derived<WorkflowContinueItem[]>([...workflows]
    .sort((left, right) => (right.updated_at ?? 0) - (left.updated_at ?? 0))
    .map(workflowSummaryToContinueItem));
  let workflowLandingItems = $derived<WorkflowContinueItem[]>([
    ...recentWorkflowContinueItems,
    ...workflowStarterItems,
  ]);
  let workflowGreetingName = $derived($userProfile.username?.trim() || 'there');
  let isManageView = $derived(!!workflowHashState.workflowId);
  let isRunsView = $derived(workflowHashState.tab === 'runs');
  let selectedRunId = $derived(workflowHashState.runId);
  let requestedWorkflowId = $derived(workflowHashState.workflowId);

  let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
  let routeReady = $derived($authStore.isInitialized && featureAvailabilityLoaded);
  let workflowsEnabled = $derived(!featureAvailabilityLoaded || ($featureAvailabilityStore.disabledById?.['platform:workflows'] !== true && $featureAvailabilityStore.disabledById !== null));
  let canLoadWorkflows = $derived(routeReady && $authStore.isAuthenticated && workflowsEnabled);
  let canRenderWorkflowData = $derived(routeReady && $authStore.isAuthenticated);
  let showManageView = $derived(canRenderWorkflowData && isManageView);
  let visibleWorkflowGreetingName = $derived(canRenderWorkflowData ? workflowGreetingName : 'there');
  let visibleWorkflowLandingItems = $derived(canRenderWorkflowData ? workflowLandingItems : []);
  let editorActivationReady = $derived(editorGraph ? workflowActivationReady(editorGraph) : false);

  onMount(() => {
    syncWorkflowHashFromLocation();
    window.addEventListener('hashchange', syncWorkflowHashFromLocation);
    void initializeWorkflowsRoute();

    return () => {
      window.removeEventListener('hashchange', syncWorkflowHashFromLocation);
    };
  });

  function stripHashPrefix(hash: string): string {
    if (!hash) return '';
    return hash.startsWith('#/') ? hash.slice(2) : hash.replace(/^#/, '');
  }

  function parseHashParams(hash: string): URLSearchParams {
    const fragment = stripHashPrefix(hash);
    if (!fragment || fragment === 'settings' || fragment.startsWith('settings/')) {
      return new URLSearchParams();
    }
    return new URLSearchParams(fragment);
  }

  function serializeHashParams(params: URLSearchParams): string {
    const pairs: string[] = [];
    params.forEach((value, key) => {
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(value).replace(/%2F/g, '/').replace(/%3A/g, ':')}`);
    });
    return pairs.length > 0 ? `#${pairs.join('&')}` : '';
  }

  function readWorkflowHashState(hash: string): WorkflowHashState {
    const params = parseHashParams(hash);
    const workflowId = params.get(WORKFLOW_ID_HASH_PARAM)?.trim() || null;
    const tab = params.get(WORKFLOW_TAB_HASH_PARAM) === 'runs' ? 'runs' : 'details';
    return {
      workflowId,
      tab: workflowId ? tab : 'details',
      runId: workflowId && tab === 'runs' ? params.get(WORKFLOW_RUN_ID_HASH_PARAM)?.trim() || null : null,
    };
  }

  function syncWorkflowHashFromLocation(): void {
    const nextState = readWorkflowHashState(window.location.hash);
    if (editorDirty && (
      nextState.workflowId !== workflowHashState.workflowId
      || nextState.tab !== workflowHashState.tab
      || nextState.runId !== workflowHashState.runId
    )) {
      const currentHash = workflowStateHash(workflowHashState.workflowId, workflowHashState.tab, workflowHashState.runId);
      replaceState(`${WORKFLOWS_ROUTE}${currentHash}`, {});
      requestNavigation(() => setWorkflowUrlState(nextState.workflowId, nextState.tab, nextState.runId));
      return;
    }
    workflowHashState = nextState;
  }

  function workflowStateHash(workflowId: string | null, tab: WorkflowTab = 'details', runId: string | null = null, baseHash = ''): string {
    const params = parseHashParams(baseHash);
    params.delete(WORKFLOW_ID_HASH_PARAM);
    params.delete(WORKFLOW_TAB_HASH_PARAM);
    params.delete(WORKFLOW_RUN_ID_HASH_PARAM);

    if (workflowId) {
      params.set(WORKFLOW_ID_HASH_PARAM, workflowId);
      params.set(WORKFLOW_TAB_HASH_PARAM, tab);
      if (tab === 'runs' && runId) {
        params.set(WORKFLOW_RUN_ID_HASH_PARAM, runId);
      }
    }

    return serializeHashParams(params);
  }

  function setWorkflowUrlState(workflowId: string | null, tab: WorkflowTab = 'details', runId: string | null = null): void {
    const nextHash = workflowStateHash(workflowId, tab, runId, window.location.hash);
    workflowHashState = readWorkflowHashState(nextHash);
    replaceState(`${WORKFLOWS_ROUTE}${nextHash}`, {});
  }

  function workflowStateHref(workflowId: string, tab: WorkflowTab = 'details'): string {
    return `${WORKFLOWS_ROUTE}${workflowStateHash(workflowId, tab)}`;
  }

  function openWorkflowDetails(workflowId: string): void {
    setWorkflowUrlState(workflowId, 'details');
  }

  function openWorkflowRuns(workflowId: string, runId: string | null = null): void {
    setWorkflowUrlState(workflowId, 'runs', runId);
  }

  function openWorkflowHome(): void {
    setWorkflowUrlState(null);
  }

  function requestNavigation(action: () => void | Promise<void>): void {
    if (editorDirty) {
      pendingNavigation = { action };
      return;
    }
    void action();
  }

  function requestWorkflowHome(): void {
    requestNavigation(openWorkflowHome);
  }

  function requestWorkflowTab(tab: 'template' | 'runs'): void {
    if (!selectedWorkflow) return;
    requestNavigation(() => tab === 'runs' ? openWorkflowRuns(selectedWorkflow.id) : openWorkflowDetails(selectedWorkflow.id));
  }

  function requestWorkflowSelection(workflowId: string): void {
    requestNavigation(async () => {
      await selectWorkflow(workflowId);
      openWorkflowDetails(workflowId);
    });
  }

  async function saveAndContinueNavigation(): Promise<void> {
    const navigation = pendingNavigation;
    if (!navigation) return;
    await saveSelectedWorkflow();
    if (editorDirty) return;
    pendingNavigation = null;
    await navigation.action();
  }

  async function discardAndContinueNavigation(): Promise<void> {
    const navigation = pendingNavigation;
    if (!navigation) return;
    undoEditorChanges();
    pendingNavigation = null;
    await navigation.action();
  }

  async function initializeWorkflowsRoute() {
    try {
      await initialize();
      await initializeFeatureAvailability();
    } catch (initError) {
      console.error('[WorkflowsRoute] Failed to initialize:', initError);
      routeError = initError instanceof Error ? initError.message : 'Failed to load workflows.';
    }
  }

  async function selectWorkflow(workflowId: string) {
    routeError = null;
    const sameWorkflowAlreadySelected = $workflowWorkspaceStore.selectedWorkflowId === workflowId;
    const workflow = await workflowWorkspaceStore.selectWorkflow(workflowId);
    if (sameWorkflowAlreadySelected && editorDirty) return;
    selectedRunContentRetention = workflow.run_content_retention ?? 'last_5';
    resetEditor(workflow);
  }

  $effect(() => {
    if (!canLoadWorkflows) return;
    void workflowWorkspaceStore.loadWorkflows().catch((loadError) => {
      console.error('[WorkflowsRoute] Failed to warm workflow cache:', loadError);
    });
  });

  $effect(() => {
    if (!canLoadWorkflows) return;
    const requestedWorkflow = requestedWorkflowId
      ? workflows.find((workflow) => workflow.id === requestedWorkflowId)
      : null;
    const workflowId = requestedWorkflow?.id ?? null;
    if (requestedWorkflowId && !workflowId && $workflowWorkspaceStore.listStatus === 'ready') {
      openWorkflowHome();
      return;
    }
    if (!workflowId || workflowId === $workflowWorkspaceStore.selectedWorkflowId) return;
    void selectWorkflow(workflowId).catch((selectError) => {
      console.error('[WorkflowsRoute] Failed to select workflow:', selectError);
    });
  });

  $effect(() => {
    if (!selectedWorkflow || hydratedEditorWorkflowId === selectedWorkflow.id) return;
    selectedRunContentRetention = selectedWorkflow.run_content_retention ?? 'last_5';
    resetEditor(selectedWorkflow);
    hydratedEditorWorkflowId = selectedWorkflow.id;
  });

  $effect(() => {
    const generation = workflowWorkspaceStore.getGeneration();
    const storeSelectedWorkflowId = $workflowWorkspaceStore.selectedWorkflowId;
    if (!canRenderWorkflowData || generation !== observedWorkflowGeneration) {
      observedWorkflowGeneration = generation;
      routeError = null;
    }
    void storeSelectedWorkflowId;
  });

  async function createRainWorkflow() {
    await createWorkflow('Daily rain alert', rainAlertGraph(), true);
  }

  async function createNewsWorkflow() {
    await createWorkflow('Twice-weekly AI news brief', newsBriefGraph(), true);
  }

  function openBlankWorkflowCreator(): void {
    blankWorkflowTitle = '';
    blankCreatorOpen = true;
  }

  async function submitBlankWorkflow(): Promise<void> {
    const title = blankWorkflowTitle.trim();
    if (!title || saving) return;
    await createWorkflow(title, blankWorkflowGraph(), false);
    if (!routeError) blankCreatorOpen = false;
  }

  function startWorkflowFromInspiration(inspiration: DailyInspiration) {
    if (!canRenderWorkflowData) return;
    workflowInputText = inspiration.phrase || inspiration.title || '';
  }

  async function continueWorkflowFromCard(item: { id: string }) {
    if (!canLoadWorkflows) return;
    requestWorkflowSelection(item.id);
  }

  async function startWorkflowFromCard(item: WorkflowContinueItem) {
    if (!canLoadWorkflows) return;
    if (item.id === 'starter-rain') {
      await createRainWorkflow();
    } else if (item.id === 'starter-news') {
      await createNewsWorkflow();
    } else if (item.id === 'starter-blank') {
      openBlankWorkflowCreator();
    } else {
      await continueWorkflowFromCard(item);
    }
  }

  async function submitWorkflowInput() {
    const title = workflowInputText.trim();
    if (!title || saving || !canLoadWorkflows) return;
    workflowInputText = '';
    await createWorkflow(title, blankWorkflowGraph(), false);
  }

  function showWorkflowVoiceInputUnavailable(): void {
    notificationStore.info('Voice input for workflows is coming soon.', 4000, true, 'workflows-voice-input');
  }

  function showWorkflowSearchUnavailable(): void {
    notificationStore.info('Workflow search is coming soon.', 4000, true, 'workflows-search');
  }

  function showAllWorkflowCards(): void {
    showAllWorkflows = true;
  }

  function showRecentWorkflowCards(): void {
    showAllWorkflows = false;
  }

  function workflowSummaryToContinueItem(workflow: WorkflowSummary): WorkflowContinueItem {
    return {
      id: workflow.id,
      title: workflow.title,
      summary: `${workflow.trigger_summary ?? 'Manual'} - ${retentionLabel(workflow.run_content_retention)}`,
      badge: workflow.enabled ? 'Enabled' : 'Paused',
      category: workflow.category ?? 'general_knowledge',
      icon: workflow.icon ?? 'help-circle',
      source: 'recent',
    };
  }

  async function createWorkflow(title: string, graph: WorkflowGraph, enabled: boolean) {
    if (!canLoadWorkflows) return;
    saving = true;
    routeError = null;
    try {
      const workflow = await workflowWorkspaceStore.createWorkflow({
        title,
        graph,
        enabled,
        runContentRetention,
      });
      await maintainTemplateProjection(workflow);
      await selectWorkflow(workflow.id);
      openWorkflowDetails(workflow.id);
    } catch (createError) {
      routeError = createError instanceof Error ? createError.message : 'Failed to create workflow.';
    } finally {
      saving = false;
    }
  }

  async function setSelectedWorkflowEnabled(enabled: boolean) {
    if (!selectedWorkflow) return;
    saving = true;
    routeError = null;
    try {
      const workflow = await workflowWorkspaceStore.setWorkflowEnabled(selectedWorkflow.id, enabled);
      resetEditor(workflow);
    } catch (saveError) {
      routeError = saveError instanceof Error ? saveError.message : 'Failed to update workflow.';
    } finally {
      saving = false;
    }
  }

  async function runSelectedWorkflow() {
    if (!selectedWorkflow) return;
    const workflowId = selectedWorkflow.id;
    saving = true;
    routeError = null;
    try {
      const run = await workflowWorkspaceStore.runWorkflow(workflowId);
      lastStartedRunId = run.id;
      openWorkflowRuns(workflowId, run.id);
    } catch (runError) {
      routeError = runError instanceof Error ? runError.message : 'Failed to run workflow.';
    } finally {
      saving = false;
    }
  }

  async function deleteSelectedWorkflow() {
    if (!selectedWorkflow || !window.confirm(`Delete “${selectedWorkflow.title}”? This cannot be undone.`)) return;
    saving = true;
    routeError = null;
    try {
      await workflowWorkspaceStore.deleteWorkflow(selectedWorkflow.id);
      openWorkflowHome();
    } catch (deleteError) {
      routeError = deleteError instanceof Error ? deleteError.message : 'Failed to delete workflow.';
    } finally {
      saving = false;
    }
  }

  async function saveSelectedWorkflow() {
    if (!selectedWorkflow || !editorGraph) return;
    saving = true;
    routeError = null;
    try {
      const workflow = await workflowWorkspaceStore.patchWorkflow(selectedWorkflow.id, {
        title: editorTitle.trim() || selectedWorkflow.title,
        description: editorDescription.trim(),
        graph: editorGraph,
        run_content_retention: selectedRunContentRetention
      });
      resetEditor(workflow);
      saving = false;
      await maintainTemplateProjection(workflow);
    } catch (saveError) {
      routeError = saveError instanceof Error ? saveError.message : 'Failed to save workflow.';
    } finally {
      saving = false;
    }
  }

  async function maintainTemplateProjection(workflow: WorkflowDetail): Promise<void> {
    try {
      await upsertWorkflowTemplateProjection(workflow);
    } catch (projectionError) {
      const message = projectionError instanceof Error ? projectionError.message : 'Could not update the encrypted workflow template projection.';
      routeError = `Workflow saved, but its shareable template was not updated: ${message}`;
    }
  }

  async function handleWorkflowVersionRestored(workflow: WorkflowDetail): Promise<void> {
    resetEditor(workflow);
    await maintainTemplateProjection(workflow);
  }

  async function unavailableTemplateImport(): Promise<ImportedWorkflowTemplate | null> {
    return null;
  }

  async function unavailableTemplateBinding(_requirement: WorkflowTemplateBindingRequirement): Promise<void> {
    return;
  }

  async function unavailableTemplateEnable(): Promise<void> {
    return;
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

  function blankWorkflowGraph(): WorkflowGraph {
    return {
      version: 1,
      trigger_node_id: null,
      nodes: [],
      edges: []
    };
  }

  function workflowActivationReady(graph: WorkflowGraph): boolean {
    if (!graph.trigger_node_id) return false;
    const qualifyingTypes = new Set(['create_chat_report', 'start_new_chat', 'send_notification', 'send_email_notification']);
    const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
    const pending = [graph.trigger_node_id];
    const visited = new Set<string>();
    while (pending.length > 0) {
      const nodeId = pending.shift();
      if (!nodeId || visited.has(nodeId)) continue;
      visited.add(nodeId);
      const node = nodesById.get(nodeId);
      if (node && qualifyingTypes.has(node.type)) return true;
      for (const edge of graph.edges) if (edge.from === nodeId) pending.push(edge.to);
    }
    return false;
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

  function resetEditor(workflow: WorkflowDetail) {
    editorTitle = workflow.title;
    editorDescription = workflow.description ?? '';
    editorGraph = cloneGraph(workflow.graph);
    editorDirty = false;
    hydratedEditorWorkflowId = workflow.id;
  }

  function undoEditorChanges() {
    if (selectedWorkflow) resetEditor(selectedWorkflow);
  }

  function cloneGraph(graph: WorkflowGraph): WorkflowGraph {
    return JSON.parse(JSON.stringify(graph)) as WorkflowGraph;
  }

  function retentionLabel(value: 'last_5' | 'none' | undefined): string {
    return value === 'none' ? 'No durable run content' : 'Keep latest 5 encrypted runs';
  }

  function updateEditorGraph(graph: WorkflowGraph): void {
    editorGraph = graph;
    editorDirty = true;
  }
</script>

{#if routeReady && !workflowsEnabled}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="workflows-route-state" data-testid="workflows-feature-disabled">
    <h1>Workflows unavailable</h1>
    <p>Workflows are disabled on this server.</p>
  </main>
{:else if routeReady && !$authStore.isAuthenticated}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="workflows-route-state" data-testid="workflows-auth-required">
    <h1>Workflows</h1>
    <p>Please log in to create, manage, and run server-side workflows.</p>
  </main>
{:else}
  <div class="main-content" class:menu-closed={!$panelState.isActivityHistoryOpen}>
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="chat-container workflows-container" class:menu-open={$panelState.isSettingsOpen}>
      <div class="workflow-sidebar-shell" class:drawer-open={$panelState.isActivityHistoryOpen}>
        <WorkflowSidebar onSelect={(workflow) => {
          void continueWorkflowFromCard(workflow);
          panelState.closeChats();
        }} />
      </div>
      <main class="active-chat-container workflows-start" class:management-view={showManageView} data-testid="workflows-page">
        {#if error}
          <div class="error-banner" data-testid="workflows-error">{error}</div>
        {/if}

        {#if !showManageView}
          <button type="button" class="blank-workflow-action" data-testid="create-blank-workflow" disabled={saving || !canRenderWorkflowData} onclick={openBlankWorkflowCreator}>New blank Workflow</button>
          <WorkspaceHomeShell
            surface="workflows"
            testId="workflows-start-screen"
            heading={`Hey ${visibleWorkflowGreetingName}!`}
            subtitle="What do you want to automate next?"
            actionItems={visibleWorkflowLandingItems}
            actionItemsTestId="workflow-mixed-row"
            itemTestId="workflow-landing-card"
            showReportIssue
            showAllMode={showAllWorkflows}
            showAllLabel={workflows.length > 0 ? `Show all ${workflows.length}` : ''}
            showAllTestId="workflows-show-all"
            allItems={allWorkflowContinueItems}
            allItemsViewTestId="all-workflows-view"
            allItemsGridTestId="all-workflows-grid"
            allItemsToolbarTestId="workflows-all-toolbar"
            allItemTestId="workflow-landing-card"
            backTestId="workflows-back-to-recent"
            searchTestId="workflows-search"
            onShowAll={workflows.length > 0 ? showAllWorkflowCards : undefined}
            onBackToRecent={showRecentWorkflowCards}
            onSearchAll={showWorkflowSearchUnavailable}
            onContinueItem={continueWorkflowFromCard}
            onActionItem={startWorkflowFromCard}
            onAllItem={continueWorkflowFromCard}
            onStartInspiration={startWorkflowFromInspiration}
          >
            <svelte:fragment slot="composer">
              <WorkspacePromptComposer
                surface="workflows"
                bind:value={workflowInputText}
                placeholder="Name a new workflow"
                submitLabel="Create workflow"
                submittingLabel="Creating..."
                disabled={saving || !canRenderWorkflowData}
                submitting={saving}
                testId="workflow-input-composer"
                inputTestId="workflow-input-textarea"
                submitTestId="workflow-input-submit"
                micTestId="workflow-input-mic"
                onSubmit={submitWorkflowInput}
                onMicClick={showWorkflowVoiceInputUnavailable}
              />
            </svelte:fragment>
          </WorkspaceHomeShell>
        {/if}

        {#if showManageView}
        <section class="workflow-management" data-testid="workflow-management">
          <div class="management-grid">
            <section class="workflow-detail" data-testid="workflow-detail">

          {#if selectedWorkflow}
            <WorkflowDetailPage
              title={editorTitle || selectedWorkflow.title}
              description={editorDescription || selectedWorkflow.description || selectedWorkflow.trigger_summary || 'Manual workflow'}
              category={selectedWorkflow.category ?? 'general_knowledge'}
              icon={selectedWorkflow.icon ?? 'help-circle'}
              createdAt={selectedWorkflow.created_at}
              nextRunAt={selectedWorkflow.next_run_at}
              enabled={selectedWorkflow.enabled}
              canEnable={editorActivationReady && !editorDirty}
              {lastStartedRunId}
              activeTab={isRunsView ? 'runs' : 'template'}
              dirty={editorDirty}
              {saving}
              onTabChange={requestWorkflowTab}
              onToggleEnabled={() => setSelectedWorkflowEnabled(!selectedWorkflow?.enabled)}
              onSaveWorkflow={saveSelectedWorkflow}
              onUndoWorkflow={undoEditorChanges}
              onCreateWorkflow={() => requestNavigation(openBlankWorkflowCreator)}
              onRunWorkflow={runSelectedWorkflow}
              onDeleteWorkflow={deleteSelectedWorkflow}
              onOpenHome={requestWorkflowHome}
              onOpenRuns={() => requestWorkflowTab('runs')}
              runsHref={workflowStateHref(selectedWorkflow.id, 'runs')}
            />

            {#if isRunsView}
              <WorkflowRunHistory
                workflow={selectedWorkflow}
                {runs}
                {selectedRunId}
                onSelectRun={(runId) => openWorkflowRuns(selectedWorkflow.id, runId)}
                editorHref={workflowStateHref(selectedWorkflow.id, 'details')}
                onOpenEditor={() => openWorkflowDetails(selectedWorkflow.id)}
              />
            {:else}
              <div id="tabpanel-template" data-testid="workflow-template-panel" role="tabpanel" aria-label="Workflow template">
                {#if editorGraph}
                  <div data-testid="workflow-editor">
                    <WorkflowGraphRenderer graph={editorGraph} readOnly={saving} onChange={updateEditorGraph} />
                  </div>
                {/if}
                <WorkflowVersionHistory
                  workflow={selectedWorkflow}
                  disabled={saving}
                  onRequestNavigation={requestNavigation}
                  onRestored={handleWorkflowVersionRestored}
                />
                <WorkflowTemplateShare
                  ownerWorkflow={selectedWorkflow}
                  disabled={saving || editorDirty}
                  onImport={unavailableTemplateImport}
                  onCompleteBinding={unavailableTemplateBinding}
                  onEnable={unavailableTemplateEnable}
                />
              </div>
            {/if}
          {:else}
            <div class="empty-detail">
              <h2>Build your first workflow</h2>
              <p>Choose a starter workflow to create a durable server-side automation.</p>
            </div>
          {/if}

            </section>
          </div>
        </section>
        {/if}

        {#if pendingNavigation}
          <div class="unsaved-guard-backdrop" data-testid="workflow-unsaved-guard" role="presentation">
            <div class="unsaved-guard" role="dialog" aria-modal="true" aria-labelledby="workflow-unsaved-title" use:focusTrap={{ onEscape: () => (pendingNavigation = null) }}>
              <h2 id="workflow-unsaved-title">Save your changes?</h2>
              <p>This Workflow has unsaved Template changes.</p>
              <div>
                <button type="button" data-testid="workflow-guard-stay" onclick={() => (pendingNavigation = null)}>Stay</button>
                <button type="button" data-testid="workflow-guard-discard" onclick={() => void discardAndContinueNavigation()}>Discard</button>
                <button type="button" class="primary" data-testid="workflow-guard-save" disabled={saving} onclick={() => void saveAndContinueNavigation()}>Save</button>
              </div>
            </div>
          </div>
        {/if}

        {#if blankCreatorOpen}
          <div class="blank-creator-backdrop" data-testid="workflow-blank-creator" role="presentation">
            <div class="blank-creator" role="dialog" aria-modal="true" aria-labelledby="blank-workflow-title" use:focusTrap={{ onEscape: () => (blankCreatorOpen = false) }}>
              <form onsubmit={(event) => { event.preventDefault(); void submitBlankWorkflow(); }}>
                <h2 id="blank-workflow-title">Start a blank Workflow</h2>
                <p>Name it now, then add a time trigger and the steps it should perform.</p>
                <label><span>Workflow name</span><input data-testid="workflow-blank-title-input" bind:value={blankWorkflowTitle} /></label>
                <div>
                  <button type="button" onclick={() => (blankCreatorOpen = false)}>Cancel</button>
                  <button type="submit" class="primary" data-testid="workflow-blank-create" disabled={saving || !blankWorkflowTitle.trim()}>{saving ? 'Creating...' : 'Create'}</button>
                </div>
              </form>
            </div>
          </div>
        {/if}
      </main>
      <div class="settings-wrapper">
        <Settings isLoggedIn={$authStore.isAuthenticated} />
      </div>
    </div>
  </div>
{/if}

<NotificationStack />

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
    container: main-content / inline-size;
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

  .workflow-sidebar-shell {
    width: 0;
    flex: 0 0 0;
    overflow: hidden;
    transition: width var(--duration-normal) var(--easing-default), flex-basis var(--duration-normal) var(--easing-default);
  }

  .workflow-sidebar-shell.drawer-open {
    width: min(325px, 28vw);
    flex-basis: min(325px, 28vw);
  }

  @media (min-width: 1100px) {
    .workflows-container.menu-open {
      gap: 20px;
    }
  }

  .workflows-start {
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: auto;
    display: grid;
    gap: 28px;
    color: var(--color-font-primary);
    background-color: var(--color-grey-20);
    border-radius: 17px;
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    position: relative;
    scroll-behavior: smooth;
  }

  .workflows-start:not(.management-view) {
    display: block;
    gap: 0;
    overflow: hidden;
  }

  .blank-workflow-action {
    position: absolute;
    z-index: var(--z-index-popover);
    inset: var(--spacing-5) var(--spacing-5) auto auto;
    color: var(--color-font-button);
    background: var(--color-button-primary);
    font-weight: 800;
    pointer-events: auto;
  }

  .workflow-management {
    display: grid;
    gap: 16px;
    padding-block-end: 36px;
  }

  .empty-detail h2 {
    margin: 0;
  }

  .management-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }

  .workflow-detail {
    min-width: 0;
    overflow: auto;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-16, 32px);
    background: var(--color-grey-0);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.08);
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

  .workflow-detail {
    padding: 0;
  }

  .unsaved-guard-backdrop {
    position: fixed;
    z-index: var(--z-index-modal, 1000);
    inset: 0;
    display: grid;
    place-items: center;
    padding: var(--spacing-6);
    background: color-mix(in srgb, var(--color-grey-100) 48%, transparent);
  }

  .unsaved-guard {
    display: grid;
    width: min(430px, 100%);
    gap: var(--spacing-5);
    padding: var(--spacing-8);
    border-radius: var(--radius-10);
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-xl);
  }

  .unsaved-guard h2,
  .unsaved-guard p { margin: 0; }
  .unsaved-guard p { color: var(--color-font-secondary); }
  .unsaved-guard div { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--spacing-3); }
  .unsaved-guard button { background: var(--color-grey-20); }
  .unsaved-guard .primary { color: var(--color-font-button); background: var(--color-button-primary); }

  .blank-creator-backdrop {
    position: fixed;
    z-index: var(--z-index-modal, 1000);
    inset: 0;
    display: grid;
    place-items: center;
    padding: var(--spacing-6);
    background: color-mix(in srgb, var(--color-grey-100) 48%, transparent);
  }

  .blank-creator {
    width: min(460px, 100%);
    padding: var(--spacing-8);
    border-radius: var(--radius-10);
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-xl);
  }

  .blank-creator form { display: grid; gap: var(--spacing-5); }

  .blank-creator h2,
  .blank-creator p { margin: 0; }
  .blank-creator p,
  .blank-creator label span { color: var(--color-font-secondary); }
  .blank-creator label { display: grid; gap: var(--spacing-3); }
  .blank-creator input { box-sizing: border-box; width: 100%; padding: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-6); color: var(--color-font-primary); background: var(--color-grey-0); font: inherit; }
  .blank-creator form > div { display: flex; justify-content: flex-end; gap: var(--spacing-3); }
  .blank-creator button { background: var(--color-grey-20); }
  .blank-creator .primary { color: var(--color-font-button); background: var(--color-button-primary); }

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

  @media (max-width: 760px) {
    .main-content {
      inset-inline-start: 0;
    }

    .workflows-container {
      height: calc(100vh - 66px);
      height: calc(100dvh - 66px);
      padding: 8px 10px;
      box-sizing: border-box;
    }

    .workflow-sidebar-shell {
      position: fixed;
      z-index: var(--z-index-modal);
      inset: 82px auto 0 0;
      width: min(325px, calc(100vw - 32px));
      transform: translateX(-110%);
      transition: transform var(--duration-normal) var(--easing-default);
      box-shadow: 12px 0 30px rgba(0, 0, 0, 0.2);
    }

    .workflow-sidebar-shell.drawer-open {
      transform: translateX(0);
    }

    .management-grid {
      grid-template-columns: 1fr;
    }

    .workflow-detail {
      border-radius: var(--radius-10, 24px);
    }

  }
</style>
