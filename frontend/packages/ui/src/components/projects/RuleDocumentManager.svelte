<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { text } from '../../i18n/translations';
  import {
    activeRuleChatId, listPersonalRuleDocuments, listProjectRuleDocuments,
    savePersonalRuleDocument, saveProjectRuleDocument, type EditableRuleDocument,
  } from '../../services/ruleDocumentService';
  import { parseRuleDocument, serializeRuleDocument, type RuleDocumentFields } from '../../utils/ruleDocuments';

  interface RuleManagerService {
    list: (source: 'personal' | 'project', projectId: string | null) => Promise<EditableRuleDocument[]>;
    save: (source: 'personal' | 'project', projectId: string | null, document: string, existing: EditableRuleDocument | null) => Promise<void>;
  }
  interface Props { projectId: string | null; onClose: () => void; service?: RuleManagerService }
  let { projectId, onClose, service: providedService }: Props = $props();
  const defaultService: RuleManagerService = {
    list: async (source, selectedProjectId) => {
      if (source === 'personal') return listPersonalRuleDocuments();
      const chatId = activeRuleChatId();
      if (!chatId || !selectedProjectId) throw new Error('rule_project_activation_required');
      return listProjectRuleDocuments({ chatId, projectId: selectedProjectId });
    },
    save: async (source, selectedProjectId, document, existing) => {
      if (source === 'personal') { await savePersonalRuleDocument({ id: existing?.id, document }); return; }
      const chatId = activeRuleChatId();
      if (!chatId || !selectedProjectId) throw new Error('rule_project_activation_required');
      await saveProjectRuleDocument({ chatId, projectId: selectedProjectId, document, existing: existing ?? undefined });
    },
  };
  let service = $derived(providedService ?? defaultService);
  let source = $state<'personal' | 'project'>(untrack(() => projectId ? 'project' : 'personal'));
  let documents = $state<EditableRuleDocument[]>([]);
  let selected = $state<EditableRuleDocument | null>(null);
  let draft = $state<RuleDocumentFields>({ title: '', description: '', when_to_use: '', body: '' });
  let loading = $state(true);
  let saving = $state(false);
  let error = $state('');
  let notice = $state('');
  let generation = 0;

  onDestroy(() => { generation += 1; });
  $effect(() => { void load(source, projectId); });

  function displayError(value: unknown): string {
    return value instanceof Error && value.message === 'rule_project_activation_required'
      ? $text('memories.activation_required') : $text('memories.save_failed');
  }

  async function load(currentSource: 'personal' | 'project', selectedProjectId: string | null) {
    const token = ++generation;
    loading = true;
    error = '';
    documents = [];
    reset();
    try {
      const loaded = await service.list(currentSource, selectedProjectId);
      if (token === generation) documents = loaded;
    } catch (value) { if (token === generation) error = displayError(value); }
    finally { if (token === generation) loading = false; }
  }

  function reset() {
    selected = null;
    draft = { title: '', description: '', when_to_use: '', body: '' };
    notice = '';
  }

  function edit(document: EditableRuleDocument) {
    selected = document;
    draft = parseRuleDocument(document.document);
    error = '';
    notice = '';
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (saving) return;
    let document: string;
    try { document = serializeRuleDocument(draft); }
    catch { error = $text('memories.invalid_document'); return; }
    saving = true;
    error = '';
    const currentSource = source;
    const selectedProjectId = projectId;
    const token = generation;
    try {
      await service.save(currentSource, selectedProjectId, document, selected);
      if (token !== generation) return;
      documents = await service.list(currentSource, selectedProjectId);
      if (token !== generation) return;
      reset();
      notice = $text('memories.saved');
    } catch (value) { if (token === generation) error = displayError(value); }
    finally { saving = false; }
  }
</script>

<section class="rule-manager" data-testid="rule-document-manager" aria-label={$text('memories.manage')}>
  <div class="heading">
    <h2>{$text('memories.manage')}</h2>
    <button type="button" onclick={onClose} disabled={saving} data-testid="rule-manager-close">{$text('common.close')}</button>
  </div>
  <p>{$text('memories.guide_description')}</p>
  <div class="scope" role="group" aria-label={$text('memories.scope')}>
    <button type="button" aria-pressed={source === 'personal'} disabled={saving} onclick={() => source = 'personal'} data-testid="rule-scope-personal">{$text('memories.source_personal')}</button>
    {#if projectId}
      <button type="button" aria-pressed={source === 'project'} disabled={saving} onclick={() => source = 'project'} data-testid="rule-scope-project">{$text('memories.source_project')}</button>
    {/if}
  </div>
  {#if source === 'project'}<p class="privacy">{$text('memories.project_storage')}</p>{/if}
  {#if loading}<p role="status">{$text('common.loading')}</p>
  {:else}
    {#if documents.length}
      <ul class="guides">
        {#each documents as document (document.id)}
          <li><button type="button" onclick={() => edit(document)} disabled={saving} data-testid="rule-document-edit">{parseRuleDocument(document.document).title}</button></li>
        {/each}
      </ul>
    {:else}<p>{$text('memories.empty')}</p>{/if}
    <form onsubmit={save} data-testid="rule-document-form">
      <label>{$text('memories.title')}<input required maxlength="180" bind:value={draft.title} disabled={saving} data-testid="rule-title" /></label>
      <label>{$text('memories.description')}<textarea required maxlength="1200" rows="2" bind:value={draft.description} disabled={saving} data-testid="rule-description"></textarea></label>
      <label>{$text('memories.when_to_use')}<textarea required maxlength="1200" rows="2" bind:value={draft.when_to_use} disabled={saving} data-testid="rule-when-to-use"></textarea></label>
      <label>{$text('memories.practices')}<textarea required maxlength="20000" rows="7" bind:value={draft.body} disabled={saving} data-testid="rule-body"></textarea></label>
      <div class="actions">
        <button type="submit" disabled={saving} data-testid="rule-save">{saving ? $text('common.loading') : $text('common.save')}</button>
        {#if selected}<button type="button" onclick={reset} disabled={saving} data-testid="rule-new">{$text('memories.new')}</button>{/if}
      </div>
    </form>
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
  {#if notice}<p role="status" data-testid="rule-saved-notice">{notice}</p>{/if}
</section>

<style>
  .rule-manager { width: 100%; min-width: 0; box-sizing: border-box; padding: var(--spacing-6); border: 1px solid var(--color-grey-25); border-radius: var(--radius-7); background: var(--color-grey-10); color: var(--color-font-primary); }
  .heading, .scope, .actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--spacing-3); }
  .heading { justify-content: space-between; }
  h2 { margin: 0; font-size: var(--font-size-p); }
  p, label { font-size: var(--font-size-small); }
  .privacy { color: var(--color-font-secondary); }
  form { display: grid; gap: var(--spacing-5); }
  label { display: grid; gap: var(--spacing-2); }
  input, textarea { width: 100%; box-sizing: border-box; min-width: 0; padding: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-4); background: var(--color-grey-0); color: var(--color-font-primary); font: inherit; }
  textarea { resize: vertical; }
  button { min-height: 2.75rem; border: 1px solid var(--color-grey-30); border-radius: var(--radius-4); padding: var(--spacing-3) var(--spacing-5); background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; overflow-wrap: anywhere; }
  button[aria-pressed='true'] { border-color: var(--color-primary); }
  :is(button, input, textarea):focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
  .guides { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
</style>
