<!-- frontend/packages/ui/src/components/IncludedMemoryPills.svelte
     Memories the user included in a turn (memory request approved in a call or a text
     chat): one pill per memory with its title and its icon in a round circle in its
     colour, like the Memories list and the loaded-memory pills. Tapping a pill opens
     that memory. Preview: /dev/preview/IncludedMemoryPills -->
<script lang="ts">
  import { text } from '../i18n/translations';
  import { includedMemoryIconClass, type IncludedMemoryBadge } from '../utils/includedMemoryBadges';

  let { memories, onOpen }: {
    memories: readonly IncludedMemoryBadge[];
    onOpen: (memory: IncludedMemoryBadge) => void;
  } = $props();
</script>

<div class="included-memories" data-testid="included-memory-pills">
  {#each memories as memory (memory.id)}
    <button type="button" class="memory-pill" data-testid="included-memory-pill" onclick={() => onOpen(memory)}>
      <span class="icon settings_size {includedMemoryIconClass(memory)} memory-icon" data-testid="included-memory-icon" aria-hidden="true"></span>
      <span class="memory-title" data-testid="included-memory-title">{memory.title ?? $text('settings.settings_memories')}</span>
    </button>
  {/each}
</div>

<style>
  .included-memories { display: flex; flex-wrap: wrap; gap: var(--spacing-3); min-width: 0; }
  .memory-pill { display: inline-flex; align-items: center; gap: var(--spacing-3); max-width: 100%; min-height: 2rem; padding: var(--spacing-2) var(--spacing-4) var(--spacing-2) var(--spacing-2); border: 1px solid var(--color-grey-30); border-radius: 999px; background: var(--color-grey-0); color: var(--color-font-primary); cursor: pointer; font-size: var(--font-size-small); overflow-wrap: anywhere; text-align: start; }
  .memory-pill:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .memory-pill .memory-icon { width: 22px; height: 22px; min-width: 22px; min-height: 22px; margin: 0; border-radius: 50%; flex: none; }
  .memory-title { min-width: 0; }
</style>
