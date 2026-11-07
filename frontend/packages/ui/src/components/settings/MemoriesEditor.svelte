<!-- frontend/packages/ui/src/components/settings/MemoriesEditor.svelte
     Memory list + editor for free-form Memories (personal account or one Project).
     Fields: title, memory (Markdown), when to use, load mode, start/expiry date.
     Spec: specifications/features/app-memories (draft v4). Personal memories are
     labelled Private; expired memories are greyed with a Renew action.
     Accepts an optional unsaved draft (suggestion deep link) shown as a diff; nothing is saved until the user clicks Save.
-->
<script module lang="ts">
  import type { EditableRuleDocument } from '../../services/ruleDocumentService';
  export interface MemoryEditorService {
    list: (source: 'personal' | 'project', projectId: string | null) => Promise<EditableRuleDocument[]>;
    save: (source: 'personal' | 'project', projectId: string | null, document: string, existing: EditableRuleDocument | null) => Promise<void>;
    /** Absent when the source cannot delete from this surface. */
    remove?: (source: 'personal' | 'project', projectId: string | null, existing: EditableRuleDocument) => Promise<void>;
  }
  export interface MemoryDraftSuggestion {
    title: string; memory: string; when_to_use?: string;
    load_mode?: 'auto_include' | 'ask_first' | 'mention_only'; valid_from?: string; valid_until?: string;
    /** Creates a memory that does not exist yet. */
    is_new?: boolean;
    /** Saved document when the suggestion was previewed; a different current document is a conflict. */
    base_document?: string;
  }
</script>

