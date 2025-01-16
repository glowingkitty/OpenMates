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
      <div class="mate-profiles-container">
        {#if chat.mates && chat.mates.length > 0}
          <div class="mate-profiles-row">
            {#each [...chat.mates].reverse() as mate}
              <div class="mate-profile mate-profile-small {mate}"></div>
            {/each}
          </div>
        {/if}
      </div>
      <span class="chat-title">{truncateText(chat.title || '')}</span>
    </div>
  {/if}
</div>

<style>
  .chat-item {
    padding: 12px 12px;
    cursor: pointer;
    border-radius: 0;
    transition: background-color 0.2s ease;
    margin: 0 0 -1px 0;
  }

  .chat-item:first-child {
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
  }

  .chat-item:last-child {
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    margin-bottom: 0;
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
    gap: 16px;
    position: relative;
  }

  .mate-profiles-container {
    flex: 0 0 28px;
    position: relative;
    height: 28px;
  }

  .mate-profiles-row {
    position: absolute;
    right: 0;
    display: flex;
    flex-direction: row-reverse;
    width: max-content;
    z-index: 1;
  }

  .mate-profiles-row :global(.mate-profile) {
    width: 28px;
    height: 28px;
    border: 2px solid var(--color-background);
    border-radius: 50%;
    flex-shrink: 0;
    position: relative;
  }

  .mate-profiles-row :global(.mate-profile:not(:first-child)) {
    position: absolute;
    right: 18px;
  }

  .mate-profiles-row :global(.mate-profile:nth-child(2)) {
    right: 18px;
  }

  .mate-profiles-row :global(.mate-profile:nth-child(3)) {
    right: 36px;
  }

  .mate-profiles-row :global(.mate-profile:nth-child(4)) {
    right: 54px;
  }

  .chat-title {
    flex: 1;
    font-weight: 500;
    display: -webkit-box;
    line-clamp: 2;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.3;
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
    gap: 6px;
    color: var(--color-grey-60);
  }

  .draft-label {
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
</style>
