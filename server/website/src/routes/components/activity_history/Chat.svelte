<script lang="ts">
  import { page } from '$app/stores';
  
  export let chat: {
    id?: string;
    title?: string;
    isDraft?: boolean;
    draftContent?: string;
    mates?: string[]; // Array of mate names (e.g., ['burton', 'lisa'])
  };
  
  // Truncate text to fit in two lines
  function truncateText(text: string, maxLength: number = 60) {
    if (text && text.length > maxLength) {
      return text.substring(0, maxLength) + '...';
    }
    return text;
  }

  // Compute if this chat is currently active
  $: isActive = $page.params.chatId === chat.id;
</script>

<div 
  class="chat-item"
  class:active={isActive}
  role="button"
  tabindex="0"
>
  {#if chat.isDraft}
    <div class="draft-content">
      <span class="draft-label">Draft:</span>
      <p class="message-preview">{truncateText(chat.draftContent || '')}</p>
    </div>
  {:else}
    <div class="chat-with-profile">
      {#if chat.mates && chat.mates.length > 0}
        <div class="mate-profiles-row">
          {#each chat.mates as mate}
            <div class="mate-profile mate-profile-small {mate}" />
          {/each}
        </div>
      {/if}
      <span class="chat-title">{truncateText(chat.title || '')}</span>
    </div>
  {/if}
</div>

<style>
  .chat-item {
    padding: 8px 12px;
    cursor: pointer;
    border-radius: 8px;
    transition: background-color 0.2s ease;
  }

  .chat-item:hover {
    background-color: var(--color-grey-10);
  }

  .chat-item.active {
    background-color: var(--color-grey-20);
  }

  .chat-with-profile {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .profile-placeholder {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background-color: var(--color-grey-20);
  }

  .draft-content {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .draft-label {
    color: var(--color-grey-60);
    font-size: 0.9em;
  }

  .message-preview {
    margin: 0;
    display: -webkit-box;
    line-clamp: 2;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.3;
  }

  .chat-title {
    font-weight: 500;
    display: -webkit-box;
    line-clamp: 2;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.3;
  }
</style>
