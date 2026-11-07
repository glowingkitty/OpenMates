<!-- Consent and needs-attention notice for memories mentioned in an Ask AI step. -->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import { mentionedMemoryIds, type AskAiMemoryState } from './workflowMemorySnapshots';

  let { prompt, memory }: { prompt: string; memory: AskAiMemoryState } = $props();
  const mentioned = $derived(mentionedMemoryIds(prompt));
  const attention = $derived(Object.keys(memory.memory_attention ?? {}).filter(id => mentioned.includes(id)));
</script>

{#if mentioned.length}
  <p class="memory-consent" data-testid="workflow-memory-snapshot-consent">{$text('workflows.builder.memory_snapshot_consent')}</p>
{/if}
{#if attention.length}
  <p class="memory-attention" role="alert" data-testid="workflow-memory-needs-attention">{$text('workflows.builder.memory_needs_attention')}</p>
{/if}

<style>
  .memory-consent,.memory-attention{margin:0;font-size:var(--font-size-small);color:var(--color-font-secondary)}
  .memory-attention{color:var(--color-error)}
</style>
