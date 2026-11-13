<!-- frontend/packages/ui/src/components/settings/MemoriesEditor.svelte
     Free-form Memories of one source (personal account or one Project): loads and saves the
     documents and shows one of three pages chosen by the caller's view: the list (MemoryList),
     the create page or one memory's page (MemoryEntryPage). Settings > Memories maps the views
     to settings routes (settings_memories, …/create, …/<id>); Projects keep them locally.
     Saves stamp created_at (first save) and updated_at (every save). An unsaved suggestion
     (deep link) is applied on top of its memory and saved only when the user clicks Save.
     Spec: specifications/features/app-memories.
     Native Swift counterparts:
     - apple/OpenMates/Sources/Features/Settings/Memories/SettingsMemoryDocuments.swift
     - apple/OpenMates/Sources/Features/Settings/Views/SettingsMemoriesFull.swift
-->
<script module lang="ts">
  import { writable } from 'svelte/store';
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
    /** App suggested for the memory; ignored when this client does not know it. */
    app_id?: string;
    /** Creates a memory that does not exist yet. */
    is_new?: boolean;
    /** Saved document when the suggestion was previewed; a different current document is a conflict. */
    base_document?: string;
  }
  /** Page of the Memories editor: the list, the create page or one memory (id or `personal:` id). */
  export type MemoryEditorView = { kind: 'list' } | { kind: 'create' } | { kind: 'entry'; id: string };
  /**
   * Confirmation of the last save. Module-level because Settings may mount a new list page
   * after navigating back from the entry page; it is cleared when a memory page opens.
   */
  export const memorySavedNotice = writable('');
</script>