<script lang="ts">
  import { text } from '../../i18n/translations';
  import MemoryBodyEditor from './MemoryBodyEditor.svelte';
  import { bodyWithLegacyReferences, referencesFromBody } from '../../utils/memoryBodyDocument';
  import {
    SettingsInput, SettingsTextarea, SettingsDropdown, SettingsButton, SettingsButtonGroup,
    SettingsInfoBox, SettingsBadge, SettingsItem, SettingsQuote,
  } from './elements';
  import {
    MAX_RULE_CATALOG_CHARS, isMemoryActive, parseRuleDocument, serializeRuleDocument,
    type MemoryLoadMode, type RuleDocumentFields,
  } from '../../utils/ruleDocuments';

  interface Props {
    source: 'personal' | 'project';
    projectId: string | null;
    service: MemoryEditorService;
    /** Memory id (or project item id) to open immediately. */
    initialMemoryId: string | null;
    /** Unsaved suggestion applied on top of the opened memory. */
    suggestion: MemoryDraftSuggestion | null;
  }
  let { source, projectId, service, initialMemoryId, suggestion }: Props = $props();

  const emptyDraft = (): RuleDocumentFields => ({ title: '', when_to_use: '', body: '', load_mode: 'auto_include' });
  let documents = $state<EditableRuleDocument[]>([]);
  let selected = $state<EditableRuleDocument | null>(null);
  let draft = $state<RuleDocumentFields>(emptyDraft());
  let original = $state<RuleDocumentFields | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  let error = $state('');
  let notice = $state('');
  let generation = 0;
  let appliedDeepLink = '';

  const loadModeOptions = $derived([
    { value: 'auto_include', label: $text('memories.load_mode_auto_include') },
    { value: 'ask_first', label: $text('memories.load_mode_ask_first') },
    { value: 'mention_only', label: $text('memories.load_mode_mention_only') },
  ]);
  const usedChars = $derived(documents.reduce((sum, item) => sum + item.document.length, 0));
  const sourceLabel = $derived(source === 'personal' ? $text('memories.visibility_private') : $text('memories.source_project'));
  const dateOnly = (iso?: string) => (iso ? iso.slice(0, 10) : '');
  const changed = (field: 'title' | 'body' | 'when_to_use') =>
    original !== null && suggestion !== null && original[field] !== draft[field];

  $effect(() => { void load(source, projectId); });

  function entries() {
    return documents.map((document) => {
      const fields = parseRuleDocument(document.document);
      return { document, fields, expired: !isMemoryActive(fields) && !!fields.valid_until && Date.now() > Date.parse(fields.valid_until) };
    });
  }

  function displayError(value: unknown): string {
    return value instanceof Error && value.message === 'rule_project_activation_required'
      ? $text('memories.activation_required') : $text('memories.save_failed');
  }

  async function load(currentSource: 'personal' | 'project', selectedProjectId: string | null) {
    const token = ++generation;
    loading = true; error = ''; documents = []; reset();
    try {
      const loaded = await service.list(currentSource, selectedProjectId);
      if (token !== generation) return;
      documents = loaded;
      applyDeepLink();
    } catch (value) { if (token === generation) error = displayError(value); }
    finally { if (token === generation) loading = false; }
  }

  function dateFields(value: MemoryDraftSuggestion): Pick<RuleDocumentFields, 'valid_from' | 'valid_until'> {
    return {
      ...(value.valid_from ? { valid_from: value.valid_from } : {}),
      ...(value.valid_until ? { valid_until: value.valid_until } : {}),
    };
  }

  function applyDeepLink() {
    if (!initialMemoryId) return;
    const key = `${initialMemoryId}:${suggestion ? 'draft' : ''}`;
    if (appliedDeepLink === key) return;
    if (suggestion?.is_new) {
      appliedDeepLink = key;
      reset();
      draft = { ...emptyDraft(), ...dateFields(suggestion), title: suggestion.title, body: suggestion.memory, when_to_use: suggestion.when_to_use ?? '', load_mode: suggestion.load_mode ?? 'auto_include' };
      return;
    }
    const target = documents.find((item) => item.id === initialMemoryId || item.id === `personal:${initialMemoryId}`);
    if (!target) return;
    appliedDeepLink = key;
    edit(target);
    if (suggestion) {
      draft = { ...draft, ...dateFields(suggestion), title: suggestion.title, body: suggestion.memory, when_to_use: suggestion.when_to_use ?? draft.when_to_use, load_mode: suggestion.load_mode ?? draft.load_mode };
    }
  }

  function reset() {
    selected = null; original = null;
    draft = emptyDraft();
    notice = '';
  }

  async function embedTypeOf(id: string): Promise<string | null> {
    const { resolveEmbed } = await import('../../services/embedResolver');
    const embed = await resolveEmbed(id);
    return embed && typeof embed.type === 'string' ? embed.type : null;
  }

  function edit(document: EditableRuleDocument) {
    selected = document;
    const fields = parseRuleDocument(document.document);
    original = { ...fields };
    draft = { ...fields, load_mode: fields.load_mode ?? 'auto_include' };
    error = ''; notice = '';
    void showLegacyReferences(document, fields);
  }

  /** Memories saved with a separate reference list show those embeds inline. */
  async function showLegacyReferences(document: EditableRuleDocument, fields: RuleDocumentFields) {
    if (!fields.references?.length) return;
    const body = await bodyWithLegacyReferences(fields.body, fields.references, embedTypeOf);
    if (selected !== document || body === fields.body || draft.body !== fields.body) return;
    setBody(body);
  }

  function setBody(body: string) {
    const references = referencesFromBody(body);
    const { references: _previous, ...rest } = draft;
    draft = { ...rest, body, ...(references.length ? { references } : {}) };
  }

  function setDate(field: 'valid_from' | 'valid_until', value: string) {
    const next = { ...draft };
    if (!value) delete next[field];
    else next[field] = field === 'valid_from' ? `${value}T00:00:00.000Z` : `${value}T23:59:59.000Z`;
    draft = next;
  }

  async function persist(fields: RuleDocumentFields, existing: EditableRuleDocument | null) {
    let document: string;
    try { document = serializeRuleDocument(fields); }
    catch { error = $text('memories.invalid_document'); return; }
    saving = true; error = '';
    const token = generation;
    try {
      // A draft previewed against an older revision must not overwrite a newer one.
      if (suggestion?.base_document !== undefined && existing) {
        const current = (await service.list(source, projectId)).find((item) => item.id === existing.id);
        if (token !== generation) return;
        if (!current || current.document !== suggestion.base_document) {
          error = $text('memories.draft_conflict');
          return;
        }
      }
      await service.save(source, projectId, document, existing);
      if (token !== generation) return;
      documents = await service.list(source, projectId);
      if (token !== generation) return;
      reset();
      notice = $text('memories.saved');
    } catch (value) { if (token === generation) error = displayError(value); }
    finally { saving = false; }
  }

  async function save(event?: SubmitEvent) {
    event?.preventDefault();
    if (!saving) await persist(draft, selected);
  }

  async function renew(document: EditableRuleDocument) {
    if (saving) return;
    const fields = parseRuleDocument(document.document);
    const until = new Date(Date.now() + 30 * 86_400_000);
    await persist({ ...fields, valid_until: `${until.toISOString().slice(0, 10)}T23:59:59.000Z` }, document);
  }

  async function remove() {
    if (saving || !selected || !service.remove) return;
    saving = true; error = '';
    const token = generation;
    try {
      await service.remove(source, projectId, selected);
      if (token !== generation) return;
      documents = await service.list(source, projectId);
      reset();
    } catch (value) { if (token === generation) error = displayError(value); }
    finally { saving = false; }
  }
</script>

