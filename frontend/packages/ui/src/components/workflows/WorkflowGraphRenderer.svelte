<!-- Progressive workflow authoring. Unsaved node inputs and test outputs stay in memory. -->
<script lang="ts">
  import { onMount, tick } from 'svelte';
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
  import { outputTemplateSyntax } from './workflowMessageTokens';
  import { outputFields, presentedItems, valueType, valueEntries } from './workflowValuePresentation';
  import { workflowFieldIcon } from './workflowFieldIcon';
  import { workflowSkillInputSummary } from './workflowSkillSummary';
  import { workflowOutputExamples, workflowUpstreamOutputs } from './workflowOutputExamples';
  import { workflowApiRequest, workflowWorkspaceStore, type WorkflowGraph, type WorkflowNode, type WorkflowNodeRun } from '../../stores/workflowWorkspaceStore';
  import type { Chat } from '../../types/chat';
  import type { AppMetadata } from '../../types/apps';
  import { record, label, schemaDefault, normalizeSchema, isAskAi, isCheck, isTrigger, isMessage, messageDestinationConfig, capabilityFor, outputsBefore, insertNode, removeNode, WorkflowNodeDependencyError, type Capability, type Insertion, type Output, type Schema } from './workflowBuilder';

  let { graph, readOnly = false, nodeRuns = [], testId = 'workflow-graph-renderer', workflowId = null, capabilityFixtures = null, chatFixtures = null, onSave = null }: {
    graph: WorkflowGraph; readOnly?: boolean; nodeRuns?: WorkflowNodeRun[]; testId?: string; workflowId?: string | null; capabilityFixtures?: Capability[] | null; chatFixtures?: Chat[] | null;
    onChange: (graph: WorkflowGraph) => void; onSave?: ((graph: WorkflowGraph) => Promise<void>) | null;
  } = $props();
  let capabilities = $state<Capability[]>([]);
  let capabilityLoad: Promise<void> | null = null;
  let loadError = $state('');
  let draft = $state<WorkflowNode | null>(null);
  let insertion = $state<Insertion>({ after: null });
  let picker = $state<'trigger' | 'action' | 'app' | 'skill' | null>(null);
  let selectedApp = $state('');
  let deleteArmed = $state(false);
  let expandedReadOnly = $state<string | null>(null);
  let busy = $state(false);
  let nodeError = $state('');
  let testStatus = $state<'idle' | 'processing' | 'completed' | 'cancelled' | 'failed'>('idle');
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
  let showAllVariables = $state(false);
  let showOutputFields = $state(false);
  let graphPanel = $state<HTMLElement>();
  let messageEditor = $state<{ insertReference: (output: Output) => void; removeMentionTrigger: () => void } | null>(null);
  let askSuggestions = $state<string[]>([]);
  let askVerdict = $state<'idle' | 'checking' | 'allowed' | 'asks_to_invoke_app_skill' | 'unverified'>('idle');
  let askReminder = $state('');
  let askHintRevision = 0;
  let askHintTimer: ReturnType<typeof setTimeout> | null = null;
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  const Play = getLucideIcon('play'); const Stop = getLucideIcon('square'); const Search = getLucideIcon('search');
  const Download = getLucideIcon('download'); const Upload = getLucideIcon('upload');
  const available = $derived(capabilities.filter(item => item.type === 'app_skill' && item.enabled && item.id !== 'ai.ask'));
  const askCapability = $derived(capabilities.find(item => item.id === 'ai.ask' && item.enabled));
  const appIds = $derived([...new Set(available.map(item => item.metadata.app_id).filter(Boolean))] as string[]);
  const draftCapability = $derived(draft ? capabilityFor(draft, capabilities) : undefined);
  const persistedDraft = $derived(!!draft && graph.nodes.some(node => node.id === draft?.id));
  const outputs = $derived(draft ? outputsBefore(graph, draft.id, capabilities, insertion) : []);
  const variableGroups = $derived(presentedItems(outputs));
  const eligibleOutputs = $derived([...variableGroups.basic, ...variableGroups.advanced]);
  const visibleVariableOutputs = $derived((showAllVariables ? eligibleOutputs : variableGroups.basic).toSorted((a, b) => Number(askSuggestions.includes(b.reference)) - Number(askSuggestions.includes(a.reference))));
  const aiCheckSelectedInputs = $derived(draft && isCheck(draft) && draft.config?.mode === 'ai' ? templateReferences(String(draft.config?.question ?? '')) : []);
  const aiCheckCanSave = $derived(!draft || !isCheck(draft) || draft.config?.mode !== 'ai' || (hasTemplateText(String(draft.config?.question ?? '')) && aiCheckSelectedInputs.length > 0));
  const blocks = $derived(Array.isArray(draft?.config?.blocks) ? draft.config.blocks as Record<string, unknown>[] : []);
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
    return () => { testRevision += 1; askHintRevision += 1; if (askHintTimer) clearTimeout(askHintTimer); };
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
    target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center', inline: 'nearest' });
    target.focus({ preventScroll: true });
  }
  function openPicker(kind: typeof picker, slot: Insertion): void { if (busy || testStatus === 'processing') return; draft = null; deleteArmed = false; nodeError = ''; preview = null; insertion = slot; picker = kind; void scrollEditorIntoView(); }
  function resetAskHints(): void { askHintRevision += 1; if (askHintTimer) clearTimeout(askHintTimer); askHintTimer = null; askSuggestions = []; askVerdict = 'idle'; askReminder = ''; }
  function closeEditor(immediate = false): void {
    const close = () => { draft = null; picker = null; deleteArmed = false; nodeError = ''; preview = null; chooseChat = false; showReferences = false; showAllVariables = false; showOutputFields = false; resetAskHints(); };
    if (immediate) close(); else transitionNodeUpdate(close);
  }
  function backFromEditor(): void {
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
    transitionNodeUpdate(() => { draft = editable; testStatus = testOutputs[node.id] ? 'completed' : 'idle'; void scrollEditorIntoView(node.id); });
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
  function predicatePatch(config: Record<string, unknown>): void { patch({ predicate: { ...record(draft?.config?.predicate), ...config } }); }
  function sourceSchema(reference: unknown) { return outputs.find(output => output.reference === reference)?.schema; }
  function operators(reference: unknown): string[] { const type = sourceSchema(reference)?.type; return ['number', 'integer'].includes(type ?? '') ? ['gt', 'gte', 'lt', 'lte', 'eq', 'ne'] : type === 'boolean' ? ['eq', 'ne'] : ['eq', 'ne', 'contains']; }
  function operatorSymbol(op: unknown): string { return ({ gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', ne: '≠', contains: tr('contains') } as Record<string, string>)[String(op)] ?? ''; }
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
  function style(node: WorkflowNode): string { const appId = String(node.config?.app_id ?? 'workflows'); return `--node-gradient: var(--color-app-${appId}, var(--gradient-primary));`; }
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
  function failForUser(error: unknown, key: string): void { console.error('[Workflow builder]', error); nodeError = tr(key); }
  function sourceApp(reference: unknown): string { const id = String(reference ?? '').split('.')[1]; return String(graph.nodes.find(node => node.id === id)?.config?.app_id ?? ''); }
  function checkMode(mode: 'exact' | 'ai'): void {
    if (!draft) return;
    draft = { ...draft, config: mode === 'ai' ? { mode: 'ai', question: '', selected_inputs: [] } : { mode: 'exact', predicate: { left: '', op: '', right: '' } } };
  }
  function templateReferences(value: string, availableOutputs: Output[] = outputs): string[] {
    const references = [...value.matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)].map(match => {
      const path = match[1].trim();
      return path.startsWith('steps.') ? path.replace(/^steps\.([^.]+)\./, '$nodes.$1.output.') : path;
    });
    return [...new Set(references.filter(reference => availableOutputs.some(output => output.reference === reference)))].slice(0, 24);
  }
  function hasTemplateText(value: string): boolean { return value.replace(/\{\{\s*[^{}]+?\s*\}\}/g, '').trim().length > 0; }
  function updateAiCheckQuestion(value: string): void { patch({ question: value, selected_inputs: templateReferences(value) }); }
  function addAiCheckReference(output: Output): void { messageEditor?.insertReference(output); showReferences = false; }
  function askInstruction(): string { return String(record(draft?.config?.input).prompt ?? ''); }
  function scheduleAskHints(instruction: string): void {
    const revision = ++askHintRevision;
    if (askHintTimer) clearTimeout(askHintTimer);
    askHintTimer = null; askSuggestions = []; askVerdict = instruction.trim() ? 'checking' : 'idle'; askReminder = '';
    if (!instruction.trim()) return;
    askHintTimer = setTimeout(() => void loadAskHints(instruction, revision), 1000);
  }
  async function loadAskHints(instruction: string, revision: number): Promise<void> {
    askHintTimer = null;
    try {
      const data = await workflowApiRequest<{ verdict: 'allowed' | 'asks_to_invoke_app_skill' | 'unverified'; suggested_references: string[]; reminder?: string | null }>('/v1/workflows/ai-authoring/hints', {
        method: 'POST',
        body: JSON.stringify({
          instruction,
          references: outputs.map(output => ({
            reference: output.reference,
            label: output.label,
            value_type: output.schema.type ?? 'unknown',
            inserted: instruction.includes(outputTemplateSyntax(output.reference)),
          })),
        }),
      });
      if (revision !== askHintRevision || instruction !== askInstruction()) return;
      askVerdict = data.verdict; askSuggestions = data.suggested_references; askReminder = data.reminder ?? '';
    } catch (error) {
      if (revision !== askHintRevision || instruction !== askInstruction()) return;
      console.warn('[Workflow Ask AI hints]', error); askVerdict = 'unverified'; askReminder = tr('ask_ai_validation_unavailable');
    }
  }
  function updateAskInstruction(value: string): void { patch({ input: { prompt: value } }); scheduleAskHints(value); }
  function addAskReference(output: Output): void { messageEditor?.insertReference(output); showReferences = false; }
  async function saveNode(): Promise<void> {
    if (!draft || !onSave || busy) return;
    if (isMessage(draft) && !String(draft.config?.title ?? '').trim()) { nodeError = tr('title_required'); return; }
    if (isCheck(draft) && draft.config?.mode === 'ai' && !aiCheckCanSave) { nodeError = tr('ai_check_required'); return; }
    if (isCheck(draft) && draft.config?.mode !== 'ai' && (!record(draft.config?.predicate).left || !record(draft.config?.predicate).op)) { nodeError = tr('check_required'); return; }
    if (isAskAi(draft) && !askInstruction().trim()) { nodeError = tr('ask_ai_instruction_required'); return; }
    if (isAskAi(draft) && askVerdict === 'asks_to_invoke_app_skill') { nodeError = tr('ask_ai_app_warning'); return; }
    busy = true; nodeError = '';
    const saved = structuredClone($state.snapshot(draft)); saved.title ||= summary(saved);
    try {
      await onSave({ ...insertNode(graph, saved, insertion), version: 2 }); closeEditor(true); busy = false;
      if (isTrigger(saved) && !graph.nodes.some(node => !isTrigger(node) && node.type !== 'end')) openPicker('action', { after: saved.id });
      else if (isCheck(saved)) openPicker('action', { after: saved.id, branch: saved.config?.mode === 'ai' ? 'true' : 'yes' });
    } catch (error) { failForUser(error, 'save_failed'); }
    finally { busy = false; }
  }
  async function deleteNode(): Promise<void> { if (!draft || !onSave || busy) return; busy = true; try { await onSave({ ...removeNode(graph, draft.id, capabilities), version: 2 }); closeEditor(); } catch (error) { if (error instanceof WorkflowNodeDependencyError) { console.error('[Workflow builder]', error); nodeError = tr('step_in_use').replace('{steps}', error.dependentNodeTitles.join(', ')); } else failForUser(error, 'save_failed'); } finally { busy = false; } }
  function requestDelete(): void { if (!deleteArmed) { deleteArmed = true; return; } void deleteNode(); }
  async function testNode(): Promise<void> {
    if (!draft || !workflowId || testStatus === 'processing') return;
    const node = structuredClone($state.snapshot(draft)); const revision = ++testRevision; testStatus = 'processing'; nodeError = '';
    try {
      const upstreamOutputs = workflowUpstreamOutputs(graph, node.id, availableTestOutputs, insertion);
      const data = await workflowApiRequest<{ run: { id: string } }>(`/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(node.id)}/test`, { method: 'POST', body: JSON.stringify({ node, input: {}, upstream_outputs: upstreamOutputs }) });
      testingRunId = data.run.id;
      for (let attempt = 0; attempt < 60 && revision === testRevision; attempt++) {
        const run = await workflowWorkspaceStore.getWorkflowRun(workflowId, data.run.id);
        if (!['accepted', 'queued', 'running', 'cancellation_requested'].includes(run.status)) {
          const result = run.node_runs?.find(item => item.node_id === node.id);
          if (run.status === 'completed') { testOutputs = { ...testOutputs, [node.id]: result?.output_summary ?? run.output_summary ?? {} }; testStatus = 'completed'; }
          else { testStatus = run.status === 'cancelled' ? 'cancelled' : 'failed'; console.error('[Workflow test]', result?.error_summary ?? run.error_summary ?? run.status); nodeError = tr('output_test_failed'); }
          testingRunId = null; return;
        }
        await new Promise(resolve => setTimeout(resolve, Math.min(1500 + attempt * 500, 5000)));
      }
      if (revision === testRevision) { testStatus = 'idle'; nodeError = tr('test_pending'); }
    } catch (error) { if (revision === testRevision) { testStatus = 'failed'; failForUser(error, 'output_test_failed'); } }
  }
  async function stopTest(): Promise<void> { if (!workflowId || !testingRunId) return; try { await workflowWorkspaceStore.cancelWorkflowRun(workflowId, testingRunId); } catch (error) { failForUser(error, 'save_failed'); } }
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
  function addReference(output: Output): void {
    if (!draft) return;
    if (['array', 'object'].includes(output.schema.type ?? '')) {
      messageEditor?.removeMentionTrigger();
      if (!blocks.some(block => block.source === output.reference)) patch({ blocks: [...blocks, { id: `block_${crypto.randomUUID().slice(0, 8)}`, source: output.reference, only_new_results: false }] });
    } else messageEditor?.insertReference(output);
    showReferences = false;
  }
  function patchBlock(index: number, values: Record<string, unknown>): void { patch({ blocks: blocks.map((block, i) => i === index ? { ...block, ...values } : block) }); }
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
    <WorkflowOutputFields {properties} {values} {appId} {path}/>
  {/if}
{/snippet}

{#snippet choice(icon: string, title: string, action: () => void, testId?: string)}
  {@const Icon = getLucideIcon(icon)}{@const asset = ({ blocks: 'app', sparkles: 'ai', 'messages-square': 'chat', 'calendar-clock': 'workflow', 'calendar-days': 'calendar', 'git-branch': 'workflow-check' } as Record<string, string>)[icon]}<button type="button" class="choice" data-testid={testId} onclick={action}>{#if asset}<span class="workflow-icon" style={assetIconStyle(asset, 27)} aria-hidden="true"></span>{:else}<Icon size={27}/>{/if}<span>{title}</span></button>
{/snippet}

{#snippet slotControls(slot: Insertion)}
  {#if !readOnly}
    {#if sameSlot(slot) && (picker || (draft && !graph.nodes.some(node => node.id === draft?.id)))}
      {#if picker}{@render pickerPanel()}{:else if draft}{@render editor()}{/if}
    {:else}
      <div class="add-controls" class:blank={!slot.after && !graph.nodes.length} data-testid="workflow-action-palette">
        {#if !graph.nodes.some(isTrigger) && !slot.branch}{@render choice('calendar-clock', tr('add_trigger'), () => openPicker('trigger', slot), 'workflow-add-time-trigger')}{/if}
        {#if !slot.after && !graph.nodes.length}{@render choice('blocks', tr('add_action'), () => openPicker('action', slot), 'workflow-add-step')}{:else}<button type="button" class="nothing" data-testid="workflow-add-step" onclick={() => openPicker('action', slot)}>{tr('do_nothing_add_step')}</button>{/if}
      </div>
    {/if}
  {/if}
{/snippet}

{#snippet pickerPanel()}
  {#key picker}
  <div class="editor picker" style={draft ? style(draft) : ''} data-testid="workflow-step-menu" tabindex="-1">
    <WorkflowEditorHeader
      title={tr(picker === 'trigger' ? 'add_trigger' : picker === 'app' ? 'use_app' : picker === 'skill' ? 'choose_skill' : 'add_action')}
      iconStyle={assetIconStyle(picker === 'trigger' ? 'workflow' : picker === 'skill' ? selectedApp : 'app', 16, 'var(--color-font-secondary)')}
      backLabel={picker === 'app' || picker === 'skill' ? tr('back') : ''}
      showDelete={persistedDraft}
      {deleteArmed}
      closeLabel={tr('close')}
      deleteLabel={tr('delete_node')}
      confirmDeleteLabel={tr('confirm_delete_node')}
      onBack={() => { picker = picker === 'skill' ? 'app' : 'action'; deleteArmed = false; }}
      onDelete={requestDelete}
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
    <div class="editor" class:skill-editor={draft.type === 'app_skill_action'} class:weather-editor={draft.type === 'app_skill_action' && String(draft.config?.app_id ?? '') === 'weather'} class:chat-destination={isMessage(draft) && chooseChat} style={style(draft)} data-testid="workflow-node-expanded" tabindex="-1">
      <WorkflowEditorHeader
        title={draft.type === 'app_skill_action' ? (isAskAi(draft) ? tr('ask_ai') : summary(draft)) : kind(draft)}
        eyebrow={draft.type === 'app_skill_action' ? kind(draft) : ''}
        subtitle={draft.type === 'app_skill_action' ? location(draft) : ''}
        backLabel={isMessage(draft) && chooseChat ? tr('add_action') : draft.type === 'app_skill_action' && !isAskAi(draft) ? tr('back_to_app_skill') : ''}
        backIconSize={24}
        iconStyle={isMessage(draft) && chooseChat ? assetIconStyle('chat', 19, 'var(--color-font-button)') : primaryNodeIconStyle(draft)}
        colored={draft.type === 'app_skill_action' || isTrigger(draft) || isMessage(draft) || isCheck(draft)}
        showDelete={persistedDraft}
        {deleteArmed}
        disabled={busy || testStatus === 'processing'}
        closeLabel={tr('close')}
        deleteLabel={tr('delete_node')}
        confirmDeleteLabel={tr('confirm_delete_node')}
        onBack={backFromEditor}
        onDelete={requestDelete}
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
        <h3>{@render editorFieldLabel('question', tr('ask_ai_question'), { type:'string' })}</h3>
        <WorkflowMessageEditor bind:this={messageEditor} value={askInstruction()} outputs={eligibleOutputs} placeholder={tr('ask_ai_placeholder')} disabled={busy || testStatus === 'processing'} onChange={updateAskInstruction} onMentionTrigger={visible => showReferences = visible}/>
        {#if eligibleOutputs.length}<div class="variable-picker"><div class="suggestions" data-testid="workflow-ai-suggestions" aria-label={tr('suggested_values')}>{#each visibleVariableOutputs as output}<button type="button" class="chip" onclick={() => addAskReference(output)}>+ {output.label}</button>{/each}</div>{#if variableGroups.advanced.length}<button type="button" class="variable-toggle" aria-expanded={showAllVariables} onclick={() => showAllVariables = !showAllVariables}>{tr(showAllVariables ? 'show_basic_variables' : 'show_all_variables')}</button>{/if}</div>{/if}
        {#if showReferences}<div class="references" aria-label={tr('select_output')}>{#each eligibleOutputs as output}<button type="button" class="quiet" onclick={() => addAskReference(output)}>{output.label}</button>{/each}</div>{/if}
        {#if askVerdict === 'asks_to_invoke_app_skill'}<p class="error ask-validation" role="alert" data-testid="workflow-ai-app-warning">{tr('ask_ai_app_warning')}</p>{:else if askVerdict === 'unverified'}<p class="reminder ask-validation" data-testid="workflow-ai-neutral-reminder">{askReminder || tr('ask_ai_validation_unavailable')}</p>{:else if askVerdict === 'checking'}<p class="reminder ask-validation" aria-live="polite">{tr('checking_instruction')}</p>{/if}
        <div class="test-control">
          {#if testStatus === 'processing'}<span aria-live="polite">{tr('processing')}</span>{#if testingRunId}<button type="button" class="quiet" onclick={() => void stopTest()}><Stop size={16}/>{tr('stop')}</button>{/if}
          {:else}<button type="button" class="quiet test" data-testid="workflow-test-action" disabled={!workflowId || !draftCapability} onclick={() => void testNode()}><Play size={16}/>{tr(testOutputs[draft.id] ? 'test_again' : 'test_action')}<span class="credits-coin-icon" aria-hidden="true"></span><span>{tr('variable_cost')}</span></button>{/if}
        </div>
        {@render outputSection(draftCapability?.metadata.output_schema?.properties ?? { answer: { type: 'string', title: tr('answer') } }, testOutputs[draft.id] ?? outputExamples.valuesByNode[draft.id], 'ai', draft.id, !!testOutputs[draft.id])}
      {:else if draft.type === 'app_skill_action'}
        <h4 class="input-heading" data-testid="workflow-input-heading"><span class="section-icon" data-testid="workflow-input-icon"><Download size={18} aria-hidden="true"/></span>{tr('input')}</h4>
        {#if draftCapability?.metadata.input_schema}<WorkflowSchemaFields schema={draftCapability.metadata.input_schema} value={draft.config?.input} {outputs} path={draft.id} appId={String(draft.config?.app_id ?? '')} timezone={workflowTimezone(draft)} onChange={value => patch({ input: value })}/>{:else}<p>{loadError || tr('schema_unavailable')}</p>{/if}
        <div class="test-control">
          {#if testStatus === 'processing'}<span aria-live="polite">{tr('processing')}</span>{#if testingRunId}<button type="button" class="quiet" onclick={() => void stopTest()}><Stop size={16}/>{tr('stop')}</button>{/if}
          {:else}<button type="button" class="quiet test" data-testid="workflow-test-action" disabled={!workflowId || draftCapability?.metadata.workflow?.test_allowed === false || !draftCapability} onclick={() => void testNode()}><Play size={16}/>{tr(testOutputs[draft.id] ? 'test_again' : 'test_action')}<span class="credits-coin-icon" aria-hidden="true"></span><span>{draftCapability?.metadata.cost?.fixed ?? draftCapability?.metadata.cost?.per_unit?.credits ?? tr('variable_cost')}</span></button>{/if}
        </div>
        {@render outputSection(draftCapability?.metadata.output_schema?.properties ?? {}, testOutputs[draft.id] ?? outputExamples.valuesByNode[draft.id], String(draft.config?.app_id ?? ''), draft.id, !!testOutputs[draft.id])}
      {:else if isCheck(draft)}
        <h3>{tr('check_question')}</h3>
        <div class="check-mode"><SettingsDropdown value={String(draft.config?.mode ?? 'exact')} options={[{value:'exact',label:tr('exact_rule')},{value:'ai',label:tr('ai_judgment')}]} ariaLabel={tr('check_mode')} onChange={value => checkMode(value as 'exact' | 'ai')}/></div>
        {#if draft.config?.mode === 'ai'}
          <h3 class="ai-check-question-heading">{@render editorFieldLabel('question', tr('ai_check_question'), { type:'string' })}</h3>
          <WorkflowMessageEditor bind:this={messageEditor} value={String(draft.config?.question ?? '')} outputs={eligibleOutputs} placeholder={tr('ai_check_placeholder')} disabled={busy || testStatus === 'processing'} onChange={updateAiCheckQuestion} onMentionTrigger={visible => showReferences = visible}/>
          {#if eligibleOutputs.length}<div class="variable-picker"><div class="reference-chips" data-testid="workflow-ai-check-variable-chips">{#each visibleVariableOutputs as output}<button type="button" class="chip" onclick={() => addAiCheckReference(output)}>+ {output.label}</button>{/each}</div>{#if variableGroups.advanced.length}<button type="button" class="variable-toggle" aria-expanded={showAllVariables} onclick={() => showAllVariables = !showAllVariables}>{tr(showAllVariables ? 'show_basic_variables' : 'show_all_variables')}</button>{/if}</div>{/if}
          {#if showReferences}<div class="references" aria-label={tr('select_output')}>{#each eligibleOutputs as output}<button type="button" class="quiet" onclick={() => addAiCheckReference(output)}>{output.label}</button>{/each}</div>{/if}
          <p class="reminder">{tr('ai_check_guidance')}</p>
        {:else}
          <h2>{tr('if')}</h2>
          <div class="check-fields"><SettingsDropdown value={String(predicate.left ?? '')} options={outputs.filter(item => !['array','object'].includes(item.schema.type ?? '')).map(output => ({value:output.reference,label:output.label}))} placeholder={tr('select_output')} ariaLabel={tr('select_output')} onChange={left => predicatePatch({ left, op: '', right: '' })}/>
            {#if predicate.left}<SettingsDropdown value={String(predicate.op ?? '')} options={operators(predicate.left).map(op => ({value:op,label:`${operatorSymbol(op)} ${tr(`operator_${op}`)}`}))} placeholder={tr('compare_type')} ariaLabel={tr('compare_type')} onChange={op => predicatePatch({ op, right: sourceSchema(predicate.left)?.type === 'boolean' ? true : '' })}/>{/if}
            {#if predicate.op}<span class="type" data-value-type={valueType(sourceSchema(predicate.left))}>{tr(`output_type_${valueType(sourceSchema(predicate.left))}`)}</span>{#if sourceSchema(predicate.left)?.type === 'boolean'}<SettingsDropdown value={String(predicate.right)} options={[{value:'true',label:tr('true')},{value:'false',label:tr('false')}]} ariaLabel={tr('compare_value')} onChange={value => predicatePatch({ right: value === 'true' })}/>{:else}<input aria-label={tr('compare_value')} type={['number','integer'].includes(sourceSchema(predicate.left)?.type ?? '') ? 'number' : 'text'} value={String(predicate.right ?? '')} oninput={event => predicatePatch({ right: ['number','integer'].includes(sourceSchema(predicate.left)?.type ?? '') ? Number(event.currentTarget.value) : event.currentTarget.value })}/>{/if}{/if}
          </div>
        {/if}
        <div class="test-control">
          {#if testStatus === 'processing'}<span aria-live="polite">{tr('processing')}</span>{#if testingRunId}<button type="button" class="quiet" onclick={() => void stopTest()}><Stop size={16}/>{tr('stop')}</button>{/if}
          {:else}<button type="button" class="quiet test" data-testid="workflow-test-action" disabled={!workflowId || (draft.config?.mode === 'ai' ? !aiCheckCanSave : !predicate.left || !predicate.op)} onclick={() => void testNode()}><Play size={16}/>{tr(testOutputs[draft.id] ? 'test_again' : 'test_action')}{#if draft.config?.mode === 'ai'}<span class="credits-coin-icon" aria-hidden="true"></span><span>1</span>{/if}</button>{/if}
        </div>
        {#if typeof record(testOutputs[draft.id]).matched === 'boolean'}
          <p class="check-test-result" role="status" data-testid="workflow-check-test-result">{tr('test_output')}: {tr(record(testOutputs[draft.id]).matched ? 'true' : 'false')}</p>
        {/if}
      {:else if isMessage(draft)}
        {#if chooseChat}<h3>{tr('chat_question')}</h3><div class="card-scroll">{#each visibleChats as chat}<ChatPreviewCard {chat} onOpen={selectChat}/>{/each}</div><div class="chat-search"><Search size={18} aria-hidden="true"/><input aria-label={tr('search_chats')} placeholder={tr('search_chats')} bind:value={chatSearch}/></div><button class="primary new-chat-destination" type="button" data-testid="workflow-new-chat-destination" onclick={() => selectChat(null)}><span class="clickable-icon icon_create new-chat-icon" aria-hidden="true"></span>{$text('common.new_chat')}</button>
        {:else}
          <h3>{@render editorFieldLabel('message', tr('message_question'), { type:'string' })}</h3><button class="quiet target" type="button" onclick={() => { chooseChat = true; void loadChats(); }}>{tr('to')}: {summary(draft)}</button>
          <label>{@render editorFieldLabel('chat_title', tr('chat_title'), { type:'string' })}<input data-testid="workflow-message-title" value={String(draft.config?.title ?? '')} oninput={event => patch({ title: event.currentTarget.value })}/></label>
          <WorkflowMessageEditor bind:this={messageEditor} value={String(draft.config?.message ?? draft.config?.summary ?? '')} outputs={eligibleOutputs} placeholder={tr('message_placeholder')} disabled={busy || testStatus === 'processing'} onChange={value => patch({ message: value })} onMentionTrigger={visible => showReferences = visible}/>
          {#if eligibleOutputs.length}<div class="variable-picker"><div class="reference-chips" data-testid="workflow-message-variable-chips">{#each visibleVariableOutputs as output}<button type="button" class="chip" onclick={() => addReference(output)}>+ {output.label}</button>{/each}</div>{#if variableGroups.advanced.length}<button type="button" class="variable-toggle" aria-expanded={showAllVariables} onclick={() => showAllVariables = !showAllVariables}>{tr(showAllVariables ? 'show_basic_variables' : 'show_all_variables')}</button>{/if}</div>{/if}
          {#if showReferences}<div class="references" aria-label={tr('select_output')}>{#each eligibleOutputs as output}<button type="button" class="quiet" onclick={() => addReference(output)}>{output.label}</button>{/each}</div>{/if}
          {#each blocks as block, index}<div class="message-block"><div><strong>{outputs.find(output => output.reference === block.source)?.label ?? String(block.source)}</strong><button type="button" class="quiet" aria-label={tr('remove')} onclick={() => patch({ blocks: blocks.filter((_, i) => i !== index) })}>×</button></div>
            {#if sourceSchema(block.source)?.type === 'array'}<label class="checkbox"><input type="checkbox" checked={block.only_new_results === true} onchange={event => patchBlock(index, { only_new_results: event.currentTarget.checked })}/>{tr('only_new_results')}</label>{/if}
            <label>{@render editorFieldLabel('include_when', tr('include_when'), { type:'boolean' })}<SettingsDropdown value={String(block.include_if ?? '')} options={[{value:'',label:tr('always')},...outputs.filter(output => output.schema.type === 'boolean').map(output => ({value:output.reference,label:`${output.label} = ${tr('true')}`}))]} ariaLabel={tr('include_when')} onChange={value => patchBlock(index, { include_if: value || null })}/></label>
          </div>{/each}
          <button class="quiet" type="button" data-testid="workflow-preview-message" disabled={busy || !String(draft.config?.title ?? '').trim()} onclick={() => void previewMessage()}>{tr('preview_message')}</button>
          {#if preview}<div class="message-preview" data-testid="workflow-message-preview">{#if preview.title}<h4>{String(preview.title)}</h4>{/if}{#if preview.message || (!Array.isArray(preview.blocks) && preview.text)}<WorkflowValueView value={preview.message || preview.text}/>{/if}{#if Array.isArray(preview.blocks)}{#each preview.blocks as value}{@const block = record(value)}<section>{#if block.label}<h4>{String(block.label)}</h4>{/if}<WorkflowValueView value={block.value} appId={sourceApp(block.source)} path={`preview.${block.id}`}/></section>{/each}{/if}</div>{/if}
        {/if}
      {:else}<WorkflowValueView value={draft.config}/>{/if}
      {#if nodeError}<p class="error" role="alert">{nodeError}</p>{/if}
      {#if !chooseChat}{#if isCheck(draft) && draft.config?.mode === 'ai' && aiCheckSelectedInputs.length === 0}<p class="reminder ai-check-save-hint" data-testid="workflow-ai-check-save-hint">{tr('ai_check_add_variable')}</p>{/if}<div class="save-row"><button type="button" class="primary" data-testid="workflow-node-save" disabled={busy || testStatus === 'processing' || !aiCheckCanSave || (isAskAi(draft) && askVerdict === 'asks_to_invoke_app_skill')} onclick={() => void saveNode()}>{tr(busy ? 'saving' : 'save')}</button></div>{/if}
    </div>
  {/if}
{/snippet}

{#snippet chain(nodeId: string, visited: string[] = [], stopAt?: string)}
  {@const node = graph.nodes.find(item => item.id === nodeId)}
  {#if node && node.type !== 'end' && !visited.includes(nodeId) && nodeId !== stopAt}
    {@const run = nodeRuns.find(item => item.node_id === node.id)}
    {@const rawRunStatus = String(isMessage(node) && run?.output_summary?.status ? run.output_summary.status : run?.status ?? '')}
    {@const runStatus = ['acknowledged','completed','no_new_results'].includes(rawRunStatus) ? 'completed' : ['failed','cancelled','skipped','queued','running','cancellation_requested'].includes(rawRunStatus) ? rawRunStatus : 'waiting'}
    <article class="flow-node" data-node-id={node.id} data-node-type={node.type} data-testid="workflow-node-card" style={`view-transition-name:${viewTransitionName(node.id)}`}>
      {#if draft?.id === node.id}{#if picker}{@render pickerPanel()}{:else}{@render editor()}{/if}{:else}
        <button type="button" class="node-summary" class:branded={node.type === 'app_skill_action' || isTrigger(node) || isMessage(node) || isCheck(node)} class:expanded={readOnly && expandedReadOnly === node.id} style={style(node)} data-testid="workflow-node-summary" aria-expanded={expandedReadOnly === node.id} onclick={() => edit(node)}><span class="node-app-icon" data-testid="workflow-node-primary-icon"><span class="workflow-icon" style={primaryNodeIconStyle(node)} aria-hidden="true"></span></span><span class="kind">{kind(node)}</span>{#if isCheck(node) && checkSource(node)}<span class="check-source">{summary(checkSource(node)!)}</span>{/if}<strong data-testid="workflow-node-title-label">{summary(node)}</strong>{#if node.type === 'app_skill_action' && skillInputSummary(node)}<span class="location" data-testid="workflow-node-input-summary">{skillInputSummary(node)}</span>{/if}{#if run}<span class="run-status" class:success={runStatus === 'completed'} class:failed={runStatus === 'failed'} data-testid="workflow-run-node-status" data-node-status={run.status} role="img" aria-label={$text(`workflows.runs.status_${runStatus}`)}>{#if runStatus === 'completed'}<span class="workflow-icon" style={assetIconStyle('check', 16, 'var(--color-font-button)')} aria-hidden="true"></span>{:else}{$text(`workflows.runs.status_${runStatus}`)}{/if}</span>{/if}</button>
        {#if readOnly && expandedReadOnly === node.id}<div class="editor" data-testid="workflow-node-expanded">{#if run}<h4>{tr('input')}</h4><WorkflowValueView value={inputValue(node, run)} appId={String(node.config?.app_id ?? '')}/><h4>{tr('output')}</h4>{#if isMessage(node)}<WorkflowValueView value={{ status: run.output_summary?.status ?? run.status, delivered_results: run.output_summary?.delivered_result_count ?? 0, pending_results: run.output_summary?.pending_result_count ?? 0 }}/>{#if run.output_summary?.chat_id}<a class="quiet" href={`/#chat-id=${encodeURIComponent(String(run.output_summary.chat_id))}`}>{tr('output_open_chat')}</a>{/if}{:else}<WorkflowValueView value={outputValue(node, run)} appId={String(node.config?.app_id ?? '')}/>{/if}{#if run.error_summary}<p class="error">{tr('output_step_failed')}</p>{/if}{#if run.skipped_reason}<p>{tr('output_step_skipped')}</p>{/if}{:else}<WorkflowValueView value={inputValue(node)} appId={String(node.config?.app_id ?? '')}/>{/if}</div>{/if}
      {/if}
    </article>
    {#if isCheck(node)}
      {@const continuation = nextId(node.id)}
      <div class="branch-group">
        {#each node.config?.mode === 'ai' ? ['true','false','unsure'] : ['yes','no'] as branch}{@const target = nextId(node.id, branch) ?? nextId(node.id, branch === 'yes' ? 'true' : branch === 'no' ? 'false' : branch)}<div class="branch"><div class="connector branch-label"><span class="workflow-icon" style={assetIconStyle('workflow-check', 18, 'var(--color-font-secondary)')} aria-hidden="true"></span>{tr(branch === 'true' || branch === 'yes' ? 'if_true' : branch === 'unsure' ? 'if_unsure' : 'else')}</div>{#if target}{@render chain(target, [...visited, node.id], continuation)}{:else}{#if !readOnly}{#if sameSlot({ after: node.id, branch }) && (picker || draft)}{@render slotControls({ after: node.id, branch })}{:else}<button type="button" class="nothing" onclick={() => openPicker('action', { after: node.id, branch })}>{tr('do_nothing_add_step')}</button>{/if}{:else}<p class="nothing">{tr('do_nothing')}</p>{/if}{/if}</div>{/each}
      </div>
    {/if}
    {@const next = nextId(node.id)}
    {#if next && next !== stopAt && graph.nodes.find(item => item.id === next)?.type !== 'end'}<div class="connector">{tr('then')}</div>{@render chain(next, [...visited, node.id], stopAt)}
    {:else if !readOnly}<div class="connector">{tr('then')}</div>{@render slotControls({ after: node.id })}{/if}
  {/if}
{/snippet}

<section class="graph-panel" bind:this={graphPanel} data-testid={testId} data-read-only={readOnly ? 'true' : 'false'}>
  <div class="graph-canvas" class:blank={!graph.nodes.some(node => node.type !== 'end')}><div class="node-stack" data-testid="workflow-node-stack">
    {#each rootNodes as root}{@render chain(root.id)}{/each}
    {#if !graph.nodes.some(node => node.type !== 'end')}{@render slotControls({ after: null })}{/if}
  </div></div>
</section>

<style>
  .workflow-icon{display:inline-block;flex:0 0 auto;width:var(--workflow-icon-size);height:var(--workflow-icon-size);background:currentColor;-webkit-mask:var(--workflow-icon) center/contain no-repeat;mask:var(--workflow-icon) center/contain no-repeat}
  .graph-panel{font-size:16px;margin:0 auto;width:min(60rem,calc(100% - 4rem));padding:0 0 2rem}.graph-canvas{min-height:16rem;padding:2rem 1.25rem;background:var(--color-grey-0);border-radius:.9rem}.node-stack{display:grid;justify-items:center}.flow-node{display:grid;justify-items:center;width:100%;min-width:0}.node-summary{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.5rem;width:min(19rem,100%);padding:.7rem 1rem .7rem;min-height:8rem;border:0;border-radius:1rem;background:var(--color-grey-10);color:var(--color-font-primary);box-shadow:var(--shadow-sm);cursor:pointer;font:inherit}.node-summary strong{font-size:16px;line-height:1.4}.node-summary> :global(svg){color:var(--color-primary)}.node-summary .kind{font-size:14px;color:var(--color-font-secondary)}.node-summary.branded{background:var(--node-gradient);color:var(--color-font-button)}.node-summary.branded .kind,.node-summary.branded> :global(svg){color:var(--color-font-button);opacity:.9}.location{font-size:16px;opacity:.8}.connector{color:var(--color-font-secondary);font-size:16px;font-weight:650;text-align:center;padding:.8rem 0}.branch-group{width:min(42rem,100%);padding:0 .75rem .7rem;border:1px solid var(--color-grey-20);border-radius:1rem;margin-top:-.5rem;box-sizing:border-box}.branch{display:grid;justify-items:center}.branch .branch-label{padding-top:1rem}.nothing{display:grid;place-items:center;box-sizing:border-box;white-space:pre-line;line-height:1.5;font:inherit;font-size:16px;cursor:pointer;background:transparent;margin:0;border:1px dashed var(--color-grey-30);border-radius:1rem;width:min(21rem,100%);min-height:9.25rem;padding:.9rem 1.25rem;text-align:center;color:var(--color-font-secondary);transition:border-color var(--duration-normal,.2s) ease}.nothing:hover,.nothing:focus-visible{border-color:var(--color-font-button)}.add-controls,.choices{display:flex;flex-wrap:wrap;gap:.8rem;justify-content:center;padding:.75rem 0}.choice{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.6rem;min-width:6.5rem;min-height:4.5rem;border:0;border-radius:.7rem;color:var(--color-font-secondary);background:var(--color-grey-10);box-shadow:var(--shadow-sm);padding:.65rem;cursor:pointer;font:inherit;font-size:16px;font-weight:600}.choice :global(svg){color:var(--color-primary)}.editor{position:relative;min-width:0;width:min(42rem,100%);box-sizing:border-box;display:grid;gap:1rem;padding:0 1.5rem 1rem;background:var(--color-grey-10);border-radius:1rem;box-shadow:var(--shadow-sm);color:var(--color-font-primary);text-align:center}.picker{min-height:11rem;animation:editor-swap .16s ease-out}h2,h3,h4,p{margin:0}h3{font-size:16px}h4{font-size:16px;text-align:start;color:var(--color-font-secondary)}.card-scroll{display:flex;flex-wrap:nowrap;min-width:0;max-width:100%;gap:1rem;overflow-x:auto;width:100%;padding:.5rem 0 1rem;scroll-snap-type:x proximity}.card-scroll :global(>*){flex-shrink:0;scroll-snap-align:center}.quiet{display:inline-flex;align-items:center;justify-content:center;gap:.35rem;min-height:2rem;padding:.3rem .5rem;border:0;box-shadow:none;background:transparent;color:var(--color-primary);font:inherit;font-size:16px;cursor:pointer}.primary{justify-self:center;min-width:9rem;min-height:2.4rem;border:0;border-radius:.8rem;padding:.55rem 1.2rem;font:inherit;font-size:16px;font-weight:650;background:var(--color-button-primary);color:var(--color-font-button);box-shadow:var(--shadow-sm);cursor:pointer}.primary:disabled{background:var(--color-grey-30);color:var(--color-font-secondary);box-shadow:none;cursor:not-allowed}.field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}label{display:grid;gap:.4rem;min-width:0;text-align:start;font-size:16px}.editor-field-label{display:inline-flex;align-items:center;gap:var(--spacing-2);min-width:0}.editor-field-label :global(svg){flex:0 0 auto;color:var(--color-font-secondary)}input{box-sizing:border-box;width:100%;min-height:2.5rem;border:1px solid var(--color-grey-25);border-radius:.8rem;padding:.5rem .7rem;background:var(--workflow-input-surface,var(--color-grey-10));color:var(--color-font-primary);font:inherit;font-size:16px;box-shadow:var(--shadow-sm)}.weekdays{display:flex;gap:.7rem;flex-wrap:wrap}.weekdays label,.checkbox{display:flex;align-items:center;gap:.45rem}.weekdays input,input[type=checkbox]{width:1.05rem;height:1.05rem;min-height:0;box-shadow:none;accent-color:var(--color-primary)}.test-control{display:flex;justify-content:center;align-items:center;gap:.7rem;font-size:16px}.output-heading{display:flex;justify-content:space-between;font-size:16px;color:var(--color-font-secondary)}.type{font-size:14px;border-radius:.2rem;background:var(--color-primary);color:var(--color-font-button);padding:.1rem .3rem;width:fit-content}.check-fields{display:grid;gap:.8rem;width:min(23rem,100%);margin:auto}.check-fields>.type{justify-self:center}.check-mode{width:min(23rem,100%);margin:auto}.ai-check-question-heading{display:flex;justify-content:center;text-align:center}.variable-picker{display:grid;min-width:0;gap:.35rem}.reference-chips,.suggestions{display:flex;flex-wrap:nowrap;min-width:0;max-width:100%;gap:.4rem;justify-content:flex-start;overflow-x:auto;padding:.15rem .1rem}.chip{flex:0 0 auto;border:0;border-radius:1rem;padding:.3rem .55rem;background:var(--color-primary);color:var(--color-font-button);font:inherit;font-size:16px;cursor:pointer}.variable-toggle{justify-self:center;border:0;padding:.2rem .4rem;background:transparent;color:var(--color-font-secondary);font:inherit;font-size:14px;cursor:pointer}.message-block{border:1px solid var(--color-grey-25);border-radius:.7rem;padding:.7rem;display:grid;gap:.6rem;text-align:start;font-size:16px}.message-block>div{display:flex;justify-content:space-between;align-items:center;gap:.5rem}.message-block strong{overflow-wrap:anywhere}.references{display:grid;text-align:start}.message-preview{white-space:pre-wrap;overflow-wrap:anywhere;user-select:text;text-align:start;font-size:16px}.message-preview{display:grid;gap:.8rem;padding:1rem;background:var(--color-grey-0);border-radius:.8rem}.save-row{display:flex;justify-content:center;align-items:center;gap:1rem;margin-top:.3rem}.error{color:var(--color-error);font-size:16px;overflow-wrap:anywhere}.reminder{color:var(--color-font-secondary);font-size:14px;text-align:start}.ai-check-save-hint{text-align:center}.ask-validation{text-align:start}.target{justify-self:start}button:disabled{opacity:.55;cursor:wait}button:focus-visible,input:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}
  @keyframes editor-swap{from{opacity:.65;transform:translateY(.25rem)}to{opacity:1;transform:translateY(0)}}@media(max-width:730px){.graph-panel{width:calc(100% - 1rem)}.graph-canvas{padding:1.5rem .5rem}.editor{padding:0 .8rem 1rem}.field-grid{grid-template-columns:1fr}.branch-group{padding-inline:.4rem}.choice{min-width:5.6rem}.card-scroll :global(.resume-chat-large-card){width:15rem;min-width:15rem;max-width:15rem}}@media(prefers-reduced-motion:reduce){.picker{animation:none}}
  .node-app-icon{display:grid;place-items:center}.message-preview section{display:grid;gap:.55rem}.graph-panel{margin-block:1.75rem}.node-summary.branded .node-app-icon{color:var(--color-font-button)}
  .node-summary{box-sizing:border-box;width:min(21rem,100%);min-height:9.25rem;padding:.9rem 1.25rem;gap:.55rem}
  .node-summary.expanded{width:min(42rem,100%);border-radius:1rem 1rem 0 0}.node-summary.expanded+.editor{border-radius:0 0 1rem 1rem}.check-source{font-size:14px;color:var(--color-font-secondary)}
  .node-summary.branded .check-source{color:var(--color-font-button);opacity:.9}
  .branch-label{display:flex;align-items:center;justify-content:center;gap:.4rem}
  .type{background:#315aef;color:white}.type[data-value-type="number"]{background:#b3213c}.type[data-value-type="date"]{background:#eb9d00}.type[data-value-type="boolean"]{background:#7651b5}
  .editor :global(.settings-dropdown-wrapper){padding:0}
  .editor :global(.settings-dropdown){min-height:3.375rem;background:var(--workflow-input-surface,var(--color-grey-10))}

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
  .nothing { width:min(21rem, 100%); }
  :global(::view-transition-group(*)) { animation-duration:var(--duration-slow, .3s); animation-timing-function:cubic-bezier(.32, 0, .2, 1); }
  :global(::view-transition-old(root)), :global(::view-transition-new(root)) { animation:none; }
  .primary { min-width:11rem; border-radius:var(--radius-8); }
  .chat-search { display:flex; align-items:center; justify-self:center; width:min(22rem, 100%); gap:.35rem; color:var(--color-font-secondary); }
  .chat-search input { min-height:2rem; border:0; background:transparent; box-shadow:none; padding:.2rem; }
  .editor.chat-destination { gap:.75rem; }
  .chat-destination .card-scroll { box-sizing:border-box; padding-inline:calc(50% - 8.96875rem); }
  .new-chat-destination { display:inline-flex; align-items:center; justify-content:center; gap:var(--spacing-4); min-height:2.5625rem; border-radius:var(--radius-full); }
  .new-chat-destination :global(.new-chat-icon) { width:20px; height:20px; flex:0 0 auto; background:var(--color-font-button); }
  .output-toggle,
  .variable-toggle { justify-self:center; border:0; padding:.2rem .4rem; background:transparent; color:var(--color-font-secondary); font:inherit; font-size:14px; cursor:pointer; }
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
</style>
