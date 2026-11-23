<!--
  SubChatWorkLink.svelte
  Header strip of a sub-chat: names the Plan assumption it checks or the Task
  it works on, with a way back to the main chat. Props-driven.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import type { SubChatWork } from './subChatWork';

  let { work, onBack }: { work: SubChatWork; onBack?: () => void } = $props();
  let label = $derived(work.kind === 'assumption'
    ? $text('plan_embeds.sub_chat.checks', { values: { text: work.label } })
    : $text('plan_embeds.sub_chat.works_on', { values: { title: work.label } }));
</script>

<div class="sub-chat-work-link" data-testid="sub-chat-work-link" data-kind={work.kind}>
  <span class="label">{label}</span>
  <button type="button" data-testid="sub-chat-work-link-back" onclick={() => onBack?.()}>{$text('plan_embeds.sub_chat.back')}</button>
</div>

<style>
  .sub-chat-work-link { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-5); padding: var(--spacing-3) var(--spacing-6); background: var(--color-grey-10); color: var(--color-font-primary); font-size: var(--font-size-small, 0.875rem); }
  .label { min-width: 0; overflow-wrap: anywhere; font-weight: 600; }
  button { flex: none; border: 0; background: none; color: var(--color-primary-start, var(--color-font-primary)); font: inherit; text-decoration: underline; cursor: pointer; }
</style>
