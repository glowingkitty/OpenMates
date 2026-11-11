<!-- frontend/packages/ui/src/components/settings/MemoryEntryPage.svelte
     Create / edit page of one Memory (Settings > Memories > Create memory, or a tapped row).
     Fields: title, memory (inline embeds), when to use, app, load mode, start and expiry date.
     An unsaved suggestion is shown with a banner and the current text of every changed field;
     nothing is saved until Save. Spec: specifications/features/app-memories.
     Preview: /dev/preview/settings/MemoryEntryPage
-->
<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { text } from '../../i18n/translations';
  import MemoryBodyEditor from './MemoryBodyEditor.svelte';
  import { bodyWithLegacyReferences, referencesFromBody } from '../../utils/memoryBodyDocument';
  import {
    SettingsButton, SettingsButtonGroup, SettingsDropdown, SettingsInfoBox, SettingsInput,
    SettingsQuote, SettingsTextarea,
  } from './elements';
  import type { MemoryLoadMode, RuleDocumentFields } from '../../utils/ruleDocuments';

  type DiffField = 'title' | 'body' | 'when_to_use';

  interface Props {
    /** Fields the page starts with (stored memory, suggestion or empty). */
    initial: RuleDocumentFields;
    /** Stored fields when a suggestion is applied on top of them; null otherwise. */
    original: RuleDocumentFields | null;
    /** True while an unsaved suggestion is shown. */
    isDraft: boolean;
    /** True for a memory that does not exist yet. */
    isNew: boolean;
    saving: boolean;
    error: string;
    canDelete: boolean;
    /** '' = no app; labels are translated app names. */
    appOptions: Array<{ value: string; label: string }>;
    onSave: (fields: RuleDocumentFields) => void;
    onCancel: () => void;
    onDelete: () => void;
    onError: (message: string) => void;
  }
  let { initial, original, isDraft, isNew, saving, error, canDelete, appOptions, onSave, onCancel, onDelete, onError }: Props = $props();

  let draft = $state<RuleDocumentFields>(untrack(() => ({ ...initial, load_mode: initial.load_mode ?? 'auto_include' })));

  const loadModeOptions = $derived([
    { value: 'auto_include', label: $text('memories.load_mode_auto_include') },
    { value: 'ask_first', label: $text('memories.load_mode_ask_first') },
    { value: 'mention_only', label: $text('memories.load_mode_mention_only') },
  ]);
  const diffFields: Array<[DiffField, string]> = [['title', 'memories.title'], ['when_to_use', 'memories.when_to_use'], ['body', 'memories.practices']];
  const dateOnly = (iso?: string) => (iso ? iso.slice(0, 10) : '');
  const changed = (field: DiffField) => isDraft && original !== null && original[field] !== draft[field];

  async function embedTypeOf(id: string): Promise<string | null> {
    const { resolveEmbed } = await import('../../services/embedResolver');
    const embed = await resolveEmbed(id);
    return embed && typeof embed.type === 'string' ? embed.type : null;
  }

  /** Memories saved with a separate reference list show those embeds inline. */
  onMount(() => {
    const start = draft;
    if (!start.references?.length) return;
    void bodyWithLegacyReferences(start.body, start.references, embedTypeOf).then((body) => {
      if (body !== start.body && draft.body === start.body) setBody(body);
    });
  });

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

  function setApp(value: string) {
    const { app_id: _previous, ...rest } = draft;
    draft = value ? { ...rest, app_id: value } : rest;
  }
  import SettingsSectionHeading from './elements/SettingsSectionHeading.svelte';
</script>

