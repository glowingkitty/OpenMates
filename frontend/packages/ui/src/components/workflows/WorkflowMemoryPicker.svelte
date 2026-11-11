<!-- Lists personal memories (not expired) the author can mention in an Ask AI step. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import { matchesWorkflowVariableQuery } from './workflowMentionQuery';
  import { listMentionableMemories, type MentionableMemory } from '../../services/workflowMemorySnapshotService';

  let { query = '', disabled = false, initialMemories, onInsert, onLoaded }: {
    query?: string; initialMemories?: MentionableMemory[]; disabled?: boolean; onInsert: (memory: MentionableMemory) => void; onLoaded: (memories: MentionableMemory[]) => void;
  } = $props();
  let memories = $state<MentionableMemory[]>([]);
  let failed = $state(false);
  const shown = $derived(memories.filter(memory => !query || matchesWorkflowVariableQuery(memory.title, query)));

  onMount(() => {
    if (initialMemories) { memories = initialMemories; return; }
    listMentionableMemories().then(list => { memories = list; onLoaded(list); }).catch(error => { console.error('[WorkflowMemoryPicker]', error); failed = true; });
  });
</script>

{#if memories.length || failed}
  <div class="memory-picker" data-testid="workflow-memory-picker" aria-label={$text('workflows.builder.memory_picker_label')}>
    <span class="label">{$text('workflows.builder.memory_picker_label')}</span>
    <div class="chip-scroll" data-testid="workflow-memory-chip-scroll">
      {#each shown as memory (memory.id)}
        <button type="button" class="chip" data-memory-id={memory.id} title={memory.title} {disabled} onclick={() => onInsert(memory)}>@ {memory.title}</button>
      {/each}
      {#if failed}<span class="note" role="status">{$text('workflows.builder.memory_picker_unavailable')}</span>{/if}
    </div>
  </div>
{/if}

<style>
  .memory-picker{display:flex;align-items:center;gap:.4rem;min-width:0}
  .label,.note{font-size:var(--font-size-small);color:var(--color-font-secondary)}
  .label{flex:0 0 auto}
  .chip-scroll{display:flex;align-items:center;gap:.4rem;flex:1 1 0;min-width:0;overflow-x:auto;scrollbar-width:none;padding:.2rem .65rem .35rem;scroll-padding-inline:.65rem;mask-image:linear-gradient(to right,transparent,#000 .65rem,#000 calc(100% - .65rem),transparent)}
  .chip-scroll::-webkit-scrollbar{display:none}
  .chip{flex:0 0 auto;max-width:14rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:0;border-radius:1rem;padding:.15rem .6rem;cursor:pointer;color:var(--color-font-button);background:linear-gradient(135deg,var(--color-primary-start),var(--color-primary-end))}
</style>
