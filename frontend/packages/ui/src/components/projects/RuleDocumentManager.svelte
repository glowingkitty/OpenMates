<script lang="ts">
  import { untrack } from 'svelte';
  import { text } from '../../i18n/translations';
  import { defaultMemoryEditorService } from '../../services/memoryEditorService';
  import MemoriesEditor, { type MemoryDraftSuggestion, type MemoryEditorService, type MemoryEditorView } from '../settings/MemoriesEditor.svelte';

  interface Props {
    projectId: string | null;
    onClose: () => void;
    service?: MemoryEditorService;
    /** Memory to open immediately (deep link). */
    initialMemoryId?: string | null;
    /** Unsaved suggestion shown as a diff against the opened memory. */
    suggestion?: MemoryDraftSuggestion | null;
  }
  let { projectId, onClose, service: providedService, initialMemoryId = null, suggestion = null }: Props = $props();
  let service = $derived(providedService ?? defaultMemoryEditorService);
  let source = $state<'personal' | 'project'>(untrack(() => projectId ? 'project' : 'personal'));
  // Projects show the list and the memory pages in place (no settings route).
  let view = $state<MemoryEditorView>(untrack(() => initialMemoryId ? { kind: 'entry', id: initialMemoryId } : { kind: 'list' }));
  let activeSuggestion = $state<MemoryDraftSuggestion | null>(untrack(() => suggestion));
  function selectSource(next: 'personal' | 'project') {
    source = next; view = { kind: 'list' }; activeSuggestion = null;
  }
  function navigate(next: MemoryEditorView) {
    if (next.kind === 'list') activeSuggestion = null;
    view = next;
  }
</script>

<section class="rule-manager" data-testid="rule-document-manager" aria-label={$text('memories.manage')}>
  <div class="heading">
    <h2>{$text('memories.manage')}</h2>
    <button type="button" onclick={onClose} data-testid="rule-manager-close">{$text('common.close')}</button>
  </div>
  <p>{$text('memories.guide_description')}</p>
  <div class="scope" role="group" aria-label={$text('memories.scope')}>
    <button type="button" aria-pressed={source === 'personal'} onclick={() => selectSource('personal')} data-testid="rule-scope-personal">{$text('memories.source_personal')}</button>
    {#if projectId}
      <button type="button" aria-pressed={source === 'project'} onclick={() => selectSource('project')} data-testid="rule-scope-project">{$text('memories.source_project')}</button>
    {/if}
  </div>
  <MemoriesEditor {source} {projectId} {service} {view} suggestion={activeSuggestion} onNavigate={navigate} />
</section>

<style>
  .rule-manager { width: 100%; min-width: 0; box-sizing: border-box; padding: var(--spacing-6); border: 1px solid var(--color-grey-25); border-radius: var(--radius-7); background: var(--color-grey-10); color: var(--color-font-primary); display: grid; gap: var(--spacing-5); }
  .heading, .scope { display: flex; align-items: center; flex-wrap: wrap; gap: var(--spacing-3); }
  .heading { justify-content: space-between; }
  h2 { margin: 0; font-size: var(--font-size-p); }
  p { margin: 0; font-size: var(--font-size-small); }
  button { min-height: 2.75rem; border: 1px solid var(--color-grey-30); border-radius: var(--radius-4); padding: var(--spacing-3) var(--spacing-5); background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; overflow-wrap: anywhere; }
  button[aria-pressed='true'] { border-color: var(--color-primary); }
  button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
</style>
