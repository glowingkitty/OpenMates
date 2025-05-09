<script lang="ts">
  import type { Chat } from '../../types/chat';
  import type { UserChatDraft, TiptapJSON } from '../../services/drafts/draftTypes';
  import { chatDB } from '../../services/db';
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '../../services/chatSyncService';

  export let chat: Chat;
  export let activeChatId: string | undefined = undefined;

  let currentUserDraft: UserChatDraft | null = null;
  let draftTextContent = ''; // Store extracted text for reactivity

  async function loadDraft() {
    if (chat && chat.chat_id) {
      currentUserDraft = await chatDB.getUserChatDraft(chat.chat_id);
      // Update draftTextContent reactively after fetching
      draftTextContent = extractTextFromDraftContent(currentUserDraft?.draft_json || null);
    } else {
      currentUserDraft = null;
      draftTextContent = '';
    }
  }

  // Reactive statement: reload draft if chat_id changes
  $: if (chat && chat.chat_id) {
    loadDraft();
  } else {
    currentUserDraft = null;
    draftTextContent = '';
  }
  
  function handleChatUpdated(event: Event) {
    // Cast event to CustomEvent to access detail property
    const customEvent = event as CustomEvent;
    if (customEvent.detail && customEvent.detail.chat_id === chat?.chat_id && customEvent.detail.type === 'draft') {
      loadDraft();
    }
  }

  onMount(() => {
    // Initial load
    loadDraft();
    // Listen to sync events to reload draft if it changes for this chat
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
            return '';
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
  
  // Update draftTextContent whenever currentUserDraft changes
  $: draftTextContent = extractTextFromDraftContent(currentUserDraft?.draft_json || null);

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
