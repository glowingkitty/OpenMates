<!-- Progressive workflow authoring. Unsaved node inputs and test outputs stay in memory. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import { appsMetadata } from '../../data/appsMetadata';
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import ChatPreviewCard from '../settings/ChatPreviewCard.svelte';
  import WorkflowSchemaFields from './WorkflowSchemaFields.svelte';
  import { workflowApiRequest, workflowWorkspaceStore, type WorkflowGraph, type WorkflowNode, type WorkflowNodeRun } from '../../stores/workflowWorkspaceStore';
  import type { Chat } from '../../types/chat';
  import type { AppMetadata } from '../../types/apps';
  import { record, label, schemaDefault, normalizeSchema, isCheck, isTrigger, isMessage, capabilityFor, outputsBefore, insertNode, removeNode, type Capability, type Insertion, type Output } from './workflowBuilder';

  let { graph, readOnly = false, nodeRuns = [], testId = 'workflow-graph-renderer', workflowId = null, capabilityFixtures = null, onSave }: {
    graph: WorkflowGraph; readOnly?: boolean; nodeRuns?: WorkflowNodeRun[]; testId?: string; workflowId?: string | null; capabilityFixtures?: Capability[] | null;
    onChange: (graph: WorkflowGraph) => void; onSave: ((graph: WorkflowGraph) => Promise<void>) | null;
  } = $props();
  let capabilities = $state<Capability[]>([]);
  let loadError = $state('');
  let draft = $state<WorkflowNode | null>(null);
  let insertion = $state<Insertion>({ after: null });
  let picker = $state<'trigger' | 'action' | 'app' | 'skill' | null>(null);
  let selectedApp = $state('');
  let expandedReadOnly = $state<string | null>(null);
  let busy = $state(false);
  let nodeError = $state('');
  let testStatus = $state<'idle' | 'processing' | 'completed' | 'cancelled' | 'failed'>('idle');
  let testingRunId = $state<string | null>(null);
  let testOutputs = $state<Record<string, Record<string, unknown>>>({});
  let testRevision = 0;
  let preview = $state('');
  let chats = $state<Chat[]>([]);
  let chatSearch = $state('');
  let chooseChat = $state(false);
  let showReferences = $state(false);
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const Close = getLucideIcon('x'); const Down = getLucideIcon('chevron-down');
  const Coin = getLucideIcon('coins'); const Play = getLucideIcon('play'); const Stop = getLucideIcon('square');
  const available = $derived(capabilities.filter(item => item.type === 'app_skill' && item.enabled && item.metadata.app_id !== 'ai'));
  const appIds = $derived([...new Set(available.map(item => item.metadata.app_id).filter(Boolean))] as string[]);
  const draftCapability = $derived(draft ? capabilityFor(draft, capabilities) : undefined);
  const outputs = $derived(draft ? outputsBefore(graph, draft.id, capabilities, insertion) : []);
  const blocks = $derived(Array.isArray(draft?.config?.blocks) ? draft.config.blocks as Record<string, unknown>[] : []);
  const rootNodes = $derived(graph.nodes.filter(node => !graph.edges.some(edge => edge.to === node.id)).sort((a, b) => Number(isTrigger(b)) - Number(isTrigger(a))));

  onMount(() => {
    const setCapabilities = (items: Capability[]) => capabilities = items.map(item => ({ ...item, metadata: { ...item.metadata, input_schema: item.metadata.input_schema ? normalizeSchema(item.metadata.input_schema) : undefined, output_schema: item.metadata.output_schema ? normalizeSchema(item.metadata.output_schema) : undefined } }));
    if (capabilityFixtures) setCapabilities(capabilityFixtures);
    else if (!readOnly) void workflowApiRequest<{ capabilities: Capability[] }>('/v1/workflows/capabilities').then(data => setCapabilities(data.capabilities)).catch(error => loadError = error.message);
    return () => { testRevision += 1; };
  });
  function appMetadata(appId: string, capability?: Capability): AppMetadata {
    const app = (appsMetadata as Record<string, AppMetadata>)[appId];
    const skill = app?.skills.find(item => item.id === capability?.metadata.skill_id);
    if (!capability) return app ?? { id: appId, name: label(appId), icon_image: `${appId}.svg`, skills: [], focus_modes: [], settings_and_memories: [] };
    return { ...appMetadata(appId), name: capability.title, name_translation_key: skill?.name_translation_key, description: '', description_translation_key: skill?.description_translation_key, icon_image: skill?.icon_image ?? `${appId}.svg` };
  }
  function sameSlot(slot: Insertion): boolean { return insertion.after === slot.after && (insertion.branch ?? '') === (slot.branch ?? ''); }
  function openPicker(kind: typeof picker, slot: Insertion): void { if (busy || testStatus === 'processing') return; draft = null; nodeError = ''; preview = ''; insertion = slot; picker = kind; }
  function closeEditor(): void { draft = null; picker = null; nodeError = ''; preview = ''; chooseChat = false; showReferences = false; }
  function edit(node: WorkflowNode): void { if (busy || testStatus === 'processing') return; if (readOnly) { expandedReadOnly = expandedReadOnly === node.id ? null : node.id; return; } closeEditor(); draft = structuredClone(node); testStatus = testOutputs[node.id] ? 'completed' : 'idle'; }
  function configure(type: WorkflowNode['type'], capability?: Capability): void {
    if (busy || testStatus === 'processing') return;
    picker = null; nodeError = ''; preview = ''; testStatus = 'idle';
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    draft = { id: `${type}_${crypto.randomUUID().slice(0, 8)}`, type, title: '', config: {} };
    if (type === 'schedule_trigger') draft.config = { schedule: { type: 'daily', time: '09:00', timezone } };
    if (type === 'app_skill_action' && capability) {
      draft.title = appMetadata(capability.metadata.app_id!, capability).name_translation_key ? $text(appMetadata(capability.metadata.app_id!, capability).name_translation_key!) : capability.title;
      draft.config = { app_id: capability.metadata.app_id, skill_id: capability.metadata.skill_id, input: schemaDefault(capability.metadata.input_schema ?? { type: 'object' }) };
    }
    if (type === 'check') draft.config = { predicate: { left: '', op: '', right: '' } };
    if (type === 'send_chat_message') { draft.config = { title: '', message: '', blocks: [] }; chooseChat = true; void loadChats(); }
  }
  function patch(config: Record<string, unknown>): void { if (draft) { draft = { ...draft, config: { ...draft.config, ...config } }; preview = ''; } }
  function schedulePatch(config: Record<string, unknown>): void { patch({ schedule: { ...record(draft?.config?.schedule), ...config } }); }
  function predicatePatch(config: Record<string, unknown>): void { patch({ predicate: { ...record(draft?.config?.predicate), ...config } }); }
  function sourceSchema(reference: unknown) { return outputs.find(output => output.reference === reference)?.schema; }
  function operators(reference: unknown): string[] { const type = sourceSchema(reference)?.type; return ['number', 'integer'].includes(type ?? '') ? ['gt', 'gte', 'lt', 'lte', 'eq', 'ne'] : type === 'boolean' ? ['eq', 'ne'] : ['eq', 'ne', 'contains']; }
  function operatorSymbol(op: unknown): string { return ({ gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', ne: '≠', contains: tr('contains') } as Record<string, string>)[String(op)] ?? ''; }
  function nodeIcon(node: WorkflowNode): string { return isTrigger(node) ? 'calendar-clock' : isCheck(node) ? 'git-branch' : isMessage(node) ? 'messages-square' : ({ weather: 'cloud-sun', news: 'newspaper', events: 'calendar-days', home: 'house' } as Record<string, string>)[String(node.config?.app_id)] ?? 'blocks'; }
  function kind(node: WorkflowNode): string { return tr(isTrigger(node) ? 'time_trigger' : isCheck(node) ? 'check' : isMessage(node) ? 'send_message' : node.type === 'app_skill_action' ? 'use_app_skill' : 'action'); }
  function summary(node: WorkflowNode): string {
    if (isTrigger(node)) { const schedule = record(node.config?.schedule); if (schedule.type === 'hourly') return `${tr('hourly')} · :${String(schedule.minute ?? 0).padStart(2, '0')}`; if (schedule.type === 'once') return String(schedule.at ?? tr('once')); return `${tr(String(schedule.type ?? 'daily'))}${schedule.type === 'weekly' ? ` · ${(Array.isArray(schedule.weekdays) ? schedule.weekdays : ['sunday']).map(day => tr(String(day))).join(', ')}` : ''}, ${schedule.time ?? '09:00'}`; }
    if (isCheck(node)) { const predicate = record(node.config?.predicate); const output = outputsBefore(graph, node.id, capabilities).find(item => item.reference === predicate.left); return `${output?.label ?? label(String(predicate.left ?? '').split('.').at(-1) ?? '')} ${operatorSymbol(predicate.op)} ${String(predicate.right ?? '')}`; }
    if (isMessage(node)) return String(node.config?.chat_id ? `${tr('to')} ${chats.find(chat => chat.chat_id === node.config?.chat_id)?.title ?? tr('existing_chat')}` : tr('new_chat_each_run'));
    const capability = capabilityFor(node, capabilities); return capability ? `${label(String(node.config?.app_id))} | ${appMetadata(String(node.config?.app_id), capability).name_translation_key ? $text(appMetadata(String(node.config?.app_id), capability).name_translation_key!) : label(String(node.config?.skill_id))}` : node.title || label(node.type);
  }
  function style(node: WorkflowNode): string { const appId = String(node.config?.app_id ?? 'workflows'); return `--node-gradient: var(--color-app-${appId}, var(--color-primary));`; }
  function nextId(nodeId: string, branch?: string): string | undefined { return graph.edges.find(edge => edge.from === nodeId && (edge.branch ?? '') === (branch ?? ''))?.to; }
  function detail(value: unknown): string { return value === undefined || value === null ? tr('unavailable') : typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
  async function saveNode(): Promise<void> {
    if (!draft || !onSave || busy) return;
    if (isMessage(draft) && !String(draft.config?.title ?? '').trim()) { nodeError = tr('title_required'); return; }
    if (isCheck(draft) && (!record(draft.config?.predicate).left || !record(draft.config?.predicate).op)) { nodeError = tr('check_required'); return; }
    busy = true; nodeError = '';
    const saved = structuredClone(draft); saved.title ||= summary(saved);
    try {
      await onSave({ ...insertNode(graph, saved, insertion), version: 2 }); closeEditor();
      if (isTrigger(saved) && !graph.nodes.some(node => !isTrigger(node) && node.type !== 'end')) openPicker('action', { after: saved.id });
      else if (isCheck(saved)) openPicker('action', { after: saved.id, branch: 'yes' });
    } catch (error) { nodeError = error instanceof Error ? error.message : tr('save_failed'); }
    finally { busy = false; }
  }
  async function deleteNode(): Promise<void> { if (!draft || !onSave || busy) return; busy = true; try { await onSave({ ...removeNode(graph, draft.id), version: 2 }); closeEditor(); } catch (error) { nodeError = String(error); } finally { busy = false; } }
  async function testNode(): Promise<void> {
    if (!draft || !workflowId || testStatus === 'processing') return;
    const node = structuredClone(draft); const revision = ++testRevision; testStatus = 'processing'; nodeError = '';
    try {
      const data = await workflowApiRequest<{ run: { id: string } }>(`/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(node.id)}/test`, { method: 'POST', body: JSON.stringify({ node, input: {}, upstream_outputs: testOutputs }) });
      testingRunId = data.run.id;
      for (let attempt = 0; attempt < 60 && revision === testRevision; attempt++) {
        const run = await workflowWorkspaceStore.getWorkflowRun(workflowId, data.run.id);
        if (!['accepted', 'queued', 'running', 'cancellation_requested'].includes(run.status)) {
          const result = run.node_runs?.find(item => item.node_id === node.id);
          if (run.status === 'completed') { testOutputs = { ...testOutputs, [node.id]: result?.output_summary ?? run.output_summary ?? {} }; testStatus = 'completed'; }
          else { testStatus = run.status === 'cancelled' ? 'cancelled' : 'failed'; nodeError = result?.error_summary ?? run.error_summary ?? run.status; }
          testingRunId = null; return;
        }
        await new Promise(resolve => setTimeout(resolve, Math.min(1500 + attempt * 500, 5000)));
      }
      if (revision === testRevision) { testStatus = 'idle'; nodeError = tr('test_pending'); }
    } catch (error) { if (revision === testRevision) { testStatus = 'failed'; nodeError = error instanceof Error ? error.message : String(error); } }
  }
  async function stopTest(): Promise<void> { if (!workflowId || !testingRunId) return; try { await workflowWorkspaceStore.cancelWorkflowRun(workflowId, testingRunId); } catch (error) { nodeError = String(error); } }
  async function loadChats(): Promise<void> { try { const { chatDB } = await import('../../services/db'); chats = await chatDB.getAllChats(undefined, { limit: 100 }); } catch { nodeError = tr('chats_unavailable'); } }
  function selectChat(chat: Chat | null): void { patch({ chat_id: chat?.chat_id ?? null }); chooseChat = false; }
  function addReference(output: Output): void {
    if (!draft) return;
    if (['array', 'object'].includes(output.schema.type ?? '')) {
      if (!blocks.some(block => block.source === output.reference)) patch({ blocks: [...blocks, { id: `block_${crypto.randomUUID().slice(0, 8)}`, source: output.reference, only_new_results: false }] });
    } else patch({ message: `${String(draft.config?.message ?? '').replace(/@$/, '')}{{${output.reference.replace(/^\$nodes\./, 'steps.').replace('.output.', '.')}}}` });
    showReferences = false;
  }
  function patchBlock(index: number, values: Record<string, unknown>): void { patch({ blocks: blocks.map((block, i) => i === index ? { ...block, ...values } : block) }); }
  async function previewMessage(): Promise<void> {
    if (!workflowId || !draft) return; busy = true; nodeError = '';
    try { const data = await workflowApiRequest<{ preview: { text?: string; message?: string; body?: string } }>(`/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(draft.id)}/preview`, { method: 'POST', body: JSON.stringify({ node: draft, input: {}, upstream_outputs: testOutputs }) }); preview = data.preview.text ?? data.preview.message ?? data.preview.body ?? tr('empty_preview'); }
    catch (error) { nodeError = error instanceof Error ? error.message : String(error); } finally { busy = false; }
  }
</script>

{#snippet choice(icon: string, title: string, action: () => void, testId?: string)}
  {@const Icon = getLucideIcon(icon)}<button type="button" class="choice" data-testid={testId} onclick={action}><Icon size={23}/><span>{title}</span></button>
{/snippet}

{#snippet slotControls(slot: Insertion)}
  {#if !readOnly}
    {#if sameSlot(slot) && (picker || (draft && !graph.nodes.some(node => node.id === draft?.id)))}
      {#if draft}{@render editor()}{:else}{@render pickerPanel()}{/if}
    {:else}
      <div class="add-controls" data-testid="workflow-action-palette">
        {#if !graph.nodes.some(isTrigger) && !slot.branch}{@render choice('calendar-clock', tr('add_trigger'), () => openPicker('trigger', slot), 'workflow-add-time-trigger')}{/if}
        {@render choice('blocks', tr('add_action'), () => openPicker('action', slot), 'workflow-add-step')}
        {#if slot.after && graph.nodes.some(node => node.id === slot.after && !isTrigger(node))}{@render choice('git-branch', tr('add_check'), () => { insertion = slot; configure('check'); }, 'add-decision-node')}{/if}
      </div>
    {/if}
  {/if}
{/snippet}

{#snippet pickerPanel()}
  <div class="editor picker" data-testid="workflow-step-menu">
    <div class="panel-top"><button type="button" class="quiet" onclick={() => picker = picker === 'skill' ? 'app' : 'action'}>{picker === 'app' || picker === 'skill' ? '‹ ' + tr('back') : ''}</button><span>{tr(picker === 'trigger' ? 'add_trigger' : picker === 'app' ? 'use_app' : picker === 'skill' ? 'choose_skill' : 'add_action')}</span><button type="button" class="quiet" aria-label={tr('close')} onclick={closeEditor}><Close size={19}/></button></div>
    <h3>{tr(picker === 'trigger' ? 'trigger_question' : picker === 'app' ? 'app_question' : picker === 'skill' ? 'skill_question' : 'action_question')}</h3>
    {#if picker === 'trigger'}<div class="choices">{@render choice('calendar-days', tr('date_time'), () => configure('schedule_trigger'), 'workflow-trigger-date-time')}</div>
    {:else if picker === 'action'}<div class="choices">{@render choice('blocks', tr('use_app'), () => picker = 'app', 'workflow-step-app-skill-action')}{@render choice('messages-square', tr('send_message'), () => configure('send_chat_message'), 'workflow-step-create-chat-report')}{#if insertion.after && !isTrigger(graph.nodes.find(node => node.id === insertion.after)!)}{@render choice('git-branch', tr('add_check'), () => configure('check'))}{/if}</div>
    {:else if picker === 'app'}<div class="card-scroll">{#each appIds as appId}<AppStoreCard app={appMetadata(appId)} onSelect={() => { selectedApp = appId; picker = 'skill'; }}/>{/each}</div>{#if !appIds.length}<p>{loadError || tr('loading_apps')}</p>{/if}
    {:else if picker === 'skill'}<div class="card-scroll">{#each available.filter(item => item.metadata.app_id === selectedApp) as capability}<AppStoreCard app={appMetadata(selectedApp, capability)} cardIconType="skill" onSelect={() => configure('app_skill_action', capability)}/>{/each}</div>{/if}
  </div>
{/snippet}

{#snippet editor()}
  {#if draft}
    {@const predicate = record(draft.config?.predicate)}
    {@const schedule = record(draft.config?.schedule)}
    <div class="editor" data-testid="workflow-node-expanded">
      <div class="panel-top"><span></span><span>{kind(draft)}</span><button type="button" class="quiet" disabled={busy || testStatus === 'processing'} aria-label={tr('close')} onclick={closeEditor}><Close size={19}/></button></div>
      {#if isTrigger(draft)}
        <h3>{tr('date_time')}</h3><div class="field-grid">
          <label>{tr('repeat')}<select data-testid="workflow-time-trigger-schedule" value={String(schedule.type ?? 'daily')} onchange={event => { const type = event.currentTarget.value; patch({ schedule: { type, timezone: schedule.timezone, ...(type === 'hourly' ? { minute: 0 } : type === 'once' ? { at: '' } : { time: schedule.time ?? '09:00', ...(type === 'weekly' ? { weekdays: ['sunday'] } : {}) }) } }); }}><option value="once">{tr('once')}</option><option value="hourly">{tr('hourly')}</option><option value="daily">{tr('daily')}</option><option value="weekly">{tr('weekly')}</option></select></label>
          {#if schedule.type === 'once'}<label>{tr('date_time')}<input type="datetime-local" value={String(schedule.at ?? '').slice(0, 16)} onchange={event => schedulePatch({ at: event.currentTarget.value })}/></label>
          {:else if schedule.type === 'hourly'}<label>{tr('minute')}<input type="number" min="0" max="59" value={Number(schedule.minute ?? 0)} oninput={event => schedulePatch({ minute: Number(event.currentTarget.value) })}/></label>
          {:else}<label>{tr('time')}<input type="time" value={String(schedule.time ?? '09:00')} oninput={event => schedulePatch({ time: event.currentTarget.value })}/></label>{/if}
          <label>{tr('timezone')}<input value={String(schedule.timezone ?? '')} oninput={event => schedulePatch({ timezone: event.currentTarget.value })}/></label>
        </div>
        {#if schedule.type === 'weekly'}<div class="weekdays">{#each ['monday','tuesday','wednesday','thursday','friday','saturday','sunday'] as day}<label><input type="checkbox" checked={Array.isArray(schedule.weekdays) && schedule.weekdays.includes(day)} onchange={event => schedulePatch({ weekdays: event.currentTarget.checked ? [...(Array.isArray(schedule.weekdays) ? schedule.weekdays : []), day] : (Array.isArray(schedule.weekdays) ? schedule.weekdays : []).filter(item => item !== day) })}/>{tr(day)}</label>{/each}</div>{/if}
      {:else if draft.type === 'app_skill_action'}
        {@const Icon = getLucideIcon(nodeIcon(draft))}
        <div class="skill-heading" style={style(draft)}><Icon size={28}/><h3>{summary(draft)}</h3></div>
        <h4>↓ {tr('input')}</h4>
        {#if draftCapability?.metadata.input_schema}<WorkflowSchemaFields schema={draftCapability.metadata.input_schema} value={draft.config?.input} {outputs} path={draft.id} onChange={value => patch({ input: value })}/>{:else}<p>{loadError || tr('schema_unavailable')}</p>{/if}
        <div class="test-control">
          {#if testStatus === 'processing'}<span aria-live="polite">{tr('processing')}</span>{#if testingRunId}<button type="button" class="quiet" onclick={() => void stopTest()}><Stop size={16}/>{tr('stop')}</button>{/if}
          {:else}<button type="button" class="quiet test" data-testid="workflow-test-action" disabled={!workflowId || draftCapability?.metadata.workflow?.test_allowed === false || !draftCapability} onclick={() => void testNode()}><Play size={16}/>{tr(testOutputs[draft.id] ? 'test_again' : 'test_action')}<Coin size={16}/><span>{draftCapability?.metadata.cost?.fixed ?? draftCapability?.metadata.cost?.per_unit?.credits ?? tr('variable_cost')}</span></button>{/if}
        </div>
        <div class="output-heading"><h4>↑ {tr('output')}</h4><span>{tr(testOutputs[draft.id] ? 'test_output' : 'example')}</span></div>
        <div class="output-fields" data-testid="workflow-output-fields">{#each Object.entries(draftCapability?.metadata.output_schema?.properties ?? {}) as [key, spec]}<div><span class="type">{spec.type ?? 'text'}</span><strong>{spec.title || label(key)}</strong><pre>{detail(testOutputs[draft.id] ? testOutputs[draft.id][key] : spec.example ?? spec.examples?.[0] ?? spec.default)}</pre></div>{/each}</div>
      {:else if isCheck(draft)}
        <h3>{tr('check_question')}</h3><h2>{tr('if')}</h2>
        <div class="check-fields"><select aria-label={tr('select_output')} value={String(predicate.left ?? '')} onchange={event => predicatePatch({ left: event.currentTarget.value, op: '', right: '' })}><option value="">{tr('select_output')}</option>{#each outputs.filter(item => !['array','object'].includes(item.schema.type ?? '')) as output}<option value={output.reference}>{output.label}</option>{/each}</select>
          {#if predicate.left}<select aria-label={tr('compare_type')} value={String(predicate.op ?? '')} onchange={event => predicatePatch({ op: event.currentTarget.value, right: sourceSchema(predicate.left)?.type === 'boolean' ? true : '' })}><option value="">{tr('compare_type')}</option>{#each operators(predicate.left) as op}<option value={op}>{operatorSymbol(op)} {tr(`operator_${op}`)}</option>{/each}</select>{/if}
          {#if predicate.op}<span class="type">{sourceSchema(predicate.left)?.type ?? 'text'}</span>{#if sourceSchema(predicate.left)?.type === 'boolean'}<select aria-label={tr('compare_value')} value={String(predicate.right)} onchange={event => predicatePatch({ right: event.currentTarget.value === 'true' })}><option value="true">{tr('true')}</option><option value="false">{tr('false')}</option></select>{:else}<input aria-label={tr('compare_value')} type={['number','integer'].includes(sourceSchema(predicate.left)?.type ?? '') ? 'number' : 'text'} value={String(predicate.right ?? '')} oninput={event => predicatePatch({ right: ['number','integer'].includes(sourceSchema(predicate.left)?.type ?? '') ? Number(event.currentTarget.value) : event.currentTarget.value })}/>{/if}{/if}
        </div>
      {:else if isMessage(draft)}
        {#if chooseChat}<h3>{tr('chat_question')}</h3><input aria-label={tr('search_chats')} placeholder={tr('search_chats')} bind:value={chatSearch}/><div class="card-scroll">{#each chats.filter(chat => (chat.title ?? '').toLowerCase().includes(chatSearch.toLowerCase())) as chat}<ChatPreviewCard {chat} onOpen={selectChat}/>{/each}</div><button class="primary" type="button" onclick={() => selectChat(null)}>+ {tr('new_chat')}</button>
        {:else}
          <h3>{tr('message_question')}</h3><button class="quiet target" type="button" onclick={() => { chooseChat = true; void loadChats(); }}>{tr('to')}: {summary(draft)}</button>
          <label>{tr('chat_title')}<input data-testid="workflow-message-title" value={String(draft.config?.title ?? '')} oninput={event => patch({ title: event.currentTarget.value })}/></label>
          <div class="reference-chips">{#each outputs as output}<button type="button" class="chip" onclick={() => addReference(output)}>+ {output.label}</button>{/each}</div>
          <textarea data-testid="workflow-message-template" rows="5" placeholder={tr('message_placeholder')} value={String(draft.config?.message ?? draft.config?.summary ?? '')} oninput={event => { patch({ message: event.currentTarget.value }); showReferences = event.currentTarget.value.endsWith('@'); }}></textarea>
          {#if showReferences}<div class="references" aria-label={tr('select_output')}>{#each outputs as output}<button type="button" class="quiet" onclick={() => addReference(output)}>{output.label}</button>{/each}</div>{/if}
          {#each blocks as block, index}<div class="message-block"><div><strong>{outputs.find(output => output.reference === block.source)?.label ?? String(block.source)}</strong><button type="button" class="quiet" aria-label={tr('remove')} onclick={() => patch({ blocks: blocks.filter((_, i) => i !== index) })}>×</button></div>
            {#if sourceSchema(block.source)?.type === 'array'}<label class="checkbox"><input type="checkbox" checked={block.only_new_results === true} onchange={event => patchBlock(index, { only_new_results: event.currentTarget.checked })}/>{tr('only_new_results')}</label>{/if}
            <label>{tr('include_when')}<select value={String(block.include_if ?? '')} onchange={event => patchBlock(index, { include_if: event.currentTarget.value || null })}><option value="">{tr('always')}</option>{#each outputs.filter(output => output.schema.type === 'boolean') as output}<option value={output.reference}>{output.label} = {tr('true')}</option>{/each}</select></label>
          </div>{/each}
          <button class="quiet" type="button" data-testid="workflow-preview-message" disabled={busy || !String(draft.config?.title ?? '').trim()} onclick={() => void previewMessage()}>{tr('preview_message')}</button>
          {#if preview}<pre class="message-preview" data-testid="workflow-message-preview">{preview}</pre>{/if}
        {/if}
      {:else}<pre>{detail(draft.config)}</pre>{/if}
      {#if nodeError}<p class="error" role="alert">{nodeError}</p>{/if}
      {#if !chooseChat}<div class="save-row"><button type="button" class="primary" data-testid="workflow-node-save" disabled={busy || testStatus === 'processing'} onclick={() => void saveNode()}>{tr(busy ? 'saving' : 'save')}</button>{#if graph.nodes.some(node => node.id === draft?.id)}<button type="button" class="quiet" data-testid="remove-workflow-node" disabled={busy || testStatus === 'processing'} onclick={() => void deleteNode()}>{tr('remove')}</button>{/if}</div>{/if}
    </div>
  {/if}
{/snippet}

{#snippet chain(nodeId: string, visited: string[] = [], stopAt?: string)}
  {@const node = graph.nodes.find(item => item.id === nodeId)}
  {#if node && node.type !== 'end' && !visited.includes(nodeId) && nodeId !== stopAt}
    {@const Icon = getLucideIcon(nodeIcon(node))}
    {@const run = nodeRuns.find(item => item.node_id === node.id)}
    <article class="flow-node" data-node-id={node.id} data-node-type={node.type} data-testid="workflow-node-card">
      {#if draft?.id === node.id}{@render editor()}{:else}
        <button type="button" class="node-summary" class:skill={node.type === 'app_skill_action'} style={style(node)} data-testid="workflow-node-summary" aria-expanded={expandedReadOnly === node.id} onclick={() => edit(node)}><span class="kind">{kind(node)}</span><Icon size={26}/><strong data-testid="workflow-node-title-label">{summary(node)}</strong>{#if node.type === 'app_skill_action' && record(node.config?.input).location}<span class="location">{String(record(node.config?.input).location)}</span>{/if}{#if run}<span data-testid="workflow-run-node-status" data-node-status={run.status}>{String(isMessage(node) && run.output_summary?.status ? run.output_summary.status : run.status).replaceAll('_',' ')}</span>{/if}<Down size={16}/></button>
        {#if readOnly && expandedReadOnly === node.id}<div class="editor" data-testid="workflow-node-expanded">{#if run}<h4>{tr('input')}</h4><pre>{detail(run.input_summary)}</pre><h4>{tr('output')}</h4><pre>{detail(run.output_summary)}</pre>{#if run.error_summary}<p class="error">{run.error_summary}</p>{/if}{#if run.skipped_reason}<p>{run.skipped_reason}</p>{/if}{:else}<pre>{detail(node.config)}</pre>{/if}</div>{/if}
      {/if}
    </article>
    {#if isCheck(node)}
      {@const continuation = nextId(node.id)}
      <div class="branch-group">
        {#each ['yes','no'] as branch}{@const target = nextId(node.id, branch) ?? nextId(node.id, branch === 'yes' ? 'true' : 'false')}<div class="branch"><div class="connector branch-label">⑂ {tr(branch === 'yes' ? 'if_true' : 'else')}</div>{#if target}{@render chain(target, [...visited, node.id], continuation)}{:else}{#if !readOnly}<p class="nothing">{tr('do_nothing')}</p>{@render slotControls({ after: node.id, branch })}{:else}<p class="nothing">{tr('do_nothing')}</p>{/if}{/if}</div>{/each}
      </div>
    {/if}
    {@const next = nextId(node.id)}
    {#if next && next !== stopAt && graph.nodes.find(item => item.id === next)?.type !== 'end'}<div class="connector">{tr('then')}</div>{@render chain(next, [...visited, node.id], stopAt)}
    {:else if !readOnly}<div class="connector">{tr('then')}</div>{@render slotControls({ after: node.id })}{/if}
  {/if}
{/snippet}

<section class="graph-panel" data-testid={testId} data-read-only={readOnly ? 'true' : 'false'}>
  <div class="graph-canvas"><div class="node-stack" data-testid="workflow-node-stack">
    {#each rootNodes as root}{@render chain(root.id)}{/each}
    {#if !graph.nodes.some(node => node.type !== 'end')}{@render slotControls({ after: null })}{/if}
  </div></div>
</section>

<style>
  .graph-panel{margin:0 auto;width:min(54rem,calc(100% - 2rem));padding:0 0 2rem}.graph-canvas{min-height:16rem;padding:2rem 1.25rem;background:var(--color-grey-0);border-radius:.9rem}.node-stack{display:grid;justify-items:center}.flow-node{display:grid;justify-items:center;width:100%;min-width:0}.node-summary{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.5rem;width:min(19rem,100%);padding:.7rem 1rem .4rem;min-height:8rem;border:0;border-radius:1rem;background:var(--color-grey-10);color:var(--color-font-primary);box-shadow:var(--shadow-sm);cursor:pointer;font:inherit}.node-summary strong{font-size:.9rem;line-height:1.4}.node-summary> :global(svg){color:var(--color-primary)}.node-summary .kind{font-size:.7rem;color:var(--color-font-secondary)}.node-summary.skill{background:var(--node-gradient);color:var(--color-font-button)}.node-summary.skill .kind,.node-summary.skill> :global(svg){color:var(--color-font-button);opacity:.9}.location{font-size:.75rem;opacity:.8}.connector{color:var(--color-font-secondary);font-size:.8rem;font-weight:650;text-align:center;padding:.8rem 0}.branch-group{width:min(42rem,100%);padding:0 .75rem .7rem;border:1px solid var(--color-grey-20);border-radius:1rem;margin-top:-.5rem;box-sizing:border-box}.branch{display:grid;justify-items:center}.branch .branch-label{padding-top:1rem}.nothing{margin:0;border:1px dashed var(--color-grey-30);border-radius:.6rem;width:min(18rem,90%);padding:.7rem;text-align:center;color:var(--color-font-secondary);font-size:.75rem}.add-controls,.choices{display:flex;flex-wrap:wrap;gap:.8rem;justify-content:center;padding:.75rem 0}.choice{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.6rem;min-width:6.5rem;min-height:4.5rem;border:0;border-radius:.7rem;color:var(--color-font-secondary);background:var(--color-grey-10);box-shadow:var(--shadow-sm);padding:.65rem;cursor:pointer;font:inherit;font-size:.75rem;font-weight:600}.choice :global(svg){color:var(--color-primary)}.editor{position:relative;width:min(42rem,100%);box-sizing:border-box;display:grid;gap:1rem;padding:0 1.5rem 1rem;background:var(--color-grey-10);border-radius:1rem;box-shadow:var(--shadow-sm);color:var(--color-font-primary);text-align:center}.picker{min-height:11rem}.panel-top{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;min-height:2rem;color:var(--color-font-secondary);font-size:.72rem}.panel-top button:first-child{justify-self:start}.panel-top button:last-child{justify-self:end}h2,h3,h4,p{margin:0}h3{font-size:.92rem}h4{font-size:.8rem;text-align:start;color:var(--color-font-secondary)}.skill-heading{display:grid;gap:.55rem;place-items:center;padding:1.25rem;margin:-1rem -1.5rem 0;background:var(--node-gradient);color:var(--color-font-button);border-radius:0 0 1rem 1rem}.card-scroll{display:flex;gap:1rem;overflow-x:auto;width:100%;padding:.5rem 0 1rem;scroll-snap-type:x proximity}.card-scroll :global(>button){flex-shrink:0;scroll-snap-align:center}.quiet{display:inline-flex;align-items:center;justify-content:center;gap:.35rem;min-height:2rem;padding:.3rem .5rem;border:0;box-shadow:none;background:transparent;color:var(--color-primary);font:inherit;font-size:.75rem;cursor:pointer}.primary{justify-self:center;min-width:9rem;min-height:2.4rem;border:0;border-radius:.8rem;padding:.55rem 1.2rem;font:inherit;font-size:.85rem;font-weight:650;background:var(--color-button-primary);color:var(--color-font-button);box-shadow:var(--shadow-sm);cursor:pointer}.field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}label{display:grid;gap:.4rem;min-width:0;text-align:start;font-size:.78rem}input,select,textarea{box-sizing:border-box;width:100%;min-height:2.5rem;border:1px solid var(--color-grey-25);border-radius:.8rem;padding:.5rem .7rem;background:var(--color-grey-0);color:var(--color-font-primary);font:inherit;font-size:.85rem;box-shadow:var(--shadow-sm)}textarea{resize:vertical;line-height:1.5;user-select:text}.weekdays{display:flex;gap:.7rem;flex-wrap:wrap}.weekdays label,.checkbox{display:flex;align-items:center;gap:.45rem}.weekdays input,input[type=checkbox]{width:1.05rem;height:1.05rem;min-height:0;box-shadow:none;accent-color:var(--color-primary)}.test-control{display:flex;justify-content:center;align-items:center;gap:.7rem;font-size:.8rem}.output-heading{display:flex;justify-content:space-between;font-size:.75rem;color:var(--color-font-secondary)}.output-fields{display:grid;gap:.5rem;text-align:start}.output-fields>div{display:grid;grid-template-columns:auto 1fr minmax(4rem,40%);align-items:start;gap:.4rem}.output-fields strong{font-size:.75rem}.type{font-size:.65rem;border-radius:.2rem;background:var(--color-primary);color:var(--color-font-button);padding:.1rem .3rem;width:fit-content}.output-fields pre{font-size:.75rem;max-height:10rem;overflow:auto;margin:0;color:var(--color-font-secondary);animation:output-appear .2s ease}.check-fields{display:grid;gap:.8rem;width:min(23rem,100%);margin:auto}.check-fields>.type{justify-self:center}.reference-chips{display:flex;flex-wrap:wrap;gap:.4rem}.chip{border:0;border-radius:1rem;padding:.3rem .55rem;background:var(--color-primary);color:var(--color-font-button);font:inherit;font-size:.67rem;cursor:pointer}.message-block{border:1px solid var(--color-grey-25);border-radius:.7rem;padding:.7rem;display:grid;gap:.6rem;text-align:start;font-size:.8rem}.message-block>div{display:flex;justify-content:space-between;align-items:center;gap:.5rem}.message-block strong{overflow-wrap:anywhere}.references{display:grid;text-align:start}.message-preview,pre{white-space:pre-wrap;overflow-wrap:anywhere;user-select:text;text-align:start;font-size:.8rem}.message-preview{padding:1rem;background:var(--color-grey-0);border-radius:.8rem}.save-row{display:flex;justify-content:center;align-items:center;gap:1rem;margin-top:.3rem}.error{color:var(--color-error);font-size:.8rem;overflow-wrap:anywhere}.target{justify-self:start}button:disabled{opacity:.55;cursor:wait}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}
  @keyframes output-appear{from{opacity:0}to{opacity:1}}@media(max-width:730px){.graph-panel{width:calc(100% - 1rem)}.graph-canvas{padding:1.5rem .5rem}.editor{padding:0 .8rem 1rem}.skill-heading{margin-inline:-.8rem}.field-grid{grid-template-columns:1fr}.branch-group{padding-inline:.4rem}.choice{min-width:5.6rem}.card-scroll :global(.resume-chat-large-card){width:15rem;min-width:15rem;max-width:15rem}.output-fields>div{grid-template-columns:auto 1fr}.output-fields pre{grid-column:1/-1}}@media(prefers-reduced-motion:reduce){.output-fields pre{animation:none}}
</style>
