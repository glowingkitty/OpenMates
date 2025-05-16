<script lang="ts">
  import type { Chat, TiptapJSON, Message } from '../../types/chat';
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '../../services/chatSyncService';

  export let chat: Chat;
  export let activeChatId: string | undefined = undefined;

  let draftTextContent = '';
  let sendingMessagePreview = '';
  let currentMessageStatusLabel = ''; // e.g., "Sending...", "Processing..."

  // Function to extract text from Tiptap JSON (used for both drafts and messages)
  function extractTextFromTiptap(jsonContent: TiptapJSON | null | undefined): string {
    if (!jsonContent || !jsonContent.content) return '';
    try {
      return jsonContent.content?.map((node: any) =>
        node.content?.map((contentNode: any) =>
          contentNode.type === 'text' ? contentNode.text : (contentNode.type === 'mate' ? '' : '')
        ).join('')
      ).join('\n').trim() || '';
    } catch (error) {
      console.error('Error extracting text from Tiptap content:', error);
      return '';
    }
  }

  // Reactive updates based on chat prop
  $: {
    if (chat) {
      draftTextContent = extractTextFromTiptap(chat.draft_json);

      const lastMessage = chat.messages && chat.messages.length > 0 ? chat.messages[chat.messages.length - 1] : null;
      if (lastMessage) {
        if (lastMessage.status === 'sending') {
          currentMessageStatusLabel = 'Sending...';
          sendingMessagePreview = extractTextFromTiptap(lastMessage.content);
        } else if (lastMessage.status === 'synced') { // 'synced' means server acknowledged
          currentMessageStatusLabel = 'Processing...';
          sendingMessagePreview = extractTextFromTiptap(lastMessage.content); // Keep showing the message being processed
        } else {
          currentMessageStatusLabel = '';
          sendingMessagePreview = '';
        }
      } else {
        currentMessageStatusLabel = '';
        sendingMessagePreview = '';
      }
    } else {
      draftTextContent = '';
      sendingMessagePreview = '';
      currentMessageStatusLabel = '';
    }
  }
  
  function handleChatOrMessageUpdated(event: Event) {
    const customEvent = event as CustomEvent;
    // The `chat` prop is updated by the parent (Chats.svelte).
    // Reactive block `$: { if (chat) ... }` will handle display updates.
    if (customEvent.detail && customEvent.detail.chat_id === chat?.chat_id) {
      // console.debug(`[Chat.svelte] Received update for chat ${chat.chat_id}`);
    } else if (customEvent.detail && customEvent.detail.chatId === chat?.chat_id) { // For messageStatusChanged
      // console.debug(`[Chat.svelte] Received message status update for chat ${chat.chat_id}`);
    }
  }

  onMount(() => {
    // Initial state is set by the reactive block.
    chatSyncService.addEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.addEventListener('messageStatusChanged', handleChatOrMessageUpdated);
  });

  onDestroy(() => {
    chatSyncService.removeEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.removeEventListener('messageStatusChanged', handleChatOrMessageUpdated);
  });

  function truncateText(text: string, maxLength: number = 60): string {
    if (text && text.length > maxLength) {
      return text.substring(0, maxLength) + '...';
    }
    return text;
  }

  $: isActive = activeChatId === chat?.chat_id;
  $: displayMate = chat?.mates ? chat.mates[chat.mates.length - 1] : null;

  function getStatusLabel(): string {
    if (currentMessageStatusLabel) return currentMessageStatusLabel;
    if (draftTextContent) return 'Draft:';
    return '';
  }

  function getStatusPreviewText(): string {
    if (sendingMessagePreview) return sendingMessagePreview;
    if (draftTextContent) return draftTextContent;
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
      {#if !displayMate && (draftTextContent || sendingMessagePreview)}
        <!-- Draft-only or Sending-only message -->
        <div class="status-only-preview">
          <span class="status-label">{getStatusLabel()}</span>
          <span class="status-content-preview">{truncateText(getStatusPreviewText(), 60)}</span>
        </div>
      {:else}
        <div class="chat-with-profile">
          <div class="mate-profiles-container">
            {#if displayMate}
              <div class="mate-profile-wrapper">
                <div class="mate-profile mate-profile-small {displayMate}">
                  {#if chat.unread_count && chat.unread_count > 0 && !currentMessageStatusLabel}
                    <!-- Hide unread badge if showing sending/processing status -->
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
            {#if draftTextContent || sendingMessagePreview}
              <span class="status-message">
                {getStatusLabel()} {truncateText(getStatusPreviewText(), 60)}
              </span>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {:else}
    <div>Loading chat...</div>
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

  .status-only-preview { /* Renamed from .draft-only */
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .status-only-preview .status-label { /* Renamed from .draft-label */
    font-family: 'Lexend Deca', sans-serif;
    font-weight: bold;
    font-size: 14px;
    color: var(--color-grey-60);
  }

  .status-only-preview .status-content-preview { /* Renamed from .draft-content */
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