<script lang="ts">
  import { text } from '../../i18n/translations';
  import { appSkillsStore, discoverableApps } from '../../stores/appSkillsStore';
  import MemoryList from './MemoryList.svelte';
  import MemoryEntryPage from './MemoryEntryPage.svelte';
  import { SettingsInfoBox } from './elements';
  import { parseRuleDocument, serializeRuleDocument, stampMemorySave, type RuleDocumentFields } from '../../utils/ruleDocuments';
  import { memoryListEntries, type MemoryListEntry } from '../../utils/memoryListEntries';

  interface Props {
    source: 'personal' | 'project';
    projectId: string | null;
    service: MemoryEditorService;
    view: MemoryEditorView;
    /** Unsaved suggestion applied on top of the opened memory (or the create page when is_new). */
    suggestion: MemoryDraftSuggestion | null;
    /** Shows another page; title is the memory title for an entry page. */
    onNavigate: (view: MemoryEditorView, title: string) => void;
  }
  let { source, projectId, service, view, suggestion, onNavigate }: Props = $props();

  const emptyDraft = (): RuleDocumentFields => ({ title: '', when_to_use: '', body: '', load_mode: 'auto_include' });
  let documents = $state<EditableRuleDocument[]>([]);
  let loading = $state(true);
  let saving = $state(false);
  let error = $state('');
  let generation = 0;

  const knownApps = appSkillsStore.getState().apps;
  const isKnownApp = (appId: string | undefined): appId is string => !!appId && !!knownApps[appId];
  const appName = (appId: string) => {
    const key = knownApps[appId]?.name_translation_key;
    return key ? $text(key) : appId;
  };

  const entries = $derived(memoryListEntries(documents));
  const usedChars = $derived(documents.reduce((sum, item) => sum + item.document.length, 0));
  const sourceLabel = $derived(source === 'personal' ? $text('memories.visibility_private') : $text('memories.source_project'));
  const target = $derived(view.kind === 'entry'
    ? documents.find((item) => item.id === view.id || item.id === `personal:${view.id}`) ?? null : null);
  /** A suggested new memory opens the create page under its draft id. */
  const creating = $derived(view.kind === 'create' || (view.kind === 'entry' && !!suggestion?.is_new));
  const page = $derived(creating ? 'create' : target ? 'entry' : 'list');
  const original = $derived(target ? parseRuleDocument(target.document) : null);

  const initialFields = $derived.by((): RuleDocumentFields => {
    const base = original ? { ...original } : emptyDraft();
    if (!suggestion || (!creating && !original)) return base;
    const knownApp = isKnownApp(suggestion.app_id) ? { app_id: suggestion.app_id } : {};
    return {
      ...base, ...knownApp,
      ...(suggestion.valid_from ? { valid_from: suggestion.valid_from } : {}),
      ...(suggestion.valid_until ? { valid_until: suggestion.valid_until } : {}),
      title: suggestion.title, body: suggestion.memory,
      when_to_use: suggestion.when_to_use ?? base.when_to_use,
      load_mode: suggestion.load_mode ?? base.load_mode ?? 'auto_include',
    };
  });

  const appOptions = $derived.by(() => {
    const ids = new Set(Object.keys($discoverableApps));
    if (isKnownApp(initialFields.app_id)) ids.add(initialFields.app_id);
    const options = [...ids].map((id) => ({ value: id, label: appName(id) }))
      .sort((a, b) => a.label.localeCompare(b.label));
    return [{ value: '', label: $text('memories.app_none') }, ...options];
  });

  $effect(() => { void load(source, projectId); });

  function appIcon(appId: string | undefined): string | null {
    return isKnownApp(appId) ? `app-${appId}` : null;
  }

  function displayError(value: unknown): string {
    return value instanceof Error && value.message === 'rule_project_activation_required'
      ? $text('memories.activation_required') : $text('memories.save_failed');
  }

  async function load(currentSource: 'personal' | 'project', selectedProjectId: string | null) {
    const token = ++generation;
    loading = true; error = ''; documents = [];
    try {
      const loaded = await service.list(currentSource, selectedProjectId);
      if (token === generation) documents = loaded;
    } catch (value) { if (token === generation) error = displayError(value); }
    finally { if (token === generation) loading = false; }
  }

  function open(next: MemoryEditorView, title: string) {
    memorySavedNotice.set('');
    error = '';
    onNavigate(next, title);
  }

  /** Saves one memory; returns true when it was stored. */
  async function persist(fields: RuleDocumentFields, existing: EditableRuleDocument | null, checkBase: boolean): Promise<boolean> {
    let document: string;
    const previous = existing ? parseRuleDocument(existing.document) : null;
    try { document = serializeRuleDocument(stampMemorySave(fields, previous, Math.floor(Date.now() / 1000))); }
    catch { error = $text('memories.invalid_document'); return false; }
    saving = true; error = '';
    const token = generation;
    try {
      // A draft previewed against an older revision must not overwrite a newer one.
      if (checkBase && suggestion?.base_document !== undefined && existing) {
        const current = (await service.list(source, projectId)).find((item) => item.id === existing.id);
        if (token !== generation) return false;
        if (!current || current.document !== suggestion.base_document) {
          error = $text('memories.draft_conflict');
          return false;
        }
      }
      await service.save(source, projectId, document, existing);
      if (token !== generation) return false;
      documents = await service.list(source, projectId);
      if (token !== generation) return false;
      memorySavedNotice.set($text('memories.saved'));
      return true;
    } catch (value) {
      if (token === generation) error = displayError(value);
      return false;
    } finally { saving = false; }
  }

  async function save(fields: RuleDocumentFields) {
    if (saving) return;
    if (await persist(fields, creating ? null : target, true)) onNavigate({ kind: 'list' }, '');
  }

  async function renew(entry: MemoryListEntry) {
    if (saving) return;
    const until = new Date(Date.now() + 30 * 86_400_000);
    await persist({ ...entry.fields, valid_until: `${until.toISOString().slice(0, 10)}T23:59:59.000Z` }, entry.document, false);
  }

  async function remove() {
    if (saving || !target || !service.remove) return;
    saving = true; error = '';
    const token = generation;
    try {
      await service.remove(source, projectId, target);
      if (token !== generation) return;
      documents = await service.list(source, projectId);
      onNavigate({ kind: 'list' }, '');
    } catch (value) { if (token === generation) error = displayError(value); }
    finally { saving = false; }
  }
</script>

<div data-testid="memories-editor" data-source={source} data-page={page}>
  {#if source === 'project'}<SettingsInfoBox type="info"><p>{$text('memories.project_storage')}</p></SettingsInfoBox>{/if}
  {#if page === 'list'}
    <MemoryList {entries} {loading} {saving} {usedChars} {sourceLabel} notice={$memorySavedNotice} {appIcon}
      onCreate={() => open({ kind: 'create' }, $text('memories.create_title'))}
      onOpen={(entry) => open({ kind: 'entry', id: entry.document.id }, entry.fields.title)}
      onRenew={(entry) => void renew(entry)} />
    {#if error}
      <SettingsInfoBox type="warning" data-testid="memory-error"><p data-testid="memory-error-text">{error}</p></SettingsInfoBox>
    {/if}
  {:else}
    {#key `${page}:${target?.id ?? ''}:${suggestion ? 'draft' : ''}`}
      <MemoryEntryPage initial={initialFields} original={suggestion && !creating ? original : null}
        isDraft={!!suggestion} isNew={creating} {saving} {error} {appOptions}
        canDelete={source === 'personal' && !!service.remove}
        onSave={(fields) => void save(fields)} onCancel={() => onNavigate({ kind: 'list' }, '')}
        onDelete={() => void remove()} onError={(message) => { error = message; }} />
    {/key}
  {/if}
</div>
