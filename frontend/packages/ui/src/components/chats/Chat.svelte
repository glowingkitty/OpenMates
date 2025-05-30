<script lang="ts">
  import type { Chat, TiptapJSON, Message } from '../../types/chat';
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '../../services/chatSyncService';
  import { chatDB } from '../../services/db'; // Import chatDB

  export let chat: Chat;
  export let activeChatId: string | undefined = undefined;
 
  let draftTextContent = ''; // Still used to get draft text once
  let displayLabel = '';     // New state for the label (e.g., "Draft:", "Sending...")
  let displayText = '';      // New state for the preview text content
 
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
  let lastMessage: Message | null = null;

  async function updateDisplayInfo(currentChat: Chat) {
    if (!currentChat) {
      draftTextContent = '';
      lastMessage = null;
      displayLabel = '';
      displayText = '';
      return;
    }

    draftTextContent = extractTextFromTiptap(currentChat.draft_json);
    
    // Fetch messages for the current chat to determine the last message
    // This is an async operation, so the UI might briefly show old state or loading state
    // if not handled carefully. For simplicity, we'll await here.
    // Consider adding a loading indicator if this fetch is slow.
    const messages = await chatDB.getMessagesForChat(currentChat.chat_id);
    lastMessage = messages && messages.length > 0 ? messages[messages.length - 1] : null;

    if (!currentChat.title) {
      // Untitled Chat Logic
        if (draftTextContent) {
          displayLabel = 'Draft:';
          displayText = draftTextContent;
        } else if (lastMessage) {
          displayText = extractTextFromTiptap(lastMessage.content);
          if (lastMessage.status === 'sending') {
            displayLabel = 'Sending...';
          } else if (lastMessage.status === 'failed') {
            displayLabel = 'Failed';
          } else { // Covers 'synced' (user or assistant), 'streaming' (assistant), etc.
            displayLabel = ''; 
          }
        } else {
          // No draft, no messages for untitled chat
          displayLabel = '';
          displayText = '';
        }
      } else {
        // Titled Chat Logic
        if (lastMessage) {
          // For titled chats, only show status if it's an ongoing action like sending/failed.
          // Completed messages (synced or otherwise) don't need a special label here.
          // displayText will also be empty unless specific conditions met.
          if (lastMessage.status === 'sending') {
            displayLabel = 'Sending...';
            displayText = extractTextFromTiptap(lastMessage.content);
          } else if (lastMessage.status === 'failed') {
            displayLabel = 'Failed';
            displayText = extractTextFromTiptap(lastMessage.content);
          } else {
            displayLabel = '';
            displayText = ''; // For titled chats, preview text is generally not shown
          }
        } else {
          // No messages in a titled chat
          displayLabel = '';
          displayText = '';
        }
      }
    // This else block is redundant due to the initial check for !currentChat
    // } else { 
    //   // No chat object
    //   draftTextContent = ''; 
    //   lastMessage = null;
    //   displayLabel = '';
    //   displayText = '';
    // }
  }

  $: if (chat) {
    updateDisplayInfo(chat);
  }

  async function handleChatOrMessageUpdated(event: Event) {
    const customEvent = event as CustomEvent; // Keep one declaration
    const detail = customEvent.detail;

    if (chat && detail && (detail.chat_id === chat.chat_id || detail.chatId === chat.chat_id)) {
        // Re-run display info calculation if our chat or its messages might have changed
        // console.debug(`[Chat.svelte] Received update relevant to chat ${chat.chat_id}, re-calculating display info.`);
        await updateDisplayInfo(chat); // chat prop itself should be updated by parent via binding or event
    }
  }

  onMount(() => {
    if (chat) {
        updateDisplayInfo(chat); // Initial update
    }
    chatSyncService.addEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.addEventListener('messageStatusChanged', handleChatOrMessageUpdated);
    // Listen for new messages or message updates that might change the last message
    chatSyncService.addEventListener('aiMessageChunk', handleChatOrMessageUpdated); // If an AI message becomes the last
    // We might need a more specific event like 'messageSavedToDb' if user messages also affect this.
    // For now, chatUpdated and messageStatusChanged should cover most cases if they trigger parent to update 'chat' prop.
  });

  onDestroy(() => {
    chatSyncService.removeEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.removeEventListener('messageStatusChanged', handleChatOrMessageUpdated);
    chatSyncService.removeEventListener('aiMessageChunk', handleChatOrMessageUpdated);
  });

  function truncateText(text: string, maxLength: number = 60): string {
    if (text && text.length > maxLength) {
      return text.substring(0, maxLength) + '...';
    }
    return text;
  }

  $: isActive = activeChatId === chat?.chat_id;
  $: displayMate = chat?.mates ? chat.mates[chat.mates.length - 1] : null;
 
  // getStatusLabel and getStatusPreviewText are no longer needed,
  // as displayLabel and displayText are used directly in the template.
 
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
      {#if !displayMate && displayText}
        <!-- Status preview for chats without a mate profile yet (e.g. new chats) -->
        <div class="status-only-preview">
          {#if displayLabel}<span class="status-label">{displayLabel}</span>{/if}
          <span class="status-content-preview">{truncateText(displayText, 60)}</span>
        </div>
      {:else}
        <div class="chat-with-profile">
          <div class="mate-profiles-container">
            {#if displayMate}
              <div class="mate-profile-wrapper">
                <div class="mate-profile mate-profile-small {displayMate}">
                  {#if chat.unread_count && chat.unread_count > 0 && !displayLabel}
                    <!-- Hide unread badge if showing a status label (Sending, Processing, Draft) -->
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
            {#if displayText}
              <span class="status-message">
                {#if displayLabel}{displayLabel} {/if}{truncateText(displayText, 60)}
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
