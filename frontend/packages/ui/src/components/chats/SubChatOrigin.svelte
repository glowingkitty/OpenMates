<!--
  SubChatOrigin.svelte
  System event at the very top of a sub-chat's message list: names the main
  chat it was created from (link to it) and, when known, the Plan assumption it
  checks or the Task it works on. Props-driven; the parent resolves the title.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import type { SubChatWork } from './subChatWork';

  let { parentTitle, work = null, onOpenParent }: {
    parentTitle: string;
    work?: SubChatWork | null;
    onOpenParent: () => void;
  } = $props();

  const MARK = '\u0000';
  let parts = $derived($text('plan_embeds.sub_chat.created_as', { values: { name: MARK } }).split(MARK));
  let name = $derived(parentTitle || $text('plan_embeds.sub_chat.parent_fallback'));
  let workLine = $derived(!work ? '' : work.kind === 'assumption'
    ? $text('plan_embeds.sub_chat.checks', { values: { text: work.label } })
    : $text('plan_embeds.sub_chat.works_on', { values: { title: work.label } }));
</script>

<div class="sub-chat-origin" data-testid="sub-chat-origin" data-kind={work?.kind ?? 'none'}>
  <div class="line">{parts[0]}<button type="button" class="parent-link" data-testid="sub-chat-origin-parent-link" onclick={() => onOpenParent()}>{name}</button>{parts[1] ?? ''}</div>
  {#if work}<div class="line work" data-testid="sub-chat-origin-work">{workLine}</div>{/if}
</div>

<style>
  .sub-chat-origin { display: flex; flex-direction: column; align-items: center; gap: var(--spacing-2); margin-block: var(--spacing-6); padding-inline: var(--spacing-6); text-align: center; color: var(--color-font-secondary); font-size: var(--font-size-small, 0.875rem); }
  .line { overflow-wrap: anywhere; }
  .work { font-weight: 600; color: var(--color-font-primary); }
  .parent-link { border: 0; padding: 0; margin: 0; min-width: 0; height: auto; box-shadow: none; filter: none; background: none; color: var(--color-primary-start, var(--color-font-primary)); font: inherit; font-weight: 600; text-decoration: underline; cursor: pointer; }
  .parent-link:hover, .parent-link:active, .parent-link:focus { box-shadow: none; filter: none; background: none; transform: none; }
</style>
