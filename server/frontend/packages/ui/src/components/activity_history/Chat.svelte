<script lang="ts">
  import type { Chat } from '../../types/chat';
  export let chat: Chat;
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

  // Update the function to check for empty content
  function extractTextFromDraftContent(draftContent: any): string {
    if (!draftContent) return '';
    
    try {
      const content = typeof draftContent === 'string' ? JSON.parse(draftContent) : draftContent;
      
      // Extract text from Tiptap JSON structure
      const text = content.content?.map((node: any) => {
        return node.content?.map((contentNode: any) => {
          if (contentNode.type === 'text') {
            return contentNode.text;
          } else if (contentNode.type === 'mate') {
            return ''; // Skip mate mentions when checking for content
          }
          return '';
        }).join('');
      }).join('\n') || '';

      // Return empty string if only whitespace remains
      return text.trim();
    } catch (error) {
      console.error('Error extracting text from draft content:', error);
      return '';
    }
  }

  function getStatusLabel(): string {
    // Only show draft status if it has actual content
    if (chat.isDraft && extractTextFromDraftContent(chat.draftContent)) return 'Draft:';
    
    // Otherwise handle other status types
    if (!chat.status) return '';
    switch (chat.status) {
      case 'sending': return 'Sending...';
      case 'pending': return 'Pending...';
      case 'typing': return `${chat.typingMate} is typing...`;
      default: return '';
    }
  }
</script>

<div 
  class="chat-item-wrapper"
  class:active={isActive}
  role="button"
  tabindex="0"
>
  <div class="chat-item">
    {#if !displayMate && chat.isDraft && extractTextFromDraftContent(chat.draftContent)}
      <!-- Draft-only message (only show if there's actual draft content) -->
      <div class="draft-only">
        <span class="draft-label">Draft:</span>
        <span class="draft-content">{truncateText(extractTextFromDraftContent(chat.draftContent), 60)}</span>
      </div>
    {:else}
      <div class="chat-with-profile">
        <div class="mate-profiles-container">
          {#if displayMate}
            <div class="mate-profile-wrapper">
              <div class="mate-profile mate-profile-small {displayMate}">
                {#if chat.unreadCount && chat.unreadCount > 0}
                  <div class="unread-badge">
                    {chat.unreadCount > 9 ? '+' : chat.unreadCount}
                  </div>
                {/if}
              </div>
            </div>
          {/if}
        </div>
        <div class="chat-content">
          <span class="chat-title">{chat.title}</span>
          {#if (chat.isDraft && extractTextFromDraftContent(chat.draftContent)) || chat.status}
            <span class="status-message">
              {getStatusLabel()}
              {#if chat.isDraft && extractTextFromDraftContent(chat.draftContent)}
                {truncateText(extractTextFromDraftContent(chat.draftContent), 60)}
              {/if}
            </span>
          {/if}
        </div>
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
    font-size: 16px;
    font-weight: 500;
    color: var(--color-text);
    margin-bottom: 2px;
  }

  .profile-placeholder {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background-color: var(--color-grey-20);
  }

  .draft-only {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .draft-only .draft-label {
    font-family: 'Lexend Deca', sans-serif;
    font-weight: bold;
    font-size: 14px;
    color: var(--color-grey-60);
  }

  .draft-only .draft-content {
    font-family: 'Lexend Deca', sans-serif;
    font-weight: bold;
    font-size: 16px;
    color: var(--color-grey-60);
  }

  .chat-content {
    display: flex;
    flex-direction: column;
    flex: 1;
  }

  .status-message {
    font-size: 14px;
    color: var(--color-grey-60);
  }

  .unread-badge {
    position: absolute;
    bottom: -2px;
    right: -2px;
    width: 21px;
    height: 21px;
    background: var(--color-primary);
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 500;
    border: 2px solid var(--color-background);
  }
</style>
