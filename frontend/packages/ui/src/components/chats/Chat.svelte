<script lang="ts">
  import type { Chat, TiptapJSON } from '../../types/chat';
  // UserChatDraft import removed
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '../../services/chatSyncService';

  export let chat: Chat;
  export let activeChatId: string | undefined = undefined;

  let draftTextContent = ''; // Store extracted text for reactivity

  // updateDraftDisplay now solely relies on the 'chat' prop.
  function updateDraftDisplay() {
    if (chat && typeof chat.draft_json !== 'undefined') { // Check if draft_json exists on chat
      draftTextContent = extractTextFromDraftContent(chat.draft_json);
    } else {
      draftTextContent = ''; // Set to empty if no draft or chat is null/undefined
    }
  }

  // Reactive statement: update display if chat object or its draft_json changes.
  // This ensures draftTextContent is updated whenever the relevant part of the chat prop changes.
  $: if (chat) {
    draftTextContent = extractTextFromDraftContent(chat.draft_json);
  } else {
    draftTextContent = '';
  }
  
  function handleChatUpdated(event: Event) {
    const customEvent = event as CustomEvent;
    // The `chat` prop itself should be updated by the parent component (Chats.svelte)
    // when a 'chatUpdated' event occurs for this specific chat.
    // This component will then react to the prop change via the reactive statement above.
    if (customEvent.detail && customEvent.detail.chat_id === chat?.chat_id) {
        // The reactive block `$: if (chat)` will handle updating the display
        // when the parent component updates the `chat` prop.
        // No direct action needed here to change `draftTextContent` as it's derived.
    }
  }

  onMount(() => {
    updateDraftDisplay(); // Initial display based on passed chat prop
    chatSyncService.addEventListener('chatUpdated', handleChatUpdated);
  });

  onDestroy(() => {
    chatSyncService.removeEventListener('chatUpdated', handleChatUpdated);
  });

  // Truncate text to fit in two lines
  function truncateText(text: string, maxLength: number = 60): string {
    if (text && text.length > maxLength) {
      return text.substring(0, maxLength) + '...';
    }
    return text;
  }

  // Compute if this chat is currently active
  $: isActive = activeChatId === chat?.chat_id;

  // Take only the most recent mate instead of 3
  $: displayMate = chat?.mates ? chat.mates[chat.mates.length - 1] : null;

  // Update the function to work with the draft object (or null)
  function extractTextFromDraftContent(draftJson: TiptapJSON | null): string {
    if (!draftJson || !draftJson.content) return '';

    try {
      const text = draftJson.content?.map((node: any) => {
        return node.content?.map((contentNode: any) => {
          if (contentNode.type === 'text') {
            return contentNode.text;
          } else if (contentNode.type === 'mate') {
            return ''; // Don't include mate names in draft preview text
          }
          return '';
        }).join('');
      }).join('\n') || '';

      return text.trim();
    } catch (error) {
      console.error('Error extracting text from draft content:', error);
      return '';
    }
  }
  
  // draftTextContent is now updated by the reactive block `$: if (chat)`

  function getStatusLabel(): string {
    if (draftTextContent) return 'Draft:';
    return '';
  }
</script>

<div
  class="chat-item-wrapper"
  class:active={isActive}
  role="button"
  tabindex="0"
  on:click={() => { /* Dispatch an event or call a function to handle chat selection */ }}
  on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { /* Dispatch selection event */ } }}
>
  {#if chat}
    <div class="chat-item">
      {#if !displayMate && draftTextContent}
        <!-- Draft-only message (only show if there's actual draft content) -->
        <div class="draft-only">
          <span class="draft-label">Draft:</span>
          <span class="draft-content">{truncateText(draftTextContent, 60)}</span>
        </div>
      {:else}
        <div class="chat-with-profile">
          <div class="mate-profiles-container">
            {#if displayMate}
              <div class="mate-profile-wrapper">
                <!-- Assuming mate-profile-small and displayMate classes handle the visual representation -->
                <div class="mate-profile mate-profile-small {displayMate}">
                  {#if chat.unread_count && chat.unread_count > 0}
                    <div class="unread-badge">
                      {chat.unread_count > 9 ? '9+' : chat.unread_count}
                    </div>
                  {/if}
                </div>
              </div>
            {/if}
          </div>
          <div class="chat-content">
            <span class="chat-title">{chat.title || 'Untitled Chat'}</span>
            {#if draftTextContent}
              <span class="status-message">
                {getStatusLabel()} {truncateText(draftTextContent, 60)}
              </span>
            {/if}
          </div>
        </div>
      {/if}
    </div>
    <!-- TODO: Implement Edit Title button -->
    <!-- TODO: Implement Delete Chat button -->
  {:else}
    <div>Loading chat...</div> <!-- Or some placeholder -->
  {/if}
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
