<!--
  Unread counter for "Continue where you left off" chat cards.
  Mirrors the sidebar chat-row badge (Chat.svelte .unread-badge) so a chat whose
  latest reply has not been read to its last line is highlighted on both surfaces.
  Reads unreadMessagesStore directly; renders nothing when the chat is read.
-->
<script lang="ts">
  import { unreadMessagesStore } from '../../stores/unreadMessagesStore';

  type Props = {
    chatId: string;
    variant: 'large' | 'compact';
  };

  let { chatId, variant }: Props = $props();

  let unreadCount = $derived($unreadMessagesStore.unreadCounts.get(chatId) ?? 0);
</script>

{#if unreadCount > 0}
  <div
    class="continue-card-unread-badge"
    class:compact={variant === 'compact'}
    data-testid="continue-card-unread-badge"
    data-unread-count={unreadCount}
  >
    {unreadCount > 9 ? '9+' : unreadCount}
  </div>
{/if}

<style>
  .continue-card-unread-badge {
    position: absolute;
    top: 12px;
    left: 12px;
    min-width: 26px;
    height: 26px;
    padding: 0 6px;
    box-sizing: border-box;
    background: var(--color-button-primary);
    color: white;
    border-radius: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--font-size-small);
    font-weight: 600;
    border: 2px solid rgba(255, 255, 255, 0.9);
    z-index: var(--z-index-raised-2);
    pointer-events: none;
  }

  .continue-card-unread-badge.compact {
    top: 4px;
    left: 4px;
    min-width: 21px;
    height: 21px;
    padding: 0 4px;
    border-radius: 11px;
  }
</style>
