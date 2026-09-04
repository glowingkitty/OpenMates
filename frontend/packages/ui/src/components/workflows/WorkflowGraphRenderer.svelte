<!--
  WorkflowGraphRenderer.svelte
  Shared vertical graph used by editable Templates, immutable versions, and runs.
  The component owns ephemeral expansion state while callers own persistence.
  Execution detail is presentation-only and never fabricates unavailable content.
-->

<script lang="ts">
  import { getCategoryGradientColors, getLucideIcon } from '../../utils/categoryUtils';
  import type { WorkflowGraph, WorkflowNode, WorkflowNodeRun, WorkflowNodeType } from '../../stores/workflowWorkspaceStore';

  type FlowItem =
    | { kind: 'connector'; id: string; label: string; indent?: boolean }
    | { kind: 'branch-label'; id: string; label: string }
    | { kind: 'placeholder'; id: string; label: string }
    | { kind: 'node'; id: string; node: WorkflowNode; branch?: boolean };

  let {
    graph,
    readOnly = false,
    nodeRuns = [],
    testId = 'workflow-graph-renderer',
    onChange,
  }: {
    graph: WorkflowGraph;
    readOnly?: boolean;
    nodeRuns?: WorkflowNodeRun[];
    testId?: string;
    onChange: (graph: WorkflowGraph) => void;
  } = $props();

  let expandedNodeId = $state<string | null>(null);
  let stepMenuOpen = $state(false);
  const ChevronIcon = getLucideIcon('chevron-down');
  const PlusIcon = getLucideIcon('plus');
  const TRIGGER_NODE_TYPES = new Set<WorkflowNodeType>(['schedule_trigger', 'manual_trigger', 'webhook_trigger', 'event_trigger']);
  const QUALIFYING_EFFECT_TYPES = new Set<WorkflowNodeType>(['create_chat_report', 'start_new_chat', 'send_notification', 'send_email_notification']);
  const triggerCount = $derived(graph.nodes.filter((node) => TRIGGER_NODE_TYPES.has(node.type)).length);
  const stepCount = $derived(graph.nodes.filter((node) => !TRIGGER_NODE_TYPES.has(node.type) && node.type !== 'end').length);
  const qualifyingEffectReachable = $derived(hasReachableQualifyingEffect());

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

  function stringValue(value: unknown, fallback = ''): string {
    return typeof value === 'string' ? value : fallback;
  }

  function numberValue(value: unknown, fallback = 0): number {
    return typeof value === 'number' ? value : fallback;
  }

  function firstRequestQuery(node: WorkflowNode): string {
    const requests = inputRecord(node).requests;
    if (!Array.isArray(requests)) return 'AI news';
    const firstRequest = requests[0];
    return isRecord(firstRequest) ? stringValue(firstRequest.query, 'AI news') : 'AI news';
  }

  function nodeTypeLabel(type: WorkflowNodeType): string {
    const labels: Record<WorkflowNodeType, string> = {
      schedule_trigger: 'Time trigger', manual_trigger: 'Manual start', webhook_trigger: 'Webhook trigger', event_trigger: 'Event trigger',
      app_skill_action: 'Use App skill', decision: 'Check', repeat: 'Repeat', create_chat_report: 'Create report', start_new_chat: 'Start chat',
      send_notification: 'Notify', send_email_notification: 'Email', ask_user: 'Ask for input', wait: 'Wait', custom_code: 'Code', end: 'End',
    };
    return labels[type];
  }

  function cardIcon(type: WorkflowNodeType): string {
    const icons: Record<WorkflowNodeType, string> = {
      schedule_trigger: 'calendar-clock', manual_trigger: 'play', webhook_trigger: 'webhook', event_trigger: 'radio', app_skill_action: 'sparkles',
      decision: 'git-branch', repeat: 'repeat-2', create_chat_report: 'file-text', start_new_chat: 'message-square-plus', send_notification: 'bell',
      send_email_notification: 'mail', ask_user: 'message-circle-question', wait: 'timer', custom_code: 'code', end: 'circle-check',
    };
    return icons[type];
  }

  function formatTime(value: string): string {
    const [hourValue, minuteValue] = value.split(':');
    const hour = Number(hourValue);
    if (!Number.isFinite(hour)) return value;
    return `${hour % 12 || 12}:${minuteValue ?? '00'}${hour >= 12 ? 'PM' : 'AM'}`;
  }

  function cardSummary(node: WorkflowNode): string {
    if (node.type === 'schedule_trigger') {
      const schedule = scheduleRecord(node);
      return `${stringValue(schedule.type, 'daily') === 'weekly' ? 'Every week' : 'Every day'}, at ${formatTime(stringValue(schedule.time, '09:00'))}`;
    }
    if (node.type === 'app_skill_action') {
      const appId = stringValue(configRecord(node).app_id, 'weather');
      if (appId === 'weather') return `Weather | Get forecast for ${stringValue(inputRecord(node).location, 'Berlin')}`;
      if (appId === 'news') return `News | Search ${firstRequestQuery(node)}`;
      return `${appId} | ${stringValue(configRecord(node).skill_id, 'action')}`;
    }
    if (node.type === 'decision') {
      const predicate = predicateRecord(node);
      const left = stringValue(predicate.left, 'value').replace('$nodes.weather.output.', '').replaceAll('_', ' ').replaceAll('.', ' ');
      const operator = { gte: '>', gt: '>', lte: '<', lt: '<', eq: '=' }[stringValue(predicate.op, 'gte')] ?? stringValue(predicate.op, 'gte');
      return `${left} ${operator} ${predicate.right ?? ''}`.trim();
    }
    if (node.type === 'send_notification') return 'Send notification';
    if (node.type === 'send_email_notification') return 'Send email';
    if (node.type === 'create_chat_report') return stringValue(configRecord(node).summary, 'Create report');
    if (node.type === 'repeat') return `Repeat up to ${numberValue(configRecord(node).max_iterations, 3)} times`;
    if (node.type === 'ask_user') return stringValue(configRecord(node).prompt, node.title ?? 'Ask for input');
    return node.title ?? nodeTypeLabel(node.type);
  }

  function flowItems(): FlowItem[] {
    const items: FlowItem[] = [];
    graph.nodes.forEach((node, index) => {
      const incomingEdge = graph.edges.find((edge) => edge.to === node.id);
      const branch = incomingEdge?.branch;
      if (index > 0) {
        items.push({
          kind: branch ? 'branch-label' : 'connector',
          id: `connector-${node.id}`,
          label: branch === 'yes' || branch === 'true' ? 'If true:' : branch === 'no' || branch === 'false' ? 'If false:' : 'then',
          ...(branch ? {} : { indent: false }),
        });
      }
      items.push({ kind: 'node', id: `node-${node.id}`, node, branch: !!branch });
    });
    const decision = graph.nodes.find((node) => node.type === 'decision');
    if (decision && !graph.edges.some((edge) => edge.from === decision.id && ['no', 'false'].includes(edge.branch ?? ''))) {
      items.push({ kind: 'branch-label', id: `if-false-${decision.id}`, label: 'If false:' });
      items.push({ kind: 'placeholder', id: `false-placeholder-${decision.id}`, label: 'Do nothing' });
    }
    return items;
  }

  function updateNode(nodeId: string, updater: (node: WorkflowNode) => WorkflowNode): void {
    if (readOnly) return;
    onChange({ ...graph, nodes: graph.nodes.map((node) => node.id === nodeId ? updater(node) : node) });
  }

  function updateNodeConfig(node: WorkflowNode, config: Record<string, unknown>): void {
    updateNode(node.id, (current) => ({ ...current, config: { ...configRecord(current), ...config } }));
  }

  function defaultNode(type: 'app_skill_action' | 'decision' | 'create_chat_report'): WorkflowNode {
    const id = `${type}-${Date.now().toString(36)}`;
    if (type === 'create_chat_report') {
      return { id, type, title: 'Create chat report', config: { summary: 'Workflow report' } };
    }
    return type === 'decision'
      ? { id, type, title: 'Decision', config: { predicate: { left: '$nodes.weather.output.rain_probability', op: 'gte', right: 60 } } }
      : { id, type, title: 'Check weather', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin', days: 1 } } };
  }

  function appendNode(type: 'app_skill_action' | 'decision' | 'create_chat_report'): void {
    if (readOnly) return;
    stepMenuOpen = false;
    const node = defaultNode(type);
    const endIndex = graph.nodes.findIndex((item) => item.type === 'end');
    const nodes = endIndex >= 0 ? [...graph.nodes.slice(0, endIndex), node, ...graph.nodes.slice(endIndex)] : [...graph.nodes, node];
    const endNode = endIndex >= 0 ? graph.nodes[endIndex] : null;
    if (!endNode) {
      const previousNode = graph.nodes.at(-1);
      onChange({ ...graph, nodes, edges: previousNode ? [...graph.edges, { from: previousNode.id, to: node.id }] : graph.edges });
      return;
    }
    const incomingEndEdges = graph.edges.filter((edge) => edge.to === endNode.id);
    const edges = incomingEndEdges.length > 0
      ? [
          ...graph.edges.filter((edge) => edge.to !== endNode.id),
          ...incomingEndEdges.map((edge) => ({ ...edge, to: node.id })),
          { from: node.id, to: endNode.id },
        ]
      : [...graph.edges, { from: node.id, to: endNode.id }];
    onChange({ ...graph, nodes, edges });
  }

  function addTimeTrigger(): void {
    if (readOnly || triggerCount > 0) return;
    const trigger: WorkflowNode = {
      id: 'trigger',
      type: 'schedule_trigger',
      title: 'Every day',
      config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } },
    };
    const firstNode = graph.nodes[0];
    onChange({
      ...graph,
      trigger_node_id: trigger.id,
      nodes: [trigger, ...graph.nodes],
      edges: firstNode ? [{ from: trigger.id, to: firstNode.id }, ...graph.edges] : graph.edges,
    });
    expandedNodeId = trigger.id;
  }

  function hasReachableQualifyingEffect(): boolean {
    if (!graph.trigger_node_id) return false;
    const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
    const pending = [graph.trigger_node_id];
    const visited = new Set<string>();
    while (pending.length > 0) {
      const nodeId = pending.shift();
      if (!nodeId || visited.has(nodeId)) continue;
      visited.add(nodeId);
      const node = nodesById.get(nodeId);
      if (node && QUALIFYING_EFFECT_TYPES.has(node.type)) return true;
      for (const edge of graph.edges) if (edge.from === nodeId) pending.push(edge.to);
    }
    return false;
  }

  function removeNode(nodeId: string): void {
    if (readOnly) return;
    const nodes = graph.nodes.filter((node) => node.id !== nodeId || ['schedule_trigger', 'manual_trigger', 'end'].includes(node.type));
    if (nodes.length === graph.nodes.length) return;
    const incoming = graph.edges.filter((edge) => edge.to === nodeId);
    const outgoing = graph.edges.filter((edge) => edge.from === nodeId);
    const bridged = incoming.flatMap((before) => outgoing.map((after) => ({ from: before.from, to: after.to, ...(before.branch ? { branch: before.branch } : after.branch ? { branch: after.branch } : {}) })));
    onChange({ ...graph, nodes, edges: [...graph.edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId), ...bridged] });
  }

  function nodeRun(nodeId: string): WorkflowNodeRun | undefined {
    return nodeRuns.find((run) => run.node_id === nodeId);
  }

  function detailValue(value: unknown): string {
    if (value === null || value === undefined) return 'Unavailable';
    if (typeof value === 'string') return value;
    return JSON.stringify(value, null, 2);
  }

  function appCardStyle(node: WorkflowNode): string | undefined {
    if (node.type !== 'app_skill_action') return undefined;
    const category = stringValue(configRecord(node).app_id) === 'weather' ? 'science' : 'general_knowledge';
    const colors = getCategoryGradientColors(category);
    return colors ? `--node-gradient-start: ${colors.start}; --node-gradient-end: ${colors.end};` : undefined;
  }