<div data-testid="memory-entry-page" data-new={isNew}>
  {#if isDraft}
    <SettingsInfoBox type="warning"><p data-testid="memory-draft-banner">{$text('memories.draft_unsaved')}</p></SettingsInfoBox>
    {#each diffFields as [field, label] (field)}
      {#if original && changed(field)}
        <div data-testid="memory-draft-diff-{field}">
          <SettingsSectionHeading title={`${$text(label)}: ${$text('memories.draft_current')}`} icon="document" />
          <SettingsQuote text={original[field] || '—'} />
        </div>
      {/if}
    {/each}
  {/if}

  <div data-testid="memory-field-title"><SettingsSectionHeading title={$text('memories.title')} icon="text" /></div>
  <SettingsInput bind:value={draft.title} maxlength={180} disabled={saving} ariaLabel={$text('memories.title')} dataTestid="rule-title" />

  <div data-testid="memory-field-memory"><SettingsSectionHeading title={$text('memories.practices')} icon="settings_memories" /></div>
  <MemoryBodyEditor value={draft.body} disabled={saving} ariaLabel={$text('memories.practices')} placeholder={$text('memories.body_placeholder')}
    dataTestid="rule-body" onChange={setBody} onLimit={() => onError($text('memories.references_limit'))} />
  <SettingsInfoBox type="info"><p>{$text('memories.references_hint')}</p></SettingsInfoBox>

  <div data-testid="memory-field-when-to-use"><SettingsSectionHeading title={$text('memories.when_to_use_optional')} icon="focus" /></div>
  <SettingsTextarea bind:value={draft.when_to_use} maxlength={1200} rows={2} disabled={saving} ariaLabel={$text('memories.when_to_use')} dataTestid="rule-when-to-use" />
  <SettingsInfoBox type="info"><p>{$text('memories.when_to_use_hint')}</p></SettingsInfoBox>

  <div data-testid="memory-field-app"><SettingsSectionHeading title={$text('memories.app')} icon="app" /></div>
  <SettingsDropdown value={draft.app_id ?? ''} options={appOptions} disabled={saving}
    ariaLabel={$text('memories.app')} dataTestid="memory-app" onChange={setApp} />

  <div data-testid="memory-field-load-mode"><SettingsSectionHeading title={$text('memories.load_mode')} icon="settings" /></div>
  <SettingsDropdown value={draft.load_mode ?? 'auto_include'} options={loadModeOptions} disabled={saving}
    ariaLabel={$text('memories.load_mode')} dataTestid="memory-load-mode"
    onChange={(value) => { draft = { ...draft, load_mode: value as MemoryLoadMode }; }} />

  <div data-testid="memory-field-valid-from-heading"><SettingsSectionHeading title={$text('memories.valid_from')} icon="calendar" /></div>
  <SettingsInput type="date" value={dateOnly(draft.valid_from)} disabled={saving} ariaLabel={$text('memories.valid_from')}
    dataTestid="memory-valid-from" onInput={(value) => setDate('valid_from', value)} />
  <div data-testid="memory-field-valid-until-heading"><SettingsSectionHeading title={$text('memories.valid_until')} icon="calendar" /></div>
  <SettingsInput type="date" value={dateOnly(draft.valid_until)} disabled={saving} ariaLabel={$text('memories.valid_until')}
    dataTestid="memory-valid-until" onInput={(value) => setDate('valid_until', value)} />

  {#if error}
    <SettingsInfoBox type="warning" data-testid="memory-error"><p data-testid="memory-error-text">{error}</p></SettingsInfoBox>
  {/if}

  <SettingsButtonGroup align="space-between">
    <SettingsButton variant="secondary" disabled={saving} dataTestid="rule-cancel" onClick={onCancel}>{$text('common.cancel')}</SettingsButton>
    {#if canDelete && !isNew}
      <SettingsButton variant="danger" disabled={saving} dataTestid="memory-delete" onClick={onDelete}>{$text('common.delete')}</SettingsButton>
    {/if}
    <SettingsButton variant="primary" loading={saving} disabled={saving} dataTestid="rule-save" onClick={() => onSave(draft)}>{$text('common.save')}</SettingsButton>
  </SettingsButtonGroup>
</div>
