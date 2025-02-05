<script lang="ts">
  export let chat: {
    id?: string;
    title?: string;
    isDraft?: boolean;
    draftContent?: string;
    mates?: string[]; // Array of mate names (e.g., ['burton', 'lisa'])
  };
  export let activeChatId: string | undefined = undefined;
  
  // Truncate text to fit in two lines
  function truncateText(text: string, maxLength: number = 60) {
    if (text && text.length > maxLength) {
      return text.substring(0, maxLength) + '...';
    }
    return text;
  }

  // Compute if this chat is currently active
  $: isActive = activeChatId === chat.id;

  // Take only the most recent mate instead of 3
  $: displayMate = chat.mates ? chat.mates[chat.mates.length - 1] : null;
</script>

<div 
  class="chat-item-wrapper"
  class:active={isActive}
  role="button"
  tabindex="0"
>
  <div class="chat-item">
    {#if chat.isDraft}
      <div class="draft-content">
        <span class="draft-label">Draft:</span>
        <p class="message-preview">{truncateText(chat.draftContent || '')}</p>
      </div>
    {:else}
      <div class="chat-with-profile">
        <div class="mate-profiles-container">
          {#if displayMate}
            <div class="mate-profiles-row">
              <div class="mate-profile-wrapper">
                <div class="mate-profile mate-profile-small {displayMate}"></div>
              </div>
            </div>
          {/if}
        </div>
        <span class="chat-title">{truncateText(chat.title || '')}</span>
      </div>
    {/if}
  </div>
</div>

<style>
  .chat-item-wrapper {
    cursor: pointer;
    transition: background-color 0.2s ease;
    margin: 0 0 -1px 0;
  }

  .chat-item-wrapper:first-child {
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
  }

  .chat-item-wrapper:last-child {
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    margin-bottom: 0;
  }

  .chat-item-wrapper:hover {
    background-color: var(--color-grey-10);
  }

  .chat-item-wrapper.active {
    background-color: var(--color-grey-20);
  }

  .chat-item {
    padding: 12px 16px;
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
    transition: opacity 0.2s ease;
  }

  .mate-profiles-row :global(.mate-profile-wrapper:nth-child(1)) {
    z-index: 3;
  }

  .mate-profiles-row :global(.mate-profile-wrapper:nth-child(2)) {
    position: absolute;
    right: 18px;
    z-index: 2;
    filter: opacity(60%);
  }

  .mate-profiles-row :global(.mate-profile-wrapper:nth-child(3)) {
    position: absolute;
    right: 36px;
    z-index: 1;
    filter: opacity(30%);
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
