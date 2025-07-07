<script lang="ts">
  import type { Chat, TiptapJSON, Message, AITypingStartedPayload, AITaskInitiatedPayload } from '../../types/chat';
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '../../services/chatSyncService';
  import { chatDB } from '../../services/db';
  import { text } from '@repo/ui'; // Use text store from @repo/ui
  import { aiTypingStore, type AITypingStatus } from '../../stores/aiTypingStore';

  export let chat: Chat;
  export let activeChatId: string | undefined = undefined;
 
  let draftTextContent = ''; 
  let displayLabel = '';     
  let displayText = '';      
  let currentTypingMateInfo: AITypingStatus | null = null;
  let lastMessage: Message | null = null; // Declare lastMessage here

  function extractTextFromTiptap(jsonContent: TiptapJSON | null | undefined): string {
    if (!jsonContent || !jsonContent.content) return '';
    try {
      return jsonContent.content?.map((node: any) =>
        node.content?.map((contentNode: any) =>
          contentNode.type === 'text' ? contentNode.text : ''
        ).join('')
      ).join('\n').trim() || '';
    } catch (error) {
      console.error('Error extracting text from Tiptap content:', error);
      return '';
    }
  }
  
  let typingStoreValue: AITypingStatus;
  aiTypingStore.subscribe(value => {
    typingStoreValue = value;
  });

  $: {
    if (chat && typingStoreValue && typingStoreValue.chatId === chat.chat_id && typingStoreValue.isTyping) {
      currentTypingMateInfo = typingStoreValue;
    } else {
      currentTypingMateInfo = null; 
    }
  }

  $: typingIndicatorInTitleView = (() => {
    if (currentTypingMateInfo?.isTyping && currentTypingMateInfo.category) {
      const mateName = $text(`mates.${currentTypingMateInfo.category}.text`);
      return $text('enter_message.is_typing.text').replace('{mate}', mateName);
    }
    return null;
  })();

  async function updateDisplayInfo(currentChat: Chat) {
    if (!currentChat) {
      draftTextContent = '';
      lastMessage = null;
      displayLabel = '';
      displayText = '';
      return;
    }

    draftTextContent = extractTextFromTiptap(currentChat.draft_json);
    const messages = await chatDB.getMessagesForChat(currentChat.chat_id);
    lastMessage = messages && messages.length > 0 ? messages[messages.length - 1] : null;

    displayLabel = '';
    displayText = '';

    // Handle sending, processing, and failed states first as they take precedence
    if (lastMessage?.status === 'sending') {
      displayLabel = $text('enter_message.sending.text');
      displayText = extractTextFromTiptap(lastMessage.content);
    } else if (lastMessage?.status === 'processing') {
      displayLabel = $text('enter_message.processing.text');
      displayText = extractTextFromTiptap(lastMessage.content);
    } else if (lastMessage?.status === 'failed') {
      displayLabel = 'Failed'; 
      displayText = extractTextFromTiptap(lastMessage.content);
    } else if (draftTextContent) {
      // If there's a draft, display draft information
      if (currentChat.title) {
        // For titled chats with draft, use specific translation that includes the beginning
        displayLabel = $text('enter_message.draft_with_beginning.text').replace('{draft_beginning}', truncateText(draftTextContent, 30));
        displayText = ''; // The label itself contains the preview for this case
      } else {
        // For untitled chats with draft
        displayLabel = $text('enter_message.draft.text');
        displayText = draftTextContent;
      }
    } else {
      // No sending, no failed, no draft:
      // For titled chats, the status line should be empty.
      // For untitled chats without a last message, also empty.
      // If there's a lastMessage for an untitled chat (and it's not sending/failed),
      // the original logic showed its content. Per feedback, this should now be empty too
      // unless explicitly decided otherwise. For now, keep it empty.
      displayLabel = '';
      displayText = '';
    }
  }

  $: if (chat) {
    updateDisplayInfo(chat);
  }

  async function handleChatOrMessageUpdated(event: Event) {
    const customEvent = event as CustomEvent;
    const detail = customEvent.detail;

    if (chat && detail && (detail.chat_id === chat.chat_id || detail.chatId === chat.chat_id)) {
      await updateDisplayInfo(chat); 
    }
  }
  
  onMount(() => {
    if (chat) {
        updateDisplayInfo(chat); 
    }
    chatSyncService.addEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.addEventListener('messageStatusChanged', handleChatOrMessageUpdated);
    chatSyncService.addEventListener('aiTaskInitiated', handleChatOrMessageUpdated as EventListener);
    chatSyncService.addEventListener('aiTaskEnded', handleChatOrMessageUpdated as EventListener); 
  });

  onDestroy(() => {
    chatSyncService.removeEventListener('chatUpdated', handleChatOrMessageUpdated);
    chatSyncService.removeEventListener('messageStatusChanged', handleChatOrMessageUpdated);
    chatSyncService.removeEventListener('aiTaskInitiated', handleChatOrMessageUpdated as EventListener);
    chatSyncService.removeEventListener('aiTaskEnded', handleChatOrMessageUpdated as EventListener);
  });

  function truncateText(textToTruncate: string, maxLength: number = 60): string { // Renamed param
    if (textToTruncate && textToTruncate.length > maxLength) {
      return textToTruncate.substring(0, maxLength) + '...';
    }
    return textToTruncate;
  }

  $: isActive = activeChatId === chat?.chat_id;
  $: displayMate = currentTypingMateInfo?.category || (chat?.mates && chat.mates.length > 0 ? chat.mates[0] : null);
  
  // Detect if this is a draft-only chat (has draft content but no title and no messages)
  $: isDraftOnly = chat && draftTextContent && !chat.title && (!lastMessage || lastMessage === null);
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
      {#if (lastMessage?.status === 'sending' || lastMessage?.status === 'processing') && !currentTypingMateInfo}
        <div class="status-only-preview">
          {#if displayLabel}<span class="status-label">{displayLabel}</span>{/if}
          {#if displayText}<span class="status-content-preview">{truncateText(displayText, 60)}</span>{/if}
        </div>
      {:else if isDraftOnly}
        <!-- Draft-only chat: left-aligned without mate profile -->
        <div class="draft-only-layout">
          <span class="status-message">{$text('enter_message.draft.text')}</span>
          <span class="draft-content-as-title">{truncateText(draftTextContent, 60)}</span>
        </div>
      {:else}
        <div class="chat-with-profile">
          <div class="mate-profiles-container">
            {#if displayMate}
              <div class="mate-profile-wrapper">
                <div class="mate-profile mate-profile-small {displayMate}">
                  {#if chat.unread_count && chat.unread_count > 0 && !typingIndicatorInTitleView && !displayLabel && lastMessage?.status !== 'processing'}
                    <div class="unread-badge">
                      {chat.unread_count > 9 ? '9+' : chat.unread_count}
                    </div>
                  {/if}
                </div>
              </div>
            {/if}
          </div>
          <div class="chat-content">
            <!-- Regular chat: show title and status messages -->
            <span class="chat-title">{chat.title || $text('chat.untitled_chat.text')}</span>
            {#if typingIndicatorInTitleView}
              <span class="status-message">{typingIndicatorInTitleView}</span>
            {:else if displayLabel && !currentTypingMateInfo} 
              <span class="status-message">
                {displayLabel}{#if displayText && displayLabel !== $text('enter_message.draft_with_beginning.text').replace('{draft_beginning}', truncateText(draftTextContent, 30))}&nbsp;{truncateText(displayText, 60)}{/if}
              </span>
            {:else if displayText && !currentTypingMateInfo} 
               <span class="status-message">{truncateText(displayText,60)}</span>
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
    background-color: var(--color-grey-10);
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

  .status-only-preview { 
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .status-only-preview .status-label { 
    font-family: 'Lexend Deca', sans-serif;
    font-weight: bold;
    font-size: 14px;
    color: var(--color-grey-60);
  }

  .status-only-preview .status-content-preview { 
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

  .draft-content-as-title {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-grey-60);
    margin-bottom: 2px;
  }

  .draft-only-layout {
    display: flex;
    flex-direction: column;
    flex: 1;
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
