<!-- Lists personal memories (not expired) the author can mention in an Ask AI step. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import { matchesWorkflowVariableQuery } from './workflowMentionQuery';
  import { listMentionableMemories, type MentionableMemory } from '../../services/workflowMemorySnapshotService';

  let { query = '', disabled = false, onInsert, onLoaded }: {
    query?: string; disabled?: boolean; onInsert: (memory: MentionableMemory) => void; onLoaded: (memories: MentionableMemory[]) => void;
  } = $props();
  let memories = $state<MentionableMemory[]>([]);
  let failed = $state(false);
  const shown = $derived(memories.filter(memory => !query || matchesWorkflowVariableQuery(memory.title, query)));

  onMount(() => {
    listMentionableMemories().then(list => { memories = list; onLoaded(list); }).catch(error => { console.error('[WorkflowMemoryPicker]', error); failed = true; });
  });
</script>

{#if memories.length || failed}
  <div class="memory-picker" data-testid="workflow-memory-picker" aria-label={$text('workflows.builder.memory_picker_label')}>
    <span class="label">{$text('workflows.builder.memory_picker_label')}</span>
    {#each shown as memory (memory.id)}
      <button type="button" class="chip" data-memory-id={memory.id} {disabled} onclick={() => onInsert(memory)}>@ {memory.title}</button>
    {/each}
    {#if failed}<span class="note" role="status">{$text('workflows.builder.memory_picker_unavailable')}</span>{/if}
  </div>
{/if}

<style>
  .memory-picker{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
  .label,.note{font-size:var(--font-size-small);color:var(--color-font-secondary)}
  .chip{border:0;border-radius:1rem;padding:.15rem .6rem;cursor:pointer;color:var(--color-font-button);background:linear-gradient(135deg,var(--color-primary-start),var(--color-primary-end))}
</style>