</script>

<section class="graph-panel" data-testid={testId} data-read-only={readOnly ? 'true' : 'false'}>
  <div class="graph-canvas">
    {#if !readOnly}
      <div class="readiness-panel" data-testid="workflow-readiness">
        <div><span>Triggers</span><strong data-testid="workflow-readiness-trigger-count">{triggerCount}</strong></div>
        <div><span>Steps</span><strong data-testid="workflow-readiness-step-count">{stepCount}</strong></div>
        <div data-testid="workflow-reachable-qualifying-side-effect" data-reachable={qualifyingEffectReachable ? 'true' : 'false'}>
          <span>Reachable result</span><strong>{qualifyingEffectReachable ? 'Ready' : 'Needed'}</strong>
        </div>
      </div>
      {#if triggerCount === 0 && stepCount === 0}
        <p class="blank-draft" data-testid="workflow-blank-draft">Add one time trigger and at least one result-producing step to activate this Workflow.</p>
      {/if}
    {/if}
    <div class="node-stack" data-testid="workflow-node-stack">
      {#each flowItems() as item (item.id)}
        {#if item.kind === 'connector'}
          <div class="flow-connector" class:branch-connector={item.indent}>{item.label}</div>
        {:else if item.kind === 'branch-label'}
          <div class="branch-label">{item.label}</div>
        {:else if item.kind === 'placeholder'}
          <article class="workflow-card placeholder-card">{item.label}</article>
        {:else}
          {@const run = nodeRun(item.node.id)}
          {@const IconComponent = getLucideIcon(cardIcon(item.node.type))}
          <article class="flow-node" class:branch-node={item.branch} class:expanded={expandedNodeId === item.node.id} data-node-type={item.node.type} data-testid="workflow-node-card">
            <button
              type="button"
              class="workflow-card"
              class:app-skill-card={item.node.type === 'app_skill_action'}
              style={appCardStyle(item.node)}
              data-testid="workflow-node-summary"
              aria-expanded={expandedNodeId === item.node.id}
              onclick={() => (expandedNodeId = expandedNodeId === item.node.id ? null : item.node.id)}
            >
              <span class="card-kind">{nodeTypeLabel(item.node.type)}</span>
              <span class="card-icon" aria-hidden="true"><IconComponent size={26} /></span>
              <strong data-testid="workflow-node-title-label">{cardSummary(item.node)}</strong>
              {#if run}<span class="node-status" data-testid="workflow-run-node-status" data-node-status={run.status}>{run.status.replaceAll('_', ' ')}</span>{/if}
              <span class="expand-icon" aria-hidden="true"><ChevronIcon size={18} /></span>
            </button>

            {#if expandedNodeId === item.node.id}
              <div class="node-editor-panel" data-testid="workflow-node-expanded">
                <div class="expanded-header">
                  <div><span>{nodeTypeLabel(item.node.type)}</span><h3>{cardSummary(item.node)}</h3></div>
                  {#if !readOnly && !['schedule_trigger', 'manual_trigger', 'end'].includes(item.node.type)}
                    <button type="button" class="remove-node" data-testid="remove-workflow-node" onclick={() => removeNode(item.node.id)}>Remove</button>
                  {/if}
                </div>

                {#if readOnly}
                  {#if run?.input_summary && Object.keys(run.input_summary).length > 0}
                    <section class="detail-group"><h4>Input</h4><pre>{detailValue(run.input_summary)}</pre></section>
                  {/if}
                  {#if run?.output_summary && Object.keys(run.output_summary).length > 0}
                    <section class="detail-group"><h4>Output and sources</h4><pre>{detailValue(run.output_summary)}</pre></section>
                  {/if}
                  {#if run?.skipped_reason}<section class="detail-group"><h4>Branch</h4><p>{run.skipped_reason}</p></section>{/if}
                  {#if run?.error_summary}<section class="detail-group error"><h4>Error</h4><p>{run.error_summary}</p></section>{/if}
                {:else}
                  <label class="node-field"><span>Action title</span><input data-testid="workflow-node-title-input" value={item.node.title ?? item.node.type} oninput={(event) => updateNode(item.node.id, (node) => ({ ...node, title: event.currentTarget.value }))} /></label>
                  {#if item.node.type === 'schedule_trigger'}
                    <div class="node-grid">
                      <label class="node-field"><span>Repeat</span><select data-testid="workflow-time-trigger-schedule" value={stringValue(scheduleRecord(item.node).type, 'daily')} oninput={(event) => updateNodeConfig(item.node, { schedule: { ...scheduleRecord(item.node), type: event.currentTarget.value } })}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>
                      <label class="node-field"><span>Time</span><input value={stringValue(scheduleRecord(item.node).time, '09:00')} oninput={(event) => updateNodeConfig(item.node, { schedule: { ...scheduleRecord(item.node), time: event.currentTarget.value } })} /></label>
                      <label class="node-field"><span>Timezone</span><input value={stringValue(scheduleRecord(item.node).timezone, 'Europe/Berlin')} oninput={(event) => updateNodeConfig(item.node, { schedule: { ...scheduleRecord(item.node), timezone: event.currentTarget.value } })} /></label>
                    </div>
                  {:else if item.node.type === 'app_skill_action'}
                    <div class="node-grid">
                      <label class="node-field"><span>Skill</span><select value={`${stringValue(configRecord(item.node).app_id, 'weather')}:${stringValue(configRecord(item.node).skill_id, 'forecast')}`} oninput={(event) => { const [appId, skillId] = event.currentTarget.value.split(':'); updateNodeConfig(item.node, { app_id: appId, skill_id: skillId, input: appId === 'news' ? { requests: [{ query: 'AI news' }] } : { location: 'Berlin', days: 1 } }); }}><option value="weather:forecast">Weather forecast</option><option value="news:search">News search</option></select></label>
                      {#if stringValue(configRecord(item.node).app_id, 'weather') === 'news'}
                        <label class="node-field wide"><span>Search query</span><input value={firstRequestQuery(item.node)} oninput={(event) => updateNodeConfig(item.node, { input: { requests: [{ query: event.currentTarget.value }] } })} /></label>
                      {:else}
                        <label class="node-field"><span>Location</span><input data-testid="workflow-node-location-input" value={stringValue(inputRecord(item.node).location, 'Berlin')} oninput={(event) => updateNodeConfig(item.node, { input: { ...inputRecord(item.node), location: event.currentTarget.value } })} /></label>
                        <label class="node-field"><span>Days</span><input type="number" min="1" max="7" value={numberValue(inputRecord(item.node).days, 1)} oninput={(event) => updateNodeConfig(item.node, { input: { ...inputRecord(item.node), days: Number(event.currentTarget.value) } })} /></label>
                      {/if}
                    </div>
                  {:else if item.node.type === 'decision'}
                    <div class="node-grid"><label class="node-field wide"><span>Check value</span><input value={stringValue(predicateRecord(item.node).left)} oninput={(event) => updateNodeConfig(item.node, { predicate: { ...predicateRecord(item.node), left: event.currentTarget.value } })} /></label><label class="node-field"><span>Value</span><input type="number" value={numberValue(predicateRecord(item.node).right, 60)} oninput={(event) => updateNodeConfig(item.node, { predicate: { ...predicateRecord(item.node), right: Number(event.currentTarget.value) } })} /></label></div>
                  {:else}
                    <p class="node-note">{detailValue(item.node.config ?? {})}</p>
                  {/if}
                {/if}
              </div>
            {/if}
          </article>
        {/if}
      {/each}
    </div>

    {#if !readOnly}
      <div class="editor-toolbar" data-testid="workflow-action-palette">
        {#if triggerCount === 0}
          <button type="button" data-testid="workflow-add-time-trigger" onclick={addTimeTrigger}><PlusIcon size={24} />Add time trigger</button>
        {/if}
        <button type="button" data-testid="workflow-add-step" onclick={() => (stepMenuOpen = !stepMenuOpen)}><PlusIcon size={24} />Add step</button>
        {#if stepMenuOpen}
          <div class="step-menu" data-testid="workflow-step-menu">
            <button type="button" data-testid="workflow-step-app-skill-action" onclick={() => appendNode('app_skill_action')}>Use App skill</button>
            <button type="button" data-testid="workflow-step-create-chat-report" onclick={() => appendNode('create_chat_report')}>Create chat report</button>
            <button type="button" data-testid="add-decision-node" onclick={() => appendNode('decision')}>Add decision</button>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</section>

<style>
  .graph-panel { margin: var(--spacing-8); padding: var(--spacing-6); border-radius: var(--radius-12); background: var(--color-grey-10); }
  .graph-canvas { display: grid; justify-items: center; gap: var(--spacing-10); padding: var(--spacing-8); border-radius: var(--radius-10); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .node-stack, .editor-toolbar, .readiness-panel, .blank-draft { width: min(680px, 100%); }
  .readiness-panel { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--spacing-3); }
  .readiness-panel div { display: grid; gap: var(--spacing-2); padding: var(--spacing-4); border-radius: var(--radius-6); background: var(--color-grey-10); text-align: center; }
  .readiness-panel span { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .readiness-panel strong { font-size: var(--font-size-h4); }
  .blank-draft { margin: 0; color: var(--color-font-secondary); text-align: center; }
  .node-stack, .flow-node { display: grid; justify-items: center; }
  .flow-node { width: 100%; }
  .flow-node.branch-node, .placeholder-card, .branch-label, .branch-connector { width: 82%; justify-self: end; }
  .flow-connector, .branch-label { color: var(--color-font-secondary); font-size: 1rem; font-weight: 800; }
  .flow-connector { padding-block: var(--spacing-6); }
  .branch-label { padding-block: var(--spacing-6) var(--spacing-4); }
  .workflow-card { position: relative; display: grid; width: 100%; min-height: 132px; place-items: center; gap: var(--spacing-4); padding: var(--spacing-8); border: 0; border-radius: var(--radius-12); color: var(--color-font-primary); background: var(--color-grey-10); box-shadow: var(--shadow-sm); cursor: pointer; }
  .workflow-card.app-skill-card { color: var(--color-grey-0); background: linear-gradient(135deg, var(--node-gradient-start), var(--node-gradient-end)); }
  .placeholder-card { min-height: 80px; color: var(--color-font-secondary); }
  .card-kind { color: var(--color-font-secondary); font-size: var(--font-size-small); font-weight: 800; }
  .app-skill-card .card-kind { color: color-mix(in srgb, var(--color-grey-0) 78%, transparent); }
  .card-icon { display: grid; width: 48px; height: 48px; place-items: center; border-radius: var(--radius-8); color: var(--color-button-primary); background: color-mix(in srgb, var(--color-button-primary) 12%, transparent); }
  .app-skill-card .card-icon { color: var(--color-grey-0); background: color-mix(in srgb, var(--color-grey-0) 18%, transparent); }
  .workflow-card strong { font-size: clamp(1.15rem, 2.5vw, 1.65rem); }
  .expand-icon { position: absolute; inset-inline-end: var(--spacing-6); inset-block-end: var(--spacing-5); }
  .node-status { padding: var(--spacing-2) var(--spacing-4); border-radius: var(--radius-full); background: color-mix(in srgb, var(--color-grey-0) 72%, transparent); color: var(--color-font-primary); font-size: var(--font-size-xs); font-weight: 800; text-transform: capitalize; }
  .node-editor-panel { box-sizing: border-box; width: min(760px, calc(100% + 72px)); display: grid; gap: var(--spacing-5); margin-block: var(--spacing-5); padding: var(--spacing-6); border-radius: var(--radius-10); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .expanded-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--spacing-5); }
  .expanded-header span { color: var(--color-font-secondary); font-size: var(--font-size-small); font-weight: 800; }
  .expanded-header h3, .detail-group h4, .detail-group p { margin: 0; }
  .remove-node { border: 0; border-radius: var(--radius-full); padding: var(--spacing-3) var(--spacing-5); background: var(--color-grey-20); }
  .node-field, .detail-group { display: grid; gap: var(--spacing-3); min-width: 0; }
  .node-field span, .detail-group h4 { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .node-field input, .node-field select { box-sizing: border-box; width: 100%; padding: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-6); color: var(--color-font-primary); background: var(--color-grey-0); font: inherit; }
  .node-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--spacing-4); }
  .node-field.wide { grid-column: span 2; }
  .node-note { margin: 0; color: var(--color-font-secondary); }
  .detail-group { padding: var(--spacing-5); border-radius: var(--radius-6); background: var(--color-grey-10); }
  .detail-group pre { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; color: var(--color-font-primary); }
  .detail-group.error { color: var(--color-danger); }
  .editor-toolbar { position: relative; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-block-start: 2px solid var(--color-grey-20); }
  .editor-toolbar button { display: flex; min-height: 84px; align-items: center; justify-content: center; gap: var(--spacing-3); border: 0; color: var(--color-font-secondary); background: transparent; font: inherit; font-weight: 800; cursor: pointer; }
  .editor-toolbar button + button { border-inline-start: 2px solid var(--color-grey-20); }
  .step-menu { position: absolute; z-index: 5; inset: calc(100% - var(--spacing-2)) 0 auto; display: grid; padding: var(--spacing-3); border-radius: var(--radius-6); background: var(--color-grey-0); box-shadow: var(--shadow-lg); }
  .step-menu button { min-height: 48px; justify-content: flex-start; padding-inline: var(--spacing-5); }
  .step-menu button + button { border-inline-start: 0; border-block-start: 1px solid var(--color-grey-20); }
  @media (max-width: 600px) { .graph-panel { margin: var(--spacing-4); padding: var(--spacing-3); } .graph-canvas { padding: var(--spacing-5); } .readiness-panel { grid-template-columns: 1fr; } .node-editor-panel { width: 100%; } .node-grid { grid-template-columns: 1fr; } .node-field.wide { grid-column: auto; } }
  @media (prefers-reduced-motion: reduce) { .workflow-card { transition: none; } }
</style>
