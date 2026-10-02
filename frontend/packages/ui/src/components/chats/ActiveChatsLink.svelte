<!--
  ActiveChatsLink provides the compact chat organization/activity surface.
  Uses shared design tokens and accessible native controls.
  Navigation stays readable within the narrow sidebar.
  Global lifecycle stores remain separate from rendering.
  Colocated fixtures provide isolated component verification.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { activeChatCount } from '../../stores/chatActivityStore';
  import { panelState } from '../../stores/panelStateStore';
  let { previewCount }: { previewCount?: number } = $props();
  const count = $derived(previewCount ?? $activeChatCount);
  function revealChats(): void {
    panelState.openChats();
    window.dispatchEvent(new Event('openmates-reveal-running-chats'));
  }
</script>

{#if count > 0}
  <button type="button" class="active-chats-link" data-testid="active-chats-link" onclick={revealChats}>
    {$text(count === 1 ? 'chats.activity.count_single' : 'chats.activity.count', { values: { count } })}
  </button>
{/if}

<style>
  .active-chats-link { background: none; border: 0; padding: var(--spacing-4); font: inherit;
    min-inline-size: 0; block-size: auto; margin: 0; filter: none; scale: 1;
    font-size: var(--font-size-small); color: var(--color-font-primary); text-decoration: underline;
    text-underline-offset: 0.2em; cursor: pointer; }
</style>
