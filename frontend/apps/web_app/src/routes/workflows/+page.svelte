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
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { ChatHeader, Header, Settings, Notification, WorkspaceHomeShell, WorkflowSidebar, authStore, initialize, notificationStore, panelState, featureAvailabilityStore, initializeFeatureAvailability, workflowWorkspaceStore } from '@repo/ui';
  import { userProfile } from '@repo/ui/stores/userProfile';
  import type { DailyInspiration, WorkflowDetail, WorkflowGraph, WorkflowNode, WorkflowNodeType, WorkflowRun, WorkflowSummary } from '@repo/ui';

  type WorkflowContinueItem = {
    id: string;
    title: string;
    summary?: string | null;
    badge?: string | null;
    category?: string | null;
    appId?: string | null;
    icon?: string | null;
  };

  type WorkflowFlowItem =
    | { kind: 'connector'; id: string; label: string; indent?: boolean }
    | { kind: 'branch-label'; id: string; label: string }
    | { kind: 'placeholder'; id: string; label: string }
    | { kind: 'node'; id: string; node: WorkflowNode; index: number; branch?: boolean };

  let workflows = $derived<WorkflowSummary[]>($workflowWorkspaceStore.workflows);
  let selectedWorkflow = $derived<WorkflowDetail | null>($workflowWorkspaceStore.selectedWorkflow);
  let runs = $derived<WorkflowRun[]>($workflowWorkspaceStore.runs);
  let saving = $state(false);
  let running = $state(false);
  let routeError = $state<string | null>(null);
  let error = $derived(routeError ?? $workflowWorkspaceStore.error);
  let runContentRetention = $state<'last_5' | 'none'>('last_5');
  let selectedRunContentRetention = $state<'last_5' | 'none'>('last_5');
  let editorTitle = $state('');
  let editorGraph = $state<WorkflowGraph | null>(null);
  let editorDirty = $state(false);
  let hydratedEditorWorkflowId = $state<string | null>(null);
  let expandedNodeId = $state<string | null>(null);
  let showAllWorkflows = $state(false);
  let workflowInputText = $state('');
  let observedWorkflowGeneration = $state(workflowWorkspaceStore.getGeneration());

  let recentWorkflows = $derived(workflows.slice(0, 6));
  let workflowStarterItems: WorkflowContinueItem[] = [
    {
      id: 'starter-rain',
      title: 'Tell me if it will rain tomorrow',
      summary: 'Weather check plus notification',
      badge: 'Starter',
      category: 'weather',
      appId: 'weather',
      icon: 'cloud-rain',
    },
    {
      id: 'starter-news',
      title: 'Send me an AI news brief twice a week',
      summary: 'Research, summarize, and notify',
      badge: 'Starter',
      category: 'technology',
      appId: 'news',
      icon: 'newspaper',
    },
    {
      id: 'starter-blank',
      title: 'Start from a blank workflow',
      summary: 'Open the visual builder',
      badge: 'Blank',
      category: 'productivity',
      appId: 'workflows',
      icon: 'workflow',
    },
  ];
  let recentWorkflowContinueItems = $derived<WorkflowContinueItem[]>(recentWorkflows.map((workflow) => ({
    id: workflow.id,
    title: workflow.title,
    summary: `${workflow.trigger_summary ?? 'Manual'} - ${retentionLabel(workflow.run_content_retention)}`,
    badge: workflow.enabled ? 'Enabled' : 'Paused',
    category: 'productivity',
    appId: 'workflows',
    icon: 'workflow',
  })));
  let workflowGreetingName = $derived($userProfile.username?.trim() || 'there');
  let workflowCountLabel = $derived(workflows.length === 1 ? '1 workflow ready' : `${workflows.length} workflows ready`);
  let isManageView = $derived(page.url.searchParams.get('view') === 'manage');
  let requestedWorkflowId = $derived(page.url.searchParams.get('workflow'));

  let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
  let routeReady = $derived($authStore.isInitialized && featureAvailabilityLoaded);
  let workflowsEnabled = $derived(!featureAvailabilityLoaded || ($featureAvailabilityStore.disabledById?.['platform:workflows'] !== true && $featureAvailabilityStore.disabledById !== null));
  let canLoadWorkflows = $derived(routeReady && $authStore.isAuthenticated && workflowsEnabled);
  let canRenderWorkflowData = $derived(routeReady && $authStore.isAuthenticated);
  let showManageView = $derived(canRenderWorkflowData && isManageView);
  let visibleWorkflowGreetingName = $derived(canRenderWorkflowData ? workflowGreetingName : 'there');
  let visibleWorkflowStarterItems = $derived(canRenderWorkflowData ? workflowStarterItems : []);
  let visibleRecentWorkflowContinueItems = $derived(canRenderWorkflowData ? recentWorkflowContinueItems : []);

  onMount(() => {
    void initializeWorkflowsRoute();
  });

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
    const workflowId = requestedWorkflow?.id ?? (isManageView ? workflows[0]?.id : null);
    if (requestedWorkflowId && !workflowId && $workflowWorkspaceStore.listStatus === 'ready') {
      void goto('/workflows?view=manage', { replaceState: true });
      return;
    }
    if (!workflowId || workflowId === $workflowWorkspaceStore.selectedWorkflowId) return;
    if (requestedWorkflowId && requestedWorkflowId !== workflowId) {
      void goto(`/workflows?view=manage&workflow=${encodeURIComponent(workflowId)}`, { replaceState: true });
    }
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

  async function createBlankWorkflow() {
    await createWorkflow('Untitled workflow', blankWorkflowGraph(), false);
  }

  function startWorkflowFromInspiration(inspiration: DailyInspiration) {
    if (!canRenderWorkflowData) return;
    workflowInputText = inspiration.phrase || inspiration.title || '';
  }

  async function continueWorkflowFromCard(item: WorkflowContinueItem) {
    if (!canLoadWorkflows) return;
    await selectWorkflow(item.id);
    await goto(`/workflows?view=manage&workflow=${encodeURIComponent(item.id)}`);
  }

  async function startWorkflowFromCard(item: WorkflowContinueItem) {
    if (!canLoadWorkflows) return;
    if (item.id === 'starter-rain') {
      await createRainWorkflow();
    } else if (item.id === 'starter-news') {
      await createNewsWorkflow();
    } else if (item.id === 'starter-blank') {
      await createBlankWorkflow();
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
      await selectWorkflow(workflow.id);
      await goto(`/workflows?view=manage&workflow=${encodeURIComponent(workflow.id)}`);
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

  async function updateSelectedWorkflowRetention() {
    if (!selectedWorkflow) return;
    saving = true;
    routeError = null;
    try {
      const workflow = await workflowWorkspaceStore.patchWorkflow(selectedWorkflow.id, {
        run_content_retention: selectedRunContentRetention
      });
      resetEditor(workflow);
    } catch (saveError) {
      routeError = saveError instanceof Error ? saveError.message : 'Failed to update workflow retention.';
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
        graph: editorGraph,
        run_content_retention: selectedRunContentRetention
      });
      resetEditor(workflow);
    } catch (saveError) {
      routeError = saveError instanceof Error ? saveError.message : 'Failed to save workflow.';
    } finally {
      saving = false;
    }
  }

  async function deleteSelectedWorkflow() {
    if (!selectedWorkflow) return;
    saving = true;
    routeError = null;
    try {
      const workflowId = selectedWorkflow.id;
      const nextWorkflow = workflows.find((workflow) => workflow.id !== workflowId) ?? null;
      await workflowWorkspaceStore.deleteWorkflow(workflowId);
      if (nextWorkflow) await selectWorkflow(nextWorkflow.id);
    } catch (deleteError) {
      routeError = deleteError instanceof Error ? deleteError.message : 'Failed to delete workflow.';
    } finally {
      saving = false;
    }
  }

  async function runSelectedWorkflow() {
    if (!selectedWorkflow) return;
    running = true;
    routeError = null;
    try {
      await workflowWorkspaceStore.runWorkflow(selectedWorkflow.id);
    } catch (runError) {
      routeError = runError instanceof Error ? runError.message : 'Failed to run workflow.';
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

  function blankWorkflowGraph(): WorkflowGraph {
    return {
      version: 1,
      trigger_node_id: 'manual',
      nodes: [
        { id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} }
      ],
      edges: []
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

  function resetEditor(workflow: WorkflowDetail) {
    editorTitle = workflow.title;
    editorGraph = cloneGraph(workflow.graph);
    editorDirty = false;
    hydratedEditorWorkflowId = workflow.id;
    expandedNodeId = null;
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

  function nodeTypeLabel(type: WorkflowNodeType): string {
    switch (type) {
      case 'schedule_trigger':
        return 'Time trigger';
      case 'manual_trigger':
        return 'Manual start';
      case 'app_skill_action':
        return 'Use App skill';
      case 'decision':
        return 'Check';
      case 'repeat':
        return 'Repeat';
      case 'create_chat_report':
        return 'Create report';
      case 'send_notification':
        return 'Notify';
      case 'send_email_notification':
        return 'Email';
      case 'end':
        return 'End';
    }
  }

  function cardIconLabel(type: WorkflowNodeType): string {
    switch (type) {
      case 'schedule_trigger':
        return 'CAL';
      case 'app_skill_action':
        return 'SUN';
      case 'decision':
        return 'IF';
      case 'send_notification':
        return 'MSG';
      case 'send_email_notification':
        return 'MAIL';
      case 'create_chat_report':
        return 'DOC';
      case 'repeat':
        return 'LOOP';
      case 'manual_trigger':
        return 'RUN';
      case 'end':
        return 'END';
    }
  }

  function cardSummary(node: WorkflowNode): string {
    if (node.type === 'schedule_trigger') {
      const schedule = scheduleRecord(node);
      const repeat = stringValue(schedule.type, 'daily') === 'weekly' ? 'Every week' : 'Every day';
      return `${repeat}, at ${formatTime(stringValue(schedule.time, '09:00'))}`;
    }
    if (node.type === 'app_skill_action') {
      const appId = stringValue(configRecord(node).app_id, 'weather');
      const skillId = stringValue(configRecord(node).skill_id, 'forecast');
      if (appId === 'weather') return `Weather | Get forecast for ${stringValue(inputRecord(node).location, 'Berlin')}`;
      if (appId === 'news') return `News | Search ${firstRequestQuery(node)}`;
      return `${appId} | ${skillId}`;
    }
    if (node.type === 'decision') {
      const predicate = predicateRecord(node);
      return `${humanizeExpression(stringValue(predicate.left, 'value'))} ${operatorLabel(stringValue(predicate.op, 'gte'))} ${predicate.right ?? ''}`.trim();
    }
    if (node.type === 'send_notification') return 'Send notification';
    if (node.type === 'send_email_notification') return 'Send email';
    if (node.type === 'create_chat_report') return stringValue(configRecord(node).summary, 'Create report');
    if (node.type === 'repeat') return `Repeat up to ${numberValue(configRecord(node).max_iterations, 3)} times`;
    return node.title ?? node.type;
  }

  function formatTime(value: string): string {
    const [hourValue, minuteValue] = value.split(':');
    const hour = Number(hourValue);
    const minute = minuteValue ?? '00';
    if (!Number.isFinite(hour)) return value;
    const period = hour >= 12 ? 'PM' : 'AM';
    const displayHour = hour % 12 || 12;
    return `${displayHour}:${minute}${period}`;
  }

  function humanizeExpression(value: string): string {
    return value
      .replace('$nodes.weather.output.', '')
      .replaceAll('_', ' ')
      .replaceAll('.', ' ');
  }

  function operatorLabel(value: string): string {
    switch (value) {
      case 'gte':
        return '>';
      case 'gt':
        return '>';
      case 'lte':
        return '<';
      case 'lt':
        return '<';
      case 'eq':
        return '=';
      default:
        return value;
    }
  }

  function flowItems(graph: WorkflowGraph | null): WorkflowFlowItem[] {
    if (!graph) return [];
    const decisionIndex = graph.nodes.findIndex((node) => node.type === 'decision');
    if (decisionIndex < 0) return linearFlowItems(graph.nodes);

    const items: WorkflowFlowItem[] = [];
    const mainNodes = graph.nodes.slice(0, decisionIndex + 1);
    mainNodes.forEach((node, index) => {
      if (index > 0) items.push({ kind: 'connector', id: `connector-${node.id}`, label: 'then' });
      items.push({ kind: 'node', id: `node-${node.id}`, node, index: graph.nodes.indexOf(node) });
    });

    const branchNodes = graph.nodes.slice(decisionIndex + 1).filter((node) => node.type !== 'end');
    items.push({ kind: 'branch-label', id: 'if-true-label', label: 'If true:' });
    branchNodes.forEach((node, branchIndex) => {
      if (branchIndex > 0) items.push({ kind: 'connector', id: `branch-connector-${node.id}`, label: 'then', indent: true });
      items.push({ kind: 'node', id: `branch-node-${node.id}`, node, index: graph.nodes.indexOf(node), branch: true });
    });
    items.push({ kind: 'branch-label', id: 'if-false-label', label: 'If false:' });
    items.push({ kind: 'placeholder', id: 'false-placeholder', label: 'Do nothing' });
    return items;
  }

  function linearFlowItems(nodes: WorkflowNode[]): WorkflowFlowItem[] {
    const items: WorkflowFlowItem[] = [];
    nodes.forEach((node, index) => {
      if (index > 0) items.push({ kind: 'connector', id: `connector-${node.id}`, label: 'then' });
      items.push({ kind: 'node', id: `node-${node.id}`, node, index });
    });
    return items;
  }

  function toggleExpandedNode(nodeId: string) {
    expandedNodeId = expandedNodeId === nodeId ? null : nodeId;
  }

  function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  function configRecord(node: WorkflowNode): Record<string, unknown> {
    return node.config ?? {};
  }

  function inputRecord(node: WorkflowNode): Record<string, unknown> {
    const input = configRecord(node).input;
    return isRecord(input) ? input : {};
  }

  function scheduleRecord(node: WorkflowNode): Record<string, unknown> {
    const schedule = configRecord(node).schedule;
    return isRecord(schedule) ? schedule : {};
  }

  function predicateRecord(node: WorkflowNode): Record<string, unknown> {
    const predicate = configRecord(node).predicate;
    return isRecord(predicate) ? predicate : { left: '', op: 'gte', right: 0 };
  }

  function firstRequestQuery(node: WorkflowNode): string {
    const requests = inputRecord(node).requests;
    if (!Array.isArray(requests)) return 'AI news';
    const firstRequest = requests[0];
    return isRecord(firstRequest) ? stringValue(firstRequest.query, 'AI news') : 'AI news';
  }

  function stringValue(value: unknown, fallback = ''): string {
    return typeof value === 'string' ? value : fallback;
  }

  function numberValue(value: unknown, fallback = 0): number {
    return typeof value === 'number' ? value : fallback;
  }

  function setEditorTitle(value: string) {
    editorTitle = value;
    editorDirty = true;
  }

  function updateEditorNode(nodeId: string, updater: (node: WorkflowNode) => WorkflowNode) {
    if (!editorGraph) return;
    editorGraph = {
      ...editorGraph,
      nodes: editorGraph.nodes.map((node) => node.id === nodeId ? updater(node) : node)
    };
    editorDirty = true;
  }

  function updateNodeTitle(nodeId: string, title: string) {
    updateEditorNode(nodeId, (node) => ({ ...node, title }));
  }

  function updateNodeConfig(nodeId: string, config: Record<string, unknown>) {
    updateEditorNode(nodeId, (node) => ({ ...node, config: { ...configRecord(node), ...config } }));
  }

  function updateSchedule(node: WorkflowNode, field: string, value: string) {
    updateNodeConfig(node.id, { schedule: { ...scheduleRecord(node), [field]: value } });
  }

  function updateInput(node: WorkflowNode, field: string, value: string | number) {
    updateNodeConfig(node.id, { input: { ...inputRecord(node), [field]: value } });
  }

  function updatePredicate(node: WorkflowNode, field: string, value: string | number) {
    updateNodeConfig(node.id, { predicate: { ...predicateRecord(node), [field]: value } });
  }

  function appendNode(type: WorkflowNodeType) {
    if (!editorGraph || type === 'schedule_trigger' || type === 'manual_trigger') return;
    const node = defaultNode(type);
    const endIndex = editorGraph.nodes.findIndex((item) => item.type === 'end');
    const nodes = endIndex >= 0
      ? [...editorGraph.nodes.slice(0, endIndex), node, ...editorGraph.nodes.slice(endIndex)]
      : [...editorGraph.nodes, node];
    editorGraph = { ...editorGraph, nodes, edges: buildLinearEdges(nodes) };
    editorDirty = true;
  }

  function removeNode(nodeId: string) {
    if (!editorGraph) return;
    const nodes = editorGraph.nodes.filter((node) => node.id !== nodeId || node.type === 'schedule_trigger' || node.type === 'end');
    editorGraph = { ...editorGraph, nodes, edges: buildLinearEdges(nodes) };
    editorDirty = true;
  }

  function defaultNode(type: WorkflowNodeType): WorkflowNode {
    const id = `${type}-${Date.now().toString(36)}`;
    switch (type) {
      case 'app_skill_action':
        return { id, type, title: 'Check weather', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin', days: 1 } } };
      case 'decision':
        return { id, type, title: 'Decision', config: { predicate: { left: '$nodes.weather.output.rain_probability', op: 'gte', right: 60 } } };
      case 'repeat':
        return { id, type, title: 'Repeat safely', config: { max_iterations: 3, max_duration_seconds: 120, max_credits: 5, per_iteration_timeout_seconds: 30 } };
      case 'create_chat_report':
        return { id, type, title: 'Create report', config: { summary: 'Workflow report' } };
      case 'send_notification':
        return { id, type, title: 'Push notification', config: { title: 'Workflow update', body: 'Your workflow finished.' } };
      case 'send_email_notification':
        return { id, type, title: 'Email notification', config: { title: 'Workflow update', body: 'Your workflow finished.' } };
      case 'end':
        return { id, type, title: 'Done', config: {} };
      case 'schedule_trigger':
      case 'manual_trigger':
        return { id, type, title: 'Manual start', config: {} };
    }
  }

  function buildLinearEdges(nodes: WorkflowNode[]): WorkflowGraph['edges'] {
    return nodes.slice(0, -1).map((node, index) => ({
      from: node.id,
      to: nodes[index + 1].id,
      ...(node.type === 'decision' ? { branch: 'yes' } : {})
    }));
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
          {#if showAllWorkflows}
            <section class="workflow-home-all" data-testid="workflows-start-screen">
              <button type="button" class="show-all-button" data-testid="workflows-show-all" onclick={() => showAllWorkflows = false}>Show recent</button>
              <div class="all-workflows-grid" data-testid="all-workflows-grid">
                {#each workflows as workflow (workflow.id)}
                  <button type="button" class="workflow-mini-card" onclick={() => continueWorkflowFromCard(workflow)}>
                    <strong>{workflow.title}</strong>
                    <span>{workflow.enabled ? 'Enabled' : 'Disabled'} - {workflow.trigger_summary ?? 'Manual'}</span>
                  </button>
                {/each}
              </div>
              <form class="workflow-input-composer" data-testid="workflow-input-composer" onsubmit={(event) => { event.preventDefault(); void submitWorkflowInput(); }}>
                <textarea data-testid="workflow-input-textarea" bind:value={workflowInputText} rows="1" placeholder="Name a new workflow" disabled={saving || !canRenderWorkflowData}></textarea>
                <div class="workflow-input-actions"><button type="submit" data-testid="workflow-input-submit" disabled={saving || !canRenderWorkflowData || !workflowInputText.trim()}>{saving ? 'Creating...' : 'Create workflow'}</button></div>
              </form>
            </section>
          {:else}
            {#if workflows.length > 0}
              <button type="button" class="show-all-button workflow-home-show-all" data-testid="workflows-show-all" onclick={() => showAllWorkflows = true}>Show all {workflows.length}</button>
            {/if}
            <WorkspaceHomeShell
              surface="workflows"
              testId="workflows-start-screen"
              heading={`Hey ${visibleWorkflowGreetingName}!`}
              subtitle="What do you want to automate next?"
              actionItems={visibleWorkflowStarterItems}
              continueItems={visibleRecentWorkflowContinueItems}
              actionItemsTestId="workflow-recommendations"
              continueSectionTestId="recent-workflows"
              onContinueItem={continueWorkflowFromCard}
              onActionItem={startWorkflowFromCard}
              onStartInspiration={startWorkflowFromInspiration}
            >
              <svelte:fragment slot="composer">
                <form class="workflow-input-composer" data-testid="workflow-input-composer" onsubmit={(event) => { event.preventDefault(); void submitWorkflowInput(); }}>
                  <textarea data-testid="workflow-input-textarea" bind:value={workflowInputText} rows="1" placeholder="Name a new workflow" disabled={saving || !canRenderWorkflowData}></textarea>
                  <div class="workflow-input-actions"><button type="submit" data-testid="workflow-input-submit" disabled={saving || !canRenderWorkflowData || !workflowInputText.trim()}>{saving ? 'Creating...' : 'Create workflow'}</button></div>
                </form>
              </svelte:fragment>
            </WorkspaceHomeShell>
          {/if}
        {/if}

        {#if showManageView}
        <section class="workflow-management" data-testid="workflow-management">
          <div class="management-header">
            <div>
              <p>Manage automations</p>
              <h2>{workflowCountLabel}</h2>
              {#if workflows.length > 0}
                <button type="button" class="show-all-button" data-testid="workflows-show-all" onclick={() => showAllWorkflows = !showAllWorkflows}>
                  {showAllWorkflows ? 'Show recent' : `Show all ${workflows.length}`}
                </button>
              {/if}
            </div>
            <div class="create-actions">
              <label class="retention-picker" for="workflow-retention">
                <span>Run content retention</span>
                <select id="workflow-retention" data-testid="workflow-retention-select" bind:value={runContentRetention}>
                  <option value="last_5">Keep latest 5 encrypted runs</option>
                  <option value="none">No durable run content</option>
                </select>
              </label>
              <button type="button" data-testid="create-blank-workflow" onclick={createBlankWorkflow} disabled={saving}>Blank workflow</button>
              <button type="button" data-testid="create-rain-workflow" onclick={createRainWorkflow} disabled={saving}>Daily rain alert</button>
              <button type="button" data-testid="create-news-workflow" onclick={createNewsWorkflow} disabled={saving}>AI news brief</button>
            </div>
          </div>

          {#if showAllWorkflows}
            <div class="all-workflows-grid" data-testid="all-workflows-grid">
              {#each workflows as workflow (workflow.id)}
                <button type="button" class="workflow-mini-card" onclick={() => selectWorkflow(workflow.id)}>
                  <strong>{workflow.title}</strong>
                  <span>{workflow.enabled ? 'Enabled' : 'Disabled'} - {workflow.trigger_summary ?? 'Manual'}</span>
                </button>
              {/each}
            </div>
          {/if}

          <div class="management-grid">
            <section class="workflow-detail" data-testid="workflow-detail">

          {#if selectedWorkflow}
            <ChatHeader
              title={editorTitle || selectedWorkflow.title}
              category="productivity"
              icon="workflow"
              summary={selectedWorkflow.trigger_summary ?? 'Manual workflow'}
              chatCreatedAt={selectedWorkflow.created_at}
            />
            <div class="detail-header">
              <div>
                <p>{selectedWorkflow.status}</p>
                <label class="title-editor" for="workflow-title-input">
                  <span>Workflow name</span>
                  <input
                    id="workflow-title-input"
                    data-testid="workflow-title-input"
                    value={editorTitle}
                    oninput={(event) => setEditorTitle(event.currentTarget.value)}
                  />
                </label>
                <span class="retention-chip" data-testid="selected-workflow-retention">Run content: {retentionLabel(selectedWorkflow.run_content_retention)}</span>
              </div>
              <div class="detail-actions">
                 <label class="inline-retention" for="selected-workflow-retention-select">
                  <span>Edit retention</span>
                  <select id="selected-workflow-retention-select" data-testid="selected-workflow-retention-select" bind:value={selectedRunContentRetention}>
                    <option value="last_5">Keep latest 5</option>
                    <option value="none">No durable content</option>
                  </select>
                 </label>
                 <button type="button" data-testid="undo-workflow" onclick={undoEditorChanges} disabled={!editorDirty || saving}>Undo</button>
                 <button type="button" data-testid="save-workflow" onclick={saveSelectedWorkflow} disabled={saving || !editorDirty}>{saving ? 'Saving...' : 'Save workflow'}</button>
                <button type="button" data-testid="save-workflow-retention" onclick={updateSelectedWorkflowRetention} disabled={saving}>Save</button>
                <button type="button" data-testid="toggle-workflow" onclick={() => setSelectedWorkflowEnabled(!selectedWorkflow?.enabled)} disabled={saving}>
                  {selectedWorkflow.enabled ? 'Disable' : 'Enable'}
                </button>
                <button type="button" data-testid="run-workflow" onclick={runSelectedWorkflow} disabled={running}>{running ? 'Running...' : 'Run test'}</button>
                <button type="button" data-testid="delete-workflow" onclick={deleteSelectedWorkflow} disabled={saving}>Delete</button>
              </div>
            </div>

            <div class="workflow-editor" data-testid="workflow-editor">
              <div class="node-stack shortcut-flow" data-testid="workflow-node-stack">
                {#each flowItems(editorGraph) as item (item.id)}
                  {#if item.kind === 'connector'}
                    <div class="flow-connector" class:branch-connector={item.indent}>{item.label}</div>
                  {:else if item.kind === 'branch-label'}
                    <div class="branch-label">{item.label}</div>
                  {:else if item.kind === 'placeholder'}
                    <article class="workflow-card placeholder-card">{item.label}</article>
                  {:else if item.kind === 'node'}
                    <article
                      class="flow-node"
                      class:branch-node={item.branch}
                      class:expanded={expandedNodeId === item.node.id}
                      data-node-type={item.node.type}
                      data-testid="workflow-node-card"
                    >
                      <button
                        type="button"
                        class="workflow-card"
                        class:app-skill-card={item.node.type === 'app_skill_action'}
                        data-testid="workflow-node-summary"
                        aria-expanded={expandedNodeId === item.node.id}
                        onclick={() => toggleExpandedNode(item.node.id)}
                      >
                        <span class="card-kind">{nodeTypeLabel(item.node.type)}</span>
                        <span class="card-icon" aria-hidden="true">{cardIconLabel(item.node.type)}</span>
                        <strong data-testid="workflow-node-title-label">{cardSummary(item.node)}</strong>
                      </button>

                      {#if expandedNodeId === item.node.id}
                        <div class="node-editor-panel" data-testid="workflow-node-expanded">
                          <div class="expanded-header">
                            <div>
                              <span>{nodeTypeLabel(item.node.type)}</span>
                              <h3>{cardSummary(item.node)}</h3>
                            </div>
                            {#if item.node.type !== 'schedule_trigger' && item.node.type !== 'end'}
                              <button type="button" class="remove-node" data-testid="remove-workflow-node" onclick={() => removeNode(item.node.id)}>Remove</button>
                            {/if}
                          </div>

                          <label class="node-field">
                            <span>Action title</span>
                            <input
                              data-testid="workflow-node-title-input"
                              value={item.node.title ?? item.node.type}
                              oninput={(event) => updateNodeTitle(item.node.id, event.currentTarget.value)}
                            />
                          </label>

                          {#if item.node.type === 'schedule_trigger'}
                            <div class="node-grid">
                              <label class="node-field">
                                <span>Repeat</span>
                                <select value={stringValue(scheduleRecord(item.node).type, 'daily')} oninput={(event) => updateSchedule(item.node, 'type', event.currentTarget.value)}>
                                  <option value="daily">Daily</option>
                                  <option value="weekly">Weekly</option>
                                </select>
                              </label>
                              <label class="node-field">
                                <span>Time</span>
                                <input value={stringValue(scheduleRecord(item.node).time, '09:00')} oninput={(event) => updateSchedule(item.node, 'time', event.currentTarget.value)} />
                              </label>
                              <label class="node-field">
                                <span>Timezone</span>
                                <input value={stringValue(scheduleRecord(item.node).timezone, 'Europe/Berlin')} oninput={(event) => updateSchedule(item.node, 'timezone', event.currentTarget.value)} />
                              </label>
                            </div>
                          {:else if item.node.type === 'app_skill_action'}
                            <div class="node-grid">
                              <label class="node-field">
                                <span>Skill</span>
                                <select
                                  value={`${stringValue(configRecord(item.node).app_id, 'weather')}:${stringValue(configRecord(item.node).skill_id, 'forecast')}`}
                                  oninput={(event) => {
                                    const [appId, skillId] = event.currentTarget.value.split(':');
                                    updateNodeConfig(item.node.id, { app_id: appId, skill_id: skillId, input: appId === 'news' ? { requests: [{ query: 'AI news' }] } : { location: 'Berlin', days: 1 } });
                                  }}
                                >
                                  <option value="weather:forecast">Weather forecast</option>
                                  <option value="news:search">News search</option>
                                </select>
                              </label>
                              {#if stringValue(configRecord(item.node).app_id, 'weather') === 'news'}
                                <label class="node-field wide">
                                  <span>Search query</span>
                                  <input
                                    value={firstRequestQuery(item.node)}
                                    oninput={(event) => updateNodeConfig(item.node.id, { input: { requests: [{ query: event.currentTarget.value }] } })}
                                  />
                                </label>
                              {:else}
                                <label class="node-field">
                                  <span>Location</span>
                                  <input data-testid="workflow-node-location-input" value={stringValue(inputRecord(item.node).location, 'Berlin')} oninput={(event) => updateInput(item.node, 'location', event.currentTarget.value)} />
                                </label>
                                <label class="node-field">
                                  <span>Days</span>
                                  <input type="number" min="1" max="7" value={numberValue(inputRecord(item.node).days, 1)} oninput={(event) => updateInput(item.node, 'days', Number(event.currentTarget.value))} />
                                </label>
                              {/if}
                            </div>
                          {:else if item.node.type === 'decision'}
                            <div class="node-grid">
                              <label class="node-field wide">
                                <span>Check value</span>
                                <input value={stringValue(predicateRecord(item.node).left, '$nodes.weather.output.rain_probability')} oninput={(event) => updatePredicate(item.node, 'left', event.currentTarget.value)} />
                              </label>
                              <label class="node-field">
                                <span>Operator</span>
                                <select value={stringValue(predicateRecord(item.node).op, 'gte')} oninput={(event) => updatePredicate(item.node, 'op', event.currentTarget.value)}>
                                  <option value="gte">is at least</option>
                                  <option value="gt">is greater than</option>
                                  <option value="lte">is at most</option>
                                  <option value="lt">is less than</option>
                                  <option value="eq">equals</option>
                                </select>
                              </label>
                              <label class="node-field">
                                <span>Value</span>
                                <input type="number" value={numberValue(predicateRecord(item.node).right, 60)} oninput={(event) => updatePredicate(item.node, 'right', Number(event.currentTarget.value))} />
                              </label>
                            </div>
                          {:else if item.node.type === 'send_notification' || item.node.type === 'send_email_notification'}
                            <div class="node-grid">
                              <label class="node-field">
                                <span>Title</span>
                                <input value={stringValue(configRecord(item.node).title, 'Workflow update')} oninput={(event) => updateNodeConfig(item.node.id, { title: event.currentTarget.value })} />
                              </label>
                              <label class="node-field wide">
                                <span>Message</span>
                                <input value={stringValue(configRecord(item.node).body, 'Your workflow finished.')} oninput={(event) => updateNodeConfig(item.node.id, { body: event.currentTarget.value })} />
                              </label>
                            </div>
                          {:else if item.node.type === 'create_chat_report'}
                            <label class="node-field">
                              <span>Report summary</span>
                              <input value={stringValue(configRecord(item.node).summary, 'Workflow report')} oninput={(event) => updateNodeConfig(item.node.id, { summary: event.currentTarget.value })} />
                            </label>
                          {:else if item.node.type === 'repeat'}
                            <div class="node-grid">
                              <label class="node-field">
                                <span>Max iterations</span>
                                <input type="number" min="1" value={numberValue(configRecord(item.node).max_iterations, 3)} oninput={(event) => updateNodeConfig(item.node.id, { max_iterations: Number(event.currentTarget.value) })} />
                              </label>
                              <label class="node-field">
                                <span>Max credits</span>
                                <input type="number" min="1" value={numberValue(configRecord(item.node).max_credits, 5)} oninput={(event) => updateNodeConfig(item.node.id, { max_credits: Number(event.currentTarget.value) })} />
                              </label>
                            </div>
                          {:else}
                            <p class="node-note">This action ends the workflow.</p>
                          {/if}
                        </div>
                      {/if}
                    </article>
                  {/if}
                {/each}
              </div>

              <div class="editor-toolbar" data-testid="workflow-action-palette">
                <button type="button" data-testid="add-weather-node" onclick={() => appendNode('app_skill_action')}>
                  <span aria-hidden="true">+</span>
                  Add action
                </button>
                <button type="button" data-testid="add-decision-node" onclick={() => appendNode('decision')}>
                  <span aria-hidden="true">+</span>
                  Add decision
                </button>
                <button type="button" data-testid="add-report-node" onclick={() => appendNode('create_chat_report')}>Add report</button>
                <button type="button" data-testid="add-push-node" onclick={() => appendNode('send_notification')}>Add push</button>
                <button type="button" data-testid="add-email-node" onclick={() => appendNode('send_email_notification')}>Add email</button>
              </div>
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
          </div>
        </section>
        {/if}
      </main>
      <div class="settings-wrapper">
        <Settings isLoggedIn={$authStore.isAuthenticated} />
      </div>
    </div>
  </div>
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
    gap: 0;
    overflow: hidden;
  }

  .management-header p,
  .detail-header p {
    margin: 0;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.75rem;
    font-weight: 900;
  }

  .workflow-management {
    display: grid;
    gap: 16px;
    padding-block-end: 36px;
  }

  .management-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    padding: 0 4px;
  }

  .management-header h2,
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

  .create-actions {
    display: flex;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0;
  }

  .retention-picker {
    display: grid;
    gap: 6px;
    color: var(--color-font-secondary);
    font-size: 0.9rem;
  }

  .retention-picker select,
  .title-editor input,
  .node-field input,
  .node-field select {
    width: 100%;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-8, 20px);
    padding: 10px 12px;
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    font: inherit;
  }

  .title-editor {
    display: grid;
    gap: 6px;
  }

  .title-editor span {
    color: var(--color-font-secondary);
    font-size: 0.85rem;
    font-weight: 700;
  }

  .title-editor input {
    max-width: 420px;
    border-color: transparent;
    padding-inline: 0;
    border-radius: 0;
    background: transparent;
    font-size: clamp(1.8rem, 4vw, 2.4rem);
    font-weight: 800;
    line-height: 1.05;
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

  .show-all-button {
    color: var(--color-font-primary);
    background: var(--color-grey-20);
  }

  .empty-copy,
  .run-row span {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: 0.9rem;
  }

  .workflow-detail {
    padding: 22px;
  }

  .workflow-mini-card {
    display: grid;
    gap: 6px;
    text-align: start;
    color: var(--color-font-primary);
    background: color-mix(in srgb, var(--color-grey-0) 86%, transparent);
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.08);
  }

  .all-workflows-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: 12px;
  }

  .workflow-mini-card {
    display: grid;
    gap: 6px;
    min-height: 116px;
    align-content: center;
    text-align: start;
  }

  .workflow-mini-card span {
    color: var(--color-font-secondary);
    font-size: 0.86rem;
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

  .detail-actions button[data-testid="save-workflow"] {
    color: var(--color-font-button);
    background: var(--color-button-primary);
  }

  .workflow-editor {
    display: grid;
    justify-items: center;
    gap: 38px;
    padding-block: 10px 24px;
  }

  .editor-toolbar {
    width: min(680px, 100%);
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    border-block-start: 3px solid var(--color-grey-20);
  }

  .editor-toolbar button {
    min-height: 118px;
    display: grid;
    place-items: center;
    gap: 8px;
    border-radius: 0;
    color: var(--color-font-secondary);
    background: transparent;
    font-size: 1.15rem;
    font-weight: 800;
  }

  .editor-toolbar button:nth-child(2) {
    border-inline-start: 3px solid var(--color-grey-20);
  }

  .editor-toolbar button:nth-child(n + 3) {
    min-height: auto;
    padding-block: 12px;
    border-block-start: 1px solid var(--color-grey-20);
    font-size: 0.9rem;
  }

  .editor-toolbar button span {
    font-size: 2rem;
    line-height: 1;
  }

  .node-stack {
    width: min(680px, 100%);
    display: grid;
    justify-items: center;
    gap: 0;
  }

  .flow-node {
    width: 100%;
    display: grid;
    justify-items: center;
  }

  .flow-node.branch-node,
  .placeholder-card {
    width: 82%;
    justify-self: end;
  }

  .flow-connector,
  .branch-label {
    color: var(--color-font-secondary);
    font-size: 1.4rem;
    font-weight: 900;
    line-height: 1;
  }

  .flow-connector {
    padding-block: 16px 20px;
    text-align: center;
  }

  .flow-connector.branch-connector {
    width: 82%;
    justify-self: end;
  }

  .branch-label {
    width: 82%;
    justify-self: end;
    padding-block: 20px 12px;
    text-align: start;
  }

  .workflow-card {
    width: 100%;
    min-height: 164px;
    display: grid;
    justify-items: center;
    align-content: center;
    gap: 18px;
    padding: 22px 26px;
    border: 0;
    border-radius: 30px;
    color: var(--color-font-primary);
    background: var(--color-grey-10);
    text-align: center;
    box-shadow: none;
    transition: transform 0.16s ease, box-shadow 0.16s ease;
  }

  .workflow-card:hover,
  .workflow-card[aria-expanded="true"] {
    transform: translateY(-1px);
    box-shadow: 0 14px 34px rgba(0, 0, 0, 0.14);
  }

  .workflow-card.app-skill-card {
    color: var(--color-font-button);
    background: linear-gradient(135deg, #0072bc 0%, #04b8cf 100%);
  }

  .workflow-card.placeholder-card {
    min-height: 96px;
    color: var(--color-font-secondary);
    font-size: 1.35rem;
    font-weight: 900;
  }

  .card-kind {
    color: var(--color-font-secondary);
    font-size: 1.25rem;
    font-weight: 900;
  }

  .app-skill-card .card-kind {
    color: color-mix(in srgb, var(--color-font-button) 76%, transparent);
  }

  .card-icon {
    width: 54px;
    height: 54px;
    display: grid;
    place-items: center;
    border-radius: var(--radius-8, 20px);
    color: var(--color-button-primary);
    background: color-mix(in srgb, var(--color-button-primary) 12%, transparent);
    font-size: 0.88rem;
    font-weight: 900;
    letter-spacing: 0.04em;
  }

  .app-skill-card .card-icon {
    color: var(--color-font-button);
    background: color-mix(in srgb, var(--color-font-button) 18%, transparent);
  }

  .workflow-card strong {
    max-width: 520px;
    color: inherit;
    font-size: clamp(1.45rem, 3vw, 2rem);
    font-weight: 900;
    line-height: 1.15;
  }

  .node-editor-panel {
    width: min(760px, calc(100% + 88px));
    display: grid;
    gap: 14px;
    margin-block: 14px 8px;
    padding: 18px;
    border: 1px solid var(--color-grey-20);
    border-radius: 28px;
    background: var(--color-grey-0);
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.14);
  }

  .branch-node .node-editor-panel {
    width: min(720px, calc(100% + 60px));
  }

  .expanded-header {
    display: flex;
    justify-items: center;
    align-items: flex-start;
    justify-content: space-between;
    gap: 14px;
  }

  .expanded-header span {
    color: var(--color-font-secondary);
    font-weight: 900;
  }

  .expanded-header h3 {
    margin: 4px 0 0;
    color: var(--color-font-primary);
    font-size: 1.25rem;
  }

  .remove-node {
    padding: 6px 10px;
    color: var(--color-font-secondary);
    background: var(--color-grey-20);
  }

  .node-field {
    display: grid;
    gap: 5px;
    min-width: 0;
  }

  .node-field span {
    color: var(--color-font-secondary);
    font-size: 0.82rem;
    font-weight: 700;
  }

  .node-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .node-field.wide {
    grid-column: span 2;
  }

  .node-note {
    margin: 0;
    color: var(--color-font-secondary);
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

  .workflow-input-composer {
    width: min(629px, 100%);
    min-height: 60px;
    z-index: 3;
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    margin: 0 auto;
    padding: 0 var(--spacing-5);
    border: 0;
    border-radius: 24px;
    background: var(--color-grey-blue);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    box-sizing: border-box;
  }

  .workflow-input-composer textarea {
    width: 100%;
    min-height: 40px;
    max-height: 160px;
    resize: none;
    flex: 1;
    min-width: 0;
    border: 0;
    outline: none;
    padding: 10px 0;
    border-radius: 0;
    color: var(--color-font-primary);
    background: transparent;
    font: inherit;
    font-size: var(--font-size-p);
  }

  .workflow-input-composer textarea::placeholder {
    color: var(--color-grey-60);
    font-weight: 600;
  }

  .workflow-input-actions {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    flex-shrink: 0;
  }

  .workflow-input-actions button {
    color: var(--color-font-primary);
    background: var(--color-grey-20);
    min-height: 40px;
    padding: var(--spacing-4) var(--spacing-8);
    border-radius: var(--radius-8);
    font-weight: 500;
  }

  .workflow-input-actions button[type="submit"] {
    color: var(--color-font-button);
    background: var(--color-button-primary);
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
      padding: 8px 10px;
    }

    .workflow-sidebar-shell {
      position: fixed;
      z-index: 30;
      inset: 82px auto 0 0;
      width: min(325px, calc(100vw - 32px));
      transform: translateX(-110%);
      transition: transform var(--duration-normal) var(--easing-default);
      box-shadow: 12px 0 30px rgba(0, 0, 0, 0.2);
    }

    .workflow-sidebar-shell.drawer-open {
      transform: translateX(0);
    }

    .management-header,
    .create-actions {
      display: grid;
    }

    .management-grid {
      grid-template-columns: 1fr;
    }

    .workflow-detail {
      border-radius: var(--radius-10, 24px);
    }

    .detail-header {
      display: grid;
    }

    .workflow-input-composer {
      flex-wrap: wrap;
      align-items: flex-end;
      padding-block: var(--spacing-4);
      border-radius: 24px;
    }

    .workflow-input-actions {
      justify-content: flex-end;
      flex-wrap: wrap;
    }
  }
</style>
