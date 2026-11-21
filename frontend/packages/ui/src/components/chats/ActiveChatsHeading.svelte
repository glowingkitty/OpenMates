<!--
  ActiveChatsHeading: title of the Chats start row while chats are running
  ("You have 1 chat active:" / "You have 2 chats active:"), plain text, not a link
  (Marco, 21 Nov). The running chats themselves are the first cards of the row.
  The count is the Rust-grouped number of visible parents with running work
  (chatActivityStore.activeChatCount). Spec: daily-inspiration.start-row-active-first.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { activeChatCount } from '../../stores/chatActivityStore';
  let { previewCount }: { previewCount?: number } = $props();
  const count = $derived(previewCount ?? $activeChatCount);
</script>

{#if count > 0}
  <p class="active-chats-heading" data-testid="active-chats-heading" data-count={count}>
    {$text(count === 1 ? 'chats.resume_last_chat.active_title_single' : 'chats.resume_last_chat.active_title', { values: { count } })}
  </p>
{/if}
