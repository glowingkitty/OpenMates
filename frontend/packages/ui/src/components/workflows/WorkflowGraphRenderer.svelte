<!-- Progressive workflow authoring. Unsaved node inputs and test outputs stay in memory. -->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { get } from 'svelte/store';
  import { text } from '../../i18n/translations';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import { appsMetadata } from '../../data/appsMetadata';
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import ChatPreviewCard from '../settings/ChatPreviewCard.svelte';
  import SettingsDropdown from '../settings/elements/SettingsDropdown.svelte';
  import WorkflowEditorHeader from './WorkflowEditorHeader.svelte';
  import WorkflowSchemaFields from './WorkflowSchemaFields.svelte';
  import WorkflowValueView from './WorkflowValueView.svelte';
  import WorkflowOutputFields from './WorkflowOutputFields.svelte';
  import WorkflowMessageEditor from './WorkflowMessageEditor.svelte';
  import WorkflowVariablePicker, { type VariableSource } from './WorkflowVariablePicker.svelte';
  import WorkflowAskAiTestPreview from './WorkflowAskAiTestPreview.svelte';
  import type { WorkflowPreviewEmbed } from '../../services/workflowStepTestStream';
  import ComposerModelSelector from '../enter_message/ComposerModelSelector.svelte';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { panelState } from '../../stores/panelStateStore';
  import { userProfile } from '../../stores/userProfile';
  import { isProviderHealthy } from '../../stores/appHealthStore';
  import { notificationStore } from '../../stores/notificationStore';
  import { canonicalizeAiModelSelection, isAiModelSelectionUsable } from '../../utils/aiModelSelection';
  import { streamWorkflowStepTest } from '../../services/workflowStepTestStream';
  import { outputTemplateSyntax } from './workflowMessageTokens';
  import { outputFields, presentedItems, valueEntries } from './workflowValuePresentation';
  import { workflowFieldIcon } from './workflowFieldIcon';
  import { workflowSkillInputSummary } from './workflowSkillSummary';
  import { workflowOutputExamples, workflowUpstreamOutputs } from './workflowOutputExamples';
  import { WorkflowApiError, workflowApiRequest, workflowWorkspaceStore, type WorkflowGraph, type WorkflowNode, type WorkflowNodeRun, type WorkflowRunDetail } from '../../stores/workflowWorkspaceStore';
  import type { Chat } from '../../types/chat';
  import type { AppMetadata } from '../../types/apps';
  import { record, label, schemaDefault, normalizeSchema, isAskAi, isCheck, isTrigger, isMessage, messageDestinationConfig, capabilityFor, outputsBefore, insertNode, removeNode, WorkflowNodeDependencyError, type Capability, type Insertion, type Output, type Schema } from './workflowBuilder';
  import { canMoveWorkflowNode, moveWorkflowNode, moveWorkflowNodeAfter } from './workflowReordering';

  let { graph, readOnly = false, nodeRuns = [], testId = 'workflow-graph-renderer', workflowId = null, capabilityFixtures = null, chatFixtures = null, aiAddedNodeIds = [], aiEditedNodeIds = [], onChange, onSave = null, onDraftStateChange }: {
    graph: WorkflowGraph; readOnly?: boolean; nodeRuns?: WorkflowNodeRun[]; testId?: string; workflowId?: string | null; capabilityFixtures?: Capability[] | null; chatFixtures?: Chat[] | null;
    aiAddedNodeIds?: string[]; aiEditedNodeIds?: string[];
    onChange: (graph: WorkflowGraph) => void; onSave?: ((graph: WorkflowGraph) => Promise<void>) | null;
    onDraftStateChange?: (hasDraft: boolean) => void;
  } = $props();
  let capabilities = $state<Capability[]>([]);
  let capabilityLoad: Promise<void> | null = null;
  let loadError = $state('');
  let draft = $state<WorkflowNode | null>(null);
  $effect(() => { onDraftStateChange?.(!readOnly && draft !== null); });
  let insertion = $state<Insertion>({ after: null });
  let picker = $state<'trigger' | 'action' | 'app' | 'skill' | null>(null);
  let selectedApp = $state('');
  let deleteArmed = $state(false);
  let expandedReadOnly = $state<string | null>(null);
  let busy = $state(false);
  let draggingNodeId = $state<string | null>(null);
  let dropSlotId = $state<string | null>(null);
  let pointerCandidate: { id: string; pointerId: number; x: number; y: number } | null = null;
  let suppressNodeClick = false;
  let nodeError = $state('');
  let testStatus = $state<'idle' | 'processing' | 'completed' | 'cancelled' | 'failed'>('idle');
  let streamedTestEmbeds = $state<WorkflowPreviewEmbed[]>([]);
  let testingRunId = $state<string | null>(null);
  let testOutputs = $state<Record<string, Record<string, unknown>>>({});
  let testOutputWorkflowId = $state<string | null>(null);
  let testRevision = 0;
  let preview = $state<Record<string, unknown> | null>(null);
  let chats = $state<Chat[]>([]);
  let chatSearch = $state('');
  const visibleChats = $derived(chatSearch.trim() ? chats.filter(chat => (chat.title ?? '').toLowerCase().includes(chatSearch.trim().toLowerCase())) : chats.slice(0, 6));
  let chooseChat = $state(false);
  let showReferences = $state(false);
  let mentionQuery = $state('');
  let selectedVariableSource = $state<string | null>(null);
  let streamedTestAnswer = $state('');
  let testAbort: AbortController | null = null;
  let showOutputFields = $state(false);
  let graphPanel = $state<HTMLElement>();
  let messageEditor = $state<{ insertReference: (output: Output) => void; removeMentionTrigger: () => void } | null>(null);
  let selectedCheckSource = $state<string | null>(null);
  let selectedCompareSource = $state<string | null>(null);
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const Play = getLucideIcon('play'); const Stop = getLucideIcon('square'); const Search = getLucideIcon('search');
  const Download = getLucideIcon('download'); const Upload = getLucideIcon('upload');
  const available = $derived(capabilities.filter(item => item.type === 'app_skill' && item.enabled && item.id !== 'ai.ask'));
  const askCapability = $derived(capabilities.find(item => item.id === 'ai.ask' && item.enabled));
  const appIds = $derived([...new Set(available.map(item => item.metadata.app_id).filter(Boolean))] as string[]);
  const draftCapability = $derived(draft ? capabilityFor(draft, capabilities) : undefined);
  const persistedDraft = $derived(!!draft && graph.nodes.some(node => node.id === draft?.id));
  const outputs = $derived((draft ? outputsBefore(graph, draft.id, capabilities, insertion) : []).map(output => {
    const node = graph.nodes.find(node => node.id === output.nodeId);
    if (node?.config?.app_id !== 'web' || node.config?.skill_id !== 'read') return output;
    const field = output.reference.split('.output.')[1];
    if (!['text','has_changed','changes','source_url'].includes(field)) return output;
    return { ...output, label: `${summary(node)} · ${tr(`website_${field}`)}` };
  }));
  const variableGroups = $derived(presentedItems(outputs));
  const eligibleOutputs = $derived([...variableGroups.basic, ...variableGroups.advanced]);
  const variableSources = $derived(graph.nodes.filter(node => eligibleOutputs.some(output => output.nodeId === node.id)).map(node => ({
    nodeId: node.id,
    label: `${summary(node)}${location(node) ? ` · ${location(node)}` : ''}${graph.nodes.filter(other => summary(other) === summary(node) && location(other) === location(node)).length > 1 ? ` · ${graph.nodes.filter(other => summary(other) === summary(node) && location(other) === location(node)).findIndex(other => other.id === node.id) + 1}` : ''}`,
    appId: String(node.config?.app_id ?? 'ai'),
    iconStyle: assetIconStyle(node.type === 'app_skill_action' ? appIcon(node) : 'workflow-check', 14, 'var(--color-font-button)'),
  })) satisfies VariableSource[]);
  const websiteChangeSelected = $derived(outputs.some(output =>
    ['has_changed', 'changes'].some(field => output.reference.endsWith(`.output.${field}`)) &&
    graph.nodes.some(node => node.id === output.nodeId && node.config?.app_id === 'web' && node.config?.skill_id === 'read') &&
    (record(draft?.config?.predicate).left === output.reference || (Array.isArray(draft?.config?.selected_inputs) && draft.config.selected_inputs.includes(output.reference)))));
  const checkSources = $derived(variableSources.filter(source => graph.nodes.some(node => node.id === source.nodeId && node.type === 'app_skill_action')));
  const checkSourceOptions = $derived([...checkSources.map(source => sourceOption(source)), {
    value: 'ai', label: tr('ai_confirms'), iconStyle: assetIconStyle('ai', 16, 'var(--color-font-button)'), iconBackground: appGradient('ai'),
  }]);
  const exactCheckCanSave = $derived.by(() => {
    const predicate = record(draft?.config?.predicate);
    if (!predicate.left || !predicate.op) return false;
    if (predicate.op === 'exists') return true;
    if (typeof predicate.right === 'string' && predicate.right.startsWith('$nodes.')) return outputs.some(output => output.reference === predicate.right && compatibleCheckOutput(output, predicate.left));
    const type = scalarCheckType(sourceSchema(predicate.left));
    return type === 'number' ? typeof predicate.right === 'number' && Number.isFinite(predicate.right) : type === 'boolean' ? typeof predicate.right === 'boolean' : typeof predicate.right === 'string';
  });
  const paidSaveValidation = $derived.by(() => {
    if (!draft || !(isAskAi(draft) || (isCheck(draft) && draft.config?.mode === 'ai'))) return false;
    const original = graph.nodes.find(node => node.id === draft?.id);
    const text = isAskAi(draft) ? askInstruction() : String(draft.config?.question ?? '');
    const originalText = original && (isAskAi(original) ? String(record(original.config?.input).prompt ?? '') : original.config?.mode === 'ai' ? String(original.config?.question ?? '') : null);
    return text.trim().length > 0 && text !== originalText;
  });
  const earlierActionOutputs = $derived(outputs.filter(output => graph.nodes.some(node => node.id === output.nodeId && node.type === 'app_skill_action')));
  const aiCheckSelectedInputs = $derived(draft && isCheck(draft) && draft.config?.mode === 'ai' ? templateReferences(String(draft.config?.question ?? '')) : []);
  const aiCheckCanSave = $derived(!draft || !isCheck(draft) || draft.config?.mode !== 'ai' || (hasTemplateText(String(draft.config?.question ?? '')) && (!earlierActionOutputs.length || templateReferences(String(draft.config?.question ?? '')).some(reference => earlierActionOutputs.some(output => output.reference === reference)))));
  const messageTemplate = $derived(String(draft?.config?.message ?? draft?.config?.summary ?? ''));
  const missingEarlierActionReference = $derived(!!draft && (
    (isMessage(draft) && !hasEarlierActionReference(messageTemplate))
    || (isAskAi(draft) && !hasEarlierActionReference(askInstruction()))
    || (isCheck(draft) && draft.config?.mode === 'ai' && !hasEarlierActionReference(String(draft.config?.question ?? '')))
  ));
  const rootNodes = $derived(graph.nodes.filter(node => !graph.edges.some(edge => edge.to === node.id)).sort((a, b) => Number(isTrigger(b)) - Number(isTrigger(a))));
  const retainedRuns = $derived(workflowId && $workflowWorkspaceStore.selectedWorkflowId === workflowId ? $workflowWorkspaceStore.runs : []);
  const outputExamples = $derived(workflowOutputExamples(graph, capabilities, retainedRuns));
  const availableTestOutputs = $derived({ ...outputExamples.valuesByNode, ...testOutputs });

  $effect(() => {
    if (workflowId === testOutputWorkflowId) return;
    testOutputWorkflowId = workflowId;
    testOutputs = {};
    testingRunId = null;
    testStatus = 'idle';
    streamedTestAnswer = '';
    streamedTestEmbeds = [];
    testAbort?.abort();
  });

  function setCapabilities(items: Capability[]): void { capabilities = items.map(item => ({ ...item, metadata: { ...item.metadata, input_schema: item.metadata.input_schema ? normalizeSchema(item.metadata.input_schema) : undefined, output_schema: item.metadata.output_schema ? normalizeSchema(item.metadata.output_schema) : undefined } })); }
  function loadCapabilities(): Promise<void> {
    if (capabilityFixtures) { setCapabilities(capabilityFixtures); return Promise.resolve(); }
    if (readOnly) return Promise.resolve();
    if (!capabilityLoad) capabilityLoad = workflowApiRequest<{ capabilities: Capability[] }>('/v1/workflows/capabilities')
      .then(data => { setCapabilities(data.capabilities); loadError = ''; })
      .catch(error => { console.error('[Workflow capabilities]', error); loadError = tr('schema_unavailable'); })
      .finally(() => { capabilityLoad = null; });
    return capabilityLoad;
  }
  onMount(() => {
    void loadCapabilities();
    if (chatFixtures) chats = chatFixtures;
    return () => { testRevision += 1; testAbort?.abort(); };
  });
  function transitionNodeUpdate(update: () => void): void {
    const transitionDocument = globalThis.document as Document & { startViewTransition?: (callback: () => void | Promise<void>) => unknown };
    const reduceMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    if (reduceMotion || !transitionDocument?.startViewTransition) { update(); return; }
    transitionDocument.startViewTransition(async () => { update(); await tick(); });
  }
  function viewTransitionName(nodeId: string): string { return `workflow-node-${nodeId.replace(/[^a-zA-Z0-9_-]/g, '-')}`; }
  function appMetadata(appId: string, capability?: Capability): AppMetadata {
    const app = (appsMetadata as Record<string, AppMetadata>)[appId];
    const skill = app?.skills.find(item => item.id === capability?.metadata.skill_id);
    if (!capability) return app ?? { id: appId, name: label(appId), icon_image: `${appId}.svg`, skills: [], focus_modes: [], settings_and_memories: [] };
    return { ...appMetadata(appId), name: capability.title, name_translation_key: skill?.name_translation_key, description: '', description_translation_key: skill?.description_translation_key, icon_image: skill?.icon_image ?? `${appId}.svg` };
  }
  function sameSlot(slot: Insertion): boolean { return insertion.after === slot.after && (insertion.branch ?? '') === (slot.branch ?? ''); }
  async function scrollEditorIntoView(nodeId?: string): Promise<void> {
    await tick();
    const nodeEditor = nodeId ? graphPanel?.querySelector<HTMLElement>(`[data-node-id="${CSS.escape(nodeId)}"] [data-testid="workflow-node-expanded"]`) : null;
    const target = nodeEditor ?? graphPanel?.querySelector<HTMLElement>('[data-testid="workflow-node-expanded"], [data-testid="workflow-step-menu"]');
    if (!target) return;
    const reduceMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest', inline: 'nearest' });
    target.focus({ preventScroll: true });
  }
  function openPicker(kind: typeof picker, slot: Insertion): void { if (busy || testStatus === 'processing') return; draft = null; deleteArmed = false; nodeError = ''; preview = null; insertion = slot; picker = kind; void scrollEditorIntoView(); }
  function closeEditor(immediate = false): void {
    const close = () => { draft = null; picker = null; deleteArmed = false; nodeError = ''; preview = null; chooseChat = false; showReferences = false; mentionQuery = ''; selectedVariableSource = null; streamedTestAnswer = ''; streamedTestEmbeds = []; showOutputFields = false; selectedCheckSource = null; selectedCompareSource = null; };
    if (immediate) close(); else transitionNodeUpdate(close);
  }
  function backFromEditor(): void {
    if (draft && (isAskAi(draft) || isCheck(draft))) { picker = 'action'; selectedVariableSource = null; showReferences = false; selectedCheckSource = null; selectedCompareSource = null; void scrollEditorIntoView(); return; }
    if (draft && isMessage(draft) && chooseChat) {
      chooseChat = false;
      if (graph.nodes.some(node => node.id === draft?.id)) return;
      draft = null; picker = 'action';
      return;
    }
    if (draft?.type === 'app_skill_action' && !isAskAi(draft)) {
      selectedApp = String(draft.config?.app_id ?? '');
      picker = 'skill';
      deleteArmed = false;
      nodeError = '';
      preview = null;
      return;
    }
    closeEditor();
  }
  function edit(node: WorkflowNode): void {
    if (busy || testStatus === 'processing') return;
    if (readOnly) { transitionNodeUpdate(() => { expandedReadOnly = expandedReadOnly === node.id ? null : node.id; }); return; }
    closeEditor(true);
    const editable: WorkflowNode = structuredClone($state.snapshot(node));
    recoverAskModel(editable);
    if (isCheck(editable) && editable.config?.mode !== 'ai' && record(editable.config?.predicate).op === 'ne') editable.config = { ...editable.config, predicate:{ ...record(editable.config?.predicate), op:'neq' } };
    if (isMessage(editable)) {
      const config = record(editable.config);
      let text = String(config.message ?? config.summary ?? '');
      for (const block of Array.isArray(config.blocks) ? config.blocks : []) {
        const source = record(block).source;
        if (typeof source !== 'string') continue;
        const token = outputTemplateSyntax(source);
        if (!text.includes(token)) text = `${text.trim()}\n${token}`.trim();
      }
      editable.config = { ...config, message: text };
    }
    if (isCheck(editable) && editable.config?.mode === 'ai') {
      const config = record(editable.config);
      const question = String(config.question ?? '');
      const editableOutputs = outputsBefore(graph, editable.id, capabilities, insertion);
      const selected = Array.isArray(config.selected_inputs) ? config.selected_inputs.filter((reference): reference is string => typeof reference === 'string' && editableOutputs.some(output => output.reference === reference)) : [];
      let migratedQuestion = question;
      if (selected.length && templateReferences(question, editableOutputs).length === 0) {
        migratedQuestion = `${question.trim()}\n${selected.map(outputTemplateSyntax).join(' ')}`.trim();
      }
      editable.config = { ...config, question: migratedQuestion, selected_inputs: templateReferences(migratedQuestion, editableOutputs) };
    }
    transitionNodeUpdate(() => { draft = editable; selectedVariableSource = null; mentionQuery = ''; streamedTestAnswer = String(testOutputs[node.id]?.answer ?? ''); streamedTestEmbeds = (testOutputs[node.id]?.preview_embeds as WorkflowPreviewEmbed[] | undefined) ?? []; testStatus = testOutputs[node.id] ? 'completed' : 'idle'; void scrollEditorIntoView(node.id); });
  }
  function configure(type: WorkflowNode['type'], capability?: Capability): void {
    if (busy || testStatus === 'processing') return;
    const replacementId = picker && draft ? draft.id : draft && graph.nodes.some(node => node.id === draft?.id) ? draft.id : null;
    picker = null; nodeError = ''; preview = null; testStatus = 'idle';
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    draft = { id: replacementId ?? `${type}_${crypto.randomUUID().slice(0, 8)}`, type, title: '', config: {} };
    if (type === 'schedule_trigger') draft.config = { schedule: { type: 'daily', time: '09:00', timezone } };
    if (type === 'app_skill_action' && capability) {
      draft.title = appMetadata(capability.metadata.app_id!, capability).name_translation_key ? $text(appMetadata(capability.metadata.app_id!, capability).name_translation_key!) : capability.title;
      draft.config = { app_id: capability.metadata.app_id, skill_id: capability.metadata.skill_id, input: schemaDefault(capability.metadata.input_schema ?? { type: 'object' }) };
    }
    if (type === 'check') draft.config = { mode: 'exact', predicate: { left: '', op: '', right: '' } };
    if (type === 'send_chat_message') { draft.config = { title: '', message: '', blocks: [] }; chooseChat = true; void loadChats(); }
    void scrollEditorIntoView(replacementId ?? undefined);
  }
  async function configureAskAi(): Promise<void> {
    if (!askCapability) await loadCapabilities();
    const capability = askCapability;
    if (!capability) { nodeError = tr('ask_ai_unavailable'); return; }
    configure('app_skill_action', capability);
    if (draft) { draft.title = tr('ask_ai'); draft.config = { app_id: 'ai', skill_id: 'ask', input: { prompt: '' } }; }
  }
  function patch(config: Record<string, unknown>): void { if (draft) { draft = { ...draft, config: { ...draft.config, ...config } }; preview = null; } }
  function schedulePatch(config: Record<string, unknown>): void { patch({ schedule: { ...record(draft?.config?.schedule), ...config } }); }
  function predicatePatch(config: Record<string, unknown>): void { nodeError = ''; patch({ mode: 'exact', predicate: { ...record(draft?.config?.predicate), ...config } }); }
  function sourceSchema(reference: unknown) { return outputs.find(output => output.reference === reference)?.schema; }
  function operators(reference: unknown): string[] { const type = sourceSchema(reference)?.type; return ['number', 'integer'].includes(type ?? '') ? ['gt', 'gte', 'lt', 'lte', 'eq', 'neq'] : type === 'boolean' ? ['eq', 'neq'] : ['eq', 'neq', 'contains']; }
  function operatorSymbol(op: unknown): string { return ({ gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', ne: '≠', neq: '≠', contains: '∋' } as Record<string, string>)[String(op)] ?? ''; }
  function kind(node: WorkflowNode): string { return tr(isTrigger(node) ? 'time_trigger' : isCheck(node) ? 'check' : isAskAi(node) ? 'ask_ai' : isMessage(node) ? 'send_message' : node.type === 'app_skill_action' ? 'use_app_skill' : 'action'); }
  function summary(node: WorkflowNode): string {
    if (isTrigger(node)) { const schedule = record(node.config?.schedule); if (schedule.type === 'hourly') return `${tr('hourly')} · :${String(schedule.minute ?? 0).padStart(2, '0')}`; if (schedule.type === 'once') return String(schedule.at ?? tr('once')); return `${tr(String(schedule.type ?? 'daily'))}${schedule.type === 'weekly' ? ` · ${(Array.isArray(schedule.weekdays) ? schedule.weekdays : ['sunday']).map(day => tr(String(day))).join(', ')}` : ''}, ${schedule.time ?? '09:00'}`; }
    if (isCheck(node)) { if (node.config?.mode === 'ai') return String(node.config?.question ?? tr('ai_judgment')); const predicate = record(node.config?.predicate); const output = outputsBefore(graph, node.id, capabilities).find(item => item.reference === predicate.left); return `${output?.label ?? label(String(predicate.left ?? '').split('.').at(-1) ?? '')} ${operatorSymbol(predicate.op)} ${String(predicate.right ?? '')}`; }
    if (isAskAi(node)) return tr('ask_ai');
    if (isMessage(node)) return String(node.config?.chat_id ? `${tr('to')} ${chats.find(chat => chat.chat_id === node.config?.chat_id)?.title ?? tr('existing_chat')}` : $text('common.new_chat'));
    if (node.type === 'app_skill_action') {
      const appId = String(node.config?.app_id ?? '');
      const skillId = String(node.config?.skill_id ?? '');
      const app = appMetadata(appId);
      const skill = app.skills.find(item => item.id === skillId);
      const appName = app.name_translation_key ? $text(app.name_translation_key) : app.name || label(appId);
      const skillName = skill?.name_translation_key ? $text(skill.name_translation_key) : label(skillId);
      return `${appName} | ${skillName}`;
    }
    return node.title || label(node.type);
  }
  function style(node: WorkflowNode): string { const appId = String(node.config?.app_id ?? 'workflows'); return `--node-gradient: ${isAskAi(node) || isCheck(node) ? 'var(--gradient-primary)' : `var(--color-app-${appId}, var(--gradient-primary))`};`; }
  function nextId(nodeId: string, branch?: string): string | undefined { return graph.edges.find(edge => edge.from === nodeId && (edge.branch ?? '') === (branch ?? ''))?.to; }
  function checkSource(node: WorkflowNode): WorkflowNode | undefined { const reference = String(record(node.config?.predicate).left ?? ''); const id = reference.startsWith('$nodes.') ? reference.split('.')[1] : reference.match(/steps\.([^.]+)/)?.[1]; return graph.nodes.find(item => item.id === id && item.type === 'app_skill_action'); }
  function appIcon(node: WorkflowNode): string { return (appMetadata(String(node.config?.app_id ?? '')).icon_image ?? `${node.config?.app_id}.svg`).trim().replace(/\.svg$/, ''); }
  function assetIconStyle(name: string, size: number, color = 'var(--color-primary-start, #4867cd)'): string { return `--workflow-icon:var(--icon-url-${name}, var(--icon-url-app));--workflow-icon-size:${size}px;color:${color}`; }
  function primaryNodeIconStyle(node: WorkflowNode): string {
    if (node.type === 'app_skill_action') return assetIconStyle(appIcon(node), 33, 'var(--color-font-button)');
    if (isCheck(node)) return assetIconStyle(checkSource(node) ? appIcon(checkSource(node)!) : 'workflow-check', 33, 'var(--color-font-button)');
    return assetIconStyle(isTrigger(node) ? 'calendar' : isMessage(node) ? 'chat' : 'app', 33, isTrigger(node) || isMessage(node) ? 'var(--color-font-button)' : 'var(--color-primary-start)');
  }
  function location(node: WorkflowNode): string { const input = record(node.config?.input); const request = Array.isArray(input.requests) ? record(input.requests[0]) : {}; return String(input.location ?? request.location ?? ''); }
  function skillInputSummary(node: WorkflowNode): string {
    return workflowSkillInputSummary(String(node.config?.app_id ?? ''), String(node.config?.skill_id ?? ''), record(node.config?.input), { in: tr('summary_in'), to: tr('summary_to') });
  }
  function workflowTimezone(node: WorkflowNode): string { const input = record(node.config?.input); const trigger = graph.nodes.find(isTrigger); return String(input.timezone || record(trigger?.config?.schedule).timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'); }
  function inputValue(node: WorkflowNode, run?: WorkflowNodeRun): Record<string, unknown> { if (Object.keys(run?.input_summary ?? {}).length) return run!.input_summary!; if (isMessage(node)) return { title: node.config?.title, message: node.config?.message ?? node.config?.summary, destination: node.config?.chat_id ? tr('existing_chat') : $text('common.new_chat') }; if (isCheck(node) && node.config?.mode === 'ai') return { question: node.config?.question, selected_inputs: node.config?.selected_inputs }; return record(node.config?.input ?? node.config?.inputs ?? node.config?.input_mapping ?? node.config?.schedule ?? node.config?.predicate); }
  function outputValue(node: WorkflowNode, run: WorkflowNodeRun): Record<string, unknown> {
    const data = record(run.output_summary);
    const fields = capabilityFor(node, capabilities)?.metadata.output_schema?.properties;
    if (fields) return Object.fromEntries(outputFields(fields).filter(([key]) => key in data).map(([key]) => [key, data[key]]));
    const keys = String(node.config?.app_id) === 'weather' ? ['summary','rain_probability','max_temperature_c','rain_expected','rain_summary','forecast_day','forecast_days','rain_periods'] : data.results ? ['result_count','results','warnings','partial'] : null;
    return keys ? Object.fromEntries(keys.filter(key => key in data).map(key => [key, data[key]])) : Object.fromEntries(valueEntries(data));
  }
  function workflowErrorText(error: unknown, fallback: string, errorCode?: string | null): string {
    const code = error instanceof WorkflowApiError ? error.code : typeof error === 'string' ? error : '';
    const keys: Record<string, string> = { WORKFLOW_AI_CHECK_NOT_BOOLEAN: 'ai_check_not_boolean', WORKFLOW_AI_ASK_REQUIRES_APP_ACTION: 'ask_ai_app_warning', INSUFFICIENT_CREDITS: 'insufficient_credits', WORKFLOW_AI_CHECK_VALIDATION_UNAVAILABLE: 'ai_validation_unavailable', WORKFLOW_AI_ASK_VALIDATION_UNAVAILABLE: 'ai_validation_unavailable' };
    Object.assign(keys, {
      WORKFLOW_WEBSITE_READ_BLOCKED: 'website_read_blocked',
      WORKFLOW_WEBSITE_READ_EMPTY: 'website_read_unusable',
      WORKFLOW_WEBSITE_READ_FAILED: 'website_read_unusable',
      WORKFLOW_WEBSITE_READ_PARTIAL: 'website_read_unusable',
      WORKFLOW_WEBSITE_READ_TOO_LARGE: 'website_change_too_large',
      WORKFLOW_WEBSITE_DIFF_TOO_LARGE: 'website_change_too_large',
      WORKFLOW_WEBSITE_REQUIRES_ONE_PAGE: 'website_change_one_page',
      WORKFLOW_WEBSITE_MULTIPLE_SOURCES: 'website_change_one_page',
      WORKFLOW_WEBSITE_PENDING_LIMIT: 'website_change_pending_limit',
    });
    return tr(keys[code ?? ''] ?? keys[errorCode ?? ''] ?? fallback);
  }
  function failForUser(error: unknown, key: string): void { console.error('[Workflow builder]', error); nodeError = workflowErrorText(error, key); }
  function checkMode(mode: 'exact' | 'ai'): void {
    if (!draft) return;
    draft = { ...draft, config: mode === 'ai' ? { mode: 'ai', question: '', selected_inputs: [] } : { mode: 'exact', predicate: { left: '', op: '', right: '' } } };
  }
  function appGradient(appId: string): string {
    return `linear-gradient(135deg,var(--color-app-${appId}-start,var(--color-primary-start)),var(--color-app-${appId}-end,var(--color-primary-end)))`;
  }
  function sourceOption(source: VariableSource) { return { value: source.nodeId, label: source.label, iconStyle: source.iconStyle, iconBackground: appGradient(source.appId) }; }
  function scalarCheckType(schema?: Schema): string { return ['number', 'integer'].includes(schema?.type ?? '') ? 'number' : schema?.type === 'boolean' ? 'boolean' : 'text'; }
  function compatibleCheckOutput(output: Output, left: unknown): boolean { return !['array', 'object'].includes(output.schema.type ?? '') && scalarCheckType(output.schema) === scalarCheckType(sourceSchema(left)); }
  function checkSourceId(): string { return selectedCheckSource ?? outputs.find(output => output.reference === record(draft?.config?.predicate).left)?.nodeId ?? ''; }
  function compareSourceId(): string { return selectedCompareSource ?? outputs.find(output => output.reference === record(draft?.config?.predicate).right)?.nodeId ?? 'literal'; }
  function checkFieldOptions(nodeId: string, selected: unknown, left?: unknown) {
    const fields = outputs.filter(output => output.nodeId === nodeId && !['array', 'object'].includes(output.schema.type ?? '') && (!output.listProjection || output.reference === selected) && (left === undefined || compatibleCheckOutput(output, left)));
    return fields.map(output => ({ value: output.reference, label: output.label.split(' · ').slice(1).join(' · ') || output.label, iconStyle: assetIconStyle(String(output.appId ?? 'ai'), 16, 'var(--color-font-button)'), iconBackground: appGradient(String(output.appId ?? 'ai')) }));
  }
  function chooseCheckSource(value: string): void {
    nodeError = ''; selectedVariableSource = null; showReferences = false; mentionQuery = '';
    if (value === 'ai') { if (draft?.config?.mode !== 'ai') checkMode('ai'); selectedCheckSource = null; return; }
    if (draft?.config?.mode === 'ai') checkMode('exact');
    selectedCheckSource = value; selectedCompareSource = null;
    predicatePatch({ left: '', op: '', right: '' });
  }
  function chooseCheckField(left: string): void { selectedCompareSource = null; predicatePatch({ left, op: '', right: '' }); }
  function chooseCheckOperator(op: string): void { selectedCompareSource = 'literal'; predicatePatch({ op, right: scalarCheckType(sourceSchema(record(draft?.config?.predicate).left)) === 'boolean' ? true : '' }); }
  function compareSourceOptions(left: unknown) {
    const type = scalarCheckType(sourceSchema(left));
    return [{ value: 'literal', label: tr(`output_type_${type}`), iconText: type === 'number' ? '123' : type === 'boolean' ? '✓' : 'Aa', iconBackground: appGradient('events') }, ...checkSources.filter(source => checkFieldOptions(source.nodeId, null, left).length).map(sourceOption)];
  }
  function chooseCompareSource(value: string): void { selectedCompareSource = value; predicatePatch({ right: value === 'literal' && scalarCheckType(sourceSchema(record(draft?.config?.predicate).left)) === 'boolean' ? true : '' }); }
  function templateReferences(value: string, availableOutputs: Output[] = outputs): string[] {
    const references = [...value.matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)].map(match => {
      const path = match[1].trim();
      return path.startsWith('steps.') ? path.replace(/^steps\.([^.]+)\./, '$nodes.$1.output.') : path;
    });
    return [...new Set(references.filter(reference => availableOutputs.some(output => output.reference === reference)))].slice(0, 24);
  }
  function hasTemplateText(value: string): boolean { return value.replace(/\{\{\s*[^{}]+?\s*\}\}/g, '').trim().length > 0; }
  function hasEarlierActionReference(value: string): boolean { return !earlierActionOutputs.length || templateReferences(value).some(reference => earlierActionOutputs.some(output => output.reference === reference)); }
  function updateAiCheckQuestion(value: string): void { nodeError = ''; patch({ question: value, selected_inputs: templateReferences(value) }); }
  function addAiCheckReference(output: Output): void { messageEditor?.insertReference(output); showReferences = false; }
  function askInstruction(): string { return String(record(draft?.config?.input).prompt ?? ''); }
  function updateAskInstruction(value: string): void { nodeError = ''; patch({ input: { ...record(draft?.config?.input), prompt: value } }); }
  function updateAskModel(model: string): void { patch({ input: { ...record(draft?.config?.input), model } }); }
  function recoverAskModel(node: WorkflowNode): void {
    if (!isAskAi(node)) return;
    const input = record(node.config?.input);
    const selection = String(input.model ?? 'auto');
    if (selection === 'auto') return;
    const canonical = canonicalizeAiModelSelection(selection);
    const profile = get(userProfile);
    const usable = canonical && isAiModelSelectionUsable(canonical, {
      disabledModels: profile.disabled_ai_models, disabledServers: profile.disabled_ai_servers,
    }, get(isProviderHealthy));
    if (!usable) notificationStore.error($text('enter_message.model_selector.unavailable_reset'));
    node.config = { ...node.config, input: { ...input, model: usable ? canonical : 'auto' } };
  }
  function openAskModelDetails(modelId: string): void { settingsDeepLink.set(`ai/model/${modelId}`); panelState.openSettings(); }
  function selectVariableSource(nodeId: string): void { selectedVariableSource = nodeId; }
  function updateMention(visible: boolean, query: string): void { showReferences = visible; mentionQuery = visible ? query : ''; }
  function addAskReference(output: Output): void { messageEditor?.insertReference(output); showReferences = false; }
  async function saveNode(): Promise<void> {
    if (!draft || !onSave || busy) return;
    if (isMessage(draft) && !String(draft.config?.title ?? '').trim()) { nodeError = tr('title_required'); return; }
    if (isCheck(draft) && draft.config?.mode === 'ai' && !aiCheckCanSave) { nodeError = tr('ai_check_required'); return; }
    if (isCheck(draft) && draft.config?.mode !== 'ai' && !exactCheckCanSave) { nodeError = tr('check_required'); return; }
    if (isAskAi(draft) && !askInstruction().trim()) { nodeError = tr('ask_ai_instruction_required'); return; }
    if ((isMessage(draft) && !hasEarlierActionReference(messageTemplate)) || (isAskAi(draft) && !hasEarlierActionReference(askInstruction())) || (isCheck(draft) && draft.config?.mode === 'ai' && !hasEarlierActionReference(String(draft.config?.question ?? '')))) { nodeError = tr('earlier_action_variable_required'); return; }
    busy = true; nodeError = '';
    const saved = structuredClone($state.snapshot(draft)); recoverAskModel(saved); saved.title ||= summary(saved);
    try {
      await onSave({ ...insertNode(graph, saved, insertion), version: 2 }); closeEditor(true); busy = false;
      if (isTrigger(saved) && !graph.nodes.some(node => !isTrigger(node) && node.type !== 'end')) openPicker('action', { after: saved.id });
      else if (isCheck(saved)) openPicker('action', { after: saved.id, branch: saved.config?.mode === 'ai' ? 'true' : 'yes' });
    } catch (error) { failForUser(error, 'save_failed'); }
    finally { busy = false; }
  }
  export function hasPendingDraft(): boolean { return !readOnly && draft !== null; }
  export function openNodeEditor(nodeId: string): void {
    const node = graph.nodes.find(candidate => candidate.id === nodeId);
    if (!node || readOnly) return;
    edit(node);
    void tick().then(() => graphPanel?.querySelector<HTMLElement>(`[data-node-id="${CSS.escape(nodeId)}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }));
  }
  export async function savePendingDraft(): Promise<boolean> {
    if (!hasPendingDraft()) return true;
    await saveNode();
    return draft === null;
  }
  export function discardPendingDraft(): void { closeEditor(true); }
  async function deleteNode(): Promise<void> { if (!draft || !onSave || busy) return; busy = true; try { await onSave({ ...removeNode(graph, draft.id, capabilities), version: 2 }); closeEditor(); } catch (error) { if (error instanceof WorkflowNodeDependencyError) { console.error('[Workflow builder]', error); nodeError = tr('step_in_use').replace('{steps}', error.dependentNodeTitles.join(', ')); } else failForUser(error, 'save_failed'); } finally { busy = false; } }
  async function persistReorder(next: WorkflowGraph | null, focusNodeId?: string): Promise<void> {
    if (!next || !onSave || busy || readOnly || testStatus === 'processing') return;
    const previous = graph;
    busy = true;
    nodeError = '';
    onChange(next);
    try {
      await onSave(next);
      if (focusNodeId && draft?.id === focusNodeId) void scrollEditorIntoView(focusNodeId);
    } catch (error) {
      const savedGraph = $workflowWorkspaceStore.selectedWorkflow?.graph;
      if (JSON.stringify(savedGraph) !== JSON.stringify(next)) onChange(previous);
      failForUser(error, 'save_failed');
    }
    finally { busy = false; }
  }
  function moveDraft(direction: 'up' | 'down'): void {
    if (!draft) return;
    void persistReorder(moveWorkflowNode(graph, draft.id, direction), draft.id);
  }
  function startPointerDrag(event: PointerEvent, nodeId: string): void {
    if (event.button !== 0 || event.pointerType !== 'mouse' || readOnly || busy || !onSave || (!canMoveWorkflowNode(graph, nodeId, 'up') && !canMoveWorkflowNode(graph, nodeId, 'down'))) return;
    pointerCandidate = { id: nodeId, pointerId: event.pointerId, x: event.clientX, y: event.clientY };
  }
  function pointerDropTarget(x: number, y: number): HTMLElement | null {
    return document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-testid="workflow-node-drop-zone"]') ?? null;
  }
  function movePointerDrag(event: PointerEvent): void {
    if (!pointerCandidate || event.pointerId !== pointerCandidate.pointerId) return;
    if (!draggingNodeId && Math.hypot(event.clientX - pointerCandidate.x, event.clientY - pointerCandidate.y) < 6) return;
    draggingNodeId = pointerCandidate.id;
    event.preventDefault();
    const target = pointerDropTarget(event.clientX, event.clientY);
    dropSlotId = target?.dataset.afterNodeId ?? null;
  }
  function finishPointerDrag(event: PointerEvent): void {
    if (!pointerCandidate || event.pointerId !== pointerCandidate.pointerId) return;
    const sourceId = pointerCandidate.id;
    pointerCandidate = null;
    const wasDragging = draggingNodeId === sourceId;
    const target = wasDragging ? pointerDropTarget(event.clientX, event.clientY) : null;
    const afterId = target?.dataset.afterNodeId;
    draggingNodeId = null;
    dropSlotId = null;
    if (wasDragging) {
      suppressNodeClick = true;
      setTimeout(() => { suppressNodeClick = false; }, 0);
    }
    if (afterId) void persistReorder(moveWorkflowNodeAfter(graph, sourceId, afterId));
  }
  function requestDelete(): void { if (!deleteArmed) { deleteArmed = true; return; } void deleteNode(); }
  async function testNode(): Promise<void> {
    if (!draft || !workflowId || testStatus === 'processing') return;
    const node = structuredClone($state.snapshot(draft)); recoverAskModel(node); if (isAskAi(node)) draft = node;
    const revision = ++testRevision; testStatus = 'processing'; nodeError = ''; showOutputFields = true; streamedTestAnswer = ''; streamedTestEmbeds = [];
    const pending = (status: string | undefined) => !status || ['accepted', 'queued', 'running', 'cancellation_requested'].includes(status);
    const finish = (run: WorkflowRunDetail): void => {
      const result = run.node_runs?.find(item => item.node_id === node.id);
      if (run.status === 'completed') {
        testOutputs = { ...testOutputs, [node.id]: result?.output_summary ?? run.output_summary ?? {} };
        testStatus = 'completed';
        if (isAskAi(node)) {
          streamedTestAnswer = String(testOutputs[node.id].answer ?? '');
          streamedTestEmbeds = (testOutputs[node.id].preview_embeds as WorkflowPreviewEmbed[] | undefined) ?? [];
        }
      } else {
        testStatus = run.status === 'cancelled' ? 'cancelled' : 'failed';
        console.error('[Workflow test]', result?.error_summary ?? run.error_summary ?? run.status);
        nodeError = workflowErrorText(result?.error_summary ?? run.error_summary, 'output_test_failed', result?.error_code);
      }
      testingRunId = null;
    };
    try {
      const upstreamOutputs = workflowUpstreamOutputs(graph, node.id, availableTestOutputs, insertion);
      if (isAskAi(node)) {
        const controller = new AbortController(); testAbort = controller;
        try {
          const run = await streamWorkflowStepTest(`/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(node.id)}/test`, { node, input: {}, upstream_outputs: upstreamOutputs }, event => {
            if (revision !== testRevision) return;
            if (event.type === 'processing' && event.run_id) testingRunId = event.run_id;
            if (event.type === 'chunk') streamedTestAnswer = event.content;
            if (event.type === 'embeds') streamedTestEmbeds = event.embeds;
            if (event.type === 'error' && event.run) finish(event.run);
          }, controller.signal);
          if (revision === testRevision) finish(run);
        } finally { if (testAbort === controller) testAbort = null; }
        return;
      }
      const data = await workflowApiRequest<{ run: WorkflowRunDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(node.id)}/test`, { method: 'POST', body: JSON.stringify({ node, input: {}, upstream_outputs: upstreamOutputs }) });
      if (revision !== testRevision) return;
      if (!pending(data.run.status)) { finish(data.run); return; }
      testingRunId = data.run.id;
      for (let attempt = 0; attempt < 60 && revision === testRevision; attempt++) {
        const run = await workflowWorkspaceStore.getWorkflowRun(workflowId, data.run.id);
        if (!pending(run.status)) { finish(run); return; }
        await new Promise(resolve => setTimeout(resolve, Math.min(1500 + attempt * 500, 5000)));
      }
      if (revision === testRevision) { testStatus = 'idle'; nodeError = tr('test_pending'); }
    } catch (error) { if (revision === testRevision) { if (error instanceof Error && error.name === 'AbortError') { testStatus = 'cancelled'; testingRunId = null; } else { testStatus = 'failed'; testingRunId = null; failForUser(error, 'output_test_failed'); } } }
  }
  async function stopTest(): Promise<void> { if (testAbort) { testAbort.abort(); return; } if (!workflowId || !testingRunId) return; try { await workflowWorkspaceStore.cancelWorkflowRun(workflowId, testingRunId); } catch (error) { failForUser(error, 'save_failed'); } }
  async function loadChats(): Promise<void> {
    if (chatFixtures) { chats = chatFixtures; return; }
    try {
      const [{ chatDB }, { chatMetadataCache }] = await Promise.all([import('../../services/db'), import('../../services/chatMetadataCache')]);
      const localChats = await chatDB.getAllChats();
      // Reuse the owner client's in-memory decryption cache; never persist these display fields.
      chats = await Promise.all(localChats.map(async chat => {
        const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
        return { ...chat, title: metadata?.title ?? chat.title, category: metadata?.category ?? chat.category, icon: metadata?.icon ?? chat.icon, chat_summary: metadata?.summary ?? chat.chat_summary };
      }));
    } catch { nodeError = tr('chats_unavailable'); }
  }
  function selectChat(chat: Chat | null): void {
    if (draft) draft = { ...draft, config: messageDestinationConfig(draft.config ?? {}, chat?.chat_id) };
    preview = null; chooseChat = false;
  }
  function addReference(output: Output): void { messageEditor?.insertReference(output); showReferences = false; }
  async function previewMessage(): Promise<void> {
    if (!workflowId || !draft) return; busy = true; nodeError = '';
    try { const data = await workflowApiRequest<{ preview: Record<string, unknown> }>(`/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(draft.id)}/preview`, { method: 'POST', body: JSON.stringify({ node: draft, input: {}, upstream_outputs: testOutputs }) }); preview = data.preview; }
    catch (error) { failForUser(error, 'output_preview_failed'); } finally { busy = false; }
  }
</script>

{#snippet editorFieldLabel(name: string, title: string, schema: Schema)}
  {@const FieldIcon = workflowFieldIcon(name, schema)}
  <span class="editor-field-label"><FieldIcon size={18} strokeWidth={2.2} aria-hidden="true"/><span>{title}</span></span>
{/snippet}

{#snippet outputSection(properties: Record<string, Schema>, values: Record<string, unknown> | undefined, appId: string, path: string, tested = false)}
  <button type="button" class="output-toggle" data-testid="workflow-show-output-fields" aria-expanded={showOutputFields} onclick={() => showOutputFields = !showOutputFields}>{tr(showOutputFields ? 'hide_output_fields' : 'show_output_fields')}</button>
  {#if showOutputFields}
    <div class="output-heading" data-testid="workflow-output-heading"><h4><span class="section-icon" data-testid="workflow-output-icon"><Upload size={18} aria-hidden="true"/></span>{tr('output')}:</h4><span data-testid="workflow-output-example-heading">{tr(tested ? 'test_output' : 'example')}:</span></div>
    {#if testStatus === 'processing'}<div class="output-progress" role="status" data-testid="workflow-test-output-loading"><span class="output-spinner" aria-hidden="true"></span>{tr('processing')}</div>
    {:else if testStatus === 'failed' || testStatus === 'cancelled'}<p class="error" role="status" data-testid="workflow-test-output-error">{nodeError || tr('output_test_failed')}</p>
    {:else if tested}<div class="tested-output" data-testid="workflow-output-fields"><WorkflowValueView value={values} {appId} {path}/></div>
    {:else}<WorkflowOutputFields {properties} {values} {appId} {path}/>{/if}
  {/if}
{/snippet}

{#snippet choice(icon: string, title: string, action: () => void, testId?: string)}
  {@const Icon = getLucideIcon(icon)}{@const asset = ({ blocks: 'app', sparkles: 'ai', 'messages-square': 'chat', 'calendar-clock': 'workflow', 'calendar-days': 'calendar', 'git-branch': 'workflow-check' } as Record<string, string>)[icon]}<button type="button" class="choice" data-testid={testId} onclick={action}>{#if asset}<span class="workflow-icon" style={assetIconStyle(asset, 27)} aria-hidden="true"></span>{:else}<Icon size={27}/>{/if}<span>{title}</span></button>
{/snippet}

{#snippet slotControls(slot: Insertion)}
  {#if !readOnly}
    {#if !slot.after && !graph.nodes.length && !(sameSlot(slot) && (picker || draft))}
      <div class="add-controls" class:blank={!slot.after && !graph.nodes.length} data-testid="workflow-action-palette">
        {#if !graph.nodes.some(isTrigger) && !slot.branch}{@render choice('calendar-clock', tr('add_trigger'), () => openPicker('trigger', slot), 'workflow-add-time-trigger')}{/if}
        {@render choice('blocks', tr('add_action'), () => openPicker('action', slot), 'workflow-add-step')}
      </div>
    {:else}
      {@const expanded = sameSlot(slot) && (picker || (draft && !graph.nodes.some(node => node.id === draft?.id)))}
      <div class="slot-surface" class:expanded={!!expanded} class:ask-ai-slot={!!expanded && !!draft && (isAskAi(draft) || isCheck(draft))} data-testid="workflow-slot-surface" data-after-node-id={slot.after ?? ''}>
        {#if expanded}
          {#if picker}{@render pickerPanel()}{:else if draft}{@render editor()}{/if}
        {:else}
          <button type="button" class="nothing" data-testid="workflow-add-step" onclick={() => openPicker('action', slot)}>{tr('do_nothing_add_step')}</button>
        {/if}
      </div>
    {/if}
  {/if}
{/snippet}

{#snippet dropZone(afterId: string)}
  <div class="drop-here" class:drop-slot={dropSlotId === afterId} role="group" aria-label={tr('drop_here_move')} data-testid="workflow-node-drop-zone" data-after-node-id={afterId}>{tr('drop_here_move')}</div>
{/snippet}

{#snippet pickerPanel()}
  {#key picker}
  <div class="editor picker" style={draft ? style(draft) : ''} data-testid="workflow-step-menu" tabindex="-1">
    <WorkflowEditorHeader
      title={tr(picker === 'trigger' ? 'add_trigger' : picker === 'app' ? 'use_app' : picker === 'skill' ? 'choose_skill' : 'add_action')}
      iconStyle={assetIconStyle(picker === 'trigger' ? 'workflow' : picker === 'skill' ? selectedApp : 'app', 16, 'var(--color-font-secondary)')}
      backLabel={picker === 'app' || picker === 'skill' ? tr('back') : ''}
      showDelete={persistedDraft}
      canMoveUp={false}
      canMoveDown={false}
      {deleteArmed}
      closeLabel={tr('close')}
      deleteLabel={tr('delete_node')}
      confirmDeleteLabel={tr('confirm_delete_node')}
      moveUpLabel={tr('move_up')}
      moveDownLabel={tr('move_down')}
      onBack={() => { picker = picker === 'skill' ? 'app' : 'action'; deleteArmed = false; }}
      onDelete={requestDelete}
      onMoveUp={() => moveDraft('up')}
      onMoveDown={() => moveDraft('down')}
      onClose={() => closeEditor()}
    />
    <h3>{tr(picker === 'trigger' ? 'trigger_question' : picker === 'app' ? 'app_question' : picker === 'skill' ? 'skill_question' : 'action_question')}</h3>
    {#if picker === 'trigger'}<div class="choices">{@render choice('calendar-days', tr('date_time'), () => configure('schedule_trigger'), 'workflow-trigger-date-time')}</div>
    {:else if picker === 'action'}<div class="choices">{@render choice('blocks', tr('use_app'), () => picker = 'app', 'workflow-step-app-skill-action')}{@render choice('sparkles', tr('ask_ai'), configureAskAi, 'workflow-step-ask-ai')}{#if (draft && !isTrigger(draft)) || (insertion.after && !isTrigger(graph.nodes.find(node => node.id === insertion.after)!))}{@render choice('git-branch', tr('add_check'), () => configure('check'))}{/if}{@render choice('messages-square', tr('send_message'), () => configure('send_chat_message'), 'workflow-step-create-chat-report')}</div>
    {:else if picker === 'app'}<div class="card-scroll">{#each appIds as appId}<AppStoreCard app={appMetadata(appId)} onSelect={() => { selectedApp = appId; picker = 'skill'; }}/>{/each}</div>{#if !appIds.length}<p>{loadError || tr('loading_apps')}</p>{/if}
    {:else if picker === 'skill'}<div class="card-scroll">{#each available.filter(item => item.metadata.app_id === selectedApp) as capability}<AppStoreCard app={appMetadata(selectedApp, capability)} cardIconType="skill" onSelect={() => configure('app_skill_action', capability)}/>{/each}</div>{/if}
    {#if nodeError}<p class="error" role="alert">{nodeError}</p>{/if}
  </div>
  {/key}
{/snippet}

{#snippet editor()}
  {#if draft}
    {@const predicate = record(draft.config?.predicate)}
    {@const schedule = record(draft.config?.schedule)}
    <div class="editor" class:ask-ai-editor={isAskAi(draft)} class:check-editor={isCheck(draft)} class:skill-editor={draft.type === 'app_skill_action'} class:weather-editor={draft.type === 'app_skill_action' && String(draft.config?.app_id ?? '') === 'weather'} class:chat-destination={isMessage(draft) && chooseChat} style={style(draft)} data-testid="workflow-node-expanded" tabindex="-1">
      <WorkflowEditorHeader
        title={isCheck(draft) ? tr('add_check') : draft.type === 'app_skill_action' ? (isAskAi(draft) ? tr('ask_ai') : summary(draft)) : kind(draft)}
        eyebrow={draft.type === 'app_skill_action' && !isAskAi(draft) ? kind(draft) : ''}
        subtitle={draft.type === 'app_skill_action' ? location(draft) : ''}
        backLabel={isAskAi(draft) || isCheck(draft) ? tr('next_step') : isMessage(draft) && chooseChat ? tr('add_action') : draft.type === 'app_skill_action' ? tr('back_to_app_skill') : ''}
        showBackLabel={isAskAi(draft) || isCheck(draft)}
        backIconSize={24}
        iconStyle={isCheck(draft) ? assetIconStyle('workflow-check', 33, 'var(--color-font-button)') : isMessage(draft) && chooseChat ? assetIconStyle('chat', 19, 'var(--color-font-button)') : primaryNodeIconStyle(draft)}
        colored={draft.type === 'app_skill_action' || isTrigger(draft) || isMessage(draft) || isCheck(draft)}
        showDelete={persistedDraft}
        canMoveUp={persistedDraft && canMoveWorkflowNode(graph, draft.id, 'up')}
        canMoveDown={persistedDraft && canMoveWorkflowNode(graph, draft.id, 'down')}
        {deleteArmed}
        disabled={busy || testStatus === 'processing'}
        closeLabel={tr('close')}
        deleteLabel={tr('delete_node')}
        confirmDeleteLabel={tr('confirm_delete_node')}
        moveUpLabel={tr('move_up')}
        moveDownLabel={tr('move_down')}
        onBack={backFromEditor}
        onDelete={requestDelete}
        onMoveUp={() => moveDraft('up')}
        onMoveDown={() => moveDraft('down')}
        onClose={() => closeEditor()}
      />
      {#if isTrigger(draft)}
        <h3>{@render editorFieldLabel('date_time', tr('date_time'), { type:'string', format:'date-time' })}</h3><div class="field-grid">
          <label>{@render editorFieldLabel('repeat', tr('repeat'), { type:'string' })}<SettingsDropdown dataTestid="workflow-time-trigger-schedule" value={String(schedule.type ?? 'daily')} options={[{value:'once',label:tr('once')},{value:'hourly',label:tr('hourly')},{value:'daily',label:tr('daily')},{value:'weekly',label:tr('weekly')}]} ariaLabel={tr('repeat')} onChange={type => patch({ schedule: { type, timezone: schedule.timezone, ...(type === 'hourly' ? { minute: 0 } : type === 'once' ? { at: '' } : { time: schedule.time ?? '09:00', ...(type === 'weekly' ? { weekdays: ['sunday'] } : {}) }) } })}/></label>
          {#if schedule.type === 'once'}<label>{@render editorFieldLabel('date_time', tr('date_time'), { type:'string', format:'date-time' })}<input type="datetime-local" value={String(schedule.at ?? '').slice(0, 16)} onchange={event => schedulePatch({ at: event.currentTarget.value })}/></label>
          {:else if schedule.type === 'hourly'}<label>{@render editorFieldLabel('minute', tr('minute'), { type:'integer' })}<input type="number" min="0" max="59" value={Number(schedule.minute ?? 0)} oninput={event => schedulePatch({ minute: Number(event.currentTarget.value) })}/></label>
          {:else}<label>{@render editorFieldLabel('time', tr('time'), { type:'string', format:'time' })}<input type="time" value={String(schedule.time ?? '09:00')} oninput={event => schedulePatch({ time: event.currentTarget.value })}/></label>{/if}
          <label>{@render editorFieldLabel('timezone', tr('timezone'), { type:'string' })}<input value={String(schedule.timezone ?? '')} oninput={event => schedulePatch({ timezone: event.currentTarget.value })}/></label>
        </div>
        {#if schedule.type === 'weekly'}<div class="weekdays">{#each ['monday','tuesday','wednesday','thursday','friday','saturday','sunday'] as day}<label><input type="checkbox" checked={Array.isArray(schedule.weekdays) && schedule.weekdays.includes(day)} onchange={event => schedulePatch({ weekdays: event.currentTarget.checked ? [...(Array.isArray(schedule.weekdays) ? schedule.weekdays : []), day] : (Array.isArray(schedule.weekdays) ? schedule.weekdays : []).filter(item => item !== day) })}/>{tr(day)}</label>{/each}</div>{/if}
      {:else if isAskAi(draft)}
        <div class="ask-ai-content">
        <WorkflowVariablePicker outputs={eligibleOutputs} sources={variableSources} selectedSourceId={selectedVariableSource}
          query={showReferences ? mentionQuery : ''} disabled={busy || testStatus === 'processing'}
          onSelectSource={selectVariableSource} onInsert={addAskReference}/>
        <div class="ask-ai-input" data-testid="workflow-ask-ai-input">
          <WorkflowMessageEditor bind:this={messageEditor} value={askInstruction()} {outputs} placeholder={tr('ask_ai_placeholder')} disabled={busy || testStatus === 'processing'} onChange={updateAskInstruction} onMentionTrigger={updateMention}/>
        </div>
        <div class="ask-ai-actions">
          <fieldset class="ask-ai-model" data-testid="workflow-ask-ai-model" disabled={busy || testStatus === 'processing'}>
            <ComposerModelSelector selection={String(record(draft.config?.input).model ?? 'auto')} onSelect={updateAskModel} onOpenDetails={openAskModelDetails}/>
          </fieldset>
        <div class="test-control ask-ai-test-control">
          <button type="button" class="quiet test" data-testid="workflow-test-action" disabled={!workflowId || !draftCapability || testStatus === 'processing'} onclick={() => void testNode()}><Play size={16}/>{tr(testOutputs[draft.id] ? 'test_again' : 'test_action')}</button>
          {#if testStatus === 'processing'}<span class="ask-ai-processing" role="status" data-testid="workflow-ask-ai-processing">{tr('processing')}</span><button type="button" class="quiet" onclick={() => void stopTest()}><Stop size={16}/>{tr('stop')}</button>{/if}
        </div>
        </div>
        <WorkflowAskAiTestPreview content={testStatus === 'processing' ? streamedTestAnswer : streamedTestAnswer || String(testOutputs[draft.id]?.answer ?? '')} processing={testStatus === 'processing'} embeds={streamedTestEmbeds.length ? streamedTestEmbeds : (testOutputs[draft.id]?.preview_embeds as WorkflowPreviewEmbed[] | undefined) ?? []}/>
        </div>
      {:else if draft.type === 'app_skill_action'}
        <h4 class="input-heading" data-testid="workflow-input-heading"><span class="section-icon" data-testid="workflow-input-icon"><Download size={18} aria-hidden="true"/></span>{tr('input')}</h4>
        {#if draftCapability?.metadata.input_schema}<WorkflowSchemaFields schema={draftCapability.metadata.input_schema} value={draft.config?.input} {outputs} path={draft.id} appId={String(draft.config?.app_id ?? '')} timezone={workflowTimezone(draft)} onChange={value => patch({ input: value })}/>{:else}<p>{loadError || tr('schema_unavailable')}</p>{/if}
        <div class="test-control">
          {#if testStatus === 'processing'}<button type="button" class="quiet test" data-testid="workflow-test-action" disabled><Play size={16}/>{tr('test_action')}</button>{#if testingRunId}<button type="button" class="quiet" onclick={() => void stopTest()}><Stop size={16}/>{tr('stop')}</button>{/if}
          {:else}<button type="button" class="quiet test" data-testid="workflow-test-action" disabled={!workflowId || draftCapability?.metadata.workflow?.test_allowed === false || !draftCapability} onclick={() => void testNode()}><Play size={16}/>{tr(testOutputs[draft.id] ? 'test_again' : 'test_action')}<span class="credits-coin-icon" aria-hidden="true"></span><span>{draftCapability?.metadata.cost?.fixed ?? draftCapability?.metadata.cost?.per_unit?.credits ?? tr('variable_cost')}</span></button>{/if}
        </div>
        {@render outputSection(draftCapability?.metadata.output_schema?.properties ?? {}, testOutputs[draft.id] ?? outputExamples.valuesByNode[draft.id], String(draft.config?.app_id ?? ''), draft.id, !!testOutputs[draft.id])}
      {:else if isCheck(draft)}
        <h2 class="if-heading">{tr('if')}</h2>
        <div class="check-fields">
          <SettingsDropdown rich value={draft.config?.mode === 'ai' ? 'ai' : checkSourceId()} options={checkSourceOptions} placeholder={tr('select_check_source')} ariaLabel={tr('select_check_source')} dataTestid="workflow-check-source" disabled={busy || testStatus === 'processing'} onChange={chooseCheckSource}/>
          {#if draft.config?.mode !== 'ai' && checkSourceId()}
            <SettingsDropdown rich value={String(predicate.left ?? '')} options={checkFieldOptions(checkSourceId(), predicate.left)} placeholder={tr('select_output')} ariaLabel={tr('select_output')} dataTestid="workflow-check-variable" disabled={busy || testStatus === 'processing'} onChange={chooseCheckField}/>
            {#if predicate.left}
              <SettingsDropdown rich value={String(predicate.op === 'ne' ? 'neq' : predicate.op ?? '')} options={operators(predicate.left).map(op => ({ value: op, label: tr(`operator_${op === 'neq' ? 'ne' : op}`), iconText: operatorSymbol(op), iconBackground: appGradient('events') }))} placeholder={tr('compare_type')} ariaLabel={tr('compare_type')} dataTestid="workflow-check-operator" disabled={busy || testStatus === 'processing'} onChange={chooseCheckOperator}/>
            {/if}
            {#if predicate.op && predicate.op !== 'exists'}
              <SettingsDropdown rich value={compareSourceId()} options={compareSourceOptions(predicate.left)} ariaLabel={tr('compare_source')} dataTestid="workflow-check-compare-source" disabled={busy || testStatus === 'processing'} onChange={chooseCompareSource}/>
              {#if compareSourceId() !== 'literal'}
                <SettingsDropdown rich value={typeof predicate.right === 'string' ? predicate.right : ''} options={checkFieldOptions(compareSourceId(), predicate.right, predicate.left)} placeholder={tr('select_output')} ariaLabel={tr('compare_variable')} dataTestid="workflow-check-compare-variable" disabled={busy || testStatus === 'processing'} onChange={right => predicatePatch({ right })}/>
              {:else if sourceSchema(predicate.left)?.type === 'boolean'}
                <SettingsDropdown rich value={String(predicate.right)} options={[{ value:'true', label:tr('true'), iconText:'✓', iconBackground:appGradient('events') },{ value:'false', label:tr('false'), iconText:'×', iconBackground:appGradient('events') }]} ariaLabel={tr('compare_value')} disabled={busy || testStatus === 'processing'} onChange={value => predicatePatch({ right:value === 'true' })}/>
              {:else}
                <input aria-label={tr('compare_value')} type={scalarCheckType(sourceSchema(predicate.left)) === 'number' ? 'number' : 'text'} value={String(predicate.right ?? '')} disabled={busy || testStatus === 'processing'} oninput={event => predicatePatch({ right:scalarCheckType(sourceSchema(predicate.left)) === 'number' && event.currentTarget.value !== '' ? Number(event.currentTarget.value) : event.currentTarget.value })}/>
              {/if}
            {/if}
          {/if}
        </div>
        {#if draft.config?.mode === 'ai'}
          <div class="ai-check-content">
            <WorkflowVariablePicker outputs={eligibleOutputs} sources={variableSources} selectedSourceId={selectedVariableSource} query={showReferences ? mentionQuery : ''} disabled={busy || testStatus === 'processing'} onSelectSource={selectVariableSource} onInsert={addAiCheckReference}/>
            <WorkflowMessageEditor bind:this={messageEditor} value={String(draft.config?.question ?? '')} {outputs} placeholder={tr('ai_check_placeholder')} disabled={busy || testStatus === 'processing'} onChange={updateAiCheckQuestion} onMentionTrigger={updateMention}/>
            <p class="reminder">{tr('ai_check_guidance')}</p>
          </div>
        {/if}
        {#if websiteChangeSelected}<p class="reminder" data-testid="workflow-website-change-guidance">{tr('website_change_guidance')}</p>{/if}
        <div class="check-test-controls">
          <div class="test-control">
            {#if testStatus === 'processing'}<button type="button" class="quiet test" disabled><Play size={16}/>{tr('test_action')}</button>{#if testingRunId}<button type="button" class="quiet" onclick={() => void stopTest()}><Stop size={16}/>{tr('stop')}</button>{/if}
            {:else}<button type="button" class="quiet test" data-testid="workflow-test-action" disabled={busy || !workflowId || (draft.config?.mode === 'ai' ? !aiCheckCanSave : !exactCheckCanSave)} onclick={() => void testNode()}><Play size={16}/>{tr(testOutputs[draft.id] ? 'test_again' : 'test_action')}{#if draft.config?.mode === 'ai'}<span class="credits-coin-icon" aria-hidden="true"></span><span>1</span>{/if}</button>{/if}
          </div>
          {#if testStatus === 'processing'}<p class="ask-processing" role="status" data-testid="workflow-check-processing">{tr('processing')}</p>{/if}
        </div>
        {#if testStatus === 'completed' && (typeof record(testOutputs[draft.id]).matched === 'boolean' || ['true','false','unsure'].includes(String(record(testOutputs[draft.id]).decision ?? '')))}
          <p class="check-test-result" role="status" data-testid="workflow-check-test-result">{tr('test_output')}: {tr(String(record(testOutputs[draft.id]).decision ?? (record(testOutputs[draft.id]).matched ? 'true' : 'false')))}</p>
        {/if}
      {:else if isMessage(draft)}
        {#if chooseChat}<h3>{tr('chat_question')}</h3><div class="card-scroll">{#each visibleChats as chat}<ChatPreviewCard {chat} onOpen={selectChat}/>{/each}</div><div class="chat-search"><Search size={18} aria-hidden="true"/><input aria-label={tr('search_chats')} placeholder={tr('search_chats')} bind:value={chatSearch}/></div><button class="primary new-chat-destination" type="button" data-testid="workflow-new-chat-destination" onclick={() => selectChat(null)}><span class="clickable-icon icon_create new-chat-icon" aria-hidden="true"></span>{$text('common.new_chat')}</button>
        {:else}
          <div class="message-content">
          <button class="quiet target" type="button" onclick={() => { chooseChat = true; void loadChats(); }}>{tr('to')}: {summary(draft)}</button>
          <label>{@render editorFieldLabel('chat_title', tr('chat_title'), { type:'string' })}<input data-testid="workflow-message-title" value={String(draft.config?.title ?? '')} oninput={event => patch({ title: event.currentTarget.value })}/></label>
          <WorkflowVariablePicker outputs={eligibleOutputs} sources={variableSources} selectedSourceId={selectedVariableSource} query={showReferences ? mentionQuery : ''} disabled={busy || testStatus === 'processing'} onSelectSource={selectVariableSource} onInsert={addReference}/>
          <div class="message-input" data-testid="workflow-send-message-input">
            <WorkflowMessageEditor bind:this={messageEditor} value={messageTemplate} {outputs} placeholder={tr('message_placeholder')} disabled={busy || testStatus === 'processing'} onChange={value => patch({ message: value })} onMentionTrigger={updateMention}/>
          </div>
          <button class="quiet" type="button" data-testid="workflow-preview-message" disabled={busy || !String(draft.config?.title ?? '').trim()} onclick={() => void previewMessage()}>{tr('preview_message')}</button>
          {#if preview}<div class="message-preview" data-testid="workflow-message-preview">{#if preview.title}<h4>{String(preview.title)}</h4>{/if}{#each Array.isArray(preview.parts) ? preview.parts : [{text: preview.text ?? preview.message}] as part}{@const item = record(part)}{#if item.text}<p>{String(item.text)}</p>{:else if item.value !== undefined}<WorkflowValueView value={item.value} appId={String(item.app_id ?? '')}/>{/if}{/each}</div>{/if}
          </div>
        {/if}
      {:else}<WorkflowValueView value={draft.config}/>{/if}
      {#if nodeError}<p class="error" role="alert">{nodeError}</p>{/if}
      {#if paidSaveValidation}<p class="reminder validation-cost" data-testid="workflow-save-validation-cost">{tr('save_validation_cost')}</p>{/if}
      {#if !chooseChat}{#if isCheck(draft) && draft.config?.mode === 'ai' && earlierActionOutputs.length > 0 && aiCheckSelectedInputs.length === 0}<p class="reminder ai-check-save-hint" data-testid="workflow-ai-check-save-hint">{tr('ai_check_add_variable')}</p>{/if}{#if missingEarlierActionReference && !(isCheck(draft) && draft.config?.mode === 'ai')}<p class="reminder ai-check-save-hint" data-testid="workflow-variable-required">{tr('earlier_action_variable_required')}</p>{/if}<div class="save-row"><button type="button" class="primary" data-testid="workflow-node-save" disabled={busy || testStatus === 'processing' || !aiCheckCanSave || missingEarlierActionReference || (isCheck(draft) && draft.config?.mode !== 'ai' && !exactCheckCanSave)} onclick={() => void saveNode()}>{tr(busy ? 'saving' : 'save')}</button></div>{/if}
    </div>
  {/if}
{/snippet}

{#snippet chain(nodeId: string, visited: string[] = [], stopAt?: string)}
  {@const node = graph.nodes.find(item => item.id === nodeId)}
  {#if node && node.type !== 'end' && !visited.includes(nodeId) && nodeId !== stopAt}
    {@const run = nodeRuns.find(item => item.node_id === node.id)}
    {@const rawRunStatus = String(isMessage(node) && run?.output_summary?.status ? run.output_summary.status : run?.status ?? '')}
    {@const runStatus = ['acknowledged','completed','no_new_results'].includes(rawRunStatus) ? 'completed' : ['failed','cancelled','skipped','queued','running','cancellation_requested'].includes(rawRunStatus) ? rawRunStatus : 'waiting'}
    <article class="flow-node" class:ai-added={aiAddedNodeIds.includes(node.id)} class:ai-edited={aiEditedNodeIds.includes(node.id)} data-ai-change={aiAddedNodeIds.includes(node.id) ? 'added' : aiEditedNodeIds.includes(node.id) ? 'edited' : undefined} data-node-id={node.id} data-node-type={node.type} data-testid="workflow-node-card" style={`view-transition-name:${viewTransitionName(node.id)}`}>
      {#if draft?.id === node.id}{#if picker}{@render pickerPanel()}{:else}{@render editor()}{/if}{:else}
        <button type="button" class="node-summary" class:branded={node.type === 'app_skill_action' || isTrigger(node) || isMessage(node) || isCheck(node)} class:expanded={readOnly && expandedReadOnly === node.id} class:dragging={draggingNodeId === node.id} style={style(node)} data-ai-label={aiAddedNodeIds.includes(node.id) ? $text('workflows.builder.ai_node_added') : aiEditedNodeIds.includes(node.id) ? $text('workflows.builder.ai_node_edited') : undefined} data-testid="workflow-node-summary" aria-expanded={expandedReadOnly === node.id} data-can-drag={!readOnly && !!onSave && (canMoveWorkflowNode(graph, node.id, 'up') || canMoveWorkflowNode(graph, node.id, 'down'))} onpointerdown={event => startPointerDrag(event, node.id)} onclick={() => { if (!suppressNodeClick && !draggingNodeId) edit(node); }}><span class="node-app-icon" data-testid="workflow-node-primary-icon"><span class="workflow-icon" style={primaryNodeIconStyle(node)} aria-hidden="true"></span></span><span class="kind">{kind(node)}</span>{#if isCheck(node) && checkSource(node)}<span class="check-source">{summary(checkSource(node)!)}</span>{/if}<strong data-testid="workflow-node-title-label">{summary(node)}</strong>{#if node.type === 'app_skill_action' && skillInputSummary(node)}<span class="location" data-testid="workflow-node-input-summary">{skillInputSummary(node)}</span>{/if}{#if run}<span class="run-status" class:success={runStatus === 'completed'} class:failed={runStatus === 'failed'} data-testid="workflow-run-node-status" data-node-status={run.status} role="img" aria-label={$text(`workflows.runs.status_${runStatus}`)}>{#if runStatus === 'completed'}<span class="workflow-icon" style={assetIconStyle('check', 16, 'var(--color-font-button)')} aria-hidden="true"></span>{:else}{$text(`workflows.runs.status_${runStatus}`)}{/if}</span>{/if}</button>
        {#if readOnly && expandedReadOnly === node.id}<div class="editor" data-testid="workflow-node-expanded">{#if run}<h4>{tr('input')}</h4><WorkflowValueView value={inputValue(node, run)} appId={String(node.config?.app_id ?? '')}/><h4>{tr('output')}</h4>{#if isMessage(node)}<WorkflowValueView value={{ status: run.output_summary?.status ?? run.status, delivered_results: run.output_summary?.delivered_result_count ?? 0, pending_results: run.output_summary?.pending_result_count ?? 0 }}/>{#if run.output_summary?.chat_id}<a class="quiet" href={`/#chat-id=${encodeURIComponent(String(run.output_summary.chat_id))}`}>{tr('output_open_chat')}</a>{/if}{:else}<WorkflowValueView value={outputValue(node, run)} appId={String(node.config?.app_id ?? '')}/>{/if}{#if run.error_summary}<p class="error">{workflowErrorText(run.error_summary, 'output_step_failed', run.error_code)}</p>{/if}{#if run.skipped_reason}<p>{tr('output_step_skipped')}</p>{/if}{:else}<WorkflowValueView value={inputValue(node)} appId={String(node.config?.app_id ?? '')}/>{/if}</div>{/if}
      {/if}
    </article>
    {#if isCheck(node)}
      {@const continuation = nextId(node.id)}
      <div class="branch-group">
        {#each node.config?.mode === 'ai' ? ['true','false','unsure'] : ['yes','no'] as branch}{@const target = nextId(node.id, branch) ?? nextId(node.id, branch === 'yes' ? 'true' : branch === 'no' ? 'false' : branch)}<div class="branch"><div class="connector branch-label"><span class="workflow-icon" style={assetIconStyle('workflow-check', 18, 'var(--color-font-secondary)')} aria-hidden="true"></span>{tr(branch === 'true' || branch === 'yes' ? 'if_true' : branch === 'unsure' ? 'if_unsure' : 'else')}</div>{#if target}{@render chain(target, [...visited, node.id], continuation)}{:else}{#if !readOnly}{@render slotControls({ after: node.id, branch })}{:else}<p class="nothing">{tr('do_nothing')}</p>{/if}{/if}</div>{/each}
      </div>
    {/if}
    {@const next = nextId(node.id)}
    {#if next && next !== stopAt && graph.nodes.find(item => item.id === next)?.type !== 'end'}
      {#if draggingNodeId && moveWorkflowNodeAfter(graph, draggingNodeId, node.id)}{@render dropZone(node.id)}{:else}<div class="connector">{tr('then')}</div>{/if}
      {@render chain(next, [...visited, node.id], stopAt)}
    {:else if !readOnly}
      <div class="connector">{tr('then')}</div>
      {#if draggingNodeId && moveWorkflowNodeAfter(graph, draggingNodeId, node.id)}{@render dropZone(node.id)}{:else}{@render slotControls({ after: node.id })}{/if}
    {/if}
  {/if}
{/snippet}

<section class="graph-panel" bind:this={graphPanel} data-testid={testId} data-read-only={readOnly ? 'true' : 'false'} data-dragging-node-id={draggingNodeId ?? ''} aria-busy={busy}>
  <div class="graph-canvas" class:blank={!graph.nodes.some(node => node.type !== 'end')}><div class="node-stack" data-testid="workflow-node-stack">
    {#each rootNodes as root}{@render chain(root.id)}{/each}
    {#if !graph.nodes.some(node => node.type !== 'end')}{@render slotControls({ after: null })}{/if}
  </div></div>
</section>

<svelte:window onpointermove={movePointerDrag} onpointerup={finishPointerDrag} />

<style>
  .editor.check-editor{background:var(--color-grey-10);overflow:visible;gap:1rem}
  .check-editor .if-heading{font-size:2rem;line-height:1.25;font-weight:650}
  .check-editor .check-fields{width:min(19rem,100%);gap:.65rem}
  .check-editor :global(.settings-dropdown){background:var(--color-grey-0);box-shadow:var(--shadow-sm)}
  .check-editor input{background:var(--color-grey-0);min-height:3rem;border:0}
  .ai-check-content{display:grid;min-width:0;gap:.7rem;width:min(38rem,100%);justify-self:center;text-align:start}
  .ai-check-content :global(.workflow-message-editor){background:var(--color-grey-0);border:0;border-radius:.75rem;box-shadow:var(--shadow-md)}
  .ai-check-content :global(.workflow-message-editor .tiptap){min-height:8rem;padding:.65rem .8rem}
  .check-test-controls{display:grid;gap:.4rem}
  .check-editor .test{color:var(--color-primary-start)}
  .validation-cost{text-align:center}

  .editor.ask-ai-editor{background:var(--color-grey-10);gap:1rem;overflow:visible}
  .ask-ai-content,.message-content{display:grid;gap:.65rem;min-width:0;width:min(31.7rem,100%);justify-self:center;padding-top:.3rem}
  .ask-ai-input,.message-input{min-width:0}
  .ask-ai-input :global(.workflow-message-editor),.message-input :global(.workflow-message-editor){background:var(--color-grey-0);border:0;border-radius:.75rem;box-shadow:var(--shadow-md)}
  .ask-ai-input :global(.workflow-message-editor .tiptap),.message-input :global(.workflow-message-editor .tiptap){min-height:10.5rem;padding:.65rem .8rem}
  .ask-ai-actions{display:flex;align-items:flex-start;justify-content:space-between;gap:.5rem;min-width:0;container-type:inline-size}
  .ask-ai-model{flex:0 1 auto;max-width:100%;margin:0;padding:0;border:0;min-width:0;text-align:start}
  .ask-ai-model :global(.model-selector){position:relative}
  .ask-ai-model :global(.model-selector-menu){left:0;right:auto;box-sizing:border-box;width:min(22rem,100cqw)}
  .ask-ai-test-control{display:grid;justify-items:center;gap:.4rem;color:var(--color-primary-start)}
  .ask-ai-test-control .test{color:var(--color-primary-start)}
  .ask-ai-processing{font-size:var(--font-size-small);color:var(--color-primary-start);animation:workflow-processing 1.4s ease-in-out infinite}
  .ask-ai-editor :global(.editor-header.colored){min-height:9rem}
  @keyframes workflow-processing{0%,100%{opacity:.45}50%{opacity:1}}
  @media(prefers-reduced-motion:reduce){.ask-ai-processing{animation:none}}
  .workflow-icon{display:inline-block;flex:0 0 auto;width:var(--workflow-icon-size);height:var(--workflow-icon-size);background:currentColor;-webkit-mask:var(--workflow-icon) center/contain no-repeat;mask:var(--workflow-icon) center/contain no-repeat}
  .graph-panel{font-size:16px;margin:0 auto;width:min(60rem,calc(100% - 4rem));padding:0 0 2rem}.graph-canvas{min-height:16rem;padding:2rem 1.25rem;background:var(--color-grey-0);border-radius:.9rem}.node-stack{display:grid;justify-items:center}.flow-node{display:grid;justify-items:center;width:100%;min-width:0}.node-summary{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.5rem;width:min(19rem,100%);padding:.7rem 1rem .7rem;min-height:8rem;border:0;border-radius:1rem;background:var(--color-grey-10);color:var(--color-font-primary);box-shadow:var(--shadow-sm);cursor:pointer;font:inherit}.node-summary strong{font-size:16px;line-height:1.4}.node-summary> :global(svg){color:var(--color-primary)}.node-summary .kind{font-size:14px;color:var(--color-font-secondary)}.node-summary.branded{background:var(--node-gradient);color:var(--color-font-button)}.node-summary.branded .kind,.node-summary.branded> :global(svg){color:var(--color-font-button);opacity:.9}.location{font-size:16px;opacity:.8}.connector{color:var(--color-font-secondary);font-size:16px;font-weight:650;text-align:center;padding:.8rem 0}.branch-group{width:min(42rem,100%);padding:0 .75rem .7rem;border:1px solid var(--color-grey-20);border-radius:1rem;margin-top:-.5rem;box-sizing:border-box}.branch{display:grid;justify-items:center}.branch .branch-label{padding-top:1rem}.nothing{display:grid;place-items:center;box-sizing:border-box;white-space:pre-line;line-height:1.5;font:inherit;font-size:16px;cursor:pointer;background:transparent;margin:0;border:1px dashed var(--color-grey-30);border-radius:1rem;width:min(21rem,100%);min-height:9.25rem;padding:.9rem 1.25rem;text-align:center;color:var(--color-font-secondary);transition:border-color var(--duration-normal,.2s) ease}.nothing:hover,.nothing:focus-visible{border-color:var(--color-font-button)}.add-controls,.choices{display:flex;flex-wrap:wrap;gap:.8rem;justify-content:center;padding:.75rem 0}.choice{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.6rem;min-width:6.5rem;min-height:4.5rem;border:0;border-radius:.7rem;color:var(--color-font-secondary);background:var(--color-grey-10);box-shadow:var(--shadow-sm);padding:.65rem;cursor:pointer;font:inherit;font-size:16px;font-weight:600}.choice :global(svg){color:var(--color-primary)}.editor{position:relative;min-width:0;width:min(42rem,100%);box-sizing:border-box;display:grid;gap:1rem;padding:0 1.5rem 1rem;background:var(--color-grey-10);border-radius:1rem;box-shadow:var(--shadow-sm);color:var(--color-font-primary);text-align:center}.picker{min-height:11rem;animation:editor-swap .16s ease-out}h2,h3,h4,p{margin:0}h3{font-size:16px}h4{font-size:16px;text-align:start;color:var(--color-font-secondary)}.card-scroll{display:flex;flex-wrap:nowrap;min-width:0;max-width:100%;gap:1rem;overflow-x:auto;width:100%;padding:.5rem 0 1rem;scroll-snap-type:x proximity}.card-scroll :global(>*){flex-shrink:0;scroll-snap-align:center}.quiet{display:inline-flex;align-items:center;justify-content:center;gap:.35rem;min-height:2rem;padding:.3rem .5rem;border:0;box-shadow:none;background:transparent;color:var(--color-primary);font:inherit;font-size:16px;cursor:pointer}.primary{justify-self:center;min-width:9rem;min-height:2.4rem;border:0;border-radius:.8rem;padding:.55rem 1.2rem;font:inherit;font-size:16px;font-weight:650;background:var(--color-button-primary);color:var(--color-font-button);box-shadow:var(--shadow-sm);cursor:pointer}.primary:disabled{background:var(--color-grey-30);color:var(--color-font-secondary);box-shadow:none;cursor:not-allowed}.field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}label{display:grid;gap:.4rem;min-width:0;text-align:start;font-size:16px}.editor-field-label{display:inline-flex;align-items:center;gap:var(--spacing-2);min-width:0}.editor-field-label :global(svg){flex:0 0 auto;color:var(--color-font-secondary)}input{box-sizing:border-box;width:100%;min-height:2.5rem;border:1px solid var(--color-grey-25);border-radius:.8rem;padding:.5rem .7rem;background:var(--workflow-input-surface,var(--color-grey-10));color:var(--color-font-primary);font:inherit;font-size:16px;box-shadow:var(--shadow-sm)}.weekdays{display:flex;gap:.7rem;flex-wrap:wrap}.weekdays label{display:flex;align-items:center;gap:.45rem}.weekdays input,input[type=checkbox]{width:1.05rem;height:1.05rem;min-height:0;box-shadow:none;accent-color:var(--color-primary)}.test-control{display:flex;justify-content:center;align-items:center;gap:.7rem;font-size:16px}.output-heading{display:flex;justify-content:space-between;font-size:16px;color:var(--color-font-secondary)}.check-fields{display:grid;gap:.8rem;width:min(23rem,100%);margin:auto}.message-preview{white-space:pre-wrap;overflow-wrap:anywhere;user-select:text;text-align:start;font-size:16px}.message-preview{display:grid;gap:.8rem;padding:1rem;background:var(--color-grey-0);border-radius:.8rem}.save-row{display:flex;justify-content:center;align-items:center;gap:1rem;margin-top:.3rem}.error{color:var(--color-error);font-size:16px;overflow-wrap:anywhere}.reminder{color:var(--color-font-secondary);font-size:14px;text-align:start}.ai-check-save-hint{text-align:center}.target{justify-self:start}button:disabled{opacity:.55;cursor:wait}button:focus-visible,input:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}
  @keyframes editor-swap{from{opacity:.65;transform:translateY(.25rem)}to{opacity:1;transform:translateY(0)}}@media(max-width:730px){.graph-panel{width:calc(100% - 1rem)}.graph-canvas{padding:1.5rem .5rem}.editor{padding:0 .8rem 1rem}.field-grid{grid-template-columns:1fr}.branch-group{padding-inline:.4rem}.choice{min-width:5.6rem}.card-scroll :global(.resume-chat-large-card){width:15rem;min-width:15rem;max-width:15rem}}@media(prefers-reduced-motion:reduce){.picker{animation:none}}
  .node-app-icon{display:grid;place-items:center}.graph-panel{margin-block:1.75rem}.node-summary.branded .node-app-icon{color:var(--color-font-button)}
  .node-summary{box-sizing:border-box;width:min(21rem,100%);min-height:9.25rem;padding:.9rem 1.25rem;gap:.55rem}
  .node-summary.expanded{width:min(42rem,100%);border-radius:1rem 1rem 0 0}.node-summary.expanded+.editor{border-radius:0 0 1rem 1rem}.check-source{font-size:14px;color:var(--color-font-secondary)}
  .node-summary[data-can-drag="true"]{cursor:grab}.node-summary[data-can-drag="true"]:active{cursor:grabbing}
  .node-summary.dragging{opacity:.55}
  .flow-node.ai-added .node-summary,.flow-node.ai-edited .node-summary{outline:3px solid var(--color-button-primary);outline-offset:4px}
  .flow-node.ai-added .node-summary::after,.flow-node.ai-edited .node-summary::after{content:attr(data-ai-label);position:absolute;top:-.8rem;right:-.7rem;padding:.15rem .5rem;border-radius:1rem;background:var(--color-button-primary);color:var(--color-font-button);font-size:12px;font-weight:700}
  .slot-surface,.drop-here{box-sizing:border-box;width:min(21rem,100%);min-height:9.25rem;border:2px dashed var(--color-font-secondary);border-radius:1rem;text-align:center}
  .slot-surface{height:9.25rem;overflow:hidden;background:transparent;interpolate-size:allow-keywords;transition:width var(--duration-slow,.3s) ease,height var(--duration-slow,.3s) ease,border-color var(--duration-normal,.2s) ease,background-color var(--duration-normal,.2s) ease}
  .slot-surface:hover,.slot-surface:focus-within{border-color:var(--color-font-button)}
  .slot-surface.expanded{width:min(48.3rem,100%);height:auto;min-height:11rem;border:1px solid var(--color-grey-20);background:var(--color-grey-0)}
  .slot-surface.ask-ai-slot{overflow:visible}
  .slot-surface>.nothing{width:calc(100% + 4px);height:calc(100% + 4px);margin:-2px;border:0}
  .slot-surface>.nothing:hover,.slot-surface>.nothing:focus-visible{border-color:var(--color-font-button)}
  .slot-surface.expanded>.editor{box-shadow:none;border:0;width:100%;border-radius:0}
  .drop-here{display:grid;place-items:center;margin:.5rem 0;padding:1rem;background:var(--color-grey-10);color:var(--color-font-primary);font-weight:650;animation:editor-swap .16s ease-out;transition:border-color .15s ease,background-color .15s ease}
  .drop-here.drop-slot{border-color:var(--color-primary);background:var(--color-grey-20);color:var(--color-primary)}
  .output-progress{display:flex;align-items:center;justify-content:center;gap:.65rem;min-height:5rem;color:var(--color-font-secondary)}
  .output-spinner{display:inline-block;width:1.15rem;height:1.15rem;border:.18rem solid var(--color-grey-30);border-top-color:var(--color-primary);border-radius:50%;animation:workflow-spin .8s linear infinite}
  .tested-output{min-width:0;text-align:start}
  @keyframes workflow-spin{to{transform:rotate(360deg)}}
  .node-summary.branded .check-source{color:var(--color-font-button);opacity:.9}
  .branch-label{display:flex;align-items:center;justify-content:center;gap:.4rem}

  .editor :global(.settings-dropdown-wrapper){padding:0}
  .editor :global(.settings-dropdown){min-height:3.375rem;background:var(--workflow-input-surface,var(--color-grey-10))}
  .editor :global(.app-store-card), .editor :global(.app-card-name), .editor :global(.app-card-description){text-align:start}
  .editor :global(.settings-input), .editor input, .editor input::placeholder, .editor :global(.workflow-message-editor .tiptap), .editor :global(.workflow-message-editor .tiptap p){text-align:start}

  /* Shared app/skill/chat pickers keep workflow typography without changing other screens. */
  .graph-panel {
    --font-size-p: max(16px, 1rem);
    --font-size-small: max(14px, 0.875rem);
    --font-size-xs: max(14px, 0.875rem);
    --font-size-xxs: max(14px, 0.875rem);
    --workflow-input-surface: linear-gradient(135deg, var(--color-grey-10) 9.04%, var(--color-grey-20) 90.06%);
  }
  /* Result cards contain local badge sizes; raise only those small labels. */
  .graph-panel :global(.workflow-value .event-location),
  .graph-panel :global(.workflow-value .event-type-badge),
  .graph-panel :global(.workflow-value .event-fee),
  .graph-panel :global(.workflow-value .event-rsvp),
  .graph-panel :global(.workflow-value .event-source),
  .graph-panel :global(.workflow-value .listing-address),
  .graph-panel :global(.workflow-value .listing-metadata),
  .graph-panel :global(.workflow-value .provider-badge) {
    font-size: max(14px, 0.875rem);
  }
  .node-summary { position:relative; }
  .run-status { position:absolute; top:.4rem; left:.4rem; display:flex; align-items:center; justify-content:center; min-height:1.5rem; padding:0 .5rem; border-radius:var(--radius-full); background:var(--color-grey-20); color:var(--color-font-primary); font-size:var(--font-size-small); }
  .run-status.success { width:1.5rem; padding:0; background:var(--color-chat-rainbow-green); }
  .run-status.failed { background:var(--color-error); color:var(--color-font-button); }

  /* Match the reference builder's narrow graph and wide in-place editors. */
  .graph-panel { width:min(52.2rem, calc(100% - 2rem)); }
  .graph-canvas { padding:1.5rem 1.25rem; }
  .graph-canvas.blank { min-height:0; padding-block:.75rem; }
  .editor { width:min(48.3rem, 100%); grid-template-columns:minmax(0,1fr); overflow:hidden; background:var(--color-grey-0); border:1px solid var(--color-grey-20); }
  .editor.weather-editor { background:var(--color-grey-10); }
  .editor :global(.editor-header.colored) { margin-top:-1px; }
  .skill-editor .input-heading,
  .skill-editor .output-heading,
  .skill-editor :global(.output-fields),
  .skill-editor :global(.schema-fields) { box-sizing:border-box; width:min(44rem,100%); justify-self:center; }
  .skill-editor .input-heading,
  .skill-editor .output-heading h4 { display:flex; align-items:center; gap:.35rem; }
  .section-icon { display:inline-flex; flex:0 0 auto; align-items:center; justify-content:center; }
  .skill-editor .output-heading { display:grid; grid-template-columns:5.5rem minmax(0,1fr) minmax(0,1fr); column-gap:.6rem; align-items:center; }
  .skill-editor .output-heading h4 { grid-column:1/3; }
  .skill-editor .output-heading > span { grid-column:3; font-weight:650; text-align:start; }
  .weather-editor :global(.schema-fields > [data-testid="workflow-schema-field-location"]),
  .weather-editor :global(.schema-fields > [data-testid="workflow-schema-field-date-range"]) { grid-column:auto; }
  .choice { box-sizing:border-box; width:9.25rem; min-width:9.25rem; min-height:6rem; margin:0; background:var(--color-grey-0); }
  .choice :global(svg) { color:var(--color-primary-start); }
  .add-controls.blank { position:relative; align-items:center; min-height:8.5rem; gap:2.25rem; padding:0; }
  .add-controls:not(.blank) { box-sizing:border-box; width:min(21rem, 100%); }
  .add-controls.blank::before { content:''; position:absolute; left:50%; top:0; bottom:0; width:1px; background:var(--color-grey-25); }
  .add-controls.blank .choice { position:relative; z-index:1; }
  .branch-group { width:min(23.5rem, 100%); }
  .branch-group:has(.editor) { width:min(48.3rem, 100%); padding-inline:0; }
  .nothing { width:min(21rem, 100%);border:2px dashed var(--color-font-secondary); }
  :global(::view-transition-group(*)) { animation-duration:var(--duration-slow, .3s); animation-timing-function:cubic-bezier(.32, 0, .2, 1); }
  :global(::view-transition-old(root)), :global(::view-transition-new(root)) { animation:none; }
  .primary { min-width:11rem; border-radius:var(--radius-8); }
  .chat-search { display:flex; align-items:center; justify-self:center; width:min(22rem, 100%); gap:.35rem; color:var(--color-font-secondary); }
  .chat-search input { min-height:2rem; border:0; background:transparent; box-shadow:none; padding:.2rem; }
  .editor.chat-destination { gap:.75rem; }
  .chat-destination .card-scroll { box-sizing:border-box; padding-inline:calc(50% - 8.96875rem); }
  .new-chat-destination { display:inline-flex; align-items:center; justify-content:center; gap:var(--spacing-4); min-height:2.5625rem; border-radius:var(--radius-full); }
  .new-chat-destination :global(.new-chat-icon) { width:20px; height:20px; flex:0 0 auto; background:var(--color-font-button); }
  .output-toggle { justify-self:center; border:0; padding:.2rem .4rem; background:transparent; color:var(--color-font-secondary); font:inherit; font-size:14px; cursor:pointer; }
  .credits-coin-icon { width:16px; height:16px; flex:0 0 auto; -webkit-mask-image:url('@openmates/ui/static/icons/coins.svg'); -webkit-mask-size:cover; -webkit-mask-position:center; -webkit-mask-repeat:no-repeat; mask-image:url('@openmates/ui/static/icons/coins.svg'); mask-size:cover; mask-position:center; mask-repeat:no-repeat; background:currentColor; }
  .save-row .primary { margin:0; }
  .card-scroll :global(.resume-chat-large-card) { width:17.9375rem; min-width:17.9375rem; max-width:17.9375rem; height:9.9375rem; min-height:9.9375rem; max-height:9.9375rem; }
  @media(max-width:730px) {
    .graph-panel { width:calc(100% - 1rem); }
    .graph-canvas { padding:1.25rem .5rem; }
    .graph-canvas.blank { padding-block:.5rem; }
    .editor { width:100%; }
    .skill-editor .output-heading { grid-template-columns:minmax(0,1fr) 6.75rem; column-gap:.5rem; }
    .skill-editor .output-heading h4 { grid-column:1; }
    .skill-editor .output-heading > span { grid-column:2; }
    .weather-editor :global(.schema-fields > [data-testid="workflow-schema-field-location"]),
    .weather-editor :global(.schema-fields > [data-testid="workflow-schema-field-date-range"]) { grid-column:1/-1; }
    .choice { width:8.625rem; min-width:8.625rem; min-height:5.5rem; }
    .choice .workflow-icon, .choice :global(svg) { width:24px; height:24px; }
    .add-controls.blank { gap:.75rem; }
    .chat-destination .card-scroll { padding-inline:calc(50% - 7.5rem); }
  }
  @media(prefers-reduced-motion:reduce){.slot-surface,.drop-here{transition:none;animation:none}.output-spinner{animation:none}}
</style>
