<script lang="ts">
  import { text } from '@repo/ui';

  let { count }: { count: number } = $props();
</script>

{#if count > 100}
  <p class="account-chat-count" data-testid="chat-account-total" data-chat-count={count}>
    {$text('chats.loadMore.account_total', { values: { count: count.toLocaleString() } })}
  </p>
{/if}

<style>
  .account-chat-count {
    color: var(--color-font-secondary);
    font-size: 0.8rem;
    margin: var(--spacing-1) var(--spacing-4) var(--spacing-2);
  }
</style>