<div class="memories-editor" data-testid="memories-editor" data-source={source}>
  {#if source === 'project'}<SettingsInfoBox type="info"><p>{$text('memories.project_storage')}</p></SettingsInfoBox>{/if}
  {#if loading}
    <p role="status">{$text('common.loading')}</p>
  {:else}
    {#if documents.length}
      <div class="memory-list" data-testid="memory-list">
        {#each entries() as entry (entry.document.id)}
          <div class="memory-row" class:expired={entry.expired} data-testid="memory-row" data-expired={entry.expired}>
            <button type="button" class="memory-open" disabled={saving} onclick={() => edit(entry.document)} data-testid="rule-document-edit">{entry.fields.title}</button>
            <SettingsBadge variant="neutral" text={sourceLabel} />
            {#if entry.expired}
              <SettingsBadge variant="warning" text={$text('memories.expired')} />
              <SettingsButton variant="secondary" size="sm" disabled={saving} dataTestid="memory-renew" onClick={() => void renew(entry.document)}>{$text('memories.renew')}</SettingsButton>
            {/if}
          </div>
        {/each}
      </div>
    {:else}
      <p>{$text('memories.empty')}</p>
    {/if}
    <p class="budget" data-testid="memory-char-budget">{$text('memories.character_budget', { values: { used: usedChars, max: MAX_RULE_CATALOG_CHARS } })}</p>

    {#if suggestion && (selected || suggestion.is_new)}
      <SettingsInfoBox type="warning"><p data-testid="memory-draft-banner">{$text('memories.draft_unsaved')}</p></SettingsInfoBox>
      {#each [['title', 'memories.title'], ['when_to_use', 'memories.when_to_use'], ['body', 'memories.practices']] as [field, label] (field)}
        {#if original && changed(field as 'title' | 'body' | 'when_to_use')}
          <div data-testid="memory-draft-diff-{field}">
            <p class="diff-label">{$text(label)}: {$text('memories.draft_current')}</p>
            <SettingsQuote text={original[field as 'title' | 'body' | 'when_to_use'] || '—'} />
          </div>
        {/if}
      {/each}
    {/if}

    <form onsubmit={save} data-testid="rule-document-form">
      <SettingsItem type="heading" title={$text('memories.title')} />
      <SettingsInput bind:value={draft.title} maxlength={180} disabled={saving} ariaLabel={$text('memories.title')} dataTestid="rule-title" />
      <SettingsItem type="heading" title={$text('memories.practices')} />
      <MemoryBodyEditor value={draft.body} disabled={saving} ariaLabel={$text('memories.practices')} placeholder={$text('memories.body_placeholder')}
        dataTestid="rule-body" onChange={setBody} onLimit={() => { error = $text('memories.references_limit'); }} />
      <SettingsInfoBox type="info"><p>{$text('memories.references_hint')}</p></SettingsInfoBox>
      <SettingsItem type="heading" title={$text('memories.when_to_use_optional')} />
      <SettingsTextarea bind:value={draft.when_to_use} maxlength={1200} rows={2} disabled={saving} ariaLabel={$text('memories.when_to_use')} dataTestid="rule-when-to-use" />
      <SettingsInfoBox type="info"><p>{$text('memories.when_to_use_hint')}</p></SettingsInfoBox>
      <SettingsItem type="heading" title={$text('memories.load_mode')} />
      <SettingsDropdown value={draft.load_mode ?? 'auto_include'} options={loadModeOptions} disabled={saving}
        ariaLabel={$text('memories.load_mode')} dataTestid="memory-load-mode"
        onChange={(value) => { draft = { ...draft, load_mode: value as MemoryLoadMode }; }} />
      <SettingsItem type="heading" title={$text('memories.valid_from')} />
      <SettingsInput type="date" value={dateOnly(draft.valid_from)} disabled={saving} ariaLabel={$text('memories.valid_from')} dataTestid="memory-valid-from" onInput={(value) => setDate('valid_from', value)} />
      <SettingsItem type="heading" title={$text('memories.valid_until')} />
      <SettingsInput type="date" value={dateOnly(draft.valid_until)} disabled={saving} ariaLabel={$text('memories.valid_until')} dataTestid="memory-valid-until" onInput={(value) => setDate('valid_until', value)} />
      <SettingsButtonGroup align="left">
        <SettingsButton variant="primary" loading={saving} disabled={saving} dataTestid="rule-save" onClick={() => void save()}>{$text('common.save')}</SettingsButton>
        {#if selected}
          <SettingsButton variant="secondary" disabled={saving} dataTestid="rule-new" onClick={reset}>{$text('memories.new')}</SettingsButton>
          {#if source === 'personal' && service.remove}<SettingsButton variant="danger" disabled={saving} dataTestid="memory-delete" onClick={() => void remove()}>{$text('common.delete')}</SettingsButton>{/if}
        {/if}
      </SettingsButtonGroup>
    </form>
  {/if}
  {#if error}<SettingsInfoBox type="warning" data-testid="memory-error"><p data-testid="memory-error-text">{error}</p></SettingsInfoBox>{/if}
  {#if notice}<p role="status" data-testid="rule-saved-notice">{notice}</p>{/if}
</div>

<style>
  .memories-editor { display: grid; gap: var(--spacing-5); min-width: 0; }
  .memory-list { display: grid; gap: var(--spacing-3); }
  .memory-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-3); }
  .memory-row.expired { opacity: 0.55; }
  .memory-open { flex: 1 1 auto; min-width: 0; min-height: 2.75rem; text-align: start; border: 0; background: transparent; color: var(--color-font-primary); font: inherit; cursor: pointer; overflow-wrap: anywhere; }
  .memory-open:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
  .budget, .diff-label { margin: 0; color: var(--color-font-secondary); font-size: var(--font-size-small); }
  p { font-size: var(--font-size-small); }
</style>
