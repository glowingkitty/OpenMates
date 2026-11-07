<!-- frontend/packages/ui/src/components/settings/MemoryReferencesField.svelte
     Reference chips for a Memory (embeds and chats). Spec: app-memories.references.embeds-and-chats.
     Chats are picked by their locally decrypted title; embeds by id (validated against the reader's own store).
     Unavailable items stay as chips with a marker; they never block saving. Nothing here leaves the device. -->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import { SettingsInput, SettingsDropdown, SettingsButton, SettingsBadge, SettingsItem } from './elements';
  import { MAX_MEMORY_REFERENCES, type MemoryReference } from '../../utils/ruleDocuments';
  import {
    defaultReferenceReaders, lookupReferenceLabels, referenceEntryId, type ReferenceLabel, type ReferenceReaders,
  } from '../../services/memoryReferences';

  interface Props {
    references: MemoryReference[];
    disabled?: boolean;
    onChange: (references: MemoryReference[]) => void;
    /** Test seam; defaults to the reader's own embed store and chat database. */
    readers?: ReferenceReaders;
    listChats?: () => Promise<Array<{ id: string; title: string }>>;
  }
  let { references, disabled = false, onChange, readers, listChats }: Props = $props();

  let labels = $state<ReferenceLabel[]>([]);
  let chats = $state<Array<{ id: string; title: string }>>([]);
  let embedId = $state('');
  let error = $state('');

  async function activeReaders(): Promise<ReferenceReaders> { return readers ?? defaultReferenceReaders(); }

  $effect(() => {
    const current = references;
    void (async () => { labels = await lookupReferenceLabels(current, await activeReaders()); })();
  });

  $effect(() => {
    void (async () => {
      if (listChats) { chats = await listChats(); return; }
      const { chatDB } = await import('../../services/db');
      chats = (await chatDB.getAllChats()).filter((chat) => chat.title?.trim()).map((chat) => ({ id: chat.chat_id, title: chat.title as string }));
    })();
  });

  const chatOptions = $derived(chats
    .filter((chat) => !references.some((ref) => ref.kind === 'chat' && ref.id === chat.id))
    .map((chat) => ({ value: chat.id, label: chat.title })));

  function add(reference: MemoryReference) {
    error = '';
    if (references.some((ref) => ref.kind === reference.kind && ref.id === reference.id)) return;
    if (references.length >= MAX_MEMORY_REFERENCES) { error = $text('memories.references_limit'); return; }
    onChange([...references, reference]);
  }

  async function addEmbed() {
    const id = embedId.trim().replace(/^embed:/, '');
    if (!id) return;
    const [label] = await lookupReferenceLabels([{ kind: 'embed', id }], await activeReaders());
    if (!label?.available) { error = $text('memories.references_embed_not_found'); return; }
    embedId = '';
    add({ kind: 'embed', id });
  }

  const remove = (reference: MemoryReference) =>
    onChange(references.filter((ref) => !(ref.kind === reference.kind && ref.id === reference.id)));
</script>

<div class="references" data-testid="memory-references">
  <SettingsItem type="heading" title={$text('memories.references')} />
  <p class="hint">{$text('memories.references_hint')}</p>
  {#if labels.length}
    <ul class="chips" data-testid="memory-reference-chips">
      {#each labels as label (referenceEntryId(label.reference))}
        <li class="chip" class:unavailable={!label.available} data-testid="memory-reference-chip"
          data-kind={label.reference.kind} data-available={label.available}>
          <SettingsBadge variant="neutral" text={$text(label.reference.kind === 'chat' ? 'memories.reference_chat' : 'memories.reference_embed')} />
          <span class="chip-title">{label.available ? label.title : $text('memories.reference_unavailable')}</span>
          <button type="button" class="chip-remove" {disabled} aria-label={$text('memories.reference_remove')}
            data-testid="memory-reference-remove" onclick={() => remove(label.reference)}>&times;</button>
        </li>
      {/each}
    </ul>
  {/if}
  <SettingsDropdown value="" options={chatOptions} {disabled} ariaLabel={$text('memories.reference_add_chat')}
    dataTestid="memory-reference-add-chat" onChange={(value) => { if (value) add({ kind: 'chat', id: value }); }} />
  <SettingsInput bind:value={embedId} {disabled} ariaLabel={$text('memories.reference_add_embed')}
    dataTestid="memory-reference-embed-id" />
  <SettingsButton variant="secondary" size="sm" {disabled} dataTestid="memory-reference-add-embed" onClick={() => void addEmbed()}>
    {$text('memories.reference_add_embed')}
  </SettingsButton>
  {#if error}<p role="alert" class="error">{error}</p>{/if}
</div>

<style>
  .references { display: grid; gap: var(--spacing-3); }
  .hint, .error { margin: 0; font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .chips { display: flex; flex-wrap: wrap; gap: var(--spacing-3); margin: 0; padding: 0; list-style: none; }
  .chip { display: inline-flex; align-items: center; gap: var(--spacing-2); min-width: 0; }
  .chip.unavailable { opacity: 0.6; }
  .chip-title { overflow-wrap: anywhere; }
  .chip-remove { min-width: 2.75rem; min-height: 2.75rem; border: 0; background: transparent; color: var(--color-font-primary); cursor: pointer; font: inherit; }
  .chip-remove:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
</style>
